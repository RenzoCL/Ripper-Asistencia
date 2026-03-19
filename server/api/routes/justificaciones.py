"""
server/api/routes/justificaciones.py
======================================
Gestión de ausencias justificadas.

El Tutor es el rol principal que crea justificaciones para su aula.
El Admin puede ver y gestionar todas. El Portero puede consultar.

Flujo de justificación:
  1. Tutor detecta que un alumno estuvo ausente (o llega con documento).
  2. Tutor abre la app, busca al alumno, ingresa fecha y motivo.
  3. (Opcional) Sube foto del documento médico/familiar.
  4. El sistema actualiza el estado de asistencia a JUSTIFICADO.
"""

import shutil
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy import and_
from sqlalchemy.orm import Session

from server.db.database import get_db
from server.db import models
from server.db.models import RolUsuario, EstadoAsistencia, TipoEvento
from server.schemas.schemas import JustificacionCreate, JustificacionResponse
from server.core.security import get_current_user, require_rol

router = APIRouter(prefix="/justificaciones", tags=["Justificaciones"])

DOCS_DIR = "./server/data/docs_justificacion"


@router.get("/", response_model=List[JustificacionResponse], summary="Listar justificaciones")
def listar_justificaciones(
    alumno_id:    int = Query(None),
    desde:        datetime = Query(None),
    hasta:        datetime = Query(None),
    db:           Session = Depends(get_db),
    current_user = Depends(require_rol(RolUsuario.ADMIN, RolUsuario.TUTOR, RolUsuario.PORTERO)),
):
    query = db.query(models.Justificacion)

    if alumno_id:
        query = query.filter(models.Justificacion.alumno_id == alumno_id)
    if desde:
        query = query.filter(models.Justificacion.fecha_ausencia >= desde)
    if hasta:
        query = query.filter(models.Justificacion.fecha_ausencia <= hasta)

    # Tutores: solo ven alumnos de su grado asignado
    if current_user.rol == RolUsuario.TUTOR and current_user.grado_asignado:
        alumnos_grado = db.query(models.Alumno.id).filter(
            models.Alumno.grado == current_user.grado_asignado
        ).subquery()
        query = query.filter(models.Justificacion.alumno_id.in_(alumnos_grado))

    return query.order_by(models.Justificacion.fecha_ausencia.desc()).all()


@router.post("/", response_model=JustificacionResponse, status_code=201)
def crear_justificacion(
    data:         JustificacionCreate,
    db:           Session = Depends(get_db),
    current_user = Depends(require_rol(RolUsuario.ADMIN, RolUsuario.TUTOR)),
):
    """
    Crea una justificación de ausencia y actualiza el registro de asistencia
    correspondiente a JUSTIFICADO si existe.
    """
    alumno = db.get(models.Alumno, data.alumno_id)
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    # Crear la justificación
    justificacion = models.Justificacion(
        alumno_id=data.alumno_id,
        fecha_ausencia=data.fecha_ausencia,
        motivo=data.motivo,
        registrado_por=current_user.id,
    )
    db.add(justificacion)

    # Actualizar el registro de asistencia de ese día a JUSTIFICADO (si existe)
    inicio_dia = data.fecha_ausencia.replace(hour=0, minute=0, second=0, microsecond=0)
    fin_dia    = data.fecha_ausencia.replace(hour=23, minute=59, second=59)

    registros_del_dia = db.query(models.Asistencia).filter(
        and_(
            models.Asistencia.alumno_id == data.alumno_id,
            models.Asistencia.fecha.between(inicio_dia, fin_dia),
            models.Asistencia.tipo_evento == TipoEvento.ENTRADA,
        )
    ).all()

    for registro in registros_del_dia:
        registro.estado = EstadoAsistencia.JUSTIFICADO

    db.commit()
    db.refresh(justificacion)
    return justificacion


@router.post("/{justificacion_id}/documento", summary="Adjuntar documento de respaldo")
async def subir_documento(
    justificacion_id: int,
    documento: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN, RolUsuario.TUTOR)),
):
    """Adjunta un archivo (foto de certificado médico, etc.) a una justificación."""
    just = db.get(models.Justificacion, justificacion_id)
    if not just:
        raise HTTPException(status_code=404, detail="Justificación no encontrada")

    ext = Path(documento.filename).suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".pdf"]:
        raise HTTPException(status_code=400, detail="Formato no válido. Use JPG, PNG o PDF.")

    dir_path = Path(DOCS_DIR) / str(just.alumno_id)
    dir_path.mkdir(parents=True, exist_ok=True)

    fecha_str = just.fecha_ausencia.strftime("%Y%m%d")
    filename  = f"just_{justificacion_id}_{fecha_str}{ext}"
    dest      = dir_path / filename

    with open(dest, "wb") as f:
        shutil.copyfileobj(documento.file, f)

    just.documento_path = str(dest)
    db.commit()

    return {"mensaje": "Documento adjuntado", "path": str(dest)}


@router.delete("/{justificacion_id}", summary="Eliminar justificación")
def eliminar_justificacion(
    justificacion_id: int,
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN)),
):
    """Solo Admin puede eliminar justificaciones."""
    just = db.get(models.Justificacion, justificacion_id)
    if not just:
        raise HTTPException(status_code=404, detail="Justificación no encontrada")

    # Revertir el estado de asistencia a AUSENTE
    inicio = just.fecha_ausencia.replace(hour=0, minute=0, second=0)
    fin    = just.fecha_ausencia.replace(hour=23, minute=59, second=59)

    registros = db.query(models.Asistencia).filter(
        and_(
            models.Asistencia.alumno_id == just.alumno_id,
            models.Asistencia.fecha.between(inicio, fin),
            models.Asistencia.estado == EstadoAsistencia.JUSTIFICADO,
        )
    ).all()
    for r in registros:
        r.estado = EstadoAsistencia.AUSENTE

    db.delete(just)
    db.commit()
    return {"mensaje": "Justificación eliminada"}
