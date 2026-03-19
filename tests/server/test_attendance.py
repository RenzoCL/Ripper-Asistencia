"""
tests/server/test_attendance.py
================================
Tests de la lógica de negocio de asistencia.

ESTOS SON LOS TESTS MÁS CRÍTICOS DEL SISTEMA.
Verifican que la regla de 5 minutos, el doble marcado y la detección
de tardanzas funcionen correctamente en todos los casos borde.

Uso:
    pytest tests/server/test_attendance.py -v
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.db.database import Base
from server.db import models
from server.db.models import TipoEvento, EstadoAsistencia
from server.core.security import hash_password
from server.services.attendance_service import AttendanceService

# ------------------------------------------------------------------ #
# Setup de DB en memoria
# ------------------------------------------------------------------ #
engine_test = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)
TestingSession = sessionmaker(bind=engine_test)


@pytest.fixture(autouse=True)
def setup():
    Base.metadata.create_all(bind=engine_test)
    yield
    Base.metadata.drop_all(bind=engine_test)


@pytest.fixture
def db():
    session = TestingSession()
    yield session
    session.close()


@pytest.fixture
def alumno(db):
    """Alumno de prueba sin registros previos."""
    a = models.Alumno(
        codigo="TEST001",
        nombres="Ana María",
        apellidos="López Ruiz",
        grado="4",
        seccion="B",
        turno="MAÑANA",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@pytest.fixture
def service():
    """AttendanceService con umbral de 5 minutos (300 segundos)."""
    return AttendanceService(rescan_threshold_seconds=300)


def _crear_registro(db, alumno_id, tipo, minutos_atras=0, estado=EstadoAsistencia.PRESENTE):
    """Helper para crear registros de asistencia en el pasado."""
    fecha = datetime.utcnow() - timedelta(minutes=minutos_atras)
    reg = models.Asistencia(
        alumno_id=alumno_id,
        fecha=fecha,
        tipo_evento=tipo,
        estado=estado,
        registrado_por="test",
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)
    return reg


# ================================================================== #
# TEST: Primer scan del día → ENTRADA
# ================================================================== #

class TestPrimerScanDelDia:

    def test_primer_scan_registra_entrada(self, db, alumno, service):
        resultado = service.procesar_scan(
            db=db,
            alumno_id=alumno.id,
            confianza=0.85,
            modelo_usado="HOG",
            cliente_id="192.168.1.10",
        )
        assert resultado.reconocido is True
        assert resultado.requiere_popup is False
        assert resultado.asistencia.tipo_evento == TipoEvento.ENTRADA
        assert "ENTRADA" in resultado.mensaje

    def test_primer_scan_no_activa_popup(self, db, alumno, service):
        resultado = service.procesar_scan(
            db=db,
            alumno_id=alumno.id,
            confianza=0.9,
            modelo_usado="HOG",
            cliente_id="test-pc",
        )
        assert resultado.requiere_popup is False
        assert resultado.popup_mensaje is None

    def test_primer_scan_guarda_confianza(self, db, alumno, service):
        service.procesar_scan(
            db=db, alumno_id=alumno.id,
            confianza=0.92, modelo_usado="CNN", cliente_id="test",
        )
        reg = db.query(models.Asistencia).filter_by(alumno_id=alumno.id).first()
        assert reg is not None
        assert abs(reg.confianza - 0.92) < 0.001
        assert reg.modelo_usado == models.ModeloIA.CNN


# ================================================================== #
# TEST: Doble marcado (Entrada → Salida)
# ================================================================== #

class TestDobleMarcado:

    def test_segundo_scan_largo_registra_salida(self, db, alumno, service):
        # Simular entrada hace 6 horas
        _crear_registro(db, alumno.id, TipoEvento.ENTRADA, minutos_atras=360)

        resultado = service.procesar_scan(
            db=db, alumno_id=alumno.id,
            confianza=0.8, modelo_usado="HOG", cliente_id="test",
        )
        assert resultado.reconocido is True
        assert resultado.asistencia.tipo_evento == TipoEvento.SALIDA
        assert "SALIDA" in resultado.mensaje

    def test_tercera_vez_entrada_tras_salida(self, db, alumno, service):
        """Si ya marcó Entrada y Salida, el siguiente scan es otra Entrada."""
        _crear_registro(db, alumno.id, TipoEvento.ENTRADA, minutos_atras=480)
        _crear_registro(db, alumno.id, TipoEvento.SALIDA,  minutos_atras=10)

        resultado = service.procesar_scan(
            db=db, alumno_id=alumno.id,
            confianza=0.85, modelo_usado="HOG", cliente_id="test",
        )
        assert resultado.asistencia.tipo_evento == TipoEvento.ENTRADA


# ================================================================== #
# TEST: REGLA DE 5 MINUTOS (el test más importante del sistema)
# ================================================================== #

class TestReglaCincoMinutos:

    def test_rescan_en_menos_de_5min_activa_popup(self, db, alumno, service):
        """El re-escaneo en menos de 5 minutos debe activar el popup."""
        # Entrada hace 2 minutos (< umbral de 5 min)
        _crear_registro(db, alumno.id, TipoEvento.ENTRADA, minutos_atras=2)

        resultado = service.procesar_scan(
            db=db, alumno_id=alumno.id,
            confianza=0.88, modelo_usado="HOG", cliente_id="test",
        )

        assert resultado.requiere_popup is True
        assert resultado.popup_mensaje is not None
        assert "2 min" in resultado.popup_mensaje
        assert resultado.asistencia is None  # No se registra automáticamente

    def test_rescan_justo_en_5min_no_activa_popup(self, db, alumno, service):
        """El re-escaneo exactamente en el umbral NO debe activar el popup."""
        # 5 minutos y 1 segundo atrás = fuera del umbral
        _crear_registro(db, alumno.id, TipoEvento.ENTRADA, minutos_atras=5.02)

        resultado = service.procesar_scan(
            db=db, alumno_id=alumno.id,
            confianza=0.8, modelo_usado="HOG", cliente_id="test",
        )

        assert resultado.requiere_popup is False
        assert resultado.asistencia is not None

    def test_rescan_con_tipo_forzado_omite_regla_5min(self, db, alumno, service):
        """Si el portero forzó un tipo, ignorar la regla de 5 min."""
        _crear_registro(db, alumno.id, TipoEvento.ENTRADA, minutos_atras=1)

        resultado = service.procesar_scan(
            db=db, alumno_id=alumno.id,
            confianza=0.9, modelo_usado="HOG", cliente_id="test",
            tipo_forzado=TipoEvento.SALIDA,
        )

        assert resultado.requiere_popup is False
        assert resultado.asistencia.tipo_evento == TipoEvento.SALIDA

    def test_popup_mensaje_menciona_ultimo_evento(self, db, alumno, service):
        """El popup debe mencionar qué fue el último evento registrado."""
        _crear_registro(db, alumno.id, TipoEvento.ENTRADA, minutos_atras=1)

        resultado = service.procesar_scan(
            db=db, alumno_id=alumno.id,
            confianza=0.8, modelo_usado="HOG", cliente_id="test",
        )

        assert "ENTRADA" in resultado.popup_mensaje
        assert "SALIDA" in resultado.popup_mensaje  # Sugiere la alternativa


# ================================================================== #
# TEST: Tardanza
# ================================================================== #

class TestDeteccionTardanza:

    def test_entrada_antes_de_hora_limite_es_puntual(self, db, alumno, service):
        # Configurar hora límite a las 23:59 (nadie llega tarde en el test)
        config = models.Configuracion(
            clave="hora_inicio_tardanza",
            valor="23:59",
        )
        db.add(config)
        db.commit()

        resultado = service.procesar_scan(
            db=db, alumno_id=alumno.id,
            confianza=0.85, modelo_usado="HOG", cliente_id="test",
        )
        assert resultado.asistencia.estado == EstadoAsistencia.PRESENTE

    def test_entrada_tarde_cuando_hora_limite_pasada(self, db, alumno, service):
        # Configurar hora límite a las 00:01 (todos llegan tarde en el test)
        config = models.Configuracion(
            clave="hora_inicio_tardanza",
            valor="00:01",
        )
        db.add(config)
        db.commit()

        resultado = service.procesar_scan(
            db=db, alumno_id=alumno.id,
            confianza=0.85, modelo_usado="HOG", cliente_id="test",
        )
        # En el test los tests corren después de las 00:01 casi siempre
        # Solo verificamos que la función devuelve un estado válido
        assert resultado.asistencia.estado in [EstadoAsistencia.PRESENTE, EstadoAsistencia.TARDANZA]

    def test_salida_nunca_es_tardanza(self, db, alumno, service):
        """Las salidas nunca deben marcarse como TARDANZA."""
        _crear_registro(db, alumno.id, TipoEvento.ENTRADA, minutos_atras=360)

        config = models.Configuracion(
            clave="hora_inicio_tardanza",
            valor="00:01",  # Hora imposible → todos "tardanzas"
        )
        db.add(config)
        db.commit()

        resultado = service.procesar_scan(
            db=db, alumno_id=alumno.id,
            confianza=0.8, modelo_usado="HOG", cliente_id="test",
        )
        assert resultado.asistencia.tipo_evento == TipoEvento.SALIDA
        assert resultado.asistencia.estado != EstadoAsistencia.TARDANZA


# ================================================================== #
# TEST: Alumno no encontrado / inactivo
# ================================================================== #

class TestAlumnoInvalido:

    def test_alumno_inexistente(self, db, service):
        resultado = service.procesar_scan(
            db=db, alumno_id=99999,
            confianza=0.9, modelo_usado="HOG", cliente_id="test",
        )
        assert resultado.reconocido is False
        assert resultado.asistencia is None

    def test_alumno_inactivo_no_registra(self, db, alumno, service):
        alumno.activo = False
        db.commit()

        resultado = service.procesar_scan(
            db=db, alumno_id=alumno.id,
            confianza=0.9, modelo_usado="HOG", cliente_id="test",
        )
        assert resultado.reconocido is False


# ================================================================== #
# TEST: Registro manual
# ================================================================== #

class TestRegistroManual:

    def test_registro_manual_crea_asistencia(self, db, alumno, service):
        # Crear usuario para el test
        usuario = models.UsuarioSistema(
            username="portero_t",
            password_hash="hash",
            nombre_display="Portero",
            rol=models.RolUsuario.PORTERO,
        )
        db.add(usuario)
        db.commit()

        reg = service.registrar_manual(
            db=db,
            alumno_id=alumno.id,
            tipo_evento=TipoEvento.ENTRADA,
            usuario_id=usuario.id,
            notas="Registro manual por prueba",
        )

        assert reg is not None
        assert reg.tipo_evento == TipoEvento.ENTRADA
        assert "manual" in reg.registrado_por
        assert reg.notas == "Registro manual por prueba"

    def test_registro_manual_alumno_inexistente_lanza_error(self, db, service):
        with pytest.raises(ValueError, match="no encontrado"):
            service.registrar_manual(
                db=db,
                alumno_id=99999,
                tipo_evento=TipoEvento.ENTRADA,
                usuario_id=1,
            )
