"""
server/schemas/schemas.py
=========================
Esquemas Pydantic para validación de datos en la API.
FIXES aplicados:
  - ScanResultado.mensaje ahora es Optional (fix crash cuando no hay alumno)
  - AsistenciaResponse: alumno es Optional (puede ser None si FK falla)
  - Añadido RefreshTokenResponse para JWT refresh
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
        from_attributes = True


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
    confianza:       Optional[float] = None
    modelo_usado:    Optional[ModeloIA] = None
    cliente_id:      Optional[str] = None
    registrado_por:  str = "facial"

class AsistenciaResponse(AsistenciaBase):
    id:              int
    fecha:           datetime
    estado:          EstadoAsistencia
    confianza:       Optional[float] = None
    modelo_usado:    Optional[ModeloIA] = None
    cliente_id:      Optional[str] = None
    registrado_por:  str
    # FIX: alumno es Optional — puede ser None si la FK apunta a un alumno borrado
    alumno:          Optional[AlumnoResponse] = None

    class Config:
        from_attributes = True


# ================================================================== #
# RESULTADO DE RECONOCIMIENTO FACIAL
# FIX CRÍTICO: mensaje ahora es Optional con default None
# Antes era `str` requerido — AttendanceService no siempre lo seteaba
# ================================================================== #

class ScanResultado(BaseModel):
    reconocido:      bool
    alumno:          Optional[AlumnoResponse] = None
    asistencia:      Optional[AsistenciaResponse] = None
    requiere_popup:  bool = False
    popup_mensaje:   Optional[str] = None
    # FIX: era `str` (requerido), ahora Optional con default descriptivo
    mensaje:         Optional[str] = None

    def get_mensaje(self) -> str:
        """Retorna el mensaje o uno genérico si es None."""
        if self.mensaje:
            return self.mensaje
        if not self.reconocido:
            return "No se detectó ningún rostro conocido"
        if self.requiere_popup:
            return "Re-escaneo detectado"
        if self.asistencia:
            tipo = self.asistencia.tipo_evento.value if self.asistencia.tipo_evento else "evento"
            return f"✅ {tipo} registrada"
        return "Scan procesado"


# ================================================================== #
# USUARIO DEL SISTEMA
# ================================================================== #

class UsuarioCreate(BaseModel):
    username:       str
    password:       str
    nombre_display: str
    rol:            RolUsuario
    grado_asignado: Optional[str] = None

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
    access_token:  str
    token_type:    str = "bearer"
    usuario:       UsuarioResponse
    # NUEVO: expira_en segundos desde ahora
    expira_en:     int = 28800  # 8 horas default


# ================================================================== #
# CONFIGURACIÓN DEL SISTEMA
# ================================================================== #

class ConfigUpdate(BaseModel):
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
    fecha:              datetime
    total_alumnos:      int
    presentes:          int
    ausentes:           int
    tardanzas:          int
    justificados:       int
    porcentaje_asistencia: float