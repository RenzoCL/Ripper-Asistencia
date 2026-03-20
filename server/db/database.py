"""
server/db/database.py
=====================
Módulo de conexión híbrida: SQLite (Local) + PostgreSQL (Nube/Supabase).
Optimizado para evitar importaciones circulares en el despliegue de Render.
"""

import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool

# 1. Obtener la URL directamente del entorno (Evita importar settings aquí)
# Esto rompe el círculo: database -> settings -> models -> database
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "sqlite:///./server/data/asistencia.db"
)

# 2. Identificar el motor de base de datos
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# 3. Preparación de entorno para SQLite (Solo local)
if IS_SQLITE:
    db_path = DATABASE_URL.replace("sqlite:///", "")
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass # Evita errores en entornos de solo lectura

# 4. Configuración del Engine adaptativa
connect_args = {}
if IS_SQLITE:
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    poolclass=StaticPool if "memory" in DATABASE_URL else None,
    echo=False,
)

# 5. Optimizaciones exclusivas para SQLite (Modo WAL)
if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# 6. Configuración de Sesiones
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# 7. Clase Base para Modelos ORM
class Base(DeclarativeBase):
    """Clase padre de la que heredarán todos tus modelos."""
    pass

# 8. Dependencia para los Endpoints de FastAPI
def get_db():
    """Provee una sesión de base de datos aislada."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()