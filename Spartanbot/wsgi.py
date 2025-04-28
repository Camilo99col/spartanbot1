from main import app
from threading import Thread
import os
import sys
import time
import signal
import subprocess

# Importar el sistema keep-alive
from keep_alive import keep_alive

# Agregar señal para manejar la detención limpia del bot
def signal_handler(sig, frame):
    print('Deteniendo el bot y el servidor web...')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Iniciar el servidor keep-alive en un hilo separado
keep_alive()

# Iniciar el bot de Discord en un proceso separado
def start_bot():
    while True:
        print("Iniciando el bot de Discord...")
        bot_process = subprocess.Popen([sys.executable, "main.py"])
        
        # Esperar al proceso del bot
        bot_process.wait()
        
        # Si el bot se detiene, esperar un poco y reiniciar
        print("El bot se detuvo, reiniciando en 10 segundos...")
        time.sleep(10)

# Iniciar el bot en un hilo separado
bot_thread = Thread(target=start_bot, daemon=True)
bot_thread.start()

# Iniciar el servidor web Flask
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)