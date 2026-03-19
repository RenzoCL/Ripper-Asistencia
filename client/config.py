# client/config.py
import os

# EL SWITCH MAESTRO
# Cambia a True cuando quieras usar Render desde casa
# Cambia a False cuando estés en el colegio usando tu servidor local
MODO_NUBE = False 

# Direcciones del servidor
URL_LOCAL = "http://localhost:8000"
URL_NUBE  = "https://tu-app-en-render.onrender.com"

# La URL que el sistema usará realmente
BASE_URL = URL_NUBE if MODO_NUBE else URL_LOCAL

# Timeout: En la nube (Render) es mejor dar un poco más de tiempo (15s) 
# porque la conexión a internet puede variar.
TIMEOUT = 15 if MODO_NUBE else 10