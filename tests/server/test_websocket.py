"""
tests/server/test_websocket.py
================================
Tests del endpoint WebSocket /ws/scan.

Usa el TestClient de FastAPI que soporta WebSockets
sin necesidad de un servidor real corriendo.

Uso:
    pytest tests/server/test_websocket.py -v
"""

import json
import base64
import pytest
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from server.db.database import Base, get_db
from server.db import models
from server.core.security import hash_password, create_access_token
from server.main import app

engine_test = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestingSession = sessionmaker(bind=engine_test)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine_test)
    db = TestingSession()
    try:
        db.add(models.UsuarioSistema(
            username="portero_ws", password_hash=hash_password("port1234"),
            nombre_display="Portero WS", rol=models.RolUsuario.PORTERO,
        ))
        db.add(models.Alumno(
            codigo="WS001", nombres="Test", apellidos="WebSocket",
            grado="1", seccion="A", turno="MAÑANA", activo=True,
        ))
        db.add(models.Configuracion(clave="modelo_ia_activo", valor="HOG"))
        db.add(models.Configuracion(clave="notificaciones_activas", valor="false"))
        db.commit()
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=engine_test)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def token_ws(client):
    """Obtiene un JWT válido para conectar el WebSocket."""
    r = client.post("/api/auth/login", json={"username": "portero_ws", "password": "port1234"})
    return r.json()["access_token"]


def _frame_b64():
    """Genera un frame JPEG mínimo en base64."""
    try:
        import cv2
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        _, jpeg = cv2.imencode(".jpg", frame)
        return base64.b64encode(jpeg.tobytes()).decode()
    except ImportError:
        # JPEG mínimo válido hardcodeado
        jpeg_min = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46,
            0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
            0xFF, 0xD9,
        ])
        return base64.b64encode(jpeg_min).decode()


# ================================================================== #
# TEST: Conexión y autenticación
# ================================================================== #

class TestWebSocketConexion:

    def test_ping_pong(self, client, token_ws):
        """El WebSocket debe responder pong a un ping."""
        with client.websocket_connect(f"/ws/scan?token={token_ws}") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "pong"

    def test_token_invalido_rechazado(self, client):
        """Con token inválido, la conexión debe rechazarse."""
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/scan?token=token_falso") as ws:
                ws.send_text(json.dumps({"type": "ping"}))
                ws.receive_text()

    def test_tipo_desconocido(self, client, token_ws):
        """Un tipo de mensaje desconocido debe retornar error."""
        with client.websocket_connect(f"/ws/scan?token={token_ws}") as ws:
            ws.send_text(json.dumps({"type": "tipo_inventado"}))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "error"

    def test_json_invalido(self, client, token_ws):
        """JSON malformado debe retornar error sin crashear."""
        with client.websocket_connect(f"/ws/scan?token={token_ws}") as ws:
            ws.send_text("esto no es json {{{")
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "error"


# ================================================================== #
# TEST: Scan por WebSocket
# ================================================================== #

class TestWebSocketScan:

    @patch("server.api.routes.reconocimiento.get_active_recognizer")
    def test_scan_sin_rostros(self, mock_recognizer, client, token_ws):
        """Sin rostros detectados, debe devolver scan_result con reconocido=False."""
        recognizer_mock = MagicMock()
        recognizer_mock.identificar.return_value = []
        mock_recognizer.return_value = recognizer_mock

        with client.websocket_connect(f"/ws/scan?token={token_ws}") as ws:
            ws.send_text(json.dumps({
                "type":       "scan",
                "frame_b64":  _frame_b64(),
                "cliente_id": "test-ws",
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "scan_result"
            assert resp["data"]["reconocido"] is False

    @patch("server.api.routes.reconocimiento.get_active_recognizer")
    def test_scan_con_alumno_registra_entrada(self, mock_recognizer, client, token_ws):
        """Con alumno reconocido, debe registrar ENTRADA y responder con datos."""
        recognizer_mock = MagicMock()
        recognizer_mock.identificar.return_value = [(1, 0.88)]
        mock_recognizer.return_value = recognizer_mock

        with client.websocket_connect(f"/ws/scan?token={token_ws}") as ws:
            ws.send_text(json.dumps({
                "type":       "scan",
                "frame_b64":  _frame_b64(),
                "cliente_id": "test-ws",
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "scan_result"
            data = resp["data"]
            assert data["reconocido"] is True
            assert "asistencia" in data
            assert data["asistencia"]["tipo_evento"] == "ENTRADA"


# ================================================================== #
# TEST: Registro manual por WebSocket
# ================================================================== #

class TestWebSocketManual:

    def test_registro_manual_valido(self, client, token_ws):
        with client.websocket_connect(f"/ws/scan?token={token_ws}") as ws:
            ws.send_text(json.dumps({
                "type":        "manual",
                "alumno_id":   1,
                "tipo_evento": "ENTRADA",
                "notas":       "Test manual WS",
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "manual_result"
            assert resp["data"].get("ok") is True

    def test_registro_manual_alumno_inexistente(self, client, token_ws):
        with client.websocket_connect(f"/ws/scan?token={token_ws}") as ws:
            ws.send_text(json.dumps({
                "type":        "manual",
                "alumno_id":   99999,
                "tipo_evento": "ENTRADA",
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "manual_result"
            assert "error" in resp["data"]

    def test_registro_manual_sin_alumno_id(self, client, token_ws):
        with client.websocket_connect(f"/ws/scan?token={token_ws}") as ws:
            ws.send_text(json.dumps({
                "type":        "manual",
                "tipo_evento": "ENTRADA",
                # sin alumno_id
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "manual_result"
            assert "error" in resp["data"]


# ================================================================== #
# TEST: Estado del WebSocket
# ================================================================== #

class TestWebSocketStatus:

    def test_endpoint_status_disponible(self, client, token_ws):
        """El endpoint HTTP /ws/status debe reportar las conexiones activas."""
        headers = {"Authorization": f"Bearer {token_ws}"}
        r = client.get("/ws/status")
        # No requiere auth, debe responder
        assert r.status_code == 200
        data = r.json()
        assert "clientes_conectados" in data
        assert isinstance(data["clientes_conectados"], int)
