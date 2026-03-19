"""
scripts/setup/primer_arranque.py
==================================
Asistente interactivo de configuración inicial.

Guía al administrador paso a paso para:
  1. Configurar la IP del servidor en .env
  2. Configurar el bot de Telegram
  3. Crear usuarios del sistema (porteros, tutores)
  4. Importar el primer lote de alumnos desde CSV
  5. Verificar que todo funciona

Uso:
    python scripts/setup/primer_arranque.py

Requiere que el servidor ya esté corriendo:
    uvicorn server.main:app --host 0.0.0.0 --port 8000
"""

import sys
import os
import socket
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Colores ANSI para la terminal
VERDE   = "\033[92m"
ROJO    = "\033[91m"
AMARILLO= "\033[93m"
AZUL    = "\033[94m"
BOLD    = "\033[1m"
RESET   = "\033[0m"

def titulo(texto):
    print(f"\n{BOLD}{AZUL}{'='*60}{RESET}")
    print(f"{BOLD}{AZUL}  {texto}{RESET}")
    print(f"{BOLD}{AZUL}{'='*60}{RESET}\n")

def ok(texto):
    print(f"  {VERDE}✅ {texto}{RESET}")

def warn(texto):
    print(f"  {AMARILLO}⚠️  {texto}{RESET}")

def error(texto):
    print(f"  {ROJO}❌ {texto}{RESET}")

def preguntar(prompt, default=""):
    val = input(f"  {BOLD}{prompt}{RESET}" + (f" [{default}]" if default else "") + ": ").strip()
    return val or default

def confirmar(prompt) -> bool:
    resp = input(f"  {BOLD}{prompt}{RESET} (s/n): ").strip().lower()
    return resp in ("s", "si", "sí", "y", "yes")


def detectar_ip_local() -> str:
    """Detecta la IP de la máquina en la LAN."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.1.100"


def paso_1_verificar_servidor():
    titulo("PASO 1 — Verificar que el servidor está corriendo")

    import requests
    url = "http://localhost:8000/health"
    try:
        r = requests.get(url, timeout=3)
        if r.ok:
            ok(f"Servidor respondiendo en {url}")
            return True
        else:
            error(f"El servidor respondió con código {r.status_code}")
    except Exception as e:
        error(f"No se pudo conectar al servidor: {e}")
        print(f"\n  Iniciar el servidor primero en otra terminal:")
        print(f"  {AMARILLO}uvicorn server.main:app --host 0.0.0.0 --port 8000{RESET}")
        return False
    return False


def paso_2_configurar_red():
    titulo("PASO 2 — Configurar red local (LAN)")

    ip_detectada = detectar_ip_local()
    print(f"  IP detectada de este servidor: {BOLD}{ip_detectada}{RESET}")
    print(f"  Esta IP es la que usarán los clientes (PCs de portería/aulas).")
    print()

    env_path = Path(".env")
    if not env_path.exists():
        error(".env no encontrado. Ejecutar setup_inicial.py primero.")
        return

    content = env_path.read_text()
    print(f"  URL actual del servidor: http://{ip_detectada}:8000")
    print(f"  Panel Admin: http://{ip_detectada}:8000/admin")
    print(f"  API Docs:    http://{ip_detectada}:8000/docs")

    ok(f"Red configurada. IP del servidor: {ip_detectada}")
    print(f"\n  {AMARILLO}Guardar esta IP — los clientes la necesitan en su .env:{RESET}")
    print(f"  SERVER_URL=http://{ip_detectada}:8000")


def paso_3_configurar_telegram():
    titulo("PASO 3 — Configurar notificaciones Telegram (opcional)")

    env_path = Path(".env")
    content = env_path.read_text() if env_path.exists() else ""

    # Verificar si ya está configurado
    if "TELEGRAM_BOT_TOKEN=" in content:
        token_linea = [l for l in content.split("\n") if l.startswith("TELEGRAM_BOT_TOKEN=")][0]
        token_actual = token_linea.split("=", 1)[1].strip()
        if token_actual and token_actual != "":
            ok("Telegram ya está configurado.")
            return

    print("  Pasos para crear el bot:")
    print(f"  {AZUL}1.{RESET} Abrir Telegram y buscar @BotFather")
    print(f"  {AZUL}2.{RESET} Enviar: /newbot")
    print(f"  {AZUL}3.{RESET} Seguir instrucciones → copiar el token")
    print(f"  {AZUL}4.{RESET} Para obtener tu chat_id: buscar @userinfobot y enviarle un mensaje")
    print()

    if not confirmar("¿Configurar Telegram ahora?"):
        warn("Omitido. Configurar después editando el archivo .env")
        return

    token    = preguntar("Token del bot (de @BotFather)")
    chat_id_porteria = preguntar("Chat ID de portería")
    chat_id_admin    = preguntar("Chat ID del admin (puede ser el mismo)")

    if token and chat_id_porteria:
        # Actualizar .env
        lineas = content.split("\n")
        nuevas = []
        for l in lineas:
            if l.startswith("TELEGRAM_BOT_TOKEN="):
                nuevas.append(f"TELEGRAM_BOT_TOKEN={token}")
            elif l.startswith("TELEGRAM_CHAT_ID_PORTERIA="):
                nuevas.append(f"TELEGRAM_CHAT_ID_PORTERIA={chat_id_porteria}")
            elif l.startswith("TELEGRAM_CHAT_ID_ADMIN="):
                nuevas.append(f"TELEGRAM_CHAT_ID_ADMIN={chat_id_admin or chat_id_porteria}")
            else:
                nuevas.append(l)

        env_path.write_text("\n".join(nuevas))
        ok("Telegram configurado en .env")
        warn("Reiniciar el servidor para aplicar los cambios de Telegram.")
    else:
        warn("Omitido — token o chat_id vacíos.")


def paso_4_crear_usuarios():
    titulo("PASO 4 — Crear usuarios del sistema")

    print("  Usuarios necesarios:")
    print(f"  {AZUL}•{RESET} Porteros: uno por PC de portería/aula")
    print(f"  {AZUL}•{RESET} Tutores: uno por grado (opcional)")
    print()
    print("  El usuario 'admin' (admin/admin1234) ya existe.")
    print(f"  {ROJO}⚠️  CAMBIAR LA CONTRASEÑA DEL ADMIN antes de continuar.{RESET}")
    print()

    if not confirmar("¿Crear usuarios ahora desde la terminal?"):
        print(f"\n  Crear usuarios después desde:")
        print(f"  {AMARILLO}• Panel Web: http://IP_SERVIDOR:8000/admin → Usuarios{RESET}")
        print(f"  {AMARILLO}• API: POST /api/admin/usuarios{RESET}")
        return

    import requests

    # Login como admin
    login_url = "http://localhost:8000/api/auth/login"
    print("\n  Autenticando como admin...")
    nueva_pass = preguntar("Nueva contraseña para 'admin'", "admin1234")

    r = requests.post(login_url, json={"username": "admin", "password": "admin1234"})
    if not r.ok:
        # Try with new password
        r = requests.post(login_url, json={"username": "admin", "password": nueva_pass})

    if not r.ok:
        error("No se pudo autenticar. Verificar que el servidor esté corriendo.")
        return

    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Cambiar contraseña del admin
    if nueva_pass != "admin1234":
        admin_id = r.json()["usuario"]["id"]
        r2 = requests.patch(
            f"http://localhost:8000/api/admin/usuarios/{admin_id}/cambiar-password",
            params={"nueva_password": nueva_pass},
            headers=headers,
        )
        if r2.ok:
            ok(f"Contraseña del admin actualizada")
        else:
            warn("No se pudo cambiar la contraseña")

    # Crear porteros
    n_porteros = preguntar("¿Cuántos porteros/puntos de acceso?", "1")
    for i in range(int(n_porteros)):
        print(f"\n  Portero #{i+1}:")
        username = preguntar(f"  Username", f"portero{i+1}")
        nombre   = preguntar(f"  Nombre completo", f"Portero {i+1}")
        password = preguntar(f"  Contraseña", "portero1234")

        r = requests.post("http://localhost:8000/api/admin/usuarios", json={
            "username": username, "password": password,
            "nombre_display": nombre, "rol": "PORTERO",
        }, headers=headers)

        if r.ok:
            ok(f"Portero '{username}' creado")
        else:
            error(f"Error: {r.json().get('detail', r.text)}")

    # Crear tutores (opcional)
    if confirmar("\n  ¿Crear tutores ahora?"):
        n_tutores = preguntar("¿Cuántos tutores?", "1")
        for i in range(int(n_tutores)):
            print(f"\n  Tutor #{i+1}:")
            username = preguntar(f"  Username", f"tutor{i+1}")
            nombre   = preguntar(f"  Nombre completo", f"Tutor {i+1}")
            grado    = preguntar(f"  Grado asignado (ej: 3A)", "")
            password = preguntar(f"  Contraseña", "tutor1234")

            r = requests.post("http://localhost:8000/api/admin/usuarios", json={
                "username": username, "password": password,
                "nombre_display": nombre, "rol": "TUTOR",
                "grado_asignado": grado or None,
            }, headers=headers)

            if r.ok:
                ok(f"Tutor '{username}' (grado {grado}) creado")
            else:
                error(f"Error: {r.json().get('detail', r.text)}")


def paso_5_importar_alumnos():
    titulo("PASO 5 — Importar alumnos")

    print("  Opciones para registrar alumnos:")
    print(f"  {AZUL}A.{RESET} Importar desde archivo CSV (masivo — recomendado)")
    print(f"  {AZUL}B.{RESET} Crear uno a uno desde el Panel Admin")
    print(f"  {AZUL}C.{RESET} Omitir ahora — hacerlo después")
    print()

    opcion = preguntar("Elegir opción", "C").upper()

    if opcion == "A":
        csv_path = preguntar("Ruta al archivo CSV de alumnos")
        if not Path(csv_path).exists():
            error(f"Archivo no encontrado: {csv_path}")
            return

        print(f"\n  Ejecutando importación (modo dry-run primero)...")
        resultado = subprocess.run(
            [sys.executable, "scripts/setup/importar_alumnos_csv.py",
             "--archivo", csv_path, "--dry-run"],
            capture_output=True, text=True
        )
        print(resultado.stdout)

        if confirmar("  ¿Confirmar importación real?"):
            subprocess.run(
                [sys.executable, "scripts/setup/importar_alumnos_csv.py",
                 "--archivo", csv_path],
            )

    elif opcion == "B":
        ip = detectar_ip_local()
        print(f"\n  Panel Admin: {AZUL}http://{ip}:8000/admin{RESET}")
        print(f"  Ir a: Alumnos → + Nuevo alumno")
    else:
        warn("Omitido. Importar alumnos desde el Panel Admin cuando esté listo.")


def paso_6_verificacion_final():
    titulo("PASO 6 — Verificación final")

    import requests

    checks = [
        ("Servidor responde /health",      "http://localhost:8000/health",      lambda r: r.ok),
        ("Panel Admin accesible",          "http://localhost:8000/admin",        lambda r: r.ok),
        ("API Docs accesible",             "http://localhost:8000/docs",         lambda r: r.ok),
        ("Endpoint login responde",        "http://localhost:8000/api/auth/login", None),
    ]

    todos_ok = True
    for nombre, url, check in checks:
        try:
            r = requests.get(url, timeout=3)
            if check is None or check(r):
                ok(nombre)
            else:
                warn(f"{nombre} (código {r.status_code})")
                todos_ok = False
        except Exception as e:
            error(f"{nombre}: {e}")
            todos_ok = False

    ip = detectar_ip_local()
    print()
    if todos_ok:
        ok("¡Sistema listo para producción!")
    else:
        warn("Algunos checks fallaron — verificar arriba.")

    print(f"\n  {'='*58}")
    print(f"  {BOLD}ACCESOS DEL SISTEMA:{RESET}")
    print(f"  {'='*58}")
    print(f"  Panel Admin Web:   {AZUL}http://{ip}:8000/admin{RESET}")
    print(f"  API Docs:          {AZUL}http://{ip}:8000/docs{RESET}")
    print(f"  Cliente Portería:  python client/ui/porteria_app.py")
    print(f"  Cliente Tutor:     python client/ui/tutor_app.py")
    print(f"  Tests:             pytest tests/ -v")
    print(f"  {'='*58}")
    print(f"\n  {AMARILLO}En los PCs cliente (portería/aulas), crear .env con:{RESET}")
    print(f"  SERVER_URL=http://{ip}:8000")


def main():
    print(f"\n{BOLD}{AZUL}{'='*60}{RESET}")
    print(f"{BOLD}{AZUL}   COLEGIO ASISTENCIA — Asistente de Primer Arranque{RESET}")
    print(f"{BOLD}{AZUL}{'='*60}{RESET}")
    print(f"\n  Este asistente configura el sistema en {BOLD}~5 minutos{RESET}.")
    print(f"  Puedes saltarte cualquier paso y configurarlo después.")

    if not paso_1_verificar_servidor():
        print(f"\n  {ROJO}Iniciar el servidor antes de continuar.{RESET}")
        sys.exit(1)

    paso_2_configurar_red()
    paso_3_configurar_telegram()
    paso_4_crear_usuarios()
    paso_5_importar_alumnos()
    paso_6_verificacion_final()

    print(f"\n{BOLD}¡Configuración completada! 🎉{RESET}\n")


if __name__ == "__main__":
    main()
