"""
scripts/setup/diagnostico.py
==============================
Diagnóstico completo del sistema antes de entrar en producción.

Verifica TODOS los componentes críticos y reporta problemas
con instrucciones claras para resolverlos.

Uso:
    python scripts/setup/diagnostico.py                    # Diagnóstico básico
    python scripts/setup/diagnostico.py --servidor-activo  # Incluye tests de API

Salida: VERDE = OK, AMARILLO = Advertencia, ROJO = Error crítico
"""

import sys
import os
import socket
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ── Colores ANSI ─────────────────────────────────────────────────────
G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; B = "\033[94m"
BOLD = "\033[1m"; DIM = "\033[2m"; RESET = "\033[0m"

ok   = lambda t: print(f"  {G}✅  {t}{RESET}")
warn = lambda t: print(f"  {Y}⚠️   {t}{RESET}")
err  = lambda t: print(f"  {R}❌  {t}{RESET}")
info = lambda t: print(f"  {B}ℹ️   {t}{RESET}")
head = lambda t: print(f"\n{BOLD}{B}{'─'*55}{RESET}\n{BOLD}  {t}{RESET}")

ERRORES_CRITICOS = []
ADVERTENCIAS     = []


def registrar_error(msg):
    ERRORES_CRITICOS.append(msg)
    err(msg)


def registrar_warn(msg):
    ADVERTENCIAS.append(msg)
    warn(msg)


# ════════════════════════════════════════════════════════════════════
# 1. PYTHON
# ════════════════════════════════════════════════════════════════════
def check_python():
    head("1. Python")
    v = sys.version_info
    if v >= (3, 10):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        registrar_error(f"Python {v.major}.{v.minor} — Se requiere 3.10+. Actualizar Python.")


# ════════════════════════════════════════════════════════════════════
# 2. DEPENDENCIAS
# ════════════════════════════════════════════════════════════════════
def check_dependencias():
    head("2. Dependencias Python")

    criticas = [
        ("fastapi",          "fastapi",          "pip install fastapi"),
        ("uvicorn",          "uvicorn",          "pip install 'uvicorn[standard]'"),
        ("sqlalchemy",       "sqlalchemy",       "pip install sqlalchemy"),
        ("pydantic",         "pydantic",         "pip install pydantic"),
        ("pydantic_settings","pydantic-settings","pip install pydantic-settings"),
        ("jose",             "python-jose",      "pip install 'python-jose[cryptography]'"),
        ("passlib",          "passlib",          "pip install passlib"),
        ("bcrypt",           "bcrypt==4.0.1",    "pip install bcrypt==4.0.1"),
        ("cv2",              "opencv-contrib-python", "pip install opencv-contrib-python"),
        ("numpy",            "numpy",            "pip install numpy"),
        ("PIL",              "Pillow",           "pip install Pillow"),
        ("httpx",            "httpx",            "pip install httpx"),
        ("apscheduler",      "apscheduler",      "pip install apscheduler"),
        ("pytz",             "pytz",             "pip install pytz"),
        ("dotenv",           "python-dotenv",    "pip install python-dotenv"),
        ("multipart",        "python-multipart", "pip install python-multipart"),
        ("aiofiles",         "aiofiles",         "pip install aiofiles"),
    ]

    opcionales = [
        ("face_recognition", "face-recognition (HOG/CNN)", "pip install face-recognition"),
        ("openpyxl",         "openpyxl (Excel export)",    "pip install openpyxl"),
        ("reportlab",        "reportlab (PDF export)",     "pip install reportlab"),
        ("selenium",         "selenium (WhatsApp Web)",    "pip install selenium"),
        ("websocket",        "websocket-client",           "pip install websocket-client"),
    ]

    for mod, nombre, cmd in criticas:
        try:
            m = __import__(mod)
            version = getattr(m, "__version__", "?")
            ok(f"{nombre} ({version})")
        except ImportError:
            registrar_error(f"{nombre} NO instalado → {cmd}")

    print(f"\n  {DIM}Opcionales:{RESET}")
    for mod, nombre, cmd in opcionales:
        try:
            m = __import__(mod)
            version = getattr(m, "__version__", "?")
            ok(f"{nombre} ({version})")
        except ImportError:
            info(f"{nombre} no instalado (opcional) → {cmd}")

    # Verificar bcrypt específicamente
    try:
        import bcrypt
        v = tuple(int(x) for x in bcrypt.__version__.split(".")[:2])
        if v >= (4, 1):
            registrar_warn(
                f"bcrypt {bcrypt.__version__} puede romper passlib. "
                "Instalar: pip install bcrypt==4.0.1"
            )
    except Exception:
        pass

    # Verificar cv2.face (requiere opencv-contrib)
    try:
        import cv2
        if not hasattr(cv2, "face"):
            registrar_error(
                "cv2.face NO disponible — instalar opencv-CONTRIB-python "
                "(no opencv-python): pip install opencv-contrib-python"
            )
        else:
            ok(f"cv2.face (LBPH disponible)")
    except ImportError:
        pass


# ════════════════════════════════════════════════════════════════════
# 3. ARCHIVOS Y DIRECTORIOS
# ════════════════════════════════════════════════════════════════════
def check_estructura():
    head("3. Estructura de archivos")
    base = Path(__file__).parent.parent.parent

    archivos_criticos = [
        "server/main.py",
        "server/db/models.py",
        "server/services/attendance_service.py",
        "server/services/recognition/recognition_service.py",
        "client/ui/porteria_app.py",
        ".env",
    ]
    for f in archivos_criticos:
        p = base / f
        if p.exists():
            ok(f"{f}")
        else:
            msg = f"{f} — NO encontrado"
            if f == ".env":
                registrar_warn(f"{msg} → Copiar .env.example a .env y configurar")
            else:
                registrar_error(msg)

    # Directorios de datos
    dirs_datos = [
        "server/data",
        "server/data/photos",
        "server/data/encodings",
        "server/data/backups",
        "server/data/logs",
    ]
    print()
    for d in dirs_datos:
        p = base / d
        if p.exists():
            ok(f"{d}/")
        else:
            registrar_warn(f"{d}/ no existe → ejecutar: python scripts/setup/setup_inicial.py")
            break  # Si falta el primero, probablemente faltan todos

    # Archivo de DB
    from dotenv import load_dotenv
    load_dotenv(base / ".env")
    db_url = os.getenv("DATABASE_URL", "sqlite:///./server/data/asistencia.db")
    db_path = Path(db_url.replace("sqlite:///", "")).resolve()
    if not db_path.is_absolute():
        db_path = base / db_url.replace("sqlite:///./", "")

    print()
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        ok(f"Base de datos: {db_path.name} ({size_mb:.2f} MB)")
    else:
        registrar_warn(
            f"DB no encontrada en {db_path} → "
            "Se creará automáticamente al iniciar el servidor"
        )


# ════════════════════════════════════════════════════════════════════
# 4. BASE DE DATOS
# ════════════════════════════════════════════════════════════════════
def check_base_datos():
    head("4. Base de datos SQLite")
    base = Path(__file__).parent.parent.parent

    from dotenv import load_dotenv
    load_dotenv(base / ".env")
    db_url  = os.getenv("DATABASE_URL", "sqlite:///./server/data/asistencia.db")
    db_path = base / db_url.replace("sqlite:///./", "")

    if not db_path.exists():
        info("DB no existe aún — se creará al iniciar el servidor")
        return

    try:
        conn = sqlite3.connect(str(db_path))

        # Integrity check
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result[0] == "ok":
            ok("Integridad de la DB: OK")
        else:
            registrar_error(f"DB corrupta: {result[0]}")

        # WAL mode
        wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if wal == "wal":
            ok("WAL mode: activo")
        else:
            registrar_warn(f"WAL mode no activo (actual: {wal}) — se activará al reiniciar el servidor")

        # Tablas
        tablas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        esperadas = {"alumno", "asistencia", "usuario_sistema", "configuracion",
                     "tutor_contacto", "justificacion", "notificacion_log"}
        faltantes = esperadas - tablas
        if faltantes:
            registrar_warn(f"Tablas faltantes: {faltantes} → Iniciar el servidor para crearlas")
        else:
            ok(f"Todas las tablas presentes ({len(tablas)})")

        # Estadísticas
        try:
            n_alumnos = conn.execute("SELECT COUNT(*) FROM alumno WHERE activo=1").fetchone()[0]
            n_registros = conn.execute("SELECT COUNT(*) FROM asistencia").fetchone()[0]
            n_usuarios = conn.execute("SELECT COUNT(*) FROM usuario_sistema").fetchone()[0]
            info(f"Alumnos activos: {n_alumnos} | Registros asistencia: {n_registros} | Usuarios: {n_usuarios}")

            if n_alumnos == 0:
                registrar_warn("No hay alumnos registrados → importar con scripts/setup/importar_alumnos_csv.py")

            enc_validos = conn.execute(
                "SELECT COUNT(*) FROM alumno WHERE encoding_valido=1"
            ).fetchone()[0]
            if n_alumnos > 0:
                pct_enc = enc_validos / n_alumnos * 100
                if pct_enc < 50:
                    registrar_warn(
                        f"Solo {enc_validos}/{n_alumnos} alumnos tienen encoding facial "
                        f"({pct_enc:.0f}%) — el reconocimiento no funcionará bien"
                    )
                else:
                    ok(f"Encodings válidos: {enc_validos}/{n_alumnos} ({pct_enc:.0f}%)")
        except sqlite3.OperationalError:
            pass  # Tablas aún no creadas

        conn.close()
    except Exception as e:
        registrar_error(f"Error accediendo a la DB: {e}")


# ════════════════════════════════════════════════════════════════════
# 5. CONFIGURACIÓN .env
# ════════════════════════════════════════════════════════════════════
def check_env():
    head("5. Variables de entorno (.env)")
    base = Path(__file__).parent.parent.parent
    env  = base / ".env"

    if not env.exists():
        registrar_error(".env no encontrado → copiar .env.example a .env")
        return

    from dotenv import load_dotenv
    load_dotenv(env)

    secret = os.getenv("SECRET_KEY", "")
    if not secret or secret in ("cambia_esto_en_produccion_12345", "CAMBIA_ESTO_EN_PRODUCCION"):
        registrar_warn("SECRET_KEY es la clave por defecto — cambiar por una aleatoria antes de producción")
    else:
        ok(f"SECRET_KEY configurada ({len(secret)} caracteres)")

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        ok(f"TELEGRAM_BOT_TOKEN configurado")
    else:
        info("TELEGRAM_BOT_TOKEN no configurado (notificaciones Telegram deshabilitadas)")

    tg_porteria = os.getenv("TELEGRAM_CHAT_ID_PORTERIA", "")
    if tg_porteria:
        ok(f"TELEGRAM_CHAT_ID_PORTERIA configurado")
    elif tg_token:
        registrar_warn("TELEGRAM_BOT_TOKEN configurado pero TELEGRAM_CHAT_ID_PORTERIA vacío")

    modelo = os.getenv("DEFAULT_RECOGNITION_MODEL", "HOG")
    ok(f"Modelo de IA default: {modelo}")


# ════════════════════════════════════════════════════════════════════
# 6. RED LAN
# ════════════════════════════════════════════════════════════════════
def check_red():
    head("6. Red y conectividad")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_local = s.getsockname()[0]
        s.close()
        ok(f"IP del servidor en LAN: {ip_local}")
        info(f"Los clientes deben usar: SERVER_URL=http://{ip_local}:8000")
    except Exception:
        registrar_warn("No se pudo detectar la IP local")

    # Verificar si el puerto 8000 está disponible
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex(("127.0.0.1", 8000))
        s.close()
        if result == 0:
            ok("Puerto 8000: en uso (servidor corriendo)")
        else:
            info("Puerto 8000: libre (servidor no iniciado)")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
# 7. API (si el servidor está activo)
# ════════════════════════════════════════════════════════════════════
def check_api():
    head("7. API del servidor (requiere servidor activo)")

    try:
        import requests
        base_url = f"http://127.0.0.1:{os.getenv('SERVER_PORT', '8000')}"

        # Health
        r = requests.get(f"{base_url}/health", timeout=3)
        if r.ok:
            data = r.json()
            ok(f"GET /health → {data.get('status')} (v{data.get('version', '?')})")
        else:
            registrar_warn(f"GET /health → HTTP {r.status_code}")

        # Login admin
        r = requests.post(f"{base_url}/api/auth/login",
                          json={"username": "admin", "password": "admin1234"}, timeout=3)
        if r.ok:
            registrar_warn(
                "Login admin/admin1234 exitoso — "
                "¡CAMBIAR LA CONTRASEÑA antes de producción!"
            )
            token = r.json()["access_token"]

            # Test endpoint protegido
            r2 = requests.get(f"{base_url}/api/admin/config",
                              headers={"Authorization": f"Bearer {token}"}, timeout=3)
            if r2.ok:
                cfgs = r2.json()
                ok(f"GET /api/admin/config → {len(cfgs)} parámetros")
            else:
                registrar_warn(f"GET /api/admin/config → HTTP {r2.status_code}")

        elif r.status_code == 401:
            ok("Login admin/admin1234 → contraseña ya fue cambiada ✓")
        else:
            registrar_warn(f"POST /api/auth/login → HTTP {r.status_code}")

        # WebSocket status
        r3 = requests.get(f"{base_url}/ws/status", timeout=3)
        if r3.ok:
            ws_data = r3.json()
            ok(f"GET /ws/status → {ws_data.get('clientes_conectados', 0)} clientes WS conectados")

    except ImportError:
        info("requests no instalado — saltando tests de API")
    except Exception as e:
        info(f"Servidor no activo o no accesible: {e}")
        info("Iniciar el servidor y ejecutar: python scripts/setup/diagnostico.py --servidor-activo")


# ════════════════════════════════════════════════════════════════════
# 8. ENCODINGS Y FOTOS
# ════════════════════════════════════════════════════════════════════
def check_encodings():
    head("8. Fotos y encodings de alumnos")
    base = Path(__file__).parent.parent.parent

    from dotenv import load_dotenv
    load_dotenv(base / ".env")

    photos_dir   = Path(os.getenv("PHOTOS_DIR",   "./server/data/photos"))
    encodings_dir = Path(os.getenv("ENCODINGS_DIR", "./server/data/encodings"))

    if not photos_dir.is_absolute():
        photos_dir   = base / photos_dir
        encodings_dir = base / encodings_dir

    # Contar fotos
    total_fotos = 0
    alumnos_con_fotos = 0
    if photos_dir.exists():
        for carpeta in photos_dir.iterdir():
            if carpeta.is_dir():
                n = len(list(carpeta.glob("*.jpg"))) + len(list(carpeta.glob("*.png")))
                if n > 0:
                    alumnos_con_fotos += 1
                    total_fotos += n
        ok(f"Fotos: {total_fotos} imágenes de {alumnos_con_fotos} alumnos")
        if alumnos_con_fotos < 3:
            registrar_warn("Muy pocas fotos — subir fotos con POST /api/alumnos/{id}/fotos")
    else:
        info("Directorio de fotos no existe aún")

    # Contar encodings
    if encodings_dir.exists():
        pkls = list(encodings_dir.glob("alumno_*.pkl"))
        lbph = encodings_dir / "lbph_model.yml"
        ok(f"Encodings HOG/CNN: {len(pkls)} archivos .pkl")
        if lbph.exists():
            size_kb = lbph.stat().st_size / 1024
            ok(f"Modelo LBPH: lbph_model.yml ({size_kb:.0f} KB)")
        else:
            info("Modelo LBPH no entrenado (normal si se usa HOG/CNN)")
    else:
        info("Directorio de encodings no existe aún")


# ════════════════════════════════════════════════════════════════════
# RESUMEN FINAL
# ════════════════════════════════════════════════════════════════════
def resumen():
    print(f"\n{'═'*57}")
    print(f"{BOLD}  RESUMEN DEL DIAGNÓSTICO{RESET}")
    print(f"{'═'*57}")

    if not ERRORES_CRITICOS and not ADVERTENCIAS:
        print(f"\n  {G}{BOLD}🎉 SISTEMA LISTO PARA PRODUCCIÓN{RESET}")
        print(f"  {G}Todos los componentes están correctamente configurados.{RESET}")
    else:
        if ERRORES_CRITICOS:
            print(f"\n  {R}{BOLD}❌ {len(ERRORES_CRITICOS)} ERROR(ES) CRÍTICO(S) — deben resolverse:{RESET}")
            for i, e in enumerate(ERRORES_CRITICOS, 1):
                print(f"  {R}{i}. {e}{RESET}")

        if ADVERTENCIAS:
            print(f"\n  {Y}{BOLD}⚠️  {len(ADVERTENCIAS)} ADVERTENCIA(S) — revisar antes de producción:{RESET}")
            for i, w in enumerate(ADVERTENCIAS, 1):
                print(f"  {Y}{i}. {w}{RESET}")

    print(f"\n  Ejecutado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'═'*57}\n")

    return len(ERRORES_CRITICOS)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Diagnóstico del sistema Colegio Asistencia")
    parser.add_argument("--servidor-activo", action="store_true",
                        help="Incluir tests que requieren el servidor corriendo")
    args = parser.parse_args()

    print(f"\n{BOLD}{B}{'═'*57}{RESET}")
    print(f"{BOLD}{B}  🏫 COLEGIO ASISTENCIA — DIAGNÓSTICO DEL SISTEMA{RESET}")
    print(f"{BOLD}{B}{'═'*57}{RESET}")

    check_python()
    check_dependencias()
    check_estructura()
    check_base_datos()
    check_env()
    check_red()
    check_encodings()

    if args.servidor_activo:
        check_api()
    else:
        print(f"\n{DIM}  [Omitiendo tests de API — usar --servidor-activo para incluirlos]{RESET}")

    n_errores = resumen()
    sys.exit(0 if n_errores == 0 else 1)


if __name__ == "__main__":
    main()
