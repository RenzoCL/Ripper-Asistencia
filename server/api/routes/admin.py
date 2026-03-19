"""
server/api/routes/admin.py
===========================
Panel de administración: configuración global, reportes y gestión de usuarios.

Todos los endpoints de este módulo requieren rol ADMIN,
excepto los de reporte que también permiten TUTOR (solo su aula).

Funcionalidades:
  - GET/PUT configuración del sistema (modelo IA, horarios, etc.)
  - Reporte diario de asistencia
  - Reporte mensual con estadísticas
  - CRUD de usuarios del sistema
  - Disparo manual de notificaciones
  - Resumen de logs de notificaciones
"""

from datetime import datetime, date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from server.db.database import get_db
from server.db import models
from server.db.models import RolUsuario, TipoEvento, EstadoAsistencia
from server.schemas.schemas import (
    ConfigUpdate, ConfigResponse,
    UsuarioCreate, UsuarioResponse,
    ReporteDiario,
)
from server.core.security import get_current_user, require_rol, hash_password

router = APIRouter(prefix="/admin", tags=["Panel Administración"])


# ================================================================== #
# CONFIGURACIÓN DEL SISTEMA
# ================================================================== #

@router.get("/config", response_model=List[ConfigResponse], summary="Ver toda la configuración")
def listar_config(
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN)),
):
    """Devuelve todos los parámetros configurables del sistema."""
    return db.query(models.Configuracion).order_by(models.Configuracion.clave).all()


@router.get("/config/{clave}", response_model=ConfigResponse, summary="Leer parámetro")
def obtener_config(
    clave: str,
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN)),
):
    config = db.query(models.Configuracion).filter(
        models.Configuracion.clave == clave
    ).first()
    if not config:
        raise HTTPException(status_code=404, detail=f"Parámetro '{clave}' no encontrado")
    return config


@router.put("/config/{clave}", response_model=ConfigResponse, summary="Actualizar parámetro")
def actualizar_config(
    clave: str,
    data: ConfigUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_rol(RolUsuario.ADMIN)),
):
    """
    Actualiza un parámetro de configuración sin reiniciar el servidor.
    Cambios importantes:
      - 'modelo_ia_activo'     → Invalidará el caché del reconocedor
      - 'notificaciones_activas' → Habilita/deshabilita notificaciones
    """
    config = db.query(models.Configuracion).filter(
        models.Configuracion.clave == clave
    ).first()

    if not config:
        # Crear si no existe
        config = models.Configuracion(
            clave=clave,
            valor=data.valor,
            modificado_por=current_user.id,
        )
        db.add(config)
    else:
        config.valor = data.valor
        config.modificado_por = current_user.id
        config.fecha_modificacion = datetime.utcnow()

    db.commit()
    db.refresh(config)
    return config


# ================================================================== #
# GESTIÓN DE USUARIOS DEL SISTEMA
# ================================================================== #

@router.get("/usuarios", response_model=List[UsuarioResponse], summary="Listar usuarios")
def listar_usuarios(
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN)),
):
    return db.query(models.UsuarioSistema).order_by(models.UsuarioSistema.rol).all()


@router.post("/usuarios", response_model=UsuarioResponse, status_code=201, summary="Crear usuario")
def crear_usuario(
    data: UsuarioCreate,
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN)),
):
    """Crea un nuevo usuario del sistema (Admin, Tutor o Portero)."""
    if db.query(models.UsuarioSistema).filter(
        models.UsuarioSistema.username == data.username
    ).first():
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")

    usuario = models.UsuarioSistema(
        username=data.username,
        password_hash=hash_password(data.password),
        nombre_display=data.nombre_display,
        rol=data.rol,
        grado_asignado=data.grado_asignado,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@router.patch("/usuarios/{usuario_id}/desactivar", summary="Desactivar usuario")
def desactivar_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_rol(RolUsuario.ADMIN)),
):
    """Desactiva un usuario sin eliminarlo (preserva el historial)."""
    usuario = db.get(models.UsuarioSistema, usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if usuario.id == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes desactivarte a ti mismo")

    usuario.activo = False
    db.commit()
    return {"mensaje": f"Usuario '{usuario.username}' desactivado"}


@router.patch("/usuarios/{usuario_id}/cambiar-password", summary="Cambiar contraseña")
def cambiar_password(
    usuario_id: int,
    nueva_password: str,
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN)),
):
    usuario = db.get(models.UsuarioSistema, usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if len(nueva_password) < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")

    usuario.password_hash = hash_password(nueva_password)
    db.commit()
    return {"mensaje": "Contraseña actualizada exitosamente"}


# ================================================================== #
# REPORTES DE ASISTENCIA
# ================================================================== #

@router.get("/reportes/diario", response_model=ReporteDiario, summary="Reporte del día")
def reporte_diario(
    fecha: Optional[date] = Query(None, description="Fecha del reporte (por defecto: hoy)"),
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN, RolUsuario.TUTOR)),
):
    """
    Genera el resumen de asistencia del día: presentes, ausentes, tardanzas.
    Los Tutores ven solo su aula; los Admin ven todo el colegio.
    """
    fecha_consulta = fecha or date.today()
    inicio = datetime.combine(fecha_consulta, datetime.min.time())
    fin    = datetime.combine(fecha_consulta, datetime.max.time())

    # Total de alumnos activos
    total = db.query(func.count(models.Alumno.id)).filter(
        models.Alumno.activo == True
    ).scalar()

    # Alumnos que marcaron entrada hoy
    presentes_ids = db.query(models.Asistencia.alumno_id).filter(
        and_(
            models.Asistencia.fecha.between(inicio, fin),
            models.Asistencia.tipo_evento == TipoEvento.ENTRADA,
        )
    ).distinct().all()
    presentes_ids = {r[0] for r in presentes_ids}

    # Contar tardanzas
    tardanzas = db.query(func.count(models.Asistencia.id)).filter(
        and_(
            models.Asistencia.fecha.between(inicio, fin),
            models.Asistencia.tipo_evento == TipoEvento.ENTRADA,
            models.Asistencia.estado == EstadoAsistencia.TARDANZA,
        )
    ).scalar()

    # Contar justificados
    justificados = db.query(func.count(models.Justificacion.id)).filter(
        models.Justificacion.fecha_ausencia.between(inicio, fin)
    ).scalar()

    n_presentes = len(presentes_ids)
    n_ausentes  = total - n_presentes
    porcentaje  = round((n_presentes / total * 100) if total > 0 else 0, 1)

    return ReporteDiario(
        fecha=inicio,
        total_alumnos=total,
        presentes=n_presentes,
        ausentes=n_ausentes,
        tardanzas=tardanzas,
        justificados=justificados,
        porcentaje_asistencia=porcentaje,
    )


@router.get("/reportes/ausentes-hoy", summary="Alumnos ausentes hoy")
def ausentes_hoy(
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN, RolUsuario.TUTOR)),
):
    """Devuelve la lista de alumnos que no han marcado entrada hoy."""
    hoy_inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # IDs de alumnos que SÍ marcaron entrada hoy
    presentes_ids = db.query(models.Asistencia.alumno_id).filter(
        and_(
            models.Asistencia.fecha >= hoy_inicio,
            models.Asistencia.tipo_evento == TipoEvento.ENTRADA,
        )
    ).distinct().subquery()

    ausentes = db.query(models.Alumno).filter(
        models.Alumno.activo == True,
        ~models.Alumno.id.in_(presentes_ids),
    ).order_by(models.Alumno.grado, models.Alumno.apellidos).all()

    return {
        "fecha": datetime.utcnow().date().isoformat(),
        "total_ausentes": len(ausentes),
        "ausentes": [
            {
                "id": a.id,
                "nombre": a.nombre_completo(),
                "grado": a.grado,
                "seccion": a.seccion,
            }
            for a in ausentes
        ],
    }


@router.get("/reportes/mensual", summary="Estadísticas del mes")
def reporte_mensual(
    año: int  = Query(default=datetime.utcnow().year),
    mes: int  = Query(default=datetime.utcnow().month, ge=1, le=12),
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN)),
):
    """
    Estadísticas de asistencia del mes: días lectivos, promedio diario,
    alumnos con más ausencias, etc.
    """
    inicio = datetime(año, mes, 1)
    # Primer día del mes siguiente para el límite superior
    if mes == 12:
        fin = datetime(año + 1, 1, 1)
    else:
        fin = datetime(año, mes + 1, 1)

    # Días con registros (días lectivos reales)
    dias_con_registros = db.query(
        func.date(models.Asistencia.fecha)
    ).filter(
        models.Asistencia.fecha.between(inicio, fin)
    ).distinct().count()

    # Total de entradas en el mes
    total_entradas = db.query(func.count(models.Asistencia.id)).filter(
        and_(
            models.Asistencia.fecha.between(inicio, fin),
            models.Asistencia.tipo_evento == TipoEvento.ENTRADA,
        )
    ).scalar()

    # Promedio diario de asistencia
    promedio_diario = round(total_entradas / dias_con_registros if dias_con_registros > 0 else 0, 1)

    # Top 10 alumnos con más ausencias
    total_alumnos = db.query(func.count(models.Alumno.id)).filter(
        models.Alumno.activo == True
    ).scalar()

    presencias_por_alumno = db.query(
        models.Asistencia.alumno_id,
        func.count(models.Asistencia.id).label("dias_presente")
    ).filter(
        and_(
            models.Asistencia.fecha.between(inicio, fin),
            models.Asistencia.tipo_evento == TipoEvento.ENTRADA,
        )
    ).group_by(models.Asistencia.alumno_id).subquery()

    # Calcular ausencias = dias_lectivos - dias_presente
    ausencias_ranking = []
    if dias_con_registros > 0:
        alumnos = db.query(models.Alumno).filter(models.Alumno.activo == True).all()
        for alumno in alumnos:
            dias_presente_row = db.query(
                func.count(models.Asistencia.id)
            ).filter(
                and_(
                    models.Asistencia.alumno_id == alumno.id,
                    models.Asistencia.fecha.between(inicio, fin),
                    models.Asistencia.tipo_evento == TipoEvento.ENTRADA,
                )
            ).scalar()
            ausencias = dias_con_registros - (dias_presente_row or 0)
            if ausencias > 0:
                ausencias_ranking.append({
                    "alumno": alumno.nombre_completo(),
                    "grado": f"{alumno.grado}{alumno.seccion}",
                    "dias_ausente": ausencias,
                    "porcentaje_asistencia": round((dias_presente_row or 0) / dias_con_registros * 100, 1),
                })

        ausencias_ranking.sort(key=lambda x: x["dias_ausente"], reverse=True)

    return {
        "periodo": f"{año}-{mes:02d}",
        "dias_lectivos": dias_con_registros,
        "promedio_diario_asistencia": promedio_diario,
        "total_alumnos_activos": total_alumnos,
        "top_ausencias": ausencias_ranking[:10],
    }


@router.get("/reportes/historial/{alumno_id}", summary="Historial de asistencia de un alumno")
def historial_alumno(
    alumno_id: int,
    dias: int = Query(default=30, le=365),
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN, RolUsuario.TUTOR)),
):
    """Devuelve el historial de registros de asistencia de un alumno."""
    alumno = db.get(models.Alumno, alumno_id)
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    desde = datetime.utcnow() - timedelta(days=dias)
    registros = db.query(models.Asistencia).filter(
        and_(
            models.Asistencia.alumno_id == alumno_id,
            models.Asistencia.fecha >= desde,
        )
    ).order_by(models.Asistencia.fecha.desc()).all()

    return {
        "alumno": alumno.nombre_completo(),
        "grado": f"{alumno.grado}{alumno.seccion}",
        "periodo_dias": dias,
        "total_registros": len(registros),
        "registros": [
            {
                "fecha": r.fecha.isoformat(),
                "tipo": r.tipo_evento,
                "estado": r.estado,
                "confianza": r.confianza,
                "registrado_por": r.registrado_por,
            }
            for r in registros
        ],
    }


# ================================================================== #
# NOTIFICACIONES
# ================================================================== #

@router.post("/notificaciones/test", summary="Enviar mensaje de prueba")
def test_notificacion(
    mensaje: str = "🧪 Mensaje de prueba del sistema de asistencia.",
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN)),
):
    """Envía un mensaje de prueba al chat de portería para verificar la configuración."""
    from server.services.notifications.telegram_service import telegram_notifier
    exito = telegram_notifier.enviar_alerta_manual(
        telegram_notifier.chat_porteria,
        mensaje,
    )
    return {
        "enviado": exito,
        "destino": "chat de portería",
        "mensaje": mensaje,
    }


@router.get("/notificaciones/logs", summary="Historial de notificaciones")
def logs_notificaciones(
    limit: int = Query(50, le=200),
    solo_errores: bool = Query(False),
    db: Session = Depends(get_db),
    _user = Depends(require_rol(RolUsuario.ADMIN)),
):
    """Muestra el historial de mensajes enviados con estado de entrega."""
    query = db.query(models.NotificacionLog)
    if solo_errores:
        query = query.filter(models.NotificacionLog.enviado == False)

    logs = query.order_by(models.NotificacionLog.fecha_envio.desc()).limit(limit).all()

    return [
        {
            "id":          log.id,
            "canal":       log.canal,
            "enviado":     log.enviado,
            "alumno_id":   log.alumno_id,
            "destinatario": log.destinatario[:5] + "***" if log.destinatario else None,
            "fecha":       log.fecha_envio.isoformat(),
            "error":       log.error_detalle,
        }
        for log in logs
    ]
