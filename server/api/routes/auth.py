"""
server/api/routes/auth.py
=========================
FIXES aplicados:
  1. Login acepta TANTO JSON (cliente Python) COMO form-data (Swagger/admin.html)
     — antes solo aceptaba form-data (OAuth2PasswordRequestForm), rompiendo api_client.py
  2. Nuevo endpoint GET /api/auth/refresh — renueva el token sin re-login
  3. Endpoint POST /api/auth/logout — para invalidación futura (preparado para Redis)
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel

from server.db.database import get_db
from server.db import models
from server.schemas.schemas import TokenResponse, UsuarioResponse, LoginRequest
from server.core.security import (
    verify_password, create_access_token, get_current_user, decode_token
)
from server.core.config import settings

router = APIRouter(prefix="/auth", tags=["Autenticación"])


def _authenticate_user(db: Session, username: str, password: str) -> models.UsuarioSistema:
    """
    Lógica compartida de autenticación.
    Extrae la validación para que ambos endpoints la usen.
    """
    user = db.query(models.UsuarioSistema).filter(
        models.UsuarioSistema.username == username,
        models.UsuarioSistema.activo == True
    ).first()

    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ================================================================== #
# POST /api/auth/login
# FIX CRÍTICO: acepta form-data (Swagger/admin.html) Y JSON (api_client.py)
# ================================================================== #

@router.post("/login", response_model=TokenResponse, summary="Iniciar sesión")
async def login(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Autenticación dual: acepta tanto form-data (OAuth2) como JSON body.

    - Swagger UI y admin.html envían: application/x-www-form-urlencoded
    - api_client.py (Python) envía: application/json

    Ambos formatos son soportados transparentemente.
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        # Modo JSON — usado por api_client.py de Python
        try:
            body = await request.json()
            username = body.get("username", "")
            password = body.get("password", "")
        except Exception:
            raise HTTPException(status_code=400, detail="JSON inválido")
    else:
        # Modo form-data — usado por Swagger, admin.html, OAuth2 estándar
        form = await request.form()
        username = form.get("username", "")
        password = form.get("password", "")

    if not username or not password:
        raise HTTPException(
            status_code=400,
            detail="Se requieren username y password"
        )

    user = _authenticate_user(db, username, password)

    # Actualizar último login
    user.ultimo_login = datetime.utcnow()
    db.commit()

    # Crear token con datos embebidos
    token = create_access_token(data={
        "sub": user.username,
        "rol": user.rol.value,
        "id":  user.id,
    })

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        usuario=UsuarioResponse.model_validate(user),
        expira_en=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ================================================================== #
# GET /api/auth/refresh
# NUEVO: renueva el token sin re-login (evita que portero quede bloqueado)
# ================================================================== #

@router.get("/refresh", response_model=TokenResponse, summary="Renovar token JWT")
def refresh_token(
    current_user: models.UsuarioSistema = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Renueva el token JWT del usuario autenticado.
    El cliente debe llamar esto cuando el token tiene < 30 min de vida.

    En api_client.py usar:
        if tiempo_restante < 1800:  # 30 minutos
            self.api.refresh_token()
    """
    new_token = create_access_token(data={
        "sub": current_user.username,
        "rol": current_user.rol.value,
        "id":  current_user.id,
    })

    return TokenResponse(
        access_token=new_token,
        token_type="bearer",
        usuario=UsuarioResponse.model_validate(current_user),
        expira_en=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ================================================================== #
# GET /api/auth/me
# ================================================================== #

@router.get("/me", response_model=UsuarioResponse, summary="Datos del usuario actual")
def get_me(current_user: models.UsuarioSistema = Depends(get_current_user)):
    return UsuarioResponse.model_validate(current_user)


# ================================================================== #
# POST /api/auth/logout
# Preparado para invalidación con Redis en v2
# ================================================================== #

@router.post("/logout", summary="Cerrar sesión")
def logout(current_user: models.UsuarioSistema = Depends(get_current_user)):
    """
    Endpoint de logout semántico.
    Por ahora solo retorna confirmación — el cliente debe borrar el token local.
    En v2 con Redis: añadir token a blacklist.
    """
    return {
        "mensaje": f"Sesión cerrada para {current_user.username}",
        "usuario": current_user.username,
    }