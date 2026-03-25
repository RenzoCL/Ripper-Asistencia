"""
client/utils/api_client.py
============================
FIXES aplicados:
  1. login() ahora envía form-data (no JSON) — compatible con OAuth2PasswordRequestForm
  2. Auto-refresh de token: si quedan < 30 min, renueva silenciosamente
  3. _token_expira_en guarda el timestamp de expiración para calcular tiempo restante
  4. Mejor manejo de errores de red con mensajes claros en español
"""

import os
import socket
import logging
import base64
import time
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

    # Renovar token cuando queden menos de 30 minutos
    REFRESH_THRESHOLD_SECONDS = 1800

    def __init__(self, server_url: str = BASE_URL):
        self.base_url = server_url.rstrip("/")
        self._token: Optional[str] = None
        self._usuario: Optional[Dict] = None
        self._token_expira_en: float = 0.0  # timestamp Unix

        entorno = "NUBE (Render)" if MODO_NUBE else "LOCAL (LAN)"
        logger.info(f"Iniciando cliente API en modo: {entorno} -> {self.base_url}")

        self.session = requests.Session()

        # Reintentos automáticos para errores de red transitorios
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
        """
        FIX: ahora envía form-data (application/x-www-form-urlencoded)
        compatible con OAuth2PasswordRequestForm del servidor.
        El servidor también acepta JSON, pero form-data es más estándar.
        """
        # FIX CRÍTICO: usar data= (form-data) en lugar de json=
        resp = self.session.post(
            f"{self.base_url}/api/auth/login",
            data={"username": username, "password": password},  # <-- form-data
            timeout=TIMEOUT
        )
        data = self._manejar_respuesta(resp)

        self._token = data["access_token"]
        self._usuario = data["usuario"]

        # Guardar tiempo de expiración para auto-refresh
        expira_en = data.get("expira_en", 28800)  # 8h por default
        self._token_expira_en = time.time() + expira_en

        self.session.headers.update({"Authorization": f"Bearer {self._token}"})
        return self._usuario

    def refresh_token_si_necesario(self) -> bool:
        """
        Renueva el token silenciosamente si quedan menos de 30 minutos.
        Llamar al inicio de cada operación crítica (scan, registro manual).
        Retorna True si se renovó, False si no era necesario.
        """
        if not self._token:
            return False

        tiempo_restante = self._token_expira_en - time.time()
        if tiempo_restante > self.REFRESH_THRESHOLD_SECONDS:
            return False

        try:
            logger.info("Token expira en %.0f min — renovando...", tiempo_restante / 60)
            resp = self.session.get(
                f"{self.base_url}/api/auth/refresh",
                timeout=TIMEOUT
            )
            data = self._manejar_respuesta(resp)
            self._token = data["access_token"]
            expira_en = data.get("expira_en", 28800)
            self._token_expira_en = time.time() + expira_en
            self.session.headers.update({"Authorization": f"Bearer {self._token}"})
            logger.info("Token renovado exitosamente")
            return True
        except Exception as e:
            logger.warning("No se pudo renovar token: %s", e)
            return False

    def logout(self):
        """Limpia el token de la sesión."""
        try:
            if self._token:
                self.session.post(f"{self.base_url}/api/auth/logout", timeout=5)
        except Exception:
            pass
        finally:
            self._token = None
            self._usuario = None
            self._token_expira_en = 0.0
            self.session.headers.pop("Authorization", None)

    @property
    def autenticado(self) -> bool:
        return self._token is not None

    @property
    def usuario_actual(self) -> Optional[Dict]:
        return self._usuario

    @property
    def segundos_hasta_expiracion(self) -> float:
        """Cuántos segundos quedan antes de que expire el token."""
        return max(0.0, self._token_expira_en - time.time())

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
        Renueva el token automáticamente si está próximo a expirar.
        """
        self.refresh_token_si_necesario()

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
        return self._get("/api/alumnos/", params={"buscar": termino, "limit": 10})

    def obtener_alumno(self, alumno_id: int) -> Dict:
        return self._get(f"/api/alumnos/{alumno_id}")

    def listar_alumnos(self, grado: str = "", limit: int = 50, skip: int = 0) -> List[Dict]:
        params = {"limit": limit, "skip": skip}
        if grado:
            params["grado"] = grado
        return self._get("/api/alumnos/", params=params) or []

    # ------------------------------------------------------------------ #
    # Asistencia
    # ------------------------------------------------------------------ #

    def registrar_manual(
        self,
        alumno_id: int,
        tipo_evento: str,
        notas: str = "",
    ) -> Dict:
        self.refresh_token_si_necesario()
        return self._post("/api/asistencia/manual", json={
            "alumno_id":   alumno_id,
            "tipo_evento": tipo_evento,
            "notas":       notas or "Registro manual desde cliente portería",
        })

    def asistencia_hoy(self, tipo: str = "") -> List[Dict]:
        params = {"tipo": tipo} if tipo else {}
        return self._get("/api/asistencia/hoy", params=params) or []

    def alumnos_dentro(self) -> Dict:
        return self._get("/api/asistencia/vivos")

    # ------------------------------------------------------------------ #
    # Reportes
    # ------------------------------------------------------------------ #

    def reporte_diario(self) -> Dict:
        return self._get("/api/admin/reportes/diario")

    def ausentes_hoy(self) -> Dict:
        return self._get("/api/admin/reportes/ausentes-hoy")

    # ------------------------------------------------------------------ #
    # Sistema
    # ------------------------------------------------------------------ #

    def ping(self) -> bool:
        try:
            resp = self.session.get(f"{self.base_url}/health", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def cambiar_modelo_ia(self, modelo: str) -> Dict:
        return self._post(f"/api/reconocimiento/modelo/{modelo}", json={})

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
            msg = "Sin conexión al servidor. "
            msg += "Verifica tu internet." if MODO_NUBE else "Verifica que el servidor esté corriendo."
            raise APIError(0, msg)
        except requests.Timeout:
            msg = f"Tiempo agotado ({TIMEOUT}s). "
            msg += "Render está despertando, reintenta." if MODO_NUBE else "El servidor no responde."
            raise APIError(0, msg)

    def _post(self, path: str, json: Dict = None) -> Any:
        try:
            resp = self.session.post(
                f"{self.base_url}{path}",
                json=json,
                timeout=TIMEOUT,
            )
            return self._manejar_respuesta(resp)
        except requests.ConnectionError:
            raise APIError(0, "No se puede conectar al servidor.")
        except requests.Timeout:
            raise APIError(0, f"Tiempo de espera agotado ({TIMEOUT}s).")

    @staticmethod
    def _manejar_respuesta(response: requests.Response) -> Any:
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
    """Detecta la IP local del PC cliente."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "desconocido"