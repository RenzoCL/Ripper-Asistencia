"""
server/services/notifications/telegram_service.py
==================================================
Servicio de notificaciones via Telegram Bot API.

Arquitectura de notificaciones:
  - Se usa la librería python-telegram-bot en modo "Bot" simple (sin Updater).
  - Los mensajes se envían de forma ASÍNCRONA para no bloquear el registro
    de asistencia (el portero ve el resultado inmediatamente).
  - Cada envío se registra en la tabla `notificacion_log` (éxito o error).

Tipos de notificación implementados:
  1. Entrada de alumno        → Chat de tutor/apoderado
  2. Salida de alumno         → Chat de tutor/apoderado
  3. Tardanza detectada       → Chat de tutor + admin
  4. Alerta de ausencia       → Chat de admin (se envía al cerrar registro diario)
  5. Resumen diario           → Chat de admin

Configuración requerida en .env:
  TELEGRAM_BOT_TOKEN         → Token del bot (obtener con @BotFather)
  TELEGRAM_CHAT_ID_PORTERIA  → Chat del portero/guardia
  TELEGRAM_CHAT_ID_ADMIN     → Chat del administrador
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from server.core.config import settings
from server.db import models
from server.db.models import CanalNotificacion, TipoEvento, EstadoAsistencia

logger = logging.getLogger(__name__)


# ================================================================== #
# CLASE PRINCIPAL: TelegramNotifier
# ================================================================== #

class TelegramNotifier:
    """
    Wrapper sobre la API de Telegram para enviar mensajes al apoderado
    y al admin cuando hay eventos de asistencia.

    Diseño asíncrono:
      Los métodos 'notificar_*' son síncronos para facilitar su llamada
      desde AttendanceService (que no es async). Internamente usan
      asyncio.run() en un thread separado para no bloquear el event loop.
    """

    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_admin = settings.TELEGRAM_CHAT_ID_ADMIN
        self.chat_porteria = settings.TELEGRAM_CHAT_ID_PORTERIA
        self._habilitado = bool(self.token)

        if not self._habilitado:
            logger.warning(
                "TelegramNotifier: TELEGRAM_BOT_TOKEN no configurado. "
                "Las notificaciones estarán deshabilitadas."
            )

    # ------------------------------------------------------------------ #
    # Método base de envío
    # ------------------------------------------------------------------ #

    async def _enviar_mensaje_async(self, chat_id: str, texto: str) -> bool:
        """
        Envía un mensaje via Telegram Bot API usando httpx (async).
        Retorna True si el envío fue exitoso.

        Por qué httpx en lugar de python-telegram-bot:
          - Más ligero: no necesitamos el framework completo del bot.
          - Suficiente para enviar mensajes unidireccionales.
          - Evita conflictos con el event loop de FastAPI.
        """
        try:
            import httpx
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id":    chat_id,
                "text":       texto,
                "parse_mode": "HTML",  # Permite <b>, <i>, <code> en el mensaje
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error("Error enviando Telegram a %s: %s", chat_id, e)
            return False

    def _enviar_en_background(self, chat_id: str, texto: str) -> bool:
        """
        Ejecuta el envío async desde un contexto síncrono (AttendanceService).
        Crea un nuevo event loop para no interferir con el de FastAPI.
        """
        if not self._habilitado or not chat_id:
            return False
        try:
            # Intentar obtener el loop existente
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Si el loop ya está corriendo (dentro de FastAPI), crear tarea
                asyncio.ensure_future(self._enviar_mensaje_async(chat_id, texto))
                return True
            else:
                return loop.run_until_complete(self._enviar_mensaje_async(chat_id, texto))
        except RuntimeError:
            # No hay event loop: crear uno nuevo (caso de tests o scripts)
            return asyncio.run(self._enviar_mensaje_async(chat_id, texto))

    # ------------------------------------------------------------------ #
    # Generadores de mensajes con formato HTML
    # ------------------------------------------------------------------ #

    @staticmethod
    def _emoji_evento(tipo: str) -> str:
        return "🟢" if tipo == "ENTRADA" else "🔴"

    @staticmethod
    def _formatear_hora(dt: datetime) -> str:
        return dt.strftime("%H:%M")

    def _msg_entrada(self, alumno: models.Alumno, registro: models.Asistencia) -> str:
        emoji = self._emoji_evento("ENTRADA")
        tardanza = " ⏰ <b>TARDANZA</b>" if registro.estado == EstadoAsistencia.TARDANZA else ""
        return (
            f"{emoji} <b>ENTRADA registrada</b>{tardanza}\n"
            f"👤 <b>{alumno.nombre_completo()}</b>\n"
            f"🏫 Grado: {alumno.grado} — Sección: {alumno.seccion}\n"
            f"🕐 Hora: <code>{self._formatear_hora(registro.fecha)}</code>\n"
            f"📊 Confianza IA: {(registro.confianza or 0)*100:.0f}%"
        )

    def _msg_salida(self, alumno: models.Alumno, registro: models.Asistencia) -> str:
        return (
            f"🔴 <b>SALIDA registrada</b>\n"
            f"👤 <b>{alumno.nombre_completo()}</b>\n"
            f"🏫 Grado: {alumno.grado} — Sección: {alumno.seccion}\n"
            f"🕐 Hora: <code>{self._formatear_hora(registro.fecha)}</code>"
        )

    def _msg_tardanza(self, alumno: models.Alumno, registro: models.Asistencia) -> str:
        return (
            f"⏰ <b>TARDANZA detectada</b>\n"
            f"👤 <b>{alumno.nombre_completo()}</b>\n"
            f"🏫 Grado: {alumno.grado} — Sección: {alumno.seccion}\n"
            f"🕐 Hora de llegada: <code>{self._formatear_hora(registro.fecha)}</code>\n"
            f"ℹ️ Notificar al apoderado según protocolo del colegio."
        )

    def _msg_ausencia(self, alumno: models.Alumno, fecha: datetime) -> str:
        return (
            f"🚨 <b>AUSENCIA sin justificar</b>\n"
            f"👤 <b>{alumno.nombre_completo()}</b>\n"
            f"🏫 Grado: {alumno.grado} — Sección: {alumno.seccion}\n"
            f"📅 Fecha: <code>{fecha.strftime('%d/%m/%Y')}</code>\n"
            f"ℹ️ El apoderado debe presentar justificación."
        )

    # ------------------------------------------------------------------ #
    # API pública: métodos de notificación
    # ------------------------------------------------------------------ #

    def notificar_evento(
        self,
        db: Session,
        alumno: models.Alumno,
        registro: models.Asistencia,
    ) -> None:
        """
        Punto de entrada principal. Determina qué notificaciones enviar
        según el tipo de evento y el estado del registro.

        Se llama DESPUÉS del commit en AttendanceService.
        Es fire-and-forget: los errores se loguean pero no interrumpen el flujo.
        """
        # Verificar si las notificaciones están globalmente habilitadas
        config = db.query(models.Configuracion).filter(
            models.Configuracion.clave == "notificaciones_activas"
        ).first()
        if config and config.valor.lower() != "true":
            return

        tipo = registro.tipo_evento.value if hasattr(registro.tipo_evento, 'value') else registro.tipo_evento

        # --- 1. Notificación al chat de portería (siempre) ---
        if tipo == "ENTRADA":
            msg_porteria = self._msg_entrada(alumno, registro)
        else:
            msg_porteria = self._msg_salida(alumno, registro)

        exito_porteria = self._enviar_en_background(self.chat_porteria, msg_porteria)
        self._registrar_log(db, alumno.id, self.chat_porteria, msg_porteria, exito_porteria)

        # --- 2. Notificación especial de tardanza al admin ---
        estado = registro.estado.value if hasattr(registro.estado, 'value') else registro.estado
        if estado == "TARDANZA" and self.chat_admin:
            msg_tardanza = self._msg_tardanza(alumno, registro)
            exito_admin = self._enviar_en_background(self.chat_admin, msg_tardanza)
            self._registrar_log(db, alumno.id, self.chat_admin, msg_tardanza, exito_admin)

        # --- 3. Notificación al apoderado (si tiene WhatsApp/Telegram configurado) ---
        self._notificar_apoderados(db, alumno, registro, tipo)

    def _notificar_apoderados(
        self,
        db: Session,
        alumno: models.Alumno,
        registro: models.Asistencia,
        tipo: str,
    ) -> None:
        """
        Notifica a los apoderados que tengan Telegram configurado
        y la preferencia de notificación activada para este tipo de evento.
        """
        tipo_lower = tipo.lower()
        estado = registro.estado.value if hasattr(registro.estado, 'value') else registro.estado

        for contacto in alumno.contactos:
            # Verificar preferencias del contacto
            debe_notificar = (
                (tipo_lower == "entrada" and contacto.notificar_entrada) or
                (tipo_lower == "salida"  and contacto.notificar_salida)  or
                (estado == "TARDANZA"    and contacto.notificar_tardanza)
            )

            if not debe_notificar:
                continue

            # Por ahora: si el campo whatsapp tiene formato @telegram_username
            # o chat_id numérico, lo usamos como destinatario Telegram
            chat_id = contacto.whatsapp  # Campo reutilizado para Telegram ID apoderado
            if not chat_id or not chat_id.lstrip("-").isdigit():
                continue  # No tiene ID de Telegram configurado

            if tipo_lower == "entrada":
                msg = self._msg_entrada(alumno, registro)
            else:
                msg = self._msg_salida(alumno, registro)

            exito = self._enviar_en_background(chat_id, msg)
            self._registrar_log(db, alumno.id, chat_id, msg, exito)

    def notificar_ausencias_del_dia(
        self,
        db: Session,
        alumnos_ausentes: list,
        fecha: datetime,
    ) -> None:
        """
        Envía un resumen de ausencias al chat admin.
        Llamar al final del horario de entrada (ej: a las 09:00).
        """
        if not alumnos_ausentes:
            return

        resumen = (
            f"📋 <b>RESUMEN DE AUSENCIAS — {fecha.strftime('%d/%m/%Y')}</b>\n"
            f"Total ausentes: <b>{len(alumnos_ausentes)}</b>\n\n"
        )
        for alumno in alumnos_ausentes[:20]:  # Máximo 20 por mensaje para no truncar
            resumen += f"• {alumno.nombre_completo()} ({alumno.grado}{alumno.seccion})\n"

        if len(alumnos_ausentes) > 20:
            resumen += f"\n... y {len(alumnos_ausentes) - 20} más. Ver reporte completo en el sistema."

        exito = self._enviar_en_background(self.chat_admin, resumen)
        self._registrar_log(db, None, self.chat_admin, resumen, exito, canal=CanalNotificacion.TELEGRAM)

    def enviar_alerta_manual(self, chat_id: str, mensaje: str) -> bool:
        """Envía un mensaje de texto libre (para uso desde el Panel Admin)."""
        return self._enviar_en_background(chat_id, mensaje)

    # ------------------------------------------------------------------ #
    # Registro en base de datos
    # ------------------------------------------------------------------ #

    def _registrar_log(
        self,
        db: Session,
        alumno_id: Optional[int],
        destinatario: str,
        mensaje: str,
        enviado: bool,
        canal: CanalNotificacion = CanalNotificacion.TELEGRAM,
        error: Optional[str] = None,
    ) -> None:
        """
        Guarda el resultado de cada intento de notificación en la DB.
        Esto permite auditar qué mensajes se enviaron y detectar fallas.
        """
        try:
            log = models.NotificacionLog(
                alumno_id=alumno_id,
                canal=canal,
                destinatario=destinatario,
                mensaje=mensaje[:500],  # Limitar longitud para no inflar la DB
                enviado=enviado,
                error_detalle=error,
                fecha_envio=datetime.utcnow(),
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.error("Error registrando log de notificación: %s", e)


# ================================================================== #
# Instancia global (singleton)
# ================================================================== #
# Se inicializa una sola vez al importar el módulo.
# AttendanceService importa esta instancia directamente.
telegram_notifier = TelegramNotifier()
