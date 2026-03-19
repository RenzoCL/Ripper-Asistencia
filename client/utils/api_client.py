"""
client/utils/api_client.py
============================
Cliente HTTP para comunicarse con el servidor FastAPI.

Abstrae todos los calls HTTP en métodos simples que la UI puede usar.
Maneja el token JWT automáticamente después del login.

Diseño:
  - Síncrono (no async) porque Tkinter no es async-friendly.
  - Timeout configurable para entornos LAN lentos.
  - Reintenta el login automáticamente si el token expira.
  - Muestra errores claros al portero si el servidor no responde.
"""

import os
import socket
import logging
import base64
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

from client.config import BASE_URL, TIMEOUT, MODO_NUBE


@dataclass
class APIError(Exception):
    """Error personalizado con código HTTP y detalle del servidor."""
    codigo:  int
    detalle: str

    def __str__(self):
        return f"[HTTP {self.codigo}] {self.detalle}"


class ColegioAPIClient:
    """
    Cliente del API del servidor de asistencia.
    Una instancia por sesión de la aplicación cliente.
    """

    def __init__(self, server_url: str = BASE_URL):
        self.base_url = server_url.rstrip("/")
        self._token: Optional[str] = None
        self._usuario: Optional[Dict] = None

        entorno = "NUBE (Render)" if MODO_NUBE else "LOCAL (LAN)"
        logger.info(f"Iniciando cliente API en modo: {entorno} -> {self.base_url}")
        
        self.session = requests.Session()

        # Configurar sesión con reintentos automáticos
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    # ------------------------------------------------------------------ #
    # Autenticación
    # ------------------------------------------------------------------ #

    def login(self, username: str, password: str) -> Dict:
        # Petición directa como formulario
        resp = self.session.post(
            f"{self.base_url}/api/auth/login", 
            data={"username": username, "password": password},
            timeout=TIMEOUT
        )
        data = self._manejar_respuesta(resp)

        self._token = data["access_token"]
        self._usuario = data["usuario"]
        self.session.headers.update({"Authorization": f"Bearer {self._token}"})
        return self._usuario

    def logout(self):
        """Limpia el token de la sesión."""
        self._token = None
        self._usuario = None
        self.session.headers.pop("Authorization", None)

    @property
    def autenticado(self) -> bool:
        return self._token is not None

    @property
    def usuario_actual(self) -> Optional[Dict]:
        return self._usuario

    # ------------------------------------------------------------------ #
    # Reconocimiento Facial
    # ------------------------------------------------------------------ #

    def enviar_scan(
        self,
        frame_bytes: bytes,
        cliente_id: str,
        tipo_forzado: Optional[str] = None,
    ) -> Dict:
        """
        Envía un frame JPEG al servidor para reconocimiento facial.

        Args:
            frame_bytes:  Frame capturado por OpenCV en formato JPEG bytes.
            cliente_id:   Identificador de este PC cliente (IP o nombre).
            tipo_forzado: "ENTRADA" o "SALIDA" (cuando el portero elige manualmente).

        Returns:
            Dict con ScanResultado del servidor.
        """
        frame_b64 = base64.b64encode(frame_bytes).decode("utf-8")
        payload = {
            "frame_base64": frame_b64,
            "cliente_id":   cliente_id,
        }
        if tipo_forzado:
            payload["tipo_forzado"] = tipo_forzado

        return self._post("/api/reconocimiento/scan", json=payload)

    # ------------------------------------------------------------------ #
    # Alumnos
    # ------------------------------------------------------------------ #

    def buscar_alumno(self, termino: str) -> List[Dict]:
        """Busca alumnos por nombre o código. Usado en búsqueda manual."""
        return self._get("/api/alumnos/", params={"buscar": termino, "limit": 10})

    def obtener_alumno(self, alumno_id: int) -> Dict:
        return self._get(f"/api/alumnos/{alumno_id}")

    # ------------------------------------------------------------------ #
    # Reportes (para Panel Admin en la UI)
    # ------------------------------------------------------------------ #

    def reporte_diario(self) -> Dict:
        return self._get("/api/admin/reportes/diario")

    def ausentes_hoy(self) -> Dict:
        return self._get("/api/admin/reportes/ausentes-hoy")

    # ------------------------------------------------------------------ #
    # Sistema
    # ------------------------------------------------------------------ #

    def ping(self) -> bool:
        """Verifica conectividad con el servidor. No requiere auth."""
        try:
            resp = self.session.get(
                f"{self.base_url}/health",
                timeout=3,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def cambiar_modelo_ia(self, modelo: str) -> Dict:
        """Cambia el modelo de IA activo (solo Admin)."""
        return self._post(f"/api/reconocimiento/modelo/{modelo}", json={})

    def registrar_manual(
        self,
        alumno_id: int,
        tipo_evento: str,
        notas: str = "",
    ) -> Dict:
        """
        Registra entrada/salida manualmente para un alumno.
        tipo_evento: 'ENTRADA' o 'SALIDA'
        Conecta con POST /api/asistencia/manual
        """
        return self._post("/api/asistencia/manual", json={
            "alumno_id": alumno_id,
            "tipo_evento": tipo_evento,
            "notas": notas or f"Registro manual desde cliente portería",
        })

    def alumnos_dentro(self) -> Dict:
        """Retorna alumnos actualmente dentro del colegio (último evento = ENTRADA)."""
        return self._get("/api/asistencia/vivos")

    def asistencia_hoy(self, tipo: str = "") -> List[Dict]:
        """Lista todos los registros de asistencia del día."""
        params = {"tipo": tipo} if tipo else {}
        return self._get("/api/asistencia/hoy", params=params) or []

    # ------------------------------------------------------------------ #
    # Métodos internos HTTP
    # ------------------------------------------------------------------ #

    def _get(self, path: str, params: Dict = None) -> Any:
        try:
            resp = self.session.get(
                f"{self.base_url}{path}",
                params=params,
                timeout=TIMEOUT,
            )
            return self._manejar_respuesta(resp)
        except requests.ConnectionError:
            msg = "Error de conexión. "
            msg += "Verifica internet" if MODO_NUBE else "Verifica el servidor local y la red LAN."
            raise APIError(0, msg)
        except requests.Timeout:
            msg = f"Tiempo agotado ({TIMEOUT}s). "
            msg += "Render está despertando, reintenta en unos segundos." if MODO_NUBE else "Servidor local lento."
            raise APIError(0, msg)

    def _post(self, path: str, json: Dict = None, autenticado: bool = True) -> Any:
        headers = {}
        if not autenticado:
            headers = {k: v for k, v in self.session.headers.items() if k != "Authorization"}

        try:
            resp = self.session.post(
                f"{self.base_url}{path}",
                json=json,
                headers=headers if not autenticado else None,
                timeout=TIMEOUT,
            )
            return self._manejar_respuesta(resp)
        except requests.ConnectionError:
            raise APIError(0, "No se puede conectar al servidor. Verificar red LAN.")
        except requests.Timeout:
            raise APIError(0, f"Tiempo de espera agotado ({TIMEOUT}s).")

    @staticmethod
    def _manejar_respuesta(response: requests.Response) -> Any:
        """Procesa la respuesta HTTP y lanza APIError si es necesario."""
        if response.ok:
            try:
                return response.json()
            except Exception:
                return response.text
        else:
            try:
                detalle = response.json().get("detail", response.text)
            except Exception:
                detalle = response.text
            raise APIError(response.status_code, str(detalle))


def obtener_ip_local() -> str:
    """
    Detecta la IP local del PC cliente para usarla como identificador.
    Útil para rastrear desde qué punto de acceso se registró cada scan.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "desconocido"
