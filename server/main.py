"""
server/main.py
==============
Punto de entrada del servidor FastAPI — Colegio Asistencia.

Este archivo:
  1. Crea la aplicación FastAPI con metadata (título, versión, docs).
  2. Configura CORS para permitir que los clientes LAN accedan.
  3. Registra todos los routers de la API bajo el prefijo /api.
  4. Crea las tablas de la DB en el primer arranque (create_all).
  5. Siembra la configuración inicial (datos por defecto).
  6. Expone un endpoint de salud /health para monitoreo.

Cómo ejecutar:
    uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload

Documentación interactiva (solo en desarrollo):
    http://localhost:8000/docs    → Swagger UI
    http://localhost:8000/redoc  → ReDoc
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.core.config import settings
from server.db.database import engine, Base
from server.db import models
from server.db.database import SessionLocal

# Importar todos los routers
from server.api.routes import auth, alumnos, reconocimiento, admin, justificaciones, asistencia, exportar, websocket_scan

# Scheduler de tareas automáticas
from server.services.scheduler import scheduler, configurar_scheduler

# ------------------------------------------------------------------ #
# Configuración de logging
# ------------------------------------------------------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Ciclo de vida de la aplicación (startup / shutdown)
# ------------------------------------------------------------------ #
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Código que se ejecuta al arrancar y detener el servidor.
    'yield' separa el startup del shutdown.
    """
    # === STARTUP ===
    logger.info("🏫 Iniciando Colegio Asistencia v1.0...")
    logger.info("📡 Servidor en: http://%s:%d", settings.SERVER_HOST, settings.SERVER_PORT)

    # Crear todas las tablas definidas en models.py (si no existen)
    # NOTA: En producción usar Alembic para migraciones controladas.
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Esquema de base de datos verificado/creado")

    # Sembrar datos iniciales (configuración por defecto y usuario admin)
    _seed_initial_data()

    # Iniciar scheduler de tareas automáticas
    configurar_scheduler()
    scheduler.start()
    logger.info("⏰ Scheduler iniciado con %d tareas automáticas", len(scheduler.get_jobs()))

    logger.info("🚀 Servidor listo para recibir conexiones")

    yield  # El servidor corre aquí

    # === SHUTDOWN ===
    scheduler.shutdown(wait=False)
    logger.info("⏰ Scheduler detenido")
    logger.info("🔴 Servidor detenido correctamente")


# ------------------------------------------------------------------ #
# Inicialización de datos por defecto
# ------------------------------------------------------------------ #
def _seed_initial_data():
    """
    Crea los registros mínimos necesarios para que el sistema funcione.
    Solo se ejecuta si los datos no existen (idempotente).
    """
    from server.core.security import hash_password

    db = SessionLocal()
    try:
        # --- Usuario Admin por defecto ---
        admin_existente = db.query(models.UsuarioSistema).filter(
            models.UsuarioSistema.username == "admin"
        ).first()

        if not admin_existente:
            admin = models.UsuarioSistema(
                username="admin",
                password_hash=hash_password("admin1234"),  # ⚠️ CAMBIAR en producción
                nombre_display="Administrador del Sistema",
                rol=models.RolUsuario.ADMIN,
            )
            db.add(admin)
            logger.warning(
                "⚠️  Usuario 'admin' creado con contraseña por defecto. "
                "¡CAMBIAR INMEDIATAMENTE desde el Panel Admin!"
            )

        # --- Configuraciones por defecto ---
        configs_default = [
            {
                "clave": "modelo_ia_activo",
                "valor": settings.DEFAULT_RECOGNITION_MODEL.value,
                "descripcion": "Modelo de reconocimiento facial (LBPH/HOG/CNN)"
            },
            {
                "clave": "hora_inicio_tardanza",
                "valor": "08:15",
                "descripcion": "Hora límite para marcar puntualidad (formato HH:MM)"
            },
            {
                "clave": "hora_inicio_clases",
                "valor": "08:00",
                "descripcion": "Hora de inicio de clases"
            },
            {
                "clave": "hora_fin_clases",
                "valor": "14:00",
                "descripcion": "Hora de fin de clases (turno mañana)"
            },
            {
                "clave": "notificaciones_activas",
                "valor": "true",
                "descripcion": "Habilitar/deshabilitar todas las notificaciones"
            },
            {
                "clave": "nombre_colegio",
                "valor": "Colegio",
                "descripcion": "Nombre del colegio (aparece en reportes y notificaciones)"
            },
        ]

        for cfg_data in configs_default:
            existe = db.query(models.Configuracion).filter(
                models.Configuracion.clave == cfg_data["clave"]
            ).first()
            if not existe:
                db.add(models.Configuracion(**cfg_data))

        db.commit()
        logger.info("✅ Configuración inicial verificada")

    except Exception as e:
        logger.error("Error en seed inicial: %s", e)
        db.rollback()
    finally:
        db.close()


# ------------------------------------------------------------------ #
# Creación de la aplicación FastAPI
# ------------------------------------------------------------------ #
app = FastAPI(
    title="🏫 Colegio Asistencia API",
    description=(
        "Sistema de asistencia escolar con reconocimiento facial para ~900 alumnos. "
        "Funciona en red local (LAN) con hardware limitado y costo cero de software."
    ),
    version="1.0.0",
    contact={
        "name": "Equipo de Desarrollo",
        "url":  "https://github.com/tu-usuario/colegio-asistencia",
    },
    license_info={
        "name": "MIT",
        "url":  "https://opensource.org/licenses/MIT",
    },
    lifespan=lifespan,
    # Deshabilitar docs en producción si se desea mayor seguridad:
    # docs_url=None, redoc_url=None,
)


# ------------------------------------------------------------------ #
# Middleware CORS
# ------------------------------------------------------------------ #
# Permite que los clientes en la red local (cualquier IP/puerto)
# hagan requests al servidor. En producción, restringir a las IPs del colegio.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Esto permite que tu panel local se conecte a Render
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ #
# Servir el panel admin web
# ------------------------------------------------------------------ #

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path as _Path

_static = _Path(__file__).parent / "static"
_admin_html = _static / "admin.html"

if _static.exists():
    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/", include_in_schema=False)
    async def serve_admin():
        if _admin_html.exists():
            return FileResponse(str(_admin_html), media_type="text/html")
        return {"error": "admin.html no encontrado"}

    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

API_PREFIX = "/api"

app.include_router(auth.router,          prefix=API_PREFIX)
app.include_router(alumnos.router,       prefix=API_PREFIX)
app.include_router(reconocimiento.router, prefix=API_PREFIX)
app.include_router(admin.router,           prefix=API_PREFIX)
app.include_router(justificaciones.router, prefix=API_PREFIX)
app.include_router(asistencia.router,    prefix=API_PREFIX)
app.include_router(exportar.router,      prefix=API_PREFIX)
app.include_router(websocket_scan.router)  # Sin prefijo /api — rutas /ws/scan y /ws/status


# ------------------------------------------------------------------ #
# Endpoints utilitarios
# ------------------------------------------------------------------ #

@app.get("/health", tags=["Sistema"], summary="Estado del servidor")
def health_check():
    """
    Endpoint de salud. Los clientes lo usan para verificar conectividad LAN.
    No requiere autenticación: debe ser accesible siempre.
    """
    return {
        "status":    "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version":   "1.0.0",
        "servidor":  f"{settings.SERVER_HOST}:{settings.SERVER_PORT}",
    }


@app.get("/", tags=["Sistema"], summary="Información del sistema")
def root():
    return {
        "sistema":  "Colegio Asistencia – Reconocimiento Facial",
        "version":  "1.0.0",
        "docs":     "/docs",
        "estado":   "✅ Operativo",
    }
