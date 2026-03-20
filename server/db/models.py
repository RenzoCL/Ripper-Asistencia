"""
server/db/models.py
===================
Definición completa del esquema de la base de datos como modelos ORM.

Diseño de tablas:
  - alumno:         Datos personales + referencia a foto/encoding.
  - tutor_contacto: Teléfonos/emails del apoderado (separado para privacidad).
  - asistencia:     Registro de cada evento (entrada/salida) con timestamp.
  - usuario_sistema:Cuentas del sistema (Admin, Tutor, Portero).
  - configuracion:  Parámetros globales persistentes (ej: modelo de IA activo).
  - justificacion:  Ausencias justificadas ingresadas por el Tutor.
  - notificacion_log: Historial de mensajes enviados (Telegram/WhatsApp).
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean,
    Float, ForeignKey, Text, Enum as SAEnum
)
from sqlalchemy.orm import relationship
import enum

from server.db.database import Base

from server.db.enums import (
    TipoEvento, EstadoAsistencia, RolUsuario, 
    ModeloIA, CanalNotificacion
)


# ================================================================== #
# TABLA: alumno
# ================================================================== #
class Alumno(Base):
    """
    Entidad central del sistema.
    El campo 'foto_encoding_path' apunta al archivo .pkl con los
    embeddings faciales ya calculados (no la foto original).
    Las fotos originales viven en /server/photos/{id_alumno}/.
    """
    __tablename__ = "alumno"

    id              = Column(Integer, primary_key=True, index=True)
    codigo          = Column(String(20), unique=True, index=True, nullable=False)
    nombres         = Column(String(100), nullable=False)
    apellidos       = Column(String(100), nullable=False)
    grado           = Column(String(10), nullable=False)   # Ej: "3A", "5B"
    seccion         = Column(String(5), nullable=False)
    turno           = Column(String(10), nullable=False)   # "MAÑANA" | "TARDE"
    foto_path       = Column(String(255))                  # Ruta relativa a foto de perfil
    encoding_path   = Column(String(255))                  # Ruta al .pkl con embeddings
    encoding_valido = Column(Boolean, default=False)       # ¿Ya fue entrenado?
    activo          = Column(Boolean, default=True)
    fecha_registro  = Column(DateTime, default=datetime.utcnow)
    fecha_actualizacion = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    contactos    = relationship("TutorContacto",   back_populates="alumno", cascade="all, delete-orphan")
    asistencias  = relationship("Asistencia",      back_populates="alumno")
    justificaciones = relationship("Justificacion", back_populates="alumno")

    def nombre_completo(self) -> str:
        return f"{self.apellidos}, {self.nombres}"

    def __repr__(self):
        return f"<Alumno {self.codigo} | {self.nombre_completo()} | {self.grado}{self.seccion}>"


# ================================================================== #
# TABLA: tutor_contacto
# ================================================================== #
class TutorContacto(Base):
    """
    Datos de contacto del apoderado/tutor del alumno.
    Tabla separada para facilitar el cumplimiento de privacidad:
    se puede truncar sin afectar el historial de asistencia.
    """
    __tablename__ = "tutor_contacto"

    id              = Column(Integer, primary_key=True, index=True)
    alumno_id       = Column(Integer, ForeignKey("alumno.id"), nullable=False)
    nombre_tutor    = Column(String(150), nullable=False)
    parentesco      = Column(String(50))                   # "Padre", "Madre", "Abuelo", etc.
    telefono        = Column(String(20))
    whatsapp        = Column(String(20))                   # Puede diferir del teléfono
    email           = Column(String(150))
    notificar_entrada  = Column(Boolean, default=True)
    notificar_salida   = Column(Boolean, default=True)
    notificar_tardanza = Column(Boolean, default=True)
    notificar_ausencia = Column(Boolean, default=True)

    # Relaciones
    alumno = relationship("Alumno", back_populates="contactos")

    def __repr__(self):
        return f"<Contacto {self.nombre_tutor} ({self.parentesco}) → Alumno ID {self.alumno_id}>"


# ================================================================== #
# TABLA: asistencia
# ================================================================== #
class Asistencia(Base):
    """
    Registro atómico de cada evento de acceso.

    Lógica de doble marcado:
      - Primer scan del día → tipo=ENTRADA
      - Segundo scan (>5 min después) → tipo=SALIDA
      - Segundo scan (<5 min) → popup al portero (no se registra automáticamente)

    El campo 'confianza' guarda el score del modelo de IA (0.0 a 1.0).
    Útil para auditorías y para detectar falsos positivos.
    """
    __tablename__ = "asistencia"

    id              = Column(Integer, primary_key=True, index=True)
    alumno_id       = Column(Integer, ForeignKey("alumno.id"), nullable=False)
    fecha           = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    tipo_evento     = Column(SAEnum(TipoEvento), nullable=False)
    estado          = Column(SAEnum(EstadoAsistencia), default=EstadoAsistencia.PRESENTE)
    confianza       = Column(Float)                         # Score del modelo (0.0–1.0)
    modelo_usado    = Column(SAEnum(ModeloIA))              # Qué modelo procesó este scan
    cliente_id      = Column(String(50))                    # IP o nombre del PC cliente
    registrado_por  = Column(String(50))                    # "facial" | "manual_portero" | "manual_tutor"
    notas           = Column(Text)                          # Observaciones manuales

    # Relaciones
    alumno = relationship("Alumno", back_populates="asistencias")

    def __repr__(self):
        return (
            f"<Asistencia Alumno#{self.alumno_id} | "
            f"{self.tipo_evento} | {self.fecha:%Y-%m-%d %H:%M} | "
            f"conf={self.confianza:.2f}>"
        )


# ================================================================== #
# TABLA: usuario_sistema
# ================================================================== #
class UsuarioSistema(Base):
    """
    Cuentas de acceso al sistema (no son alumnos).
    La contraseña SIEMPRE se almacena hasheada con bcrypt.
    NUNCA guardar contraseñas en texto plano.
    """
    __tablename__ = "usuario_sistema"

    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String(50), unique=True, nullable=False, index=True)
    password_hash   = Column(String(255), nullable=False)   # bcrypt hash
    nombre_display  = Column(String(100), nullable=False)
    rol             = Column(SAEnum(RolUsuario), nullable=False)
    grado_asignado  = Column(String(10))                    # Solo para Tutores: su aula
    activo          = Column(Boolean, default=True)
    ultimo_login    = Column(DateTime)
    fecha_creacion  = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Usuario {self.username} | Rol: {self.rol}>"


# ================================================================== #
# TABLA: configuracion
# ================================================================== #
class Configuracion(Base):
    """
    Tabla clave-valor para parámetros del sistema.
    Permite cambiar configuraciones desde el Panel Admin sin editar
    archivos .env ni reiniciar el servidor.

    Ejemplos de claves:
      "modelo_ia_activo" → "HOG"
      "hora_inicio_tardanza" → "08:15"
      "whatsapp_habilitado" → "true"
    """
    __tablename__ = "configuracion"

    id          = Column(Integer, primary_key=True, index=True)
    clave       = Column(String(100), unique=True, nullable=False, index=True)
    valor       = Column(Text, nullable=False)
    descripcion = Column(Text)                              # Para mostrar en el Admin
    modificado_por = Column(Integer, ForeignKey("usuario_sistema.id"))
    fecha_modificacion = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Config {self.clave}={self.valor}>"


# ================================================================== #
# TABLA: justificacion
# ================================================================== #
class Justificacion(Base):
    """
    Ausencias justificadas ingresadas por un Tutor.
    Puede referirse a una fecha pasada (justificación retroactiva).
    """
    __tablename__ = "justificacion"

    id              = Column(Integer, primary_key=True, index=True)
    alumno_id       = Column(Integer, ForeignKey("alumno.id"), nullable=False)
    fecha_ausencia  = Column(DateTime, nullable=False, index=True)
    motivo          = Column(Text, nullable=False)
    documento_path  = Column(String(255))                   # Ej: foto de certificado médico
    registrado_por  = Column(Integer, ForeignKey("usuario_sistema.id"), nullable=False)
    fecha_registro  = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    alumno = relationship("Alumno", back_populates="justificaciones")

    def __repr__(self):
        return f"<Justificacion Alumno#{self.alumno_id} | {self.fecha_ausencia:%Y-%m-%d}>"


# ================================================================== #
# TABLA: notificacion_log
# ================================================================== #
class NotificacionLog(Base):
    """
    Historial de todas las notificaciones enviadas.
    Permite auditar qué mensajes se enviaron, cuándo y si llegaron.
    """
    __tablename__ = "notificacion_log"

    id              = Column(Integer, primary_key=True, index=True)
    alumno_id       = Column(Integer, ForeignKey("alumno.id"))
    canal           = Column(SAEnum(CanalNotificacion), nullable=False)
    destinatario    = Column(String(200))                   # Número/chat_id/username
    mensaje         = Column(Text, nullable=False)
    enviado         = Column(Boolean, default=False)
    error_detalle   = Column(Text)                          # Mensaje de error si falló
    fecha_envio     = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        estado = "✓" if self.enviado else "✗"
        return f"<Notif {estado} | {self.canal} | Alumno#{self.alumno_id}>"
