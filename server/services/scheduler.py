"""
server/services/scheduler.py
=============================
Tareas automáticas programadas con APScheduler.

Tareas implementadas:
  1. 09:30 — Detectar y notificar ausencias del día
             (alumnos que no marcaron entrada antes del límite de tardanza)
  2. 20:00 — Backup automático de la base de datos SQLite
  3. 23:55 — Limpiar logs de notificación con más de 30 días
  4. Lunes 06:00 — Reporte semanal de asistencia al admin vía Telegram

Integración con FastAPI:
    El scheduler se inicia y detiene en el lifespan de main.py.
    Usa AsyncIOScheduler para no bloquear el event loop de FastAPI.

Dependencia adicional requerida:
    pip install apscheduler==3.10.4
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import and_

logger = logging.getLogger(__name__)

# Instancia global del scheduler
scheduler = AsyncIOScheduler(timezone="America/Lima")


# ================================================================== #
# TAREA 1: Notificar ausencias del día
# ================================================================== #

async def tarea_notificar_ausencias():
    """
    Se ejecuta a las 09:30 (configurable).
    Detecta alumnos sin registro de ENTRADA hoy y notifica al admin.
    """
    from server.db.database import SessionLocal
    from server.db import models
    from server.db.models import TipoEvento
    from server.services.notifications.telegram_service import telegram_notifier

    logger.info("[Scheduler] Iniciando detección de ausencias del día...")
    db = SessionLocal()
    try:
        hoy_inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # IDs de alumnos que SÍ marcaron entrada hoy
        presentes_ids = db.query(models.Asistencia.alumno_id).filter(
            and_(
                models.Asistencia.fecha >= hoy_inicio,
                models.Asistencia.tipo_evento == TipoEvento.ENTRADA,
            )
        ).distinct().subquery()

        # Alumnos activos que NO marcaron entrada
        ausentes = db.query(models.Alumno).filter(
            models.Alumno.activo == True,
            ~models.Alumno.id.in_(presentes_ids),
        ).order_by(models.Alumno.grado, models.Alumno.apellidos).all()

        if not ausentes:
            logger.info("[Scheduler] Sin ausencias hoy — todos presentes.")
            return

        logger.info("[Scheduler] %d alumnos ausentes detectados.", len(ausentes))
        telegram_notifier.notificar_ausencias_del_dia(db, ausentes, datetime.utcnow())

    except Exception as e:
        logger.error("[Scheduler] Error en tarea_notificar_ausencias: %s", e)
    finally:
        db.close()


# ================================================================== #
# TAREA 2: Backup automático de la DB
# ================================================================== #

async def tarea_backup_db():
    """
    Se ejecuta todos los días a las 20:00.
    Llama a la misma lógica del script backup_db.py.
    """
    import sqlite3
    import os
    from server.core.config import settings

    logger.info("[Scheduler] Iniciando backup automático de la DB...")

    try:
        db_path = Path(settings.DATABASE_URL.replace("sqlite:///", ""))
        if not db_path.exists():
            logger.warning("[Scheduler] DB no encontrada en %s", db_path)
            return

        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"asistencia_backup_{timestamp}.db"

        # Backup vía API nativa SQLite (thread-safe con WAL)
        conn_origen = sqlite3.connect(str(db_path))
        conn_backup = sqlite3.connect(str(backup_path))
        conn_origen.backup(conn_backup, steps=100)
        conn_origen.close()
        conn_backup.close()

        size_kb = backup_path.stat().st_size / 1024
        logger.info("[Scheduler] Backup completado: %s (%.1f KB)", backup_path.name, size_kb)

        # Limpiar backups antiguos (retener los últimos 30)
        backups = sorted(backup_dir.glob("asistencia_backup_*.db"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        for viejo in backups[30:]:
            viejo.unlink()
            logger.info("[Scheduler] Backup antiguo eliminado: %s", viejo.name)

    except Exception as e:
        logger.error("[Scheduler] Error en tarea_backup_db: %s", e)


# ================================================================== #
# TAREA 3: Limpiar logs de notificación viejos
# ================================================================== #

async def tarea_limpiar_logs():
    """
    Se ejecuta a las 23:55.
    Elimina registros de notificacion_log con más de 30 días.
    Evita que la tabla crezca indefinidamente.
    """
    from server.db.database import SessionLocal
    from server.db import models

    db = SessionLocal()
    try:
        limite = datetime.utcnow() - timedelta(days=30)
        eliminados = db.query(models.NotificacionLog).filter(
            models.NotificacionLog.fecha_envio < limite
        ).delete()
        db.commit()
        if eliminados:
            logger.info("[Scheduler] %d logs de notificación antiguos eliminados.", eliminados)
    except Exception as e:
        logger.error("[Scheduler] Error en tarea_limpiar_logs: %s", e)
        db.rollback()
    finally:
        db.close()


# ================================================================== #
# TAREA 4: Reporte semanal al admin
# ================================================================== #

async def tarea_reporte_semanal():
    """
    Se ejecuta los lunes a las 06:00.
    Envía al admin un resumen de la semana anterior por Telegram.
    """
    from server.db.database import SessionLocal
    from server.db import models
    from server.db.models import TipoEvento, EstadoAsistencia
    from sqlalchemy import func
    from server.services.notifications.telegram_service import telegram_notifier

    logger.info("[Scheduler] Generando reporte semanal...")
    db = SessionLocal()
    try:
        hoy   = datetime.utcnow()
        lunes  = hoy - timedelta(days=hoy.weekday() + 7)
        lunes  = lunes.replace(hour=0, minute=0, second=0, microsecond=0)
        domingo = lunes + timedelta(days=7)

        # Días lectivos de la semana pasada
        dias = db.query(
            func.date(models.Asistencia.fecha)
        ).filter(
            models.Asistencia.fecha.between(lunes, domingo)
        ).distinct().count()

        # Total entradas
        entradas = db.query(func.count(models.Asistencia.id)).filter(
            and_(
                models.Asistencia.fecha.between(lunes, domingo),
                models.Asistencia.tipo_evento == TipoEvento.ENTRADA,
            )
        ).scalar() or 0

        # Tardanzas
        tardanzas = db.query(func.count(models.Asistencia.id)).filter(
            and_(
                models.Asistencia.fecha.between(lunes, domingo),
                models.Asistencia.estado == EstadoAsistencia.TARDANZA,
            )
        ).scalar() or 0

        total_alumnos = db.query(func.count(models.Alumno.id)).filter(
            models.Alumno.activo == True
        ).scalar() or 1

        promedio = round(entradas / dias if dias > 0 else 0, 1)
        pct = round(promedio / total_alumnos * 100, 1) if total_alumnos else 0

        msg = (
            f"📊 <b>REPORTE SEMANAL</b>\n"
            f"📅 {lunes.strftime('%d/%m')} – {domingo.strftime('%d/%m/%Y')}\n\n"
            f"📚 Días lectivos:      <b>{dias}</b>\n"
            f"✅ Prom. asistencia:  <b>{promedio}</b> alumnos/día (<b>{pct}%</b>)\n"
            f"⏰ Tardanzas totales: <b>{tardanzas}</b>\n"
            f"👥 Total alumnos:     <b>{total_alumnos}</b>\n\n"
            f"Ver detalles en: http://TU-SERVIDOR:8000/admin"
        )

        telegram_notifier._enviar_en_background(
            telegram_notifier.chat_admin, msg
        )
        logger.info("[Scheduler] Reporte semanal enviado.")

    except Exception as e:
        logger.error("[Scheduler] Error en tarea_reporte_semanal: %s", e)
    finally:
        db.close()


# ================================================================== #
# Registrar todas las tareas
# ================================================================== #

def configurar_scheduler():
    """
    Registra todas las tareas en el scheduler.
    Llamar una sola vez desde main.py al arrancar.
    Los horarios usan zona horaria America/Lima (configurable arriba).
    """

    # Tarea 1: Ausencias — 09:30 todos los días de semana (L-V)
    scheduler.add_job(
        tarea_notificar_ausencias,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=30),
        id="ausencias_diarias",
        replace_existing=True,
        misfire_grace_time=300,  # Si falla el disparo, reintentar en 5 min
    )

    # Tarea 2: Backup — 20:00 todos los días
    scheduler.add_job(
        tarea_backup_db,
        CronTrigger(hour=20, minute=0),
        id="backup_diario",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Tarea 3: Limpiar logs — 23:55 todos los días
    scheduler.add_job(
        tarea_limpiar_logs,
        CronTrigger(hour=23, minute=55),
        id="limpiar_logs",
        replace_existing=True,
    )

    # Tarea 4: Reporte semanal — Lunes 06:00
    scheduler.add_job(
        tarea_reporte_semanal,
        CronTrigger(day_of_week="mon", hour=6, minute=0),
        id="reporte_semanal",
        replace_existing=True,
    )

    logger.info(
        "[Scheduler] %d tareas registradas: %s",
        len(scheduler.get_jobs()),
        [j.id for j in scheduler.get_jobs()]
    )
