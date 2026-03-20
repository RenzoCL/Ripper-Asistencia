"""
server/db/enums.py
==================
Enumeraciones separadas para evitar importaciones circulares.
"""

import enum


class TipoEvento(str, enum.Enum):
    ENTRADA = "ENTRADA"
    SALIDA  = "SALIDA"

class EstadoAsistencia(str, enum.Enum):
    PRESENTE     = "PRESENTE"
    AUSENTE      = "AUSENTE"
    TARDANZA     = "TARDANZA"
    JUSTIFICADO  = "JUSTIFICADO"

class RolUsuario(str, enum.Enum):
    ADMIN   = "ADMIN"
    TUTOR   = "TUTOR"
    PORTERO = "PORTERO"

class ModeloIA(str, enum.Enum):
    LBPH = "LBPH"
    HOG  = "HOG"
    CNN  = "CNN"

class CanalNotificacion(str, enum.Enum):
    TELEGRAM  = "TELEGRAM"
    WHATSAPP  = "WHATSAPP"
    INTERNO   = "INTERNO"