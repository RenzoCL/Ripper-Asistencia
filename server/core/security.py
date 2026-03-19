"""
server/core/security.py
=======================
Módulo de seguridad: hashing de contraseñas y tokens JWT.

Por qué JWT (JSON Web Tokens):
  - El cliente (PC de portería) se autentica UNA vez y recibe un token.
  - Cada request posterior incluye el token en el header HTTP.
  - El servidor verifica el token sin consultar la DB en cada llamada.
  - Stateless: perfecto para una red local con múltiples clientes.

Por qué bcrypt:
  - Es el estándar de la industria para hashear contraseñas.
  - Tiene un factor de costo configurable que lo hace resistente a
    ataques de fuerza bruta incluso si la DB es robada.
  - NUNCA usar MD5 o SHA para contraseñas.
"""

from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from server.core.config import settings
from server.db.database import get_db
from server.db import models

# ------------------------------------------------------------------ #
# Configuración de hashing
# ------------------------------------------------------------------ #
# schemes=["bcrypt"]: Usar bcrypt como algoritmo de hash
# deprecated="auto": Actualizar hashes viejos automáticamente
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Esquema OAuth2: el cliente envía el token en el header Authorization: Bearer <token>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ALGORITHM = "HS256"


# ------------------------------------------------------------------ #
# Funciones de contraseña
# ------------------------------------------------------------------ #

def hash_password(password: str) -> str:
    """Hashea una contraseña en texto plano. Usar al crear/actualizar usuario."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si una contraseña plana coincide con su hash. Usar en login."""
    return pwd_context.verify(plain_password, hashed_password)


# ------------------------------------------------------------------ #
# Funciones de JWT
# ------------------------------------------------------------------ #

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea un token JWT firmado.

    Args:
        data: Diccionario con el payload (usualmente {"sub": username, "rol": rol}).
        expires_delta: Tiempo de vida del token. Por defecto usa ACCESS_TOKEN_EXPIRE_MINUTES.

    Returns:
        Token JWT como string.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decodifica y valida un token JWT.
    Lanza HTTPException si el token es inválido o expirado.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception


# ------------------------------------------------------------------ #
# Dependencias de FastAPI para proteger rutas
# ------------------------------------------------------------------ #

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> models.UsuarioSistema:
    """
    Dependency que extrae el usuario autenticado del token JWT.
    Inyectar en cualquier endpoint que requiera autenticación.

    Uso:
        @router.get("/protegido")
        def endpoint(user = Depends(get_current_user)):
            ...
    """
    payload = decode_token(token)
    username = payload.get("sub")

    user = db.query(models.UsuarioSistema).filter(
        models.UsuarioSistema.username == username,
        models.UsuarioSistema.activo == True
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado o inactivo")
    return user


def require_rol(*roles: models.RolUsuario):
    """
    Factory de dependencias para proteger rutas según el rol del usuario.
    
    Uso:
        @router.delete("/alumno/{id}")
        def eliminar(user = Depends(require_rol(RolUsuario.ADMIN))):
            ...
    """
    def _check_rol(current_user: models.UsuarioSistema = Depends(get_current_user)):
        if current_user.rol not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acceso denegado. Se requiere rol: {[r.value for r in roles]}"
            )
        return current_user
    return _check_rol
