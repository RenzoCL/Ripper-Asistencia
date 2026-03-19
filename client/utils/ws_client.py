"""
client/utils/ws_client.py
==========================
Cliente WebSocket para comunicación de baja latencia con el servidor.

Usar en lugar de api_client.py cuando:
  - La LAN está cargada y el HTTP POST /scan tarda >400ms
  - Se quieren recibir notificaciones push del servidor sin polling

Diferencias con api_client.py:
  - Mantiene una conexión persistente (no handshake por cada frame)
  - ~3x más rápido en LANs cargadas
  - Requiere pip install websocket-client

Uso desde porteria_app.py:
    from client.utils.ws_client import WSCameraClient

    # Opcionalmente reemplazar la lógica HTTP:
    self.ws_client = WSCameraClient(server_url, token)
    self.ws_client.conectar()
    resultado = self.ws_client.enviar_scan(frame_bytes, cliente_id)
"""

import json
import base64
import logging
import threading
import time
from typing import Optional, Callable, Dict

logger = logging.getLogger(__name__)


class WSCameraClient:
    """
    Cliente WebSocket síncrono (ejecuta el loop WS en un hilo background).
    Expone métodos síncronos que la UI Tkinter puede llamar directamente.
    """

    def __init__(self, server_url: str, token: str):
        """
        Args:
            server_url: URL base del servidor, ej: "ws://192.168.1.100:8000"
            token:      JWT obtenido del login HTTP
        """
        self.ws_url    = f"{server_url.replace('http', 'ws')}/ws/scan?token={token}"
        self._ws       = None
        self._conectado = False
        self._lock     = threading.Lock()
        self._pendientes: Dict[str, dict] = {}  # msg_id → respuesta

    def conectar(self) -> bool:
        """
        Abre la conexión WebSocket en un hilo background.
        Retorna True si la conexión fue exitosa.
        """
        try:
            import websocket  # pip install websocket-client

            def on_message(ws, raw):
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("type", "")
                    with self._lock:
                        # Guardar respuesta para que el llamador la recoja
                        self._pendientes[msg_type] = msg
                except Exception as e:
                    logger.error("[WS] Error procesando mensaje: %s", e)

            def on_open(ws):
                self._conectado = True
                logger.info("[WS] Conexión establecida")

            def on_close(ws, code, msg):
                self._conectado = False
                logger.warning("[WS] Conexión cerrada (code=%s)", code)

            def on_error(ws, error):
                logger.error("[WS] Error: %s", error)

            self._ws = websocket.WebSocketApp(
                self.ws_url,
                on_message=on_message,
                on_open=on_open,
                on_close=on_close,
                on_error=on_error,
            )

            hilo = threading.Thread(
                target=self._ws.run_forever,
                kwargs={"ping_interval": 30, "ping_timeout": 10},
                daemon=True,
            )
            hilo.start()

            # Esperar hasta 3 segundos a que se conecte
            for _ in range(30):
                if self._conectado:
                    return True
                time.sleep(0.1)

            logger.warning("[WS] Timeout al conectar")
            return False

        except ImportError:
            logger.error("[WS] websocket-client no instalado. Ejecutar: pip install websocket-client")
            return False
        except Exception as e:
            logger.error("[WS] Error al conectar: %s", e)
            return False

    def desconectar(self):
        if self._ws:
            self._ws.close()
            self._conectado = False

    @property
    def activo(self) -> bool:
        return self._conectado

    def _enviar_y_esperar(self, payload: dict, tipo_respuesta: str, timeout: float = 5.0) -> Optional[dict]:
        """
        Envía un mensaje JSON y espera la respuesta del tipo indicado.
        Implementación simplificada: espera polling con lock.
        """
        if not self._conectado or not self._ws:
            return None

        # Limpiar respuesta anterior del mismo tipo
        with self._lock:
            self._pendientes.pop(tipo_respuesta, None)

        try:
            self._ws.send(json.dumps(payload))
        except Exception as e:
            logger.error("[WS] Error enviando: %s", e)
            return None

        # Esperar respuesta (polling con sleep corto)
        inicio = time.time()
        while time.time() - inicio < timeout:
            with self._lock:
                if tipo_respuesta in self._pendientes:
                    return self._pendientes.pop(tipo_respuesta)
            time.sleep(0.02)

        logger.warning("[WS] Timeout esperando respuesta tipo: %s", tipo_respuesta)
        return None

    def ping(self) -> bool:
        """Verifica que la conexión esté viva."""
        resp = self._enviar_y_esperar({"type": "ping"}, "pong", timeout=3.0)
        return resp is not None

    def enviar_scan(
        self,
        frame_bytes: bytes,
        cliente_id: str,
        tipo_forzado: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Envía un frame JPEG y retorna el ScanResultado del servidor.
        Equivalente a ColegioAPIClient.enviar_scan() pero vía WebSocket.
        """
        payload = {
            "type":       "scan",
            "frame_b64":  base64.b64encode(frame_bytes).decode(),
            "cliente_id": cliente_id,
        }
        if tipo_forzado:
            payload["tipo_forzado"] = tipo_forzado

        resp = self._enviar_y_esperar(payload, "scan_result", timeout=8.0)
        if resp:
            return resp.get("data", {})
        return None

    def registrar_manual(
        self,
        alumno_id: int,
        tipo_evento: str,
        notas: str = "",
    ) -> Optional[dict]:
        """Registro manual vía WebSocket."""
        payload = {
            "type":        "manual",
            "alumno_id":   alumno_id,
            "tipo_evento": tipo_evento,
            "notas":       notas,
        }
        resp = self._enviar_y_esperar(payload, "manual_result", timeout=5.0)
        if resp:
            return resp.get("data", {})
        return None
