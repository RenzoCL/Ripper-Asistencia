"""
server/schemas/schemas.py
=========================
Esquemas Pydantic para validación de datos en la API.

Por qué Pydantic:
  - FastAPI los usa automáticamente para validar request/response bodies.
  - Generan documentación OpenAPI (Swagger) de forma automática.
  - Separan el modelo de DB (SQLAlchemy) del modelo de API (Pydantic):
    así podemos devolver solo lo que el cliente necesita ver, sin exponer
    campos internos como password_hash o encoding_path.

Convención de nomenclatura:
  - *Base:    Campos comunes compartidos entre crear y leer.
  - *Create:  Campos necesarios al crear un registro.
  - *Update:  Campos opcionales para actualizar (todos con Optional).
  - *Response:Campos que devuelve la API al cliente.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, field_validator
from server.db.models import TipoEvento, EstadoAsistencia, RolUsuario, ModeloIA, CanalNotificacion


# ================================================================== #
# ALUMNO
# ================================================================== #

class AlumnoBase(BaseModel):
    codigo: str
    nombres: str
    apellidos: str
    grado: str
    seccion: str
    turno: str

class AlumnoCreate(AlumnoBase):
    pass

class AlumnoUpdate(BaseModel):
    nombres:    Optional[str] = None
    apellidos:  Optional[str] = None
    grado:      Optional[str] = None
    seccion:    Optional[str] = None
    turno:      Optional[str] = None
    activo:     Optional[bool] = None

class AlumnoResponse(AlumnoBase):
    id:               int
    encoding_valido:  bool
    activo:           bool
    foto_path:        Optional[str] = None
    fecha_registro:   datetime

    class Config:
        from_attributes = True  # Permite crear desde objetos ORM


# ================================================================== #
# CONTACTO TUTOR
# ================================================================== #

class ContactoBase(BaseModel):
    nombre_tutor:       str
    parentesco:         Optional[str] = None
    telefono:           Optional[str] = None
    whatsapp:           Optional[str] = None
    email:              Optional[EmailStr] = None
    notificar_entrada:  bool = True
    notificar_salida:   bool = True
    notificar_tardanza: bool = True
    notificar_ausencia: bool = True

class ContactoCreate(ContactoBase):
    alumno_id: int

class ContactoResponse(ContactoBase):
    id:        int
    alumno_id: int

    class Config:
        from_attributes = True


# ================================================================== #
# ASISTENCIA
# ================================================================== #

class AsistenciaBase(BaseModel):
    alumno_id:   int
    tipo_evento: TipoEvento

class AsistenciaCreate(AsistenciaBase):
    """
    Payload que envía el cliente (PC de portería) al detectar un rostro.
    El servidor calcula fecha y valida la regla de 5 minutos.
    """
    confianza:       Optional[float] = None
    modelo_usado:    Optional[ModeloIA] = None
    cliente_id:      Optional[str] = None    # IP del PC cliente
    registrado_por:  str = "facial"

class AsistenciaResponse(AsistenciaBase):
    id:              int
    fecha:           datetime
    estado:          EstadoAsistencia
    confianza:       Optional[float] = None
    modelo_usado:    Optional[ModeloIA] = None
    cliente_id:      Optional[str] = None
    registrado_por:  str
    alumno:          AlumnoResponse             # Datos del alumno embebidos

    class Config:
        from_attributes = True


# ================================================================== #
# RESULTADO DE RECONOCIMIENTO FACIAL (respuesta del endpoint de scan)
# ================================================================== #

class ScanResultado(BaseModel):
    """
    Respuesta del endpoint POST /reconocimiento/scan.
    El cliente la usa para mostrar el resultado en pantalla.
    """
    reconocido:      bool
    alumno:          Optional[AlumnoResponse] = None
    asistencia:      Optional[AsistenciaResponse] = None
    requiere_popup:  bool = False               # True si aplica regla <5 min
    popup_mensaje:   Optional[str] = None       # Texto para mostrar al portero
    mensaje:         str                        # Mensaje de estado legible


# ================================================================== #
# USUARIO DEL SISTEMA
# ================================================================== #

class UsuarioCreate(BaseModel):
    username:       str
    password:       str                        # Se hashea antes de guardar
    nombre_display: str
    rol:            RolUsuario
    grado_asignado: Optional[str] = None       # Solo para tutores

    @field_validator("password")
    @classmethod
    def password_minima_longitud(cls, v):
        if len(v) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")
        return v

class UsuarioResponse(BaseModel):
    id:             int
    username:       str
    nombre_display: str
    rol:            RolUsuario
    grado_asignado: Optional[str] = None
    activo:         bool
    ultimo_login:   Optional[datetime] = None

    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    usuario:      UsuarioResponse


# ================================================================== #
# CONFIGURACIÓN DEL SISTEMA
# ================================================================== #

class ConfigUpdate(BaseModel):
    """Payload para actualizar un parámetro desde el Panel Admin."""
    valor: str

class ConfigResponse(BaseModel):
    clave:       str
    valor:       str
    descripcion: Optional[str] = None
    fecha_modificacion: Optional[datetime] = None

    class Config:
        from_attributes = True


# ================================================================== #
# JUSTIFICACIÓN
# ================================================================== #

class JustificacionCreate(BaseModel):
    alumno_id:      int
    fecha_ausencia: datetime
    motivo:         str

class JustificacionResponse(JustificacionCreate):
    id:               int
    fecha_registro:   datetime
    documento_path:   Optional[str] = None

    class Config:
        from_attributes = True


# ================================================================== #
# REPORTE DE ASISTENCIA DIARIA
# ================================================================== #

class ReporteDiario(BaseModel):
    """Resumen del día para el Panel Admin."""
    fecha:              datetime
    total_alumnos:      int
    presentes:          int
    ausentes:           int
    tardanzas:          int
    justificados:       int
    porcentaje_asistencia: float
