"""
server/api/routes/websocket_scan.py
=====================================
Endpoint WebSocket para escaneo facial de baja latencia.

¿Cuándo usar WebSocket en vez de HTTP POST /scan?
  - La LAN está sobrecargada y el POST tarda >400ms consistentemente.
  - Hay múltiples clientes enviando frames simultáneamente.
  - Se quiere push de notificaciones del servidor al cliente (sin polling).

Protocolo de mensajes (JSON):
  Cliente → Servidor:
    {"type": "scan",   "frame_b64": "<jpeg base64>", "cliente_id": "192.168.1.10"}
    {"type": "manual", "alumno_id": 5, "tipo_evento": "ENTRADA", "notas": "..."}
    {"type": "ping"}

  Servidor → Cliente:
    {"type": "scan_result",   "data": <ScanResultado>}
    {"type": "manual_result", "data": {...}}
    {"type": "pong"}
    {"type": "error",         "detail": "mensaje de error"}
    {"type": "push",          "data": {...}}  ← notificaciones proactivas del servidor

Autenticación:
  El token JWT se envía en el parámetro de query:
    ws://192.168.1.100:8000/ws/scan?token=<jwt>
  Esto es necesario porque los WebSockets del browser no admiten
  headers personalizados al hacer el handshake.

Uso desde el cliente Python:
    import websockets, json, asyncio
    async def main():
        async with websockets.connect("ws://servidor:8000/ws/scan?token=...") as ws:
            await ws.send(json.dumps({"type": "ping"}))
            resp = json.loads(await ws.recv())
            print(resp)  # {"type": "pong"}
"""

import json
import base64
import logging
from typing import Dict, Set

try:
    import cv2
    import face_recognition
except ImportError:
    cv2 = None
    face_recognition = None
    print("Aviso: Librerías de visión no instaladas. Modo API activo.")
    
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.orm import Session

from server.core.security import decode_token
from server.db.database import get_db, SessionLocal
from server.db import models
from server.db.models import TipoEvento
from server.core.config import settings
from server.services.attendance_service import AttendanceService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])

_attendance_service = AttendanceService(
    rescan_threshold_seconds=settings.RESCAN_THRESHOLD_SECONDS
)


# ================================================================== #
# Gestor de conexiones activas
# ================================================================== #

class ConnectionManager:
    """
    Gestiona todas las conexiones WebSocket abiertas.
    Permite hacer broadcast a todos los clientes conectados
    (útil para notificaciones proactivas del servidor).
    """

    def __init__(self):
        # {cliente_id: websocket}
        self.conexiones: Dict[str, WebSocket] = {}

    async def conectar(self, ws: WebSocket, cliente_id: str):
        await ws.accept()
        self.conexiones[cliente_id] = ws
        logger.info("[WS] Cliente conectado: %s | Total: %d", cliente_id, len(self.conexiones))

    def desconectar(self, cliente_id: str):
        self.conexiones.pop(cliente_id, None)
        logger.info("[WS] Cliente desconectado: %s | Total: %d", cliente_id, len(self.conexiones))

    async def broadcast(self, mensaje: dict):
        """Envía un mensaje a todos los clientes conectados."""
        desconectados = []
        for cid, ws in self.conexiones.items():
            try:
                await ws.send_json(mensaje)
            except Exception:
                desconectados.append(cid)
        for cid in desconectados:
            self.desconectar(cid)

    async def enviar_a(self, cliente_id: str, mensaje: dict):
        """Envía un mensaje a un cliente específico."""
        ws = self.conexiones.get(cliente_id)
        if ws:
            try:
                await ws.send_json(mensaje)
            except Exception:
                self.desconectar(cliente_id)

    @property
    def total_clientes(self) -> int:
        return len(self.conexiones)


# Instancia global compartida entre todas las conexiones
manager = ConnectionManager()


# ================================================================== #
# Endpoint WebSocket principal
# ================================================================== #

@router.websocket("/ws/scan")
async def websocket_scan(
    ws: WebSocket,
    token: str = Query(..., description="JWT token del usuario"),
):
    """
    WebSocket de escaneo facial.
    
    Flujo de conexión:
      1. Cliente conecta con ?token=<jwt>
      2. Servidor valida el JWT → rechaza si inválido
      3. Loop: cliente envía frames → servidor responde con resultados
      4. Desconexión limpia al cerrar la app cliente
    """
    # --- Validar JWT antes de aceptar la conexión ---
    try:
        payload = decode_token(token)
        username = payload.get("sub")
        cliente_id = payload.get("id", username)
    except Exception:
        # Rechazar conexión con código 4001 (custom: auth failed)
        await ws.close(code=4001, reason="Token inválido o expirado")
        return

    await manager.conectar(ws, str(cliente_id))

    # Importar reconocedor (lazy para no ralentizar el startup)
    from server.api.routes.reconocimiento import get_active_recognizer

    try:
        while True:
            # Esperar mensaje del cliente (texto JSON)
            raw = await ws.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "detail": "JSON inválido"})
                continue

            msg_type = msg.get("type", "")

            # ── PING ──────────────────────────────────────────────
            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
                continue

            # ── SCAN FACIAL ───────────────────────────────────────
            if msg_type == "scan":
                result = await _procesar_scan_ws(
                    msg=msg,
                    ws=ws,
                    get_active_recognizer=get_active_recognizer,
                )
                if result:
                    await ws.send_json({"type": "scan_result", "data": result})
                continue

            # ── REGISTRO MANUAL ───────────────────────────────────
            if msg_type == "manual":
                result = await _procesar_manual_ws(msg)
                await ws.send_json({"type": "manual_result", "data": result})
                continue

            await ws.send_json({"type": "error", "detail": f"Tipo desconocido: {msg_type}"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("[WS] Error en cliente %s: %s", cliente_id, e)
    finally:
        manager.desconectar(str(cliente_id))


# ================================================================== #
# Helpers internos
# ================================================================== #

async def _procesar_scan_ws(msg: dict, ws: WebSocket, get_active_recognizer) -> dict:
    """Procesa un mensaje de tipo 'scan' y retorna el ScanResultado serializado."""
    frame_b64   = msg.get("frame_b64", "")
    cliente_id  = msg.get("cliente_id", "ws-client")
    tipo_forzado = msg.get("tipo_forzado")

    # Decodificar frame
    try:
        img_bytes = base64.b64decode(frame_b64)
        np_arr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Frame inválido")
    except Exception as e:
        return {"reconocido": False, "mensaje": f"Error decodificando frame: {e}"}

    # Sesión DB para este request
    db = SessionLocal()
    try:
        recognizer = get_active_recognizer(db)
        resultados = recognizer.identificar(frame)

        if not resultados:
            return {"reconocido": False, "mensaje": "Sin rostros detectados"}

        alumno_id, confianza = max(resultados, key=lambda x: x[1])

        # Tipo forzado desde el popup del portero
        tipo_forzado_enum = None
        if tipo_forzado:
            try:
                tipo_forzado_enum = TipoEvento(tipo_forzado.upper())
            except ValueError:
                pass

        config_modelo = db.query(models.Configuracion).filter(
            models.Configuracion.clave == "modelo_ia_activo"
        ).first()
        modelo_nombre = config_modelo.valor if config_modelo else "HOG"

        resultado = _attendance_service.procesar_scan(
            db=db,
            alumno_id=alumno_id,
            confianza=confianza,
            modelo_usado=modelo_nombre,
            cliente_id=cliente_id,
            tipo_forzado=tipo_forzado_enum,
        )

        return _serialize_resultado(resultado)

    finally:
        db.close()


async def _procesar_manual_ws(msg: dict) -> dict:
    """Procesa un registro manual enviado por WebSocket."""
    alumno_id   = msg.get("alumno_id")
    tipo_evento = msg.get("tipo_evento", "ENTRADA")
    notas       = msg.get("notas", "Manual vía WebSocket")

    if not alumno_id:
        return {"error": "alumno_id requerido"}

    db = SessionLocal()
    try:
        try:
            tipo = TipoEvento(tipo_evento.upper())
        except ValueError:
            return {"error": f"tipo_evento inválido: {tipo_evento}"}

        registro = _attendance_service.registrar_manual(
            db=db,
            alumno_id=alumno_id,
            tipo_evento=tipo,
            usuario_id=0,  # WebSocket no tiene usuario_id directo; usar 0 = sistema
            notas=notas,
        )

        alumno = db.get(models.Alumno, alumno_id)
        return {
            "ok": True,
            "mensaje": f"{tipo.value} registrada para {alumno.nombre_completo() if alumno else alumno_id}",
            "registro_id": registro.id,
        }
    except ValueError as e:
        return {"error": str(e)}
    finally:
        db.close()


def _serialize_resultado(resultado) -> dict:
    """Serializa un ScanResultado a dict simple para enviar por JSON."""
    d = {
        "reconocido":     resultado.reconocido,
        "requiere_popup": resultado.requiere_popup,
        "popup_mensaje":  resultado.popup_mensaje,
        "mensaje":        resultado.mensaje,
    }
    if resultado.alumno:
        a = resultado.alumno
        d["alumno"] = {
            "id":        a.id,
            "nombres":   a.nombres,
            "apellidos": a.apellidos,
            "grado":     a.grado,
            "seccion":   a.seccion,
            "turno":     a.turno,
        }
    if resultado.asistencia:
        r = resultado.asistencia
        d["asistencia"] = {
            "id":          r.id,
            "tipo_evento": r.tipo_evento.value if hasattr(r.tipo_evento, 'value') else r.tipo_evento,
            "estado":      r.estado.value if hasattr(r.estado, 'value') else r.estado,
            "fecha":       r.fecha.isoformat() if r.fecha else None,
            "confianza":   r.confianza,
        }
    return d


# ================================================================== #
# Endpoint de estado del WebSocket (HTTP normal)
# ================================================================== #

@router.get("/ws/status", summary="Estado de conexiones WebSocket activas")
def ws_status():
    """Muestra cuántos clientes están conectados por WebSocket."""
    return {
        "clientes_conectados": manager.total_clientes,
        "ids": list(manager.conexiones.keys()),
    }
