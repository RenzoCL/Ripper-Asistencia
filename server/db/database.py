"""
server/db/database.py
=====================
Módulo de conexión híbrida: SQLite (Local) + PostgreSQL (Nube/Supabase).

Este módulo adapta la conexión según la DATABASE_URL configurada:
  - En Local: Activa el modo WAL para soportar ~900 alumnos en LAN.
  - En Nube: Configura el pool de conexiones para PostgreSQL en Render.
"""

from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from server.core.config import settings
from sqlalchemy.pool import StaticPool

# 1. Obtener la URL de configuración (Pydantic la lee de .env o Render)
DATABASE_URL = settings.DATABASE_URL

# 2. Identificar el motor de base de datos
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# 3. Preparación de entorno para SQLite (Solo local)
if IS_SQLITE:
    # Extraer la ruta del archivo para asegurar que la carpeta exista
    db_path = DATABASE_URL.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

# 4. Configuración del Engine adaptativa
# PostgreSQL NO acepta 'check_same_thread', por eso es condicional.
connect_args = {}
if IS_SQLITE:
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    # StaticPool se usa principalmente para pruebas en memoria
    poolclass=StaticPool if "memory" in DATABASE_URL else None,
    echo=False,  # Cambiar a True para ver las consultas SQL en consola
)

# 5. Optimizaciones exclusivas para SQLite (Modo WAL)
# Esto permite que la laptop procese asistencias mientras el Admin consulta reportes.
if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# 6. Configuración de Sesiones
# 'autoflush=False' mejora el rendimiento al insertar encodings masivos.
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# 7. Clase Base para Modelos ORM (SQLAlchemy 2.0+)
class Base(DeclarativeBase):
    """Clase padre de la que heredarán todos tus modelos (Alumnos, Asistencia, etc)."""
    pass

# 8. Dependencia para los Endpoints de FastAPI
def get_db():
    """
    Provee una sesión de base de datos por cada petición y la cierra al terminar.
    Garantiza que no queden conexiones colgadas en Supabase.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()