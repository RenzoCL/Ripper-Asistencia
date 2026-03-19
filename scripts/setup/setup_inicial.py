#!/usr/bin/env python3
"""
scripts/setup/setup_inicial.py
===============================
Script de instalación y configuración inicial del sistema.

Ejecutar UNA SOLA VEZ después de clonar el repositorio:
    python scripts/setup/setup_inicial.py

Qué hace:
  1. Verifica que Python >= 3.10 esté instalado.
  2. Crea las carpetas de datos necesarias (excluidas del repo).
  3. Copia .env.example → .env si no existe.
  4. Verifica que las dependencias críticas estén instaladas.
  5. Inicializa la base de datos con el esquema.
"""

import sys
import os
import shutil
from pathlib import Path

# Asegurar que podemos importar el módulo del proyecto
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def verificar_python():
    print("🔍 Verificando versión de Python...")
    version = sys.version_info
    if version < (3, 10):
        print(f"❌ Error: Se requiere Python 3.10+. Tienes Python {version.major}.{version.minor}")
        sys.exit(1)
    print(f"   ✅ Python {version.major}.{version.minor}.{version.micro}")


def crear_directorios():
    print("\n📁 Creando estructura de directorios de datos...")
    dirs = [
        "server/data",
        "server/data/photos",
        "server/data/encodings",
        "server/data/logs",
        "server/data/docs_justificacion",
    ]
    for d in dirs:
        path = PROJECT_ROOT / d
        path.mkdir(parents=True, exist_ok=True)
        # Crear .gitkeep para mantener estructura en git sin datos sensibles
        gitkeep = path / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()
        print(f"   ✅ {d}")


def crear_env():
    print("\n⚙️  Configurando archivo .env...")
    env_example = PROJECT_ROOT / ".env.example"
    env_file = PROJECT_ROOT / ".env"

    if env_file.exists():
        print("   ℹ️  El archivo .env ya existe. No se sobreescribirá.")
        return

    if not env_example.exists():
        print("   ❌ No se encontró .env.example")
        return

    shutil.copy(env_example, env_file)
    print("   ✅ .env creado desde .env.example")
    print("   ⚠️  IMPORTANTE: Editar .env con los valores reales antes de iniciar el servidor")


def verificar_dependencias():
    print("\n📦 Verificando dependencias críticas...")
    deps = {
        "fastapi":    "FastAPI",
        "sqlalchemy": "SQLAlchemy",
        "cv2":        "OpenCV",
        "pydantic":   "Pydantic",
        "jose":       "python-jose",
        "passlib":    "passlib",
    }
    todas_ok = True
    for module, nombre in deps.items():
        try:
            __import__(module)
            print(f"   ✅ {nombre}")
        except ImportError:
            print(f"   ❌ {nombre} NO instalado — ejecutar: pip install -r requirements.txt")
            todas_ok = False

    # face_recognition es opcional (puede no instalarse en PCs sin compilador)
    # NOTA: face_recognition 1.3.0 imprime un mensaje de advertencia al importar
    # incluso cuando face_recognition_models SÍ está instalado. Esto es un bug conocido.
    # El mensaje puede ignorarse — el reconocimiento funciona normalmente.
    try:
        import io as _io
        import sys as _sys
        _old_stderr = _sys.stderr
        _sys.stderr = _io.StringIO()  # Suprimir el stderr durante el import
        try:
            import face_recognition
            print("   ✅ face_recognition (HOG/CNN habilitado)")
        finally:
            _sys.stderr = _old_stderr
    except ImportError:
        print("   ⚠️  face_recognition NO instalado — solo modo LBPH disponible")

    return todas_ok


def inicializar_base_de_datos():
    print("\n🗄️  Inicializando base de datos...")
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")

        from server.db.database import engine, Base
        from server.db import models  # noqa: F401 — importar para registrar modelos

        Base.metadata.create_all(bind=engine)
        print("   ✅ Tablas creadas/verificadas en SQLite")

        # Crear usuario admin inicial
        from server.db.database import SessionLocal
        from server.core.security import hash_password

        db = SessionLocal()
        try:
            admin = db.query(models.UsuarioSistema).filter(
                models.UsuarioSistema.username == "admin"
            ).first()

            if not admin:
                admin = models.UsuarioSistema(
                    username="admin",
                    password_hash=hash_password("admin1234"),
                    nombre_display="Administrador",
                    rol=models.RolUsuario.ADMIN,
                )
                db.add(admin)
                db.commit()
                print("   ✅ Usuario admin creado (usuario: admin / contraseña: admin1234)")
                print("   🔴 CAMBIAR LA CONTRASEÑA INMEDIATAMENTE después del primer login")
            else:
                print("   ℹ️  Usuario admin ya existe")
        finally:
            db.close()

    except Exception as e:
        print(f"   ❌ Error inicializando DB: {e}")
        print("      Verificar que .env esté correctamente configurado")


def mostrar_resumen():
    print("\n" + "="*60)
    print("🎉 INSTALACIÓN COMPLETADA")
    print("="*60)
    print("\nPróximos pasos:")
    print("  1. Editar .env con los tokens de Telegram y configuración de red")
    print("  2. Iniciar el servidor: uvicorn server.main:app --host 0.0.0.0 --port 8000")
    print("  3. Abrir: http://localhost:8000/docs para ver la API")
    print("  4. Loguearse como admin/admin1234 y CAMBIAR la contraseña")
    print("  5. Registrar alumnos y subir fotos para entrenamiento")
    print("\n📖 Ver README.md para instrucciones completas")


if __name__ == "__main__":
    print("🏫 COLEGIO ASISTENCIA — Setup Inicial")
    print("=" * 60)

    verificar_python()
    crear_directorios()
    crear_env()
    deps_ok = verificar_dependencias()

    if deps_ok:
        inicializar_base_de_datos()
        mostrar_resumen()
    else:
        print("\n⚠️  Instalar dependencias faltantes y volver a ejecutar este script")
        print("   pip install -r requirements.txt")
