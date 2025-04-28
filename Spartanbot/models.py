from datetime import datetime
from app import db
from flask_login import UserMixin

class User(UserMixin, db.Model):
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