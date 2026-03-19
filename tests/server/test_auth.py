"""
tests/server/test_auth.py
==========================
Tests de autenticación: login, tokens JWT, protección de rutas y roles.

Uso:
    pytest tests/ -v
    pytest tests/server/test_auth.py -v --tb=short
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.main import app
from server.db.database import Base, get_db
from server.db import models
from server.core.security import hash_password

# ------------------------------------------------------------------ #
# Base de datos en memoria para tests (no toca la DB de producción)
# ------------------------------------------------------------------ #
TEST_DB_URL = "sqlite:///:memory:"

engine_test = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Sustituir la DB real por la de tests
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Crea las tablas y datos de prueba antes de cada test; las borra al finalizar."""
    Base.metadata.create_all(bind=engine_test)

    # Crear usuarios de prueba
    db = TestingSessionLocal()
    try:
        usuarios_test = [
            models.UsuarioSistema(
                username="admin_test",
                password_hash=hash_password("admin1234"),
                nombre_display="Admin de Prueba",
                rol=models.RolUsuario.ADMIN,
            ),
            models.UsuarioSistema(
                username="portero_test",
                password_hash=hash_password("portero1234"),
                nombre_display="Portero de Prueba",
                rol=models.RolUsuario.PORTERO,
            ),
            models.UsuarioSistema(
                username="tutor_test",
                password_hash=hash_password("tutor1234"),
                nombre_display="Tutor de Prueba",
                rol=models.RolUsuario.TUTOR,
                grado_asignado="3A",
            ),
        ]
        for u in usuarios_test:
            db.add(u)

        # Alumno de prueba
        alumno = models.Alumno(
            codigo="2024001",
            nombres="Juan Carlos",
            apellidos="Pérez Gómez",
            grado="3",
            seccion="A",
            turno="MAÑANA",
        )
        db.add(alumno)
        db.commit()
    finally:
        db.close()

    yield  # Correr el test

    Base.metadata.drop_all(bind=engine_test)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def token_admin(client):
    resp = client.post("/api/auth/login", json={"username": "admin_test", "password": "admin1234"})
    return resp.json()["access_token"]


@pytest.fixture
def token_portero(client):
    resp = client.post("/api/auth/login", json={"username": "portero_test", "password": "portero1234"})
    return resp.json()["access_token"]


@pytest.fixture
def headers_admin(token_admin):
    return {"Authorization": f"Bearer {token_admin}"}


@pytest.fixture
def headers_portero(token_portero):
    return {"Authorization": f"Bearer {token_portero}"}


# ================================================================== #
# TEST: Login
# ================================================================== #

class TestLogin:

    def test_login_exitoso_admin(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "admin_test",
            "password": "admin1234",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["usuario"]["rol"] == "ADMIN"

    def test_login_exitoso_portero(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "portero_test",
            "password": "portero1234",
        })
        assert resp.status_code == 200
        assert resp.json()["usuario"]["rol"] == "PORTERO"

    def test_login_password_incorrecta(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "admin_test",
            "password": "password_equivocada",
        })
        assert resp.status_code == 401
        assert "incorrectos" in resp.json()["detail"].lower()

    def test_login_usuario_inexistente(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "no_existe",
            "password": "cualquiera",
        })
        assert resp.status_code == 401

    def test_login_usuario_inactivo(self, client):
        # Desactivar el portero
        db = TestingSessionLocal()
        portero = db.query(models.UsuarioSistema).filter_by(username="portero_test").first()
        portero.activo = False
        db.commit()
        db.close()

        resp = client.post("/api/auth/login", json={
            "username": "portero_test",
            "password": "portero1234",
        })
        assert resp.status_code == 401


class TestGetMe:

    def test_get_me_autenticado(self, client, headers_admin):
        resp = client.get("/api/auth/me", headers=headers_admin)
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin_test"

    def test_get_me_sin_token(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_get_me_token_invalido(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer token_falso"})
        assert resp.status_code == 401


# ================================================================== #
# TEST: Protección de rutas por rol
# ================================================================== #

class TestProteccionRoles:

    def test_admin_puede_crear_alumno(self, client, headers_admin):
        resp = client.post("/api/alumnos/", json={
            "codigo": "2024999",
            "nombres": "Test",
            "apellidos": "Alumno",
            "grado": "1",
            "seccion": "B",
            "turno": "MAÑANA",
        }, headers=headers_admin)
        assert resp.status_code == 201

    def test_portero_no_puede_crear_alumno(self, client, headers_portero):
        resp = client.post("/api/alumnos/", json={
            "codigo": "2024888",
            "nombres": "Test",
            "apellidos": "Alumno",
            "grado": "1",
            "seccion": "B",
            "turno": "MAÑANA",
        }, headers=headers_portero)
        assert resp.status_code == 403

    def test_portero_puede_listar_alumnos(self, client, headers_portero):
        resp = client.get("/api/alumnos/", headers=headers_portero)
        assert resp.status_code == 200

    def test_portero_no_puede_ver_config_admin(self, client, headers_portero):
        resp = client.get("/api/admin/config", headers=headers_portero)
        assert resp.status_code == 403

    def test_admin_puede_ver_config(self, client, headers_admin):
        resp = client.get("/api/admin/config", headers=headers_admin)
        assert resp.status_code == 200


# ================================================================== #
# TEST: Health y endpoints públicos
# ================================================================== #

class TestEndpointsPublicos:

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_alumnos_requiere_auth(self, client):
        resp = client.get("/api/alumnos/")
        assert resp.status_code == 401
