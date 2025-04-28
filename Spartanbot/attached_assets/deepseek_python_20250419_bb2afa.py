import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Almacenamiento temporal (en producción usa una base de datos)
inscritos = []
activision_ids = {}

class TeamFinderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.members_joined = []

    @discord.ui.button(label="Unirse", style=discord.ButtonStyle.success, emoji="✅", custom_id="join_team")
    async def join_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.members_joined:
            self.members_joined.append(interaction.user)
            await interaction.response.send_message(
                f"{interaction.user.mention} se ha unido al equipo.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("⚠️ Ya estás en este equipo.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    try:
        synced = await tree.sync()
        print(f"🌐 {len(synced)} comandos sincronizados")
        bot.add_view(TeamFinderView())
    except Exception as e:
        print(f"❌ Error: {e}")

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
    ]
)
async def buscar_equipo(
    interaction: discord.Interaction,
    plataforma: app_commands.Choice[str],
    modo: app_commands.Choice[str],
    kd_minimo: float = 0.0
):
    embed = discord.Embed(
        title="📣 BÚSQUEDA DE EQUIPO",
        description=f"{interaction.user.mention} busca equipo",
        color=0x00ff00
    )
    embed.add_field(name="🖥️ Plataforma", value=plataforma.value, inline=True)
    embed.add_field(name="🎮 Modo", value=modo.value, inline=True)
    embed.add_field(name="📊 K/D Mínimo", value=str(kd_minimo), inline=True)
    await interaction.response.send_message(embed=embed, view=TeamFinderView())

bot.run(TOKEN)