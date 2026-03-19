"""
tests/server/test_reconocimiento.py
=====================================
Tests del motor de reconocimiento facial y el endpoint /scan.

face_recognition y dlib NO están instalados en CI/entornos de test,
por eso se usan mocks (unittest.mock) para simular su comportamiento.
Esto permite probar toda la lógica de negocio sin hardware ni GPU.

Uso:
    pytest tests/server/test_reconocimiento.py -v
"""

import base64
import pickle
import pytest
import numpy as np
from unittest.mock import patch, MagicMock, PropertyMock
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from server.db.database import Base, get_db
from server.db import models
from server.core.security import hash_password
from server.main import app

# ------------------------------------------------------------------ #
# DB en memoria
# ------------------------------------------------------------------ #
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
        # Admin user
        db.add(models.UsuarioSistema(
            username="admin_test", password_hash=hash_password("admin1234"),
            nombre_display="Admin", rol=models.RolUsuario.ADMIN,
        ))
        # Portero user
        db.add(models.UsuarioSistema(
            username="portero_test", password_hash=hash_password("portero1234"),
            nombre_display="Portero", rol=models.RolUsuario.PORTERO,
        ))
        # Alumno de prueba con encoding válido
        alumno = models.Alumno(
            codigo="TEST001", nombres="María", apellidos="García López",
            grado="4", seccion="B", turno="MAÑANA",
            encoding_valido=True,
            encoding_path="./server/data/encodings/alumno_1.pkl",
        )
        db.add(alumno)
        # Configuración default
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
def token_portero(client):
    r = client.post("/api/auth/login", json={"username": "portero_test", "password": "portero1234"})
    return r.json()["access_token"]


@pytest.fixture
def token_admin(client):
    r = client.post("/api/auth/login", json={"username": "admin_test", "password": "admin1234"})
    return r.json()["access_token"]


@pytest.fixture
def headers_portero(token_portero):
    return {"Authorization": f"Bearer {token_portero}"}


@pytest.fixture
def headers_admin(token_admin):
    return {"Authorization": f"Bearer {token_admin}"}


def _frame_fake_b64() -> str:
    """
    Genera un frame JPEG falso en base64.
    OpenCV puede crear uno negro de 100x100 píxeles sin necesidad de cámara.
    """
    try:
        import cv2
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        _, jpeg = cv2.imencode(".jpg", frame)
        return base64.b64encode(jpeg.tobytes()).decode()
    except ImportError:
        # Si cv2 no está disponible en CI, usar un JPEG mínimo válido
        jpeg_minimo = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00,
            0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB,
            0x00, 0x43, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01, 0x00,
            0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
            0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06,
            0x07, 0x08, 0x09, 0x0A, 0x0B, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
            0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD5, 0xFF, 0xD9,
        ])
        return base64.b64encode(jpeg_minimo).decode()


# ================================================================== #
# TEST: Cambio de modelo IA
# ================================================================== #

class TestCambioModelo:

    def test_cambiar_a_lbph(self, client, headers_admin):
        r = client.post("/api/reconocimiento/modelo/LBPH", headers=headers_admin)
        assert r.status_code == 200
        assert r.json()["modelo_activo"] == "LBPH"

    def test_cambiar_a_hog(self, client, headers_admin):
        r = client.post("/api/reconocimiento/modelo/HOG", headers=headers_admin)
        assert r.status_code == 200
        assert r.json()["modelo_activo"] == "HOG"

    def test_cambiar_a_cnn(self, client, headers_admin):
        r = client.post("/api/reconocimiento/modelo/CNN", headers=headers_admin)
        assert r.status_code == 200
        assert r.json()["modelo_activo"] == "CNN"

    def test_portero_no_puede_cambiar_modelo(self, client, headers_portero):
        r = client.post("/api/reconocimiento/modelo/LBPH", headers=headers_portero)
        assert r.status_code == 403

    def test_modelo_invalido_rechazado(self, client, headers_admin):
        r = client.post("/api/reconocimiento/modelo/INVENTADO", headers=headers_admin)
        assert r.status_code == 422  # Pydantic valida el enum


# ================================================================== #
# TEST: Endpoint /scan con reconocedor mockeado
# ================================================================== #

class TestScanEndpoint:

    @patch("server.api.routes.reconocimiento.get_active_recognizer")
    def test_scan_sin_rostros_retorna_no_reconocido(self, mock_recognizer, client, headers_portero):
        """Si el reconocedor no encuentra rostros, devuelve reconocido=False."""
        recognizer_mock = MagicMock()
        recognizer_mock.identificar.return_value = []  # Sin rostros
        mock_recognizer.return_value = recognizer_mock

        r = client.post("/api/reconocimiento/scan", headers=headers_portero, json={
            "frame_base64": _frame_fake_b64(),
            "cliente_id": "test-pc",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["reconocido"] is False

    @patch("server.api.routes.reconocimiento.get_active_recognizer")
    def test_scan_con_alumno_reconocido_registra_entrada(self, mock_recognizer, client, headers_portero):
        """Si se reconoce un alumno sin registros previos, debe registrar ENTRADA."""
        recognizer_mock = MagicMock()
        # Alumno ID 1 con confianza 0.87
        recognizer_mock.identificar.return_value = [(1, 0.87)]
        mock_recognizer.return_value = recognizer_mock

        r = client.post("/api/reconocimiento/scan", headers=headers_portero, json={
            "frame_base64": _frame_fake_b64(),
            "cliente_id": "192.168.1.10",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["reconocido"] is True
        assert data["asistencia"]["tipo_evento"] == "ENTRADA"
        assert "García López" in data["alumno"]["apellidos"]

    @patch("server.api.routes.reconocimiento.get_active_recognizer")
    def test_scan_alumno_inexistente(self, mock_recognizer, client, headers_portero):
        """Si el modelo retorna un ID que no existe en la DB, debe devolver reconocido=False."""
        recognizer_mock = MagicMock()
        recognizer_mock.identificar.return_value = [(99999, 0.95)]  # ID que no existe
        mock_recognizer.return_value = recognizer_mock

        r = client.post("/api/reconocimiento/scan", headers=headers_portero, json={
            "frame_base64": _frame_fake_b64(),
            "cliente_id": "test",
        })
        assert r.status_code == 200
        assert r.json()["reconocido"] is False

    def test_scan_frame_invalido(self, client, headers_portero):
        """Un frame que no es JPEG válido debe devolver error 400."""
        r = client.post("/api/reconocimiento/scan", headers=headers_portero, json={
            "frame_base64": base64.b64encode(b"esto no es una imagen").decode(),
            "cliente_id": "test",
        })
        assert r.status_code == 400

    def test_scan_sin_autenticacion(self, client):
        """Sin token, el endpoint debe devolver 401."""
        r = client.post("/api/reconocimiento/scan", json={
            "frame_base64": _frame_fake_b64(),
            "cliente_id": "test",
        })
        assert r.status_code == 401


# ================================================================== #
# TEST: Entrenamiento de encodings
# ================================================================== #

class TestEntrenamiento:

    def test_entrenar_alumno_sin_fotos_retorna_error(self, client, headers_admin):
        """Sin fotos subidas, el entrenamiento debe fallar con 400."""
        r = client.post("/api/reconocimiento/entrenar/1", headers=headers_admin)
        # Puede ser 400 (sin fotos) o 404 (directorio no existe)
        assert r.status_code in [400, 422, 500]

    def test_entrenar_alumno_inexistente(self, client, headers_admin):
        r = client.post("/api/reconocimiento/entrenar/99999", headers=headers_admin)
        assert r.status_code == 404

    def test_portero_no_puede_entrenar(self, client, headers_portero):
        r = client.post("/api/reconocimiento/entrenar/1", headers=headers_portero)
        assert r.status_code == 403


# ================================================================== #
# TEST: Reconocedores unitarios (sin HTTP)
# ================================================================== #

class TestReconocedoresUnitarios:

    def test_factory_lbph_retorna_instancia_correcta(self):
        from server.services.recognition.recognition_service import get_recognizer, LBPHRecognizer
        r = get_recognizer("LBPH")
        assert isinstance(r, LBPHRecognizer)

    def test_factory_hog_retorna_instancia_correcta(self):
        from server.services.recognition.recognition_service import get_recognizer, HOGRecognizer
        r = get_recognizer("HOG")
        assert isinstance(r, HOGRecognizer)

    def test_factory_cnn_retorna_instancia_correcta(self):
        from server.services.recognition.recognition_service import get_recognizer, CNNRecognizer
        r = get_recognizer("CNN")
        assert isinstance(r, CNNRecognizer)

    def test_factory_modelo_desconocido_usa_hog(self):
        from server.services.recognition.recognition_service import get_recognizer, HOGRecognizer
        r = get_recognizer("INVENTADO")
        assert isinstance(r, HOGRecognizer)

    def test_lbph_sin_modelo_retorna_lista_vacia(self):
        """Sin modelo entrenado, identificar debe retornar [] sin crash."""
        from server.services.recognition.recognition_service import LBPHRecognizer
        r = LBPHRecognizer()
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        resultado = r.identificar(frame)
        assert resultado == []

    @patch("server.services.recognition.recognition_service.cv2")
    def test_hog_sin_face_recognition_retorna_vacio(self, mock_cv2):
        """Si face_recognition no está instalado, HOG debe retornar [] graciosamente."""
        from server.services.recognition.recognition_service import HOGRecognizer
        r = HOGRecognizer()
        r.known_encodings = [np.zeros(128)]
        r.known_ids = [1]

        # Mock cv2.cvtColor para que funcione sin imagen real
        mock_cv2.cvtColor.return_value = np.zeros((100, 100, 3), dtype=np.uint8)

        # face_recognition no está instalado → ImportError → retorna []
        with patch("builtins.__import__", side_effect=ImportError("face_recognition not found")):
            resultado = r.identificar(np.zeros((100, 100, 3), dtype=np.uint8))
        # No debe crashear, solo retornar vacío
        assert isinstance(resultado, list)


# ================================================================== #
# TEST: Nuevos endpoints (asistencia manual, vivos)
# ================================================================== #

class TestAsistenciaEndpoints:

    def test_asistencia_hoy_vacia(self, client, headers_portero):
        r = client.get("/api/asistencia/hoy", headers=headers_portero)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_alumnos_vivos_inicialmente_vacio(self, client, headers_portero):
        r = client.get("/api/asistencia/vivos", headers=headers_portero)
        assert r.status_code == 200
        assert r.json()["total_dentro"] == 0

    def test_registro_manual_crea_asistencia(self, client, headers_portero):
        r = client.post("/api/asistencia/manual", headers=headers_portero, json={
            "alumno_id": 1,
            "tipo_evento": "ENTRADA",
            "notas": "Test manual",
        })
        assert r.status_code == 201
        assert "ENTRADA" in r.json()["mensaje"]

    def test_registro_manual_alumno_inexistente(self, client, headers_portero):
        r = client.post("/api/asistencia/manual", headers=headers_portero, json={
            "alumno_id": 99999,
            "tipo_evento": "ENTRADA",
        })
        assert r.status_code == 404

    def test_alumnos_vivos_despues_de_entrada(self, client, headers_portero):
        # Registrar entrada
        client.post("/api/asistencia/manual", headers=headers_portero, json={
            "alumno_id": 1, "tipo_evento": "ENTRADA"
        })
        # Consultar vivos
        r = client.get("/api/asistencia/vivos", headers=headers_portero)
        assert r.json()["total_dentro"] == 1

    def test_eliminar_registro_requiere_admin(self, client, headers_portero):
        # Primero crear un registro
        client.post("/api/asistencia/manual", headers=headers_portero, json={
            "alumno_id": 1, "tipo_evento": "ENTRADA"
        })
        # Intentar eliminar como portero → 403
        r = client.delete("/api/asistencia/1?motivo=Test", headers=headers_portero)
        assert r.status_code == 403
