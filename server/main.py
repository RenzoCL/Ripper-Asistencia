"""
server/main.py — versión corregida y mejorada
CAMBIOS:
  1. Integración de slowapi para rate limiting global
  2. Handler de RateLimitExceeded con mensaje claro en español
  3. Header X-Process-Time en cada respuesta (útil para debug de latencia)
  4. Endpoint /api/status más completo (modelo activo, versión, uptime)
"""

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from server.core.config import settings
from server.core.rate_limit import limiter
from server.db.database import engine, Base
from server.db import models
from server.db.database import SessionLocal
from server.api.routes import (
    auth, alumnos, reconocimiento, admin,
    justificaciones, asistencia, exportar, websocket_scan
)
from server.services.scheduler import scheduler, configurar_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Para calcular uptime
_startup_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_time
    _startup_time = time.time()

    logger.info("🏫 Iniciando Colegio Asistencia v1.1...")
    logger.info("📡 Servidor en: http://%s:%d", settings.SERVER_HOST, settings.SERVER_PORT)

    Base.metadata.create_all(bind=engine)
    logger.info("✅ Esquema de base de datos verificado/creado")

    _seed_initial_data()

    configurar_scheduler()
    scheduler.start()
    logger.info("⏰ Scheduler iniciado con %d tareas", len(scheduler.get_jobs()))
    logger.info("🚀 Servidor listo")

    yield

    scheduler.shutdown(wait=False)
    logger.info("🔴 Servidor detenido correctamente")


def _seed_initial_data():
    from server.core.security import hash_password

    db = SessionLocal()
    try:
        if not db.query(models.UsuarioSistema).filter_by(username="admin").first():
            db.add(models.UsuarioSistema(
                username="admin",
                password_hash=hash_password("admin1234"),
                nombre_display="Administrador del Sistema",
                rol=models.RolUsuario.ADMIN,
            ))
            logger.warning("⚠️  Usuario 'admin' creado — CAMBIAR CONTRASEÑA INMEDIATAMENTE")

        configs_default = [
            ("modelo_ia_activo",       settings.DEFAULT_RECOGNITION_MODEL.value,
             "Modelo de reconocimiento facial (LBPH/HOG/CNN)"),
            ("hora_inicio_tardanza",   "08:15",
             "Hora límite para puntualidad (HH:MM)"),
            ("hora_inicio_clases",     "08:00", "Hora de inicio de clases"),
            ("hora_fin_clases",        "14:00", "Hora de fin de clases"),
            ("notificaciones_activas", "true",  "Habilitar notificaciones"),
            ("nombre_colegio",         "Colegio", "Nombre del colegio"),
        ]

        for clave, valor, desc in configs_default:
            if not db.query(models.Configuracion).filter_by(clave=clave).first():
                db.add(models.Configuracion(clave=clave, valor=valor, descripcion=desc))

        db.commit()
        logger.info("✅ Configuración inicial verificada")
    except Exception as e:
        logger.error("Error en seed inicial: %s", e)
        db.rollback()
    finally:
        db.close()


# ================================================================== #
# Creación de la app
# ================================================================== #

app = FastAPI(
    title="🏫 Colegio Asistencia API",
    description=(
        "Sistema de asistencia escolar con reconocimiento facial. "
        "Operación en LAN con hardware limitado."
    ),
    version="1.1.0",
    lifespan=lifespan,
)

# Rate limiter — debe registrarse antes de los middlewares
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Middleware de tiempo de respuesta (útil para debug de latencia del scan)
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    process_time = (time.time() - start) * 1000  # ms
    response.headers["X-Process-Time-Ms"] = f"{process_time:.1f}"
    return response


# ================================================================== #
# Static / Admin panel
# ================================================================== #
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

# ================================================================== #
# Routers
# ================================================================== #
API_PREFIX = "/api"
app.include_router(auth.router,            prefix=API_PREFIX)
app.include_router(alumnos.router,         prefix=API_PREFIX)
app.include_router(reconocimiento.router,  prefix=API_PREFIX)
app.include_router(admin.router,           prefix=API_PREFIX)
app.include_router(justificaciones.router, prefix=API_PREFIX)
app.include_router(asistencia.router,      prefix=API_PREFIX)
app.include_router(exportar.router,        prefix=API_PREFIX)
app.include_router(websocket_scan.router)


# ================================================================== #
# Endpoints de sistema
# ================================================================== #

@app.get("/health", tags=["Sistema"], summary="Estado del servidor")
def health_check():
    uptime_segundos = int(time.time() - _startup_time)
    horas, resto = divmod(uptime_segundos, 3600)
    minutos, segs = divmod(resto, 60)

    return {
        "status":    "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version":   "1.1.0",
        "uptime":    f"{horas:02d}:{minutos:02d}:{segs:02d}",
    }


@app.get("/api/status", tags=["Sistema"], summary="Estado detallado del sistema")
def system_status():
    """Estado completo: modelo activo, scheduler, conexiones WS."""
    from server.api.routes.websocket_scan import manager

    db = SessionLocal()
    try:
        cfg_modelo = db.query(models.Configuracion).filter_by(
            clave="modelo_ia_activo"
        ).first()
        modelo_activo = cfg_modelo.valor if cfg_modelo else "desconocido"

        total_alumnos = db.query(models.Alumno).filter_by(activo=True).count()
        con_encoding  = db.query(models.Alumno).filter_by(
            activo=True, encoding_valido=True
        ).count()
    finally:
        db.close()

    return {
        "version":            "1.1.0",
        "modelo_ia_activo":   modelo_activo,
        "total_alumnos":      total_alumnos,
        "alumnos_entrenados": con_encoding,
        "ws_clientes":        manager.total_clientes,
        "scheduler_jobs":     len(scheduler.get_jobs()),
        "uptime_segundos":    int(time.time() - _startup_time),
    }


@app.get("/", tags=["Sistema"])
def root():
    return {
        "sistema": "Colegio Asistencia – Reconocimiento Facial",
        "version": "1.1.0",
        "docs":    "/docs",
        "admin":   "/admin",
        "status":  "✅ Operativo",
    }