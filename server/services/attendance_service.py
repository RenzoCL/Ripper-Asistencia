"""
server/services/attendance_service.py
======================================
Servicio de lógica de negocio de asistencia.

Encapsula las reglas de negocio FUERA de los endpoints de la API.
Esto permite testear la lógica sin necesidad de un servidor HTTP.

Reglas implementadas:
  1. Doble marcado (Entrada → Salida)
  2. Regla de 5 minutos: re-escaneo rápido → popup al portero
  3. Detección automática de tardanza según hora de inicio configurada
  4. Disparar notificaciones post-registro
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from server.db import models
from server.db.models import TipoEvento, EstadoAsistencia, ModeloIA
from server.schemas.schemas import ScanResultado, AsistenciaResponse, AlumnoResponse

logger = logging.getLogger(__name__)

# Importación diferida para evitar imports circulares al inicio
# El notificador se inyecta en el primer uso
_telegram_notifier = None

def _get_telegram():
    """Carga el notificador de Telegram solo cuando se necesita."""
    global _telegram_notifier
    if _telegram_notifier is None:
        try:
            from server.services.notifications.telegram_service import telegram_notifier
            _telegram_notifier = telegram_notifier
        except Exception as e:
            logger.warning("No se pudo cargar TelegramNotifier: %s", e)
    return _telegram_notifier


class AttendanceService:
    """
    Servicio de asistencia. Se instancia una vez y se reutiliza.
    """

    def __init__(self, rescan_threshold_seconds: int = 300):
        """
        Args:
            rescan_threshold_seconds: Segundos mínimos entre dos scans
                                      del mismo alumno para activar popup.
        """
        self.rescan_threshold = timedelta(seconds=rescan_threshold_seconds)

    # ------------------------------------------------------------------ #
    # MÉTODO PRINCIPAL: Procesar un scan facial
    # ------------------------------------------------------------------ #

    def procesar_scan(
        self,
        db: Session,
        alumno_id: int,
        confianza: float,
        modelo_usado: str,
        cliente_id: str,
        tipo_forzado: Optional[TipoEvento] = None,  # Cuando el portero decide manualmente
    ) -> ScanResultado:
        """
        Procesa el resultado de un reconocimiento facial y decide qué hacer.

        Flujo de decisión:
          1. ¿Existe el alumno? → Si no, retornar "no reconocido"
          2. ¿Hay registro previo hoy? → Si no, registrar ENTRADA
          3. ¿El último registro fue hace <5 min? → Popup al portero
          4. ¿El último registro fue ENTRADA? → Registrar SALIDA
          5. ¿El último registro fue SALIDA? → Registrar nueva ENTRADA

        Args:
            db:           Sesión de base de datos.
            alumno_id:    ID del alumno reconocido.
            confianza:    Score del modelo (0.0–1.0).
            modelo_usado: Nombre del modelo ("LBPH"/"HOG"/"CNN").
            cliente_id:   IP del PC que envió el scan.
            tipo_forzado: Si el portero ya decidió (entrada/salida forzada).

        Returns:
            ScanResultado con toda la información para el cliente.
        """
        # --- Paso 1: Obtener datos del alumno ---
        alumno = db.get(models.Alumno, alumno_id)
        if not alumno or not alumno.activo:
            return ScanResultado(
                reconocido=False,
                mensaje="Alumno no encontrado o inactivo",
            )

        # --- Paso 2: Obtener el último registro de HOY ---
        hoy_inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        ultimo_registro = (
            db.query(models.Asistencia)
            .filter(
                models.Asistencia.alumno_id == alumno_id,
                models.Asistencia.fecha >= hoy_inicio,
            )
            .order_by(models.Asistencia.fecha.desc())
            .first()
        )

        ahora = datetime.utcnow()

        # --- Paso 3: Aplicar regla de 5 minutos ---
        if not tipo_forzado and ultimo_registro:
            tiempo_desde_ultimo = ahora - ultimo_registro.fecha
            if tiempo_desde_ultimo < self.rescan_threshold:
                # Re-escaneo rápido → popup al portero, NO registrar automáticamente
                return ScanResultado(
                    reconocido=True,
                    alumno=AlumnoResponse.model_validate(alumno),
                    requiere_popup=True,
                    popup_mensaje=(
                        f"⚠️ {alumno.nombre_completo()} ya marcó "
                        f"{ultimo_registro.tipo_evento} hace "
                        f"{int(tiempo_desde_ultimo.seconds / 60)} min. "
                        f"¿Ignorar o registrar como "
                        f"{'SALIDA' if ultimo_registro.tipo_evento == TipoEvento.ENTRADA else 'ENTRADA'}?"
                    ),
                    mensaje=f"Re-escaneo detectado (<{self.rescan_threshold.seconds//60} min)",
                )

        # --- Paso 4: Determinar tipo de evento ---
        if tipo_forzado:
            tipo_evento = tipo_forzado
        elif not ultimo_registro:
            tipo_evento = TipoEvento.ENTRADA  # Primer scan del día
        elif ultimo_registro.tipo_evento == TipoEvento.ENTRADA:
            tipo_evento = TipoEvento.SALIDA
        else:
            tipo_evento = TipoEvento.ENTRADA  # Nueva entrada tras salida

        # --- Paso 5: Determinar estado (tardanza/puntual) ---
        estado = self._calcular_estado(db, tipo_evento, ahora)

        # --- Paso 6: Crear registro en la base de datos ---
        nuevo_registro = models.Asistencia(
            alumno_id=alumno_id,
            fecha=ahora,
            tipo_evento=tipo_evento,
            estado=estado,
            confianza=confianza,
            modelo_usado=modelo_usado,
            cliente_id=cliente_id,
            registrado_por="facial",
        )
        db.add(nuevo_registro)
        db.commit()
        db.refresh(nuevo_registro)

        logger.info(
            "Asistencia registrada: Alumno=%s | Evento=%s | Confianza=%.2f",
            alumno.codigo, tipo_evento.value, confianza
        )

        # --- Paso 7: Disparar notificaciones (fire-and-forget) ---
        # Se ejecuta DESPUÉS del commit para garantizar que el registro existe.
        # Si la notificación falla, el registro de asistencia NO se ve afectado.
        notificador = _get_telegram()
        if notificador:
            try:
                notificador.notificar_evento(db, alumno, nuevo_registro)
            except Exception as e:
                logger.error("Error disparando notificación Telegram: %s", e)

        return ScanResultado(
            reconocido=True,
            alumno=AlumnoResponse.model_validate(alumno),
            asistencia=AsistenciaResponse.model_validate(nuevo_registro),
            requiere_popup=False,
            mensaje=f"✅ {tipo_evento.value} registrada para {alumno.nombre_completo()}",
        )

    # ------------------------------------------------------------------ #
    # Método auxiliar: calcular estado (puntual/tardanza)
    # ------------------------------------------------------------------ #

    def _calcular_estado(
        self,
        db: Session,
        tipo_evento: TipoEvento,
        momento: datetime
    ) -> EstadoAsistencia:
        """
        Determina si una ENTRADA es puntual o tardanza.
        La hora límite se lee desde la tabla de configuración.
        """
        if tipo_evento != TipoEvento.ENTRADA:
            return EstadoAsistencia.PRESENTE  # Las salidas no aplican tardanza

        # Leer hora límite desde configuración (formato "HH:MM")
        config_tardanza = db.query(models.Configuracion).filter(
            models.Configuracion.clave == "hora_inicio_tardanza"
        ).first()

        if not config_tardanza:
            return EstadoAsistencia.PRESENTE  # Sin config, no hay tardanza

        try:
            hora_str = config_tardanza.valor  # Ej: "08:15"
            hora_limite = datetime.strptime(hora_str, "%H:%M").time()
            if momento.time() > hora_limite:
                return EstadoAsistencia.TARDANZA
        except ValueError:
            logger.warning("Formato inválido en hora_inicio_tardanza: %s", config_tardanza.valor)

        return EstadoAsistencia.PRESENTE

    # ------------------------------------------------------------------ #
    # Registro manual (sin reconocimiento facial)
    # ------------------------------------------------------------------ #

    def registrar_manual(
        self,
        db: Session,
        alumno_id: int,
        tipo_evento: TipoEvento,
        usuario_id: int,
        notas: Optional[str] = None,
    ) -> models.Asistencia:
        """
        Registra asistencia manualmente (por un Portero o Tutor).
        Se usa cuando el reconocimiento facial falla o como corrección.
        """
        alumno = db.get(models.Alumno, alumno_id)
        if not alumno:
            raise ValueError(f"Alumno ID {alumno_id} no encontrado")

        registro = models.Asistencia(
            alumno_id=alumno_id,
            fecha=datetime.utcnow(),
            tipo_evento=tipo_evento,
            estado=self._calcular_estado(db, tipo_evento, datetime.utcnow()),
            registrado_por=f"manual_usuario_{usuario_id}",
            notas=notas,
        )
        db.add(registro)
        db.commit()
        db.refresh(registro)

        logger.info(
            "Asistencia MANUAL: Alumno=%s | Evento=%s | Usuario=%d",
            alumno.codigo, tipo_evento.value, usuario_id
        )
        return registro
