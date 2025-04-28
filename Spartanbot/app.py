import os
from flask import Flask, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# Configure database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///instance/warzone_teams.db"

# Initialize the app with the extension
db.init_app(app)

# Import models
from models import User, Team, TeamMember

# Create tables
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)