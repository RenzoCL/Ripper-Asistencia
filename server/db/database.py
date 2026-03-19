"""
server/db/database.py
=====================
Módulo central de base de datos con SQLite + SQLAlchemy.

Por qué SQLite:
  - Cero configuración: el archivo .db ES la base de datos.
  - Velocidad suficiente para ~900 alumnos en LAN.
  - Funciona offline sin servidor externo.
  - Fácil backup: copiar el archivo .db es todo.

Por qué SQLAlchemy (ORM):
  - Abstrae el SQL raw, reduciendo errores y mejorando legibilidad.
  - Permite migrar a PostgreSQL en el futuro cambiando solo DATABASE_URL.
"""

import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool

# ------------------------------------------------------------------ #
# Configuración de la ruta de la base de datos
# ------------------------------------------------------------------ #
# Leemos la URL desde variable de entorno, con fallback seguro.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./server/data/asistencia.db"
)

# Crear directorio de datos si no existe (primer arranque del sistema)
db_path = DATABASE_URL.replace("sqlite:///", "")
Path(db_path).parent.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ #
# Creación del engine de SQLAlchemy
# ------------------------------------------------------------------ #
# check_same_thread=False: SQLite por defecto solo permite acceso desde
# el hilo que lo creó. FastAPI usa múltiples hilos, por eso lo deshabilitamos.
# StaticPool: Necesario para tests (mantiene una única conexión en memoria).
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool if "memory" in DATABASE_URL else None,
    echo=False,  # Cambiar a True para ver SQL en consola (debug)
)


# ------------------------------------------------------------------ #
# Activar WAL mode para SQLite
# ------------------------------------------------------------------ #
# WAL (Write-Ahead Logging): Permite lecturas y escrituras concurrentes.
# Crítico para que múltiples clientes en la LAN no bloqueen la DB.
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")   # Concurrencia
    cursor.execute("PRAGMA synchronous=NORMAL")  # Balance velocidad/seguridad
    cursor.execute("PRAGMA foreign_keys=ON")     # Integridad referencial
    cursor.close()


# ------------------------------------------------------------------ #
# Sesión de base de datos
# ------------------------------------------------------------------ #
# Cada request de FastAPI obtiene su propia sesión aislada.
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# ------------------------------------------------------------------ #
# Clase base para todos los modelos ORM
# ------------------------------------------------------------------ #
class Base(DeclarativeBase):
    """Clase padre de todos los modelos de la DB."""
    pass


# ------------------------------------------------------------------ #
# Dependency Injection para FastAPI
# ------------------------------------------------------------------ #
def get_db():
    """
    Generador que provee una sesión de DB a cada endpoint de FastAPI.
    El bloque 'finally' garantiza que la sesión se cierre SIEMPRE,
    incluso si ocurre una excepción durante el request.

    Uso en un endpoint:
        @router.get("/algo")
        def mi_endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
