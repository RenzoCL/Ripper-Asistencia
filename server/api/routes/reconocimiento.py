"""
server/api/routes/reconocimiento.py
=====================================
Endpoints del motor de reconocimiento facial.

Endpoint crítico: POST /scan
  - Recibe un frame de la webcam del cliente.
  - Lo pasa al reconocedor activo.
  - Aplica la lógica de asistencia (regla de 5 min, doble marcado).
  - Retorna el resultado al cliente para mostrar en pantalla.
"""

import base64
import logging
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from server.db.database import get_db
from server.db import models
from server.db.models import RolUsuario, TipoEvento, ModeloIA
from server.schemas.schemas import ScanResultado
from server.core.security import get_current_user, require_rol
from server.core.config import settings
from server.services.recognition.recognition_service import get_recognizer, BaseRecognizer
from server.services.attendance_service import AttendanceService
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reconocimiento", tags=["Reconocimiento Facial"])

# ------------------------------------------------------------------ #
# Estado global del reconocedor (en memoria, se reinicia con el server)
# ------------------------------------------------------------------ #
# Mantenemos una instancia del reconocedor cargada en RAM para evitar
# recargar los encodings en cada request (sería muy lento).
_recognizer_cache: Optional[BaseRecognizer] = None
_attendance_service = AttendanceService(
    rescan_threshold_seconds=settings.RESCAN_THRESHOLD_SECONDS
)


def get_active_recognizer(db: Session) -> BaseRecognizer:
    """
    Obtiene el reconocedor activo, recargándolo si el modelo cambió.
    Lee el modelo activo desde la tabla de configuración (no desde .env)
    para respetar cambios hechos desde el Panel Admin.
    """
    global _recognizer_cache

    # Leer modelo activo desde DB (así el Admin puede cambiarlo en caliente)
    config = db.query(models.Configuracion).filter(
        models.Configuracion.clave == "modelo_ia_activo"
    ).first()

    modelo_actual = config.valor if config else settings.DEFAULT_RECOGNITION_MODEL.value

    # Si no hay reconocedor en caché, crear uno nuevo
    if _recognizer_cache is None or type(_recognizer_cache).__name__.upper() not in modelo_actual:
        logger.info("Cargando reconocedor: %s", modelo_actual)
        _recognizer_cache = get_recognizer(modelo_actual, settings.FACE_TOLERANCE)
        _recognizer_cache.cargar_encodings(settings.ENCODINGS_DIR)

    return _recognizer_cache


# ------------------------------------------------------------------ #
# Schemas de request
# ------------------------------------------------------------------ #

class ScanRequest(BaseModel):
    """
    Payload del cliente al enviar un frame para reconocimiento.
    El frame se envía como imagen base64 para simplificar el transporte HTTP.
    """
    frame_base64:  str            # Frame JPG codificado en base64
    cliente_id:    str            # IP o nombre del PC cliente
    tipo_forzado:  Optional[str] = None  # "ENTRADA" o "SALIDA" (solo si portero decide manualmente)


class EntrenarRequest(BaseModel):
    alumno_id: int


# ------------------------------------------------------------------ #
# ENDPOINT PRINCIPAL: Procesar scan facial
# ------------------------------------------------------------------ #

@router.post("/scan", response_model=ScanResultado, summary="Procesar frame de webcam")
def procesar_scan(
    request: ScanRequest,
    db: Session = Depends(get_db),
    _user: models.UsuarioSistema = Depends(get_current_user),
):
    """
    Endpoint más crítico del sistema.

    Flujo:
      1. Decodificar el frame base64 → array NumPy.
      2. Pasar el frame al reconocedor activo (LBPH/HOG/CNN).
      3. Si se detecta un alumno, procesar con AttendanceService.
      4. Retornar ScanResultado al cliente.

    El cliente (PC de portería) llama a este endpoint cada vez que
    la cámara captura un frame con un rostro.
    """
    # --- Decodificar frame ---
    try:
        img_bytes = base64.b64decode(request.frame_base64)
        np_arr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if frame is None:
            raise ValueError("Frame inválido")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error decodificando frame: {e}")

    # --- Obtener reconocedor y procesar ---
    recognizer = get_active_recognizer(db)
    resultados = recognizer.identificar(frame)

    if not resultados:
        return ScanResultado(
            reconocido=False,
            mensaje="No se detectó ningún rostro conocido",
        )

    # Tomar el resultado con mayor confianza (si detecta varios rostros)
    alumno_id, confianza = max(resultados, key=lambda x: x[1])

    # Obtener modelo activo para registrar en la DB
    config_modelo = db.query(models.Configuracion).filter(
        models.Configuracion.clave == "modelo_ia_activo"
    ).first()
    modelo_nombre = config_modelo.valor if config_modelo else settings.DEFAULT_RECOGNITION_MODEL.value

    # Procesar tipo forzado (cuando el portero decide manualmente tras popup)
    tipo_forzado = None
    if request.tipo_forzado:
        try:
            tipo_forzado = TipoEvento(request.tipo_forzado.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail="tipo_forzado inválido. Use 'ENTRADA' o 'SALIDA'")

    # --- Aplicar lógica de asistencia ---
    resultado = _attendance_service.procesar_scan(
        db=db,
        alumno_id=alumno_id,
        confianza=confianza,
        modelo_usado=modelo_nombre,
        cliente_id=request.cliente_id,
        tipo_forzado=tipo_forzado,
    )

    return resultado


# ------------------------------------------------------------------ #
# ENDPOINT: Entrenar encoding de un alumno
# ------------------------------------------------------------------ #

@router.post("/entrenar/{alumno_id}", summary="Entrenar encoding facial de un alumno")
def entrenar_alumno(
    alumno_id: int,
    db: Session = Depends(get_db),
    _user: models.UsuarioSistema = Depends(require_rol(RolUsuario.ADMIN)),
):
    """
    Genera el archivo de encoding a partir de las fotos subidas.
    Debe ejecutarse después de subir nuevas fotos con POST /alumnos/{id}/fotos.
    """
    import os
    from pathlib import Path

    alumno = db.get(models.Alumno, alumno_id)
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    fotos_dir = Path(settings.PHOTOS_DIR) / str(alumno_id)
    if not fotos_dir.exists() or not any(fotos_dir.glob("*.jpg")):
        raise HTTPException(
            status_code=400,
            detail="No hay fotos para este alumno. Subir fotos primero con POST /alumnos/{id}/fotos"
        )

    encoding_path = Path(settings.ENCODINGS_DIR) / f"alumno_{alumno_id}.pkl"

    # Usar el reconocedor activo para el entrenamiento
    recognizer = get_active_recognizer(db)
    exito = recognizer.entrenar(
        alumno_id=alumno_id,
        fotos_dir=str(fotos_dir),
        encoding_path=str(encoding_path),
    )

    if not exito:
        raise HTTPException(
            status_code=422,
            detail="No se pudieron extraer encodings faciales. Verificar calidad de las fotos."
        )

    # Actualizar estado en la DB
    alumno.encoding_path = str(encoding_path)
    alumno.encoding_valido = True
    db.commit()

    # Invalidar caché del reconocedor para que recargue con el nuevo alumno
    global _recognizer_cache
    _recognizer_cache = None

    return {
        "mensaje": f"Encoding generado exitosamente para {alumno.nombre_completo()}",
        "encoding_path": str(encoding_path),
    }


# ------------------------------------------------------------------ #
# ENDPOINT: Cambiar modelo de IA (Panel Admin)
# ------------------------------------------------------------------ #

@router.post("/modelo/{nombre_modelo}", summary="Cambiar modelo de reconocimiento activo")
def cambiar_modelo(
    nombre_modelo: ModeloIA,
    db: Session = Depends(get_db),
    _user: models.UsuarioSistema = Depends(require_rol(RolUsuario.ADMIN)),
):
    """
    Selector de Modelos (Funcionalidad Crítica).
    Cambia el modelo activo sin reiniciar el servidor.
    El cambio persiste en la DB y afecta a todos los clientes.
    """
    global _recognizer_cache

    # Guardar nuevo modelo en configuración persistente
    config = db.query(models.Configuracion).filter(
        models.Configuracion.clave == "modelo_ia_activo"
    ).first()

    if config:
        config.valor = nombre_modelo.value
    else:
        config = models.Configuracion(
            clave="modelo_ia_activo",
            valor=nombre_modelo.value,
            descripcion="Modelo de reconocimiento facial activo (LBPH/HOG/CNN)",
        )
        db.add(config)

    db.commit()

    # Invalidar caché: el próximo scan cargará el nuevo modelo
    _recognizer_cache = None

    descripciones = {
        "LBPH": "Nivel 1 – Ultra ligero (PCs antiguas, OpenCV puro)",
        "HOG":  "Nivel 2 – Balanceado (CPU moderno, DEFAULT)",
        "CNN":  "Nivel 3 – Alta precisión (requiere GPU para máxima velocidad)",
    }

    logger.info("Modelo cambiado a: %s por usuario %s", nombre_modelo.value, _user.username)

    return {
        "modelo_activo": nombre_modelo.value,
        "descripcion":   descripciones.get(nombre_modelo.value, ""),
        "mensaje":       f"Modelo cambiado a {nombre_modelo.value}. Se recargará en el próximo scan.",
    }
