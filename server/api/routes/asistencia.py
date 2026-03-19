"""
server/api/routes/asistencia.py
=================================
Endpoints de asistencia manual y consulta de registros.

Complementa el endpoint de scan facial (reconocimiento.py).
Cubre los casos donde el reconocimiento falla o el portero
necesita registrar manualmente desde la búsqueda.

Endpoints:
  POST /api/asistencia/manual      → Registrar entrada/salida manual
  GET  /api/asistencia/hoy         → Todos los registros del día
  GET  /api/asistencia/alumno/{id} → Registros de un alumno (paginado)
  GET  /api/asistencia/vivos       → Alumnos actualmente DENTRO del colegio
  DELETE /api/asistencia/{id}      → Eliminar registro erróneo (solo Admin)
"""

from datetime import datetime, date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from server.db.database import get_db
from server.db import models
from server.db.models import RolUsuario, TipoEvento, EstadoAsistencia
from server.core.security import get_current_user, require_rol
from server.services.attendance_service import AttendanceService
from server.core.config import settings

router = APIRouter(prefix="/asistencia", tags=["Asistencia"])

_attendance_service = AttendanceService(
    rescan_threshold_seconds=settings.RESCAN_THRESHOLD_SECONDS
)


# ================================================================== #
# POST /api/asistencia/manual
# ================================================================== #

class RegistroManualPayload:
    pass

from pydantic import BaseModel

class RegistroManualIn(BaseModel):
    alumno_id:   int
    tipo_evento: TipoEvento
    notas:       Optional[str] = None


@router.post("/manual", status_code=201, summary="Registro manual de asistencia")
def registrar_manual(
    data:         RegistroManualIn,
    db:           Session = Depends(get_db),
    current_user  = Depends(require_rol(RolUsuario.ADMIN, RolUsuario.PORTERO, RolUsuario.TUTOR)),
):
    """
    Registra una entrada o salida sin reconocimiento facial.
    Usado por el portero desde la búsqueda manual en la UI,
    o por el tutor para corregir registros de su aula.
    No aplica la regla de 5 minutos (es una acción deliberada del usuario).
    """
    try:
        registro = _attendance_service.registrar_manual(
            db=db,
            alumno_id=data.alumno_id,
            tipo_evento=data.tipo_evento,
            usuario_id=current_user.id,
            notas=data.notas,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    alumno = db.get(models.Alumno, data.alumno_id)
    return {
        "mensaje": f"✅ {data.tipo_evento.value} registrada manualmente para {alumno.nombre_completo()}",
        "registro_id": registro.id,
        "fecha":       registro.fecha.isoformat(),
        "tipo_evento": registro.tipo_evento,
        "estado":      registro.estado,
        "registrado_por": registro.registrado_por,
    }


# ================================================================== #
# GET /api/asistencia/hoy
# ================================================================== #

@router.get("/hoy", summary="Todos los registros del día actual")
def asistencia_hoy(
    grado:    Optional[str] = Query(None, description="Filtrar por grado (ej: '3A')"),
    tipo:     Optional[TipoEvento] = Query(None),
    db:       Session = Depends(get_db),
    _user     = Depends(get_current_user),
):
    """
    Devuelve todos los eventos de asistencia de hoy.
    Tutores: solo ven su grado asignado.
    Porteros y Admin: ven todo.
    """
    hoy_inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    query = db.query(models.Asistencia).filter(
        models.Asistencia.fecha >= hoy_inicio
    )

    if tipo:
        query = query.filter(models.Asistencia.tipo_evento == tipo)

    # Tutores solo ven su grado
    if _user.rol == RolUsuario.TUTOR and _user.grado_asignado:
        alumnos_grado = db.query(models.Alumno.id).filter(
            models.Alumno.grado == _user.grado_asignado
        ).subquery()
        query = query.filter(models.Asistencia.alumno_id.in_(alumnos_grado))
    elif grado:
        alumnos_grado = db.query(models.Alumno.id).filter(
            models.Alumno.grado + models.Alumno.seccion == grado
        ).subquery()
        query = query.filter(models.Asistencia.alumno_id.in_(alumnos_grado))

    registros = query.order_by(models.Asistencia.fecha.desc()).all()

    return [
        {
            "id":          r.id,
            "alumno_id":   r.alumno_id,
            "nombre":      r.alumno.nombre_completo() if r.alumno else "—",
            "grado":       f"{r.alumno.grado}{r.alumno.seccion}" if r.alumno else "—",
            "tipo_evento": r.tipo_evento,
            "estado":      r.estado,
            "hora":        r.fecha.strftime("%H:%M:%S"),
            "confianza":   r.confianza,
            "registrado_por": r.registrado_por,
        }
        for r in registros
    ]


# ================================================================== #
# GET /api/asistencia/vivos
# ================================================================== #

@router.get("/vivos", summary="Alumnos actualmente dentro del colegio")
def alumnos_dentro(
    db:    Session = Depends(get_db),
    _user  = Depends(get_current_user),
):
    """
    Devuelve la lista de alumnos cuyo ÚLTIMO registro del día fue una ENTRADA.
    Estos son los alumnos que actualmente están dentro del colegio.
    Útil para el portero como control de presencia en tiempo real.
    """
    hoy_inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Subconsulta: último registro de cada alumno hoy
    ultimo_por_alumno = db.query(
        models.Asistencia.alumno_id,
        func.max(models.Asistencia.fecha).label("ultima_fecha")
    ).filter(
        models.Asistencia.fecha >= hoy_inicio
    ).group_by(models.Asistencia.alumno_id).subquery()

    # Registros que corresponden al último evento de cada alumno
    ultimos_registros = db.query(models.Asistencia).join(
        ultimo_por_alumno,
        and_(
            models.Asistencia.alumno_id == ultimo_por_alumno.c.alumno_id,
            models.Asistencia.fecha == ultimo_por_alumno.c.ultima_fecha,
        )
    ).filter(
        models.Asistencia.tipo_evento == TipoEvento.ENTRADA
    ).all()

    return {
        "total_dentro": len(ultimos_registros),
        "hora_consulta": datetime.utcnow().strftime("%H:%M:%S"),
        "alumnos": [
            {
                "id":    r.alumno_id,
                "nombre": r.alumno.nombre_completo() if r.alumno else "—",
                "grado": f"{r.alumno.grado}{r.alumno.seccion}" if r.alumno else "—",
                "hora_entrada": r.fecha.strftime("%H:%M"),
                "estado": r.estado,
            }
            for r in ultimos_registros
        ],
    }


# ================================================================== #
# DELETE /api/asistencia/{id}
# ================================================================== #

@router.delete("/{registro_id}", summary="Eliminar registro erróneo")
def eliminar_registro(
    registro_id: int,
    motivo:      str = Query(..., description="Motivo de la eliminación (requerido para auditoría)"),
    db:          Session = Depends(get_db),
    _user        = Depends(require_rol(RolUsuario.ADMIN)),
):
    """
    Solo Admin puede eliminar registros de asistencia.
    El motivo es obligatorio para mantener trazabilidad.
    Se registra en los logs del servidor.
    """
    import logging
    log = logging.getLogger(__name__)

    registro = db.get(models.Asistencia, registro_id)
    if not registro:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    log.warning(
        "ELIMINACIÓN de asistencia ID=%d (Alumno=%d, %s %s) por Admin %s. Motivo: %s",
        registro.id, registro.alumno_id,
        registro.tipo_evento, registro.fecha.strftime("%Y-%m-%d %H:%M"),
        _user.username, motivo,
    )

    db.delete(registro)
    db.commit()
    return {"mensaje": f"Registro #{registro_id} eliminado. Motivo: {motivo}"}
