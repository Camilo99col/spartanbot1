import os
from flask import Flask, jsonify
from threading import Thread
import datetime


class Monitor:  # Assuming a basic Monitor class structure

    def __init__(self, config):
        self.config = config

    def run(self):
        print(f"Monitoring website: {self.config['website']}"
              )  # Placeholder monitoring logic


app = Flask(__name__)


@app.route('/')
def home():
    return "Bot is alive and running!"


@app.route('/status')
def status():
    """Endpoint para monitorización con información detallada"""
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uptime = get_uptime()

    status_data = {
        "status": "online",
        "message": "Bot is running properly",
        "timestamp": current_time,
        "uptime": uptime,
        "service": "Warzone Team Finder Bot"
    }

    return jsonify(status_data)


def get_uptime():
    """Obtiene el tiempo que ha estado funcionando el servidor"""
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
            return str(datetime.timedelta(seconds=uptime_seconds))
    except:
        return "Unknown"


def run():
    app.run(host='0.0.0.0', port=8080)


def keep_alive():
    """Keep the app running by starting a web server on a separate thread."""
    t = Thread(target=run)
    t.start()
    keepAlive = app
    monitor = Monitor({
        'website':
        f'https://{os.getenv("REPL_SLUG")}.{os.getenv("REPL_OWNER")}.repl.co',
        'title': 'Warzone Team Finder Bot',
        'interval': 2  # minutos
    })
    monitor.run()


if __name__ == "__main__":
    keep_alive()
