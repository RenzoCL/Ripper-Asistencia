from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm  # <--- NUEVO IMPORT
from sqlalchemy.orm import Session

from server.db.database import get_db
from server.db import models
from server.schemas.schemas import TokenResponse, UsuarioResponse
from server.core.security import verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["Autenticación"])

@router.post("/login", response_model=TokenResponse, summary="Iniciar sesión")
def login(
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()  # <--- CAMBIO AQUÍ
):
    """
    Autentica a un usuario del sistema y retorna un token JWT.
    Compatible con el botón 'Authorize' de Swagger.
    """
    # Buscar usuario activo en la DB usando form_data.username
    user = db.query(models.UsuarioSistema).filter(
        models.UsuarioSistema.username == form_data.username,
        models.UsuarioSistema.activo == True
    ).first()

    # Verificar existencia y contraseña
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
        )

    # Actualizar último login
    user.ultimo_login = datetime.utcnow()
    db.commit()

    # Crear token con datos embebidos
    token = create_access_token(data={
        "sub": user.username,
        "rol": user.rol.value,
        "id":  user.id,
    })

    # Retornar la respuesta esperada
    return TokenResponse(
        access_token=token,
        token_type="bearer", # Asegúrate de que TokenResponse tenga este campo o agrégalo
        usuario=UsuarioResponse.model_validate(user),
    )

@router.get("/me", response_model=UsuarioResponse, summary="Datos del usuario actual")
def get_me(current_user: models.UsuarioSistema = Depends(get_current_user)):
    return UsuarioResponse.model_validate(current_user)