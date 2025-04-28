import os
import logging
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import re
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
import threading

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    logger.error("No Discord token found in environment variables!")
    exit(1)

# Set up bot with necessary intents
# Using default intents only to avoid privileged intent errors
intents = discord.Intents.default()
intents.members = True  # For checking server members
intents.presences = True  # For checking activities/games

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Use dictionary for active team searches
# These get stored in the database but we keep an in-memory copy for performance
team_searches = {}  # Track active team searches

# Regular expression pattern for Activision ID validation
ACTIVISION_ID_PATTERN = re.compile(r'^[A-Za-z0-9_]{3,16}#[0-9]{1,10}$')

class RegistrationModal(discord.ui.Modal, title='Registrar Activision ID'):
    activision_id = discord.ui.TextInput(
        label='Tu Activision ID (nombre#12345)',
        placeholder='Ejemplo: Warzone#12345',
        required=True,
        min_length=5,
        max_length=30
    )

    kd_ratio = discord.ui.TextInput(
        label='Tu K/D Ratio (ej: 1.2)',
        placeholder='Ejemplo: 1.2',
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        activision_id = self.activision_id.value

        # Validate Activision ID format
        if not ACTIVISION_ID_PATTERN.match(activision_id):
            await interaction.response.send_message(
                "⚠️ El formato del Activision ID no es válido. Debe ser nombre#12345", 
                ephemeral=True
            )
            return

        # Validate KD ratio
        try:
            kd = float(self.kd_ratio.value)
            if kd < 0:
                raise ValueError("KD cannot be negative")
        except ValueError:
            await interaction.response.send_message(
                "⚠️ Por favor, introduce un valor válido para el K/D ratio (ej: 1.2)", 
                ephemeral=True
            )
            return

        with app.app_context():
            try:
                # Check if user exists in database
                existing_user = User.query.filter_by(discord_id=str(interaction.user.id)).first()

                if existing_user:
                    # Update existing user
                    existing_user.activision_id = activision_id
                    existing_user.kd_ratio = kd
                    existing_user.username = interaction.user.name
                    existing_user.discriminator = interaction.user.discriminator or ""
                    existing_user.updated_at = datetime.utcnow()
                else:
                    # Create new user
                    new_user = User(
                        discord_id=str(interaction.user.id),
                        username=interaction.user.name,
                        discriminator=interaction.user.discriminator or "",
                        activision_id=activision_id,
                        kd_ratio=kd
                    )
                    db.session.add(new_user)

                # Commit changes
                db.session.commit()
                logger.info(f"User {interaction.user.id} saved to database with Activision ID: {activision_id}")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error saving user to database: {e}")
                await interaction.response.send_message(
                    "❌ Error al guardar tus datos. Por favor, inténtalo de nuevo más tarde.",
                    ephemeral=True
                )
                return

        await interaction.response.send_message(
            f"✅ Registrado correctamente!\nActivision ID: `{activision_id}`\nK/D Ratio: `{kd}`", 
            ephemeral=True
        )

class TeamFinderView(discord.ui.View):
    def __init__(self, owner_id, search_id, max_players=4, voice_channel_id=None):
        super().__init__(timeout=None)
        self.members_joined = []
        self.owner_id = owner_id
        self.search_id = search_id
        self.max_players = max_players
        self.voice_channel_id = voice_channel_id

    @discord.ui.button(label="Unirse", style=discord.ButtonStyle.success, emoji="✅", custom_id="join_team")
    async def join_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        discord_id = str(interaction.user.id)

        # Check if user is registered in the database
        with app.app_context():
            user = User.query.filter_by(discord_id=discord_id).first()

            if not user or not user.activision_id:
                await interaction.response.send_message(
                    "⚠️ Necesitas registrar tu Activision ID primero. Usa `/registrar`",
                    ephemeral=True
                )
                return

        # Check if team is full
        if len(self.members_joined) >= self.max_players - 1:  # -1 because owner is not in the list
            await interaction.response.send_message(
                "⚠️ Este equipo ya está completo.",
                ephemeral=True
            )
            return

        # Check if user is already in this team
        if interaction.user.id in [member.id for member in self.members_joined]:
            await interaction.response.send_message(
                "⚠️ Ya estás en este equipo.",
                ephemeral=True
            )
            return

        # Check if search still exists
        if self.search_id not in team_searches:
            await interaction.response.send_message(
                "⚠️ Esta búsqueda de equipo ya no está activa.",
                ephemeral=True
            )
            return

        # Add user to team
        self.members_joined.append(interaction.user)

        # Get search details for notifications
        search = team_searches[self.search_id]

        # Add user to team in database if the team exists in DB
        if 'team_id' in search:
            with app.app_context():
                team = Team.query.get(search['team_id'])
                if team:
                    team_member = TeamMember(
                        team_id=team.id,
                        user_id=user.id
                    )
                    db.session.add(team_member)
                    db.session.commit()
                    logger.info(f"User {interaction.user.id} joined team {team.id}")

        # Notify user
        await interaction.response.send_message(
            f"✅ Te has unido al equipo para {search['mode']}.\n"
            f"Activision ID: `{user.activision_id}`",
            ephemeral=True
        )

        # Notify team owner via DM
        owner = await bot.fetch_user(self.owner_id)
        if owner:
            try:
                with app.app_context():
                    owner_user_db = User.query.filter_by(discord_id=str(self.owner_id)).first()

                await owner.send(
                    f"📢 {interaction.user.mention} se ha unido a tu equipo de {search['mode']}.\n"
                    f"Activision ID: `{user.activision_id}`\n"
                    f"K/D: `{user.kd_ratio}`"
                )
            except discord.errors.Forbidden:
                logger.warning(f"Could not send DM to {owner.name} - messages may be disabled")
            except Exception as e:
                logger.error(f"Error sending DM: {e}")

        # Update the original message with current team members
        # Get owner from cache or fetch if needed
        owner_user = bot.get_user(self.owner_id)
        if not owner_user:
            try:
                owner_user = await bot.fetch_user(self.owner_id)
            except:
                logger.error(f"Could not fetch user with ID {self.owner_id}")
                owner_user = None

        owner_mention = owner_user.mention if owner_user else f"<@{self.owner_id}>"

        # Get Activision IDs from the database
        members_text = ""
        for member in self.members_joined:
            with app.app_context():
                member_user = User.query.filter_by(discord_id=str(member.id)).first()
                activision_id = member_user.activision_id if member_user else "Unknown"

            members_text += f"- {member.mention} - `{activision_id}`\n"

        # Get the original message
        message = interaction.message
        embed = message.embeds[0]

        # Update the embed with current team members
        embed.set_field_at(
            3,  # Assuming the team members field is at index 3
            name=f"👥 Equipo ({len(self.members_joined) + 1}/{self.max_players})",
            value=f"{owner_mention} (Líder)\n{members_text}" if members_text else f"{owner_mention} (Líder)",
            inline=False
        )

        await message.edit(embed=embed)

    @discord.ui.button(label="Actualizar", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="update_team")
    async def update_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if search still exists
        if self.search_id not in team_searches:
            await interaction.response.send_message(
                "⚠️ Esta búsqueda ya no está activa.",
                ephemeral=True
            )
            return

        # Check if user is in voice channel
        voice_state = interaction.user.voice
        if voice_state and voice_state.channel:
            # Update the voice channel ID
            self.voice_channel_id = voice_state.channel.id
            team_searches[self.search_id]['voice_channel_id'] = voice_state.channel.id

            await interaction.response.send_message(
                f"✅ Se ha actualizado el canal de voz a: {voice_state.channel.name}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "⚠️ Debes estar en un canal de voz para actualizarlo en la búsqueda.",
                ephemeral=True
            )
            if self.voice_channel_id:
                # Remove the voice channel if the user is no longer in one
                self.voice_channel_id = None
                if 'voice_channel_id' in team_searches[self.search_id]:
                    del team_searches[self.search_id]['voice_channel_id']

        # Update the message
        message = interaction.message
        embed = message.embeds[0]

        # Update voice channel field or add it if it doesn't exist
        voice_channel_info = "No conectado a canal de voz"
        if self.voice_channel_id:
            voice_channel = interaction.guild.get_channel(self.voice_channel_id)
            voice_channel_info = f"🔊 {voice_channel.name}" if voice_channel else "Canal desconocido"

        # Check if voice channel field exists
        voice_field_index = None
        for i, field in enumerate(embed.fields):
            if field.name.startswith("🔊 Canal de Voz"):
                voice_field_index = i
                break

        if voice_field_index is not None:
            # Update existing field
            embed.set_field_at(
                voice_field_index,
                name="🔊 Canal de Voz",
                value=voice_channel_info,
                inline=False
            )
        else:
            # Add new field
            embed.add_field(
                name="🔊 Canal de Voz",
                value=voice_channel_info,
                inline=False
            )

        await message.edit(embed=embed)

    @discord.ui.button(label="Cancelar búsqueda", style=discord.ButtonStyle.danger, emoji="❌", custom_id="cancel_search")
    async def cancel_search(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only the owner can cancel the search
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "⚠️ Solo el creador de la búsqueda puede cancelarla.",
                ephemeral=True
            )
            return

        # Check if search still exists
        if self.search_id not in team_searches:
            await interaction.response.send_message(
                "⚠️ Esta búsqueda ya ha sido cancelada.",
                ephemeral=True
            )
            return

        # Remove search from active searches
        del team_searches[self.search_id]

        # Update the message
        embed = interaction.message.embeds[0]
        embed.colour = discord.Colour.red()
        embed.title = "📢 BÚSQUEDA CANCELADA"
        embed.description = f"{interaction.user.mention} ha cancelado esta búsqueda de equipo."

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            "✅ Has cancelado esta búsqueda de equipo.",
            ephemeral=True
        )

@bot.event
async def on_ready():
    logger.info(f"✅ Bot conectado como {bot.user}")

    # Set bot activity
    await bot.change_presence(activity=discord.Game(name="Warzone | /buscar_equipo"))

    # Sync commands
    try:
        synced = await tree.sync()
        logger.info(f"🌐 {len(synced)} comandos sincronizados")
    except Exception as e:
        logger.error(f"❌ Error sincronizando comandos: {e}")

    # Register global views (for persistent buttons)
    for search_id, search in team_searches.items():
        voice_channel_id = search.get('voice_channel_id', None)
        bot.add_view(TeamFinderView(search['owner_id'], search_id, search['max_players'], voice_channel_id))

    logger.info("🔄 Bot listo y esperando comandos")

@tree.command(name="registrar", description="Registra tu Activision ID para poder unirte a equipos")
async def registrar(interaction: discord.Interaction):
    """Registra tu Activision ID para poder unirte a equipos"""
    modal = RegistrationModal()
    await interaction.response.send_modal(modal)

@tree.command(name="perfil", description="Muestra tu perfil de Warzone registrado")
@app_commands.describe(publico="Mostrar el perfil públicamente")
async def perfil(interaction: discord.Interaction, publico: bool = False):
    """Muestra tu perfil de Warzone registrado"""
    discord_id = str(interaction.user.id)

    with app.app_context():
        # Check if user exists in database
        user = User.query.filter_by(discord_id=discord_id).first()

        if not user or not user.activision_id:
            await interaction.response.send_message(
                "⚠️ No has registrado tu Activision ID todavía. Usa `/registrar`",
                ephemeral=True
            )
            return

        # Create an embed with user profile information
        embed = discord.Embed(
            title=f"🎮 Perfil de {interaction.user.display_name}",
            description="Información registrada para encontrar equipos en Warzone",
            color=0x3498db
        )

        # Add user information
        embed.add_field(name="📋 Discord", value=interaction.user.mention, inline=True)
        embed.add_field(name="🆔 Activision ID", value=f"`{user.activision_id}`", inline=True)
        embed.add_field(name="📊 K/D Ratio", value=f"`{user.kd_ratio}`", inline=True)

        # Set user avatar as thumbnail if available
        if interaction.user.avatar:
            embed.set_thumbnail(url=interaction.user.avatar.url)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="buscar_equipo", description="Busca equipo para Warzone")
@app_commands.choices(
    plataforma=[
        app_commands.Choice(name="PC", value="PC"),
        app_commands.Choice(name="Xbox", value="Xbox"),
        app_commands.Choice(name="PlayStation", value="PlayStation"),
        app_commands.Choice(name="Crossplay", value="Crossplay")
    ],
    modo=[
        app_commands.Choice(name="Battle Royale", value="Battle Royale"),
        app_commands.Choice(name="Resurgimiento", value="Resurgimiento"),
        app_commands.Choice(name="Ranked BR", value="Ranked BR"),
        app_commands.Choice(name="Ranked Multijugador", value="Ranked Multijugador"),
        app_commands.Choice(name="Zombies", value="Zombies"),
        app_commands.Choice(name="Saqueo", value="Saqueo")
    ],
    max_jugadores=[
        app_commands.Choice(name="Duo (2)", value=2),
        app_commands.Choice(name="Trio (3)", value=3),
        app_commands.Choice(name="Squad (4)", value=4),
    ]
)
async def buscar_equipo(
    interaction: discord.Interaction,
    plataforma: app_commands.Choice[str],
    modo: app_commands.Choice[str],
    kd_minimo: float = 0.0,
    max_jugadores: app_commands.Choice[int] = 4,
    descripcion: str = None
):
    """Publica una búsqueda de equipo para Warzone"""
    discord_id = str(interaction.user.id)

    # Get user from database
    with app.app_context():
        user = User.query.filter_by(discord_id=discord_id).first()

        if not user or not user.activision_id:
            await interaction.response.send_message(
                "⚠️ Necesitas registrar tu Activision ID primero. Usa `/registrar`",
                ephemeral=True
            )
            return

    # Create a unique ID for this search
    search_id = f"{discord_id}_{len(team_searches) + 1}"

    # Check KD value is valid
    if kd_minimo < 0:
        await interaction.response.send_message(
            "⚠️ El K/D mínimo no puede ser negativo.",
            ephemeral=True
        )
        return

    # Create the embed with team search details
    embed = discord.Embed(
        title="📣 BÚSQUEDA DE EQUIPO",
        description=f"{interaction.user.mention} busca equipo para Warzone",
        color=0x00ff00
    )

    # Add fields with search details
    embed.add_field(name="🖥️ Plataforma", value=plataforma.value, inline=True)
    embed.add_field(name="🎮 Modo", value=modo.value, inline=True)
    embed.add_field(name="📊 K/D Mínimo", value=str(kd_minimo), inline=True)
    embed.add_field(
        name=f"👥 Equipo (1/{max_jugadores.value})",
        value=f"{interaction.user.mention} (Líder)",
        inline=False
    )

    # Add user's own KD
    embed.add_field(
        name="👑 Líder K/D",
        value=str(user.kd_ratio),
        inline=True
    )

    # Add Activision ID
    embed.add_field(
        name="🆔 Activision ID",
        value=f"`{user.activision_id}`",
        inline=True
    )

    # Add description if provided
    if descripcion:
        embed.add_field(name="📝 Descripción", value=descripcion, inline=False)

    # Store search details in memory
    team_searches[search_id] = {
        'owner_id': interaction.user.id,
        'platform': plataforma.value,
        'mode': modo.value,
        'kd_min': kd_minimo,
        'max_players': max_jugadores.value,
        'description': descripcion
    }

    # Store search in database
    with app.app_context():
        new_team = Team(
            owner_id=user.id,
            platform=plataforma.value,
            mode=modo.value,
            kd_minimum=kd_minimo,
            max_players=max_jugadores.value,
            description=descripcion,
            is_active=True
        )
        db.session.add(new_team)
        db.session.commit()
        team_searches[search_id]['team_id'] = new_team.id

    # Check if user is in a voice channel and add it to the search
    voice_channel_id = None
    voice_channel_info = "No conectado a canal de voz"

    if interaction.user.voice and interaction.user.voice.channel:
        voice_channel = interaction.user.voice.channel
        voice_channel_id = voice_channel.id
        voice_channel_info = f"🔊 {voice_channel.name}"
        team_searches[search_id]['voice_channel_id'] = voice_channel_id

        # Add voice channel to embed
        embed.add_field(
            name="🔊 Canal de Voz",
            value=voice_channel_info,
            inline=False
        )

    # Create view with buttons
    view = TeamFinderView(interaction.user.id, search_id, max_jugadores.value, voice_channel_id)

    # Send the message
    await interaction.response.send_message(embed=embed, view=view)

@tree.command(name="ver_perfil", description="Ver el perfil de un usuario")
@app_commands.describe(usuario="Usuario del que quieres ver el perfil (opcional)", publico="Mostrar el perfil públicamente")
async def ver_perfil(
    interaction: discord.Interaction, 
    usuario: discord.Member = None,
    publico: bool = False
):
    """Ver el perfil de un usuario o el tuyo propio"""
    target_user = usuario or interaction.user

    with app.app_context():
        # Get user from database
        user = User.query.filter_by(discord_id=str(target_user.id)).first()

        if not user or not user.activision_id:
            await interaction.response.send_message(
                f"⚠️ {target_user.mention} no tiene un perfil registrado. Usa `/registrar` para crear uno.",
                ephemeral=not publico
            )
            return

        # Create embed for profile
        embed = discord.Embed(
            title=f"🎮 Perfil de {target_user.display_name}",
            description="Información registrada para Warzone",
            color=0x3498db
        )

        # Add user information
        embed.add_field(name="📋 Discord", value=target_user.mention, inline=True)
        embed.add_field(name="🆔 Activision ID", value=f"`{user.activision_id}`", inline=True)
        embed.add_field(name="📊 K/D Ratio", value=f"`{user.kd_ratio}`", inline=True)

        # Add registration date
        embed.add_field(
            name="📅 Registrado el",
            value=user.created_at.strftime("%d/%m/%Y"),
            inline=False
        )

        # Set user avatar as thumbnail if available
        if target_user.avatar:
            embed.set_thumbnail(url=target_user.avatar.url)

    await interaction.response.send_message(
        embed=embed,
        ephemeral=not publico
    )

@tree.command(name="jugadores", description="Muestra los jugadores en línea jugando Call of Duty")
async def jugadores(interaction: discord.Interaction):
    """Muestra los jugadores que están jugando Call of Duty"""

    # Create embeds for different games
    warzone_players = []
    black_ops_players = []
    other_cod_players = []

    # Check all members in the server
    for member in interaction.guild.members:
        if member.activity and isinstance(member.activity, discord.Activity):
            activity_name = member.activity.name.lower()

            # Check different CoD games
            if "warzone" in activity_name:
                warzone_players.append(member)
            elif "black ops" in activity_name:
                black_ops_players.append(member)
            elif "call of duty" in activity_name or "cod" in activity_name:
                other_cod_players.append(member)

    # Create embed
    embed = discord.Embed(
        title="🎮 Jugadores de Call of Duty",
        description="Lista de jugadores en línea jugando CoD",
        color=0x00ff00
    )

    # Add fields for each game
    if warzone_players:
        players_str = "\n".join([f"• {player.mention} - {player.activity.name}" for player in warzone_players])
        embed.add_field(name="🔫 Warzone", value=players_str, inline=False)
    else:
        embed.add_field(name="🔫 Warzone", value="No hay jugadores en Warzone", inline=False)

    if black_ops_players:
        players_str = "\n".join([f"• {player.mention} - {player.activity.name}" for player in black_ops_players])
        embed.add_field(name="⚔️ Black Ops", value=players_str, inline=False)
    else:
        embed.add_field(name="⚔️ Black Ops", value="No hay jugadores en Black Ops", inline=False)

    if other_cod_players:
        players_str = "\n".join([f"• {player.mention} - {player.activity.name}" for player in other_cod_players])
        embed.add_field(name="🎯 Otros CoD", value=players_str, inline=False)

    await interaction.response.send_message(embed=embed)

@tree.command(name="jugadores_inscritos", description="Muestra la lista de jugadores registrados")
@app_commands.describe(publico="Mostrar la lista públicamente")
async def jugadores_inscritos(interaction: discord.Interaction, publico: bool = False):
    """Muestra la lista de todos los jugadores registrados"""
    with app.app_context():
        users = User.query.all()

        if not users:
            await interaction.response.send_message(
                "⚠️ No hay jugadores registrados todavía.",
                ephemeral=not publico
            )
            return

        embed = discord.Embed(
            title="📋 Lista de Jugadores Registrados",
            description="Jugadores registrados en el bot",
            color=0x3498db
        )

        for user in users:
            # Get Discord member object
            member = interaction.guild.get_member(int(user.discord_id))
            if member:
                embed.add_field(
                    name=f"👤 {member.display_name}",
                    value=f"Activision ID: `{user.activision_id}`\nK/D: `{user.kd_ratio}`",
                    inline=True
                )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=not publico
        )

@tree.command(name="crear_privada", description="Crear una partida privada")
@app_commands.choices(
    modo=[
        app_commands.Choice(name="Battle Royale", value="Battle Royale"),
        app_commands.Choice(name="Resurgimiento", value="Resurgimiento")
    ],
    tamanio_equipo=[
        app_commands.Choice(name="Duos (2)", value=2),
        app_commands.Choice(name="Trios (3)", value=3),
        app_commands.Choice(name="Cuartetos (4)", value=4)
    ]
)
async def crear_privada(
    interaction: discord.Interaction,
    modo: app_commands.Choice[str],
    tamanio_equipo: app_commands.Choice[int],
    descripcion: str = None
):
    """Crear una partida privada personalizada"""
    # Create unique match ID
    match_id = f"{interaction.guild_id}_{int(datetime.utcnow().timestamp())}"

    # Store match info in database
    with app.app_context():
        match = Team(
            owner_id=str(interaction.user.id),
            mode=modo.value,
            max_players=tamanio_equipo.value,
            description=descripcion,
            discord_message_id=match_id,
            is_active=True
        )
        db.session.add(match)
        db.session.commit()

    # Create embed for private match
    embed = discord.Embed(
        title="🎮 PARTIDA PRIVADA",
        description=f"{interaction.user.mention} ha creado una partida privada",
        color=0xff9900
    )

    # Add match details
    embed.add_field(name="🎯 Modo", value=modo.value, inline=True)
    embed.add_field(name="👥 Tamaño de Equipo", value=f"{tamanio_equipo.value} jugadores", inline=True)
    embed.add_field(name="👑 Host", value=interaction.user.mention, inline=True)

    if descripcion:
        embed.add_field(name="📝 Descripción", value=descripcion, inline=False)

    embed.add_field(name="✅ Jugadores Inscritos", value="0", inline=False)
    embed.timestamp = datetime.utcnow()

    # Create view with buttons
    view = PrivateMatchView(match_id, tamanio_equipo.value)
    await interaction.response.send_message(embed=embed, view=view)

class PrivateMatchView(discord.ui.View):
    def __init__(self, match_id: str, team_size: int):
        super().__init__(timeout=None)
        self.match_id = match_id
        self.team_size = team_size
        self.registered_players = []

    @discord.ui.button(label="Inscribirse", style=discord.ButtonStyle.success, emoji="✅")
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.registered_players:
            await interaction.response.send_message("⚠️ Ya estás inscrito en esta partida.", ephemeral=True)
            return

        self.registered_players.append(interaction.user)

        # Update embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(
            -1, 
            name="✅ Jugadores Inscritos",
            value=str(len(self.registered_players)),
            inline=False
        )

        await interaction.message.edit(embed=embed)
        await interaction.response.send_message("✅ Te has inscrito en la partida.", ephemeral=True)

    @discord.ui.button(label="Comenzar Sorteo", style=discord.ButtonStyle.primary, emoji="🎲")
    async def start_draw(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.registered_players) < self.team_size:
            await interaction.response.send_message(
                f"⚠️ No hay suficientes jugadores inscritos. Se necesitan al menos {self.team_size} jugadores.",
                ephemeral=True
            )
            return

        # Randomize players and create teams
        import random
        random.shuffle(self.registered_players)

        teams = []
        for i in range(0, len(self.registered_players), self.team_size):
            team = self.registered_players[i:i + self.team_size]
            if len(team) == self.team_size:  # Only add complete teams
                teams.append(team)

        # Create embed with teams
        embed = discord.Embed(
            title="🎲 Sorteo de Equipos",
            description="Equipos formados aleatoriamente",
            color=0x00ff00
        )

        for i, team in enumerate(teams, 1):
            team_members = "\n".join([player.mention for player in team])
            embed.add_field(
                name=f"Equipo {i}",
                value=team_members,
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Actualizar", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def update(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        await interaction.response.send_message("✅ Lista actualizada.", ephemeral=True)
        await interaction.message.edit(embed=embed)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        with app.app_context():
            match = Team.query.filter_by(discord_message_id=self.match_id).first()
            if match:
                match.is_active = False
                db.session.commit()

        # Disable all buttons
        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "❌ PARTIDA CANCELADA"

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("✅ Partida cancelada.", ephemeral=True)
    """Crear una partida privada personalizada"""

    # Create embed for private match
    embed = discord.Embed(
        title="🎮 PARTIDA PRIVADA",
        description=f"{interaction.user.mention} ha creado una partida privada",
        color=0xff9900
    )

    # Add match details
    embed.add_field(name="🎯 Modo", value=modo.value, inline=True)
    embed.add_field(name="👥 Tamaño de Equipo", value=f"{tamanio_equipo.value} jugadores", inline=True)
    embed.add_field(
        name="👑 Host",
        value=interaction.user.mention,
        inline=True
    )

    # Add description if provided
    if descripcion:
        embed.add_field(name="📝 Descripción", value=descripcion, inline=False)

    # Add voice channel if user is in one
    if interaction.user.voice and interaction.user.voice.channel:
        embed.add_field(
            name="🔊 Canal de Voz",
            value=interaction.user.voice.channel.mention,
            inline=False
        )

    # Add timestamp
    embed.timestamp = datetime.utcnow()

    await interaction.response.send_message(embed=embed)

@tree.command(name="crear_torneo", description="Crear un torneo personalizado")
@app_commands.choices(
    modo=[
        app_commands.Choice(name="Battle Royale", value="Battle Royale"),
        app_commands.Choice(name="Resurgimiento", value="Resurgimiento")
    ],
    tamanio_equipo=[
        app_commands.Choice(name="Duos (2)", value=2),
        app_commands.Choice(name="Trios (3)", value=3),
        app_commands.Choice(name="Cuartetos (4)", value=4)
    ]
)
async def crear_torneo(
    interaction: discord.Interaction,
    modo: app_commands.Choice[str],
    tamanio_equipo: app_commands.Choice[int],
    premio: str,
    descripcion: str = None
):
    """Crear un torneo personalizado"""

    # Create unique tournament ID
    tournament_id = f"T_{interaction.guild_id}_{int(datetime.utcnow().timestamp())}"

    # Store tournament info in database
    with app.app_context():
        tournament = Team(
            owner_id=str(interaction.user.id),
            mode=modo.value,
            max_players=tamanio_equipo.value,
            description=descripcion,
            discord_message_id=tournament_id,
            is_active=True
        )
        db.session.add(tournament)
        db.session.commit()

    # Create embed for tournament
    embed = discord.Embed(
        title="🏆 TORNEO",
        description=f"{interaction.user.mention} ha creado un torneo",
        color=0xffd700
    )

    # Add tournament details
    embed.add_field(name="🎯 Modo", value=modo.value, inline=True)
    embed.add_field(name="👥 Tamaño de Equipo", value=f"{tamanio_equipo.value} jugadores", inline=True)
    embed.add_field(name="👑 Organizador", value=interaction.user.mention, inline=True)
    embed.add_field(name="🎁 Premio", value=premio, inline=True)

    if descripcion:
        embed.add_field(name="📝 Descripción", value=descripcion, inline=False)

    embed.add_field(name="✅ Equipos Inscritos", value="0", inline=False)
    embed.timestamp = datetime.utcnow()

    # Create view with buttons
    view = TournamentView(tournament_id, tamanio_equipo.value)
    await interaction.response.send_message(embed=embed, view=view)

class TournamentView(discord.ui.View):
    def __init__(self, tournament_id: str, team_size: int):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.team_size = team_size
        self.registered_teams = []

    @discord.ui.button(label="Inscribir Equipo", style=discord.ButtonStyle.success, emoji="✅")
    async def register_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in [member for team in self.registered_teams for member in team]:
            await interaction.response.send_message("⚠️ Ya estás inscrito en este torneo.", ephemeral=True)
            return

        # Create a new team
        new_team = [interaction.user]
        self.registered_teams.append(new_team)

        # Update embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(
            -1, 
            name="✅ Equipos Inscritos",
            value=str(len(self.registered_teams)),
            inline=False
        )

        await interaction.message.edit(embed=embed)
        await interaction.response.send_message("✅ Has inscrito tu equipo en el torneo.", ephemeral=True)

    @discord.ui.button(label="Generar Brackets", style=discord.ButtonStyle.primary, emoji="🔄")
    async def generate_brackets(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.registered_teams) < 2:
            await interaction.response.send_message(
                "⚠️ No hay suficientes equipos inscritos. Se necesitan al menos 2 equipos.",
                ephemeral=True
            )
            return

        # Randomize teams and create brackets
        import random
        random.shuffle(self.registered_teams)

        # Create embed with brackets
        embed = discord.Embed(
            title="🏆 Brackets del Torneo",
            description="Enfrentamientos del torneo",
            color=0xffd700
        )

        # Create matches
        for i in range(0, len(self.registered_teams), 2):
            if i + 1 < len(self.registered_teams):
                team1 = "\n".join([player.mention for player in self.registered_teams[i]])
                team2 = "\n".join([player.mention for player in self.registered_teams[i + 1]])
                embed.add_field(
                    name=f"Partido {i//2 + 1}",
                    value=f"Equipo A:\n{team1}\n\nVS\n\nEquipo B:\n{team2}",
                    inline=False
                )

        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Actualizar", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def update(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        await interaction.response.send_message("✅ Lista actualizada.", ephemeral=True)
        await interaction.message.edit(embed=embed)

    @discord.ui.button(label="Cancelar Torneo", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        with app.app_context():
            tournament = Team.query.filter_by(discord_message_id=self.tournament_id).first()
            if tournament:
                tournament.is_active = False
                db.session.commit()

        # Disable all buttons
        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "❌ TORNEO CANCELADO"

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("✅ Torneo cancelado.", ephemeral=True)

@tree.command(name="ver_inscritos", description="Ver la lista de jugadores inscritos en la partida privada")
async def ver_inscritos(interaction: discord.Interaction):
    """Muestra la lista de jugadores inscritos en la partida privada"""
    with app.app_context():
        # Get all users from database
        users = User.query.all()

        if not users:
            await interaction.response.send_message(
                "⚠️ No hay jugadores inscritos en la partida privada.",
                ephemeral=True
            )
            return

        # Create embed
        embed = discord.Embed(
            title="📋 Lista de Jugadores Inscritos",
            description="Jugadores registrados para la partida privada",
            color=0x3498db
        )

        # Add fields for each player
        for user in users:
            # Get Discord member object
            member = interaction.guild.get_member(int(user.discord_id))
            if member:
                field_value = f"Activision ID: `{user.activision_id}`\nK/D: `{user.kd_ratio}`"
                embed.add_field(
                    name=f"👤 {member.display_name}",
                    value=field_value,
                    inline=True
                )

        # Add timestamp
        embed.timestamp = datetime.utcnow()

        await interaction.response.send_message(embed=embed)

@tree.command(name="help", description="Muestra la ayuda del bot")
@app_commands.describe(publico="Mostrar la ayuda públicamente")
async def help_command(interaction: discord.Interaction, publico: bool = False):
    """Muestra la ayuda del bot"""
    embed = discord.Embed(
        title="🤖 Warzone Team Finder - Ayuda",
        description="Este bot te ayuda a encontrar compañeros para jugar Warzone",
        color=0x3498db
    )

    # Add command descriptions
    embed.add_field(
        name="/registrar",
        value="Registra tu Activision ID y K/D ratio para poder unirte a equipos",
        inline=False
    )

    embed.add_field(
        name="/perfil",
        value="Muestra tu perfil registrado con tu Activision ID y K/D",
        inline=False
    )

    embed.add_field(
        name="/buscar_equipo",
        value="Crea una búsqueda de equipo donde otros jugadores pueden unirse",
        inline=False
    )

    embed.add_field(
        name="/ver_perfil",
        value="Ver tu perfil o el de otro usuario. Puedes hacerlo público usando la opción 'publico'",
        inline=False
    )

    embed.add_field(
        name="/jugadores",
        value="Muestra los jugadores que están jugando Call of Duty actualmente",
        inline=False
    )

    embed.add_field(
        name="/jugadores_inscritos",
        value="Muestra la lista de todos los jugadores registrados en el bot",
        inline=False
    )

    embed.add_field(
        name="/crear_privada",
        value="Crear una partida privada personalizada con modo y tamaño de equipo",
        inline=False
    )

    embed.add_field(
        name="/ver_inscritos",
        value="Ver la lista de jugadores inscritos en la partida privada",
        inline=False
    )

    embed.add_field(
        name="/help",
        value="Muestra este mensaje de ayuda",
        inline=False
    )

    # Add buttons descriptions
    embed.add_field(
        name="Botones de la búsqueda",
        value="**🔄 Actualizar**: Actualiza el canal de voz del equipo al que estás conectado\n"
              "**✅ Unirse**: Únete a una búsqueda de equipo\n"
              "**❌ Cancelar**: Cancela una búsqueda de equipo (solo el creador)",
        inline=False
    )

    # Add footer with bot version
    embed.set_footer(text="Warzone Team Finder v1.0")

    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    """Handle errors from slash commands"""
    if isinstance(error, app_commands.errors.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏱️ Este comando está en cooldown. Inténtalo de nuevo en {error.retry_after:.2f} segundos.",
            ephemeral=True
        )
    elif isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "⚠️ No tienes permisos para usar este comando.",
            ephemeral=True
        )
    else:
        # Log the error
        logger.error(f"Command error: {error}")

        # Notify the user
        await interaction.response.send_message(
            f"❌ Se produjo un error al ejecutar el comando: `{error}`\n"
            "Por favor, inténtalo de nuevo más tarde.",
            ephemeral=True
        )

@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler"""
    logger.error(f"Event error in {event}: {args} {kwargs}")

# Flask web application setup
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# Configure database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///instance/warzone_teams.db"

# Initialize the app with the extension
db.init_app(app)

# Define DB models inline
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    discord_id = db.Column(db.String(64), unique=True, nullable=False)
    username = db.Column(db.String(64), nullable=False)
    discriminator = db.Column(db.String(6), nullable=True)
    activision_id = db.Column(db.String(40), nullable=True)
    kd_ratio = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    teams = db.relationship('Team', backref='owner', lazy=True)
    team_memberships = db.relationship('TeamMember', backref='user', lazy=True)

    def __repr__(self):
        return f'<User {self.username}#{self.discriminator}>'

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    platform = db.Column(db.String(20), nullable=False)
    mode = db.Column(db.String(30), nullable=False)
    kd_minimum = db.Column(db.Float, default=0.0)
    max_players = db.Column(db.Integer, default=4)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    discord_message_id = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    members = db.relationship('TeamMember', backref='team', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Team {self.id} - {self.mode}>'

class TeamMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<TeamMember {self.user_id} in team {self.team_id}>'

# Create the database tables
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    """Home page, shows information about the bot"""
    return render_template('index.html')

@app.route('/commands')
def commands():
    """Shows available bot commands"""
    return render_template('commands.html')

@app.route('/about')
def about():
    """About page with bot information"""
    return render_template('about.html')

@app.route('/add-bot')
def add_bot():
    """Page for adding the bot to Discord servers"""
    return render_template('add_bot.html')

# Function to run the Discord bot
async def run_discord_bot():
    async with bot:
        try:
            await bot.start(TOKEN)
        except discord.errors.LoginFailure:
            logger.error("Invalid Discord token provided. Please check your .env file.")
        except Exception as e:
            logger.error(f"Error starting bot: {e}")

# Importar keep_alive para mantener el bot corriendo 24/7
from keep_alive import keep_alive

# Run both the Flask app and Discord bot in parallel when directly running this file
if __name__ == "__main__":
    # Iniciar el servidor keep_alive para mantener el bot activo
    keep_alive()

    # Run the Flask app in a separate thread if running independently
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)).start()

    # Run the Discord bot in the main thread
    try:
        asyncio.run(run_discord_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")