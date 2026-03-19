"""
server/api/routes/alumnos.py
============================
CRUD de alumnos + endpoints de fotos y entrenamiento facial.
"""

import io
import os
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from server.db.database import get_db
from server.db import models
from server.db.models import RolUsuario
from server.schemas.schemas import AlumnoCreate, AlumnoUpdate, AlumnoResponse
from server.core.security import get_current_user, require_rol
from server.core.config import settings

router = APIRouter(prefix="/alumnos", tags=["Alumnos"])


@router.get("/", response_model=List[AlumnoResponse], summary="Listar alumnos")
def listar_alumnos(
    grado:   Optional[str] = Query(None, description="Filtrar por grado (ej: '3A')"),
    activo:  bool = Query(True, description="Solo alumnos activos"),
    buscar:  Optional[str] = Query(None, description="Buscar por nombre o código"),
    skip:    int = Query(0, ge=0),
    limit:   int = Query(50, le=200),
    db:      Session = Depends(get_db),
    _user:   models.UsuarioSistema = Depends(get_current_user),
):
    """Lista alumnos con filtros opcionales. Disponible para todos los roles."""
    query = db.query(models.Alumno).filter(models.Alumno.activo == activo)

    if grado:
        query = query.filter(models.Alumno.grado == grado)

    if buscar:
        like_pattern = f"%{buscar}%"
        query = query.filter(
            models.Alumno.nombres.ilike(like_pattern) |
            models.Alumno.apellidos.ilike(like_pattern) |
            models.Alumno.codigo.ilike(like_pattern)
        )

    return query.order_by(models.Alumno.apellidos).offset(skip).limit(limit).all()


@router.get("/{alumno_id}", response_model=AlumnoResponse, summary="Obtener alumno por ID")
def obtener_alumno(
    alumno_id: int,
    db: Session = Depends(get_db),
    _user: models.UsuarioSistema = Depends(get_current_user),
):
    alumno = db.get(models.Alumno, alumno_id)
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    return alumno


@router.post("/", response_model=AlumnoResponse, status_code=201, summary="Crear alumno")
def crear_alumno(
    data: AlumnoCreate,
    db: Session = Depends(get_db),
    _user: models.UsuarioSistema = Depends(require_rol(RolUsuario.ADMIN)),
):
    """Solo Admin puede crear alumnos."""
    # Verificar código único
    if db.query(models.Alumno).filter(models.Alumno.codigo == data.codigo).first():
        raise HTTPException(status_code=400, detail=f"El código '{data.codigo}' ya existe")

    alumno = models.Alumno(**data.model_dump())
    db.add(alumno)
    db.commit()
    db.refresh(alumno)
    return alumno


@router.patch("/{alumno_id}", response_model=AlumnoResponse, summary="Actualizar alumno")
def actualizar_alumno(
    alumno_id: int,
    data: AlumnoUpdate,
    db: Session = Depends(get_db),
    _user: models.UsuarioSistema = Depends(require_rol(RolUsuario.ADMIN)),
):
    """Solo Admin puede modificar datos de alumnos."""
    alumno = db.get(models.Alumno, alumno_id)
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(alumno, field, value)

    db.commit()
    db.refresh(alumno)
    return alumno


@router.post("/{alumno_id}/fotos", summary="Subir fotos para entrenamiento")
async def subir_fotos(
    alumno_id: int,
    fotos: List[UploadFile] = File(..., description="Imágenes JPG del alumno (mínimo 3)"),
    db: Session = Depends(get_db),
    _user: models.UsuarioSistema = Depends(require_rol(RolUsuario.ADMIN)),
):
    """
    Sube fotos del alumno al servidor para ser usadas en el entrenamiento.
    Las fotos se guardan en /server/data/photos/{alumno_id}/.
    Formatos aceptados: .jpg, .jpeg, .png
    """
    alumno = db.get(models.Alumno, alumno_id)
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    fotos_dir = Path(settings.PHOTOS_DIR) / str(alumno_id)
    fotos_dir.mkdir(parents=True, exist_ok=True)

    subidas = []
    for foto in fotos:
        ext = Path(foto.filename).suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png"]:
            continue

        destino = fotos_dir / foto.filename
        with open(destino, "wb") as f:
            shutil.copyfileobj(foto.file, f)
        subidas.append(foto.filename)

    if not subidas:
        raise HTTPException(status_code=400, detail="No se subieron fotos válidas (JPG/PNG)")

    # Marcar encoding como no válido (requiere reentrenamiento)
    alumno.encoding_valido = False
    db.commit()

    return {
        "mensaje": f"{len(subidas)} foto(s) subidas exitosamente",
        "fotos": subidas,
        "nota": "Ejecutar POST /reconocimiento/entrenar/{alumno_id} para actualizar el modelo",
    }


@router.post("/fotos-zip", summary="Subir fotos de TODOS los alumnos en un ZIP")
async def subir_fotos_zip(
    archivo_zip: UploadFile = File(..., description="ZIP con carpetas llamadas por código de alumno"),
    entrenar:    bool = False,
    db:          Session = Depends(get_db),
    _user        = Depends(require_rol(RolUsuario.ADMIN)),
):
    """
    Importación masiva de fotos para múltiples alumnos desde un ZIP.

    Estructura esperada del ZIP:
        fotos_alumnos.zip
        ├── 2024001/          ← código del alumno
        │   ├── foto1.jpg
        │   ├── foto2.jpg
        │   └── foto3.jpg
        ├── 2024002/
        │   ├── frente.jpg
        │   └── perfil.jpg
        └── ...

    El sistema busca cada carpeta por el código del alumno en la DB.
    Si la carpeta no coincide con ningún alumno conocido, se omite.

    Parámetro `entrenar=true` lanza el entrenamiento HOG inmediatamente
    después de extraer las fotos (puede tardar varios minutos para 900 alumnos).
    """
    import zipfile
    import tempfile

    if not archivo_zip.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un .zip")

    # Leer el ZIP en memoria
    zip_bytes = await archivo_zip.read()

    resultados = {"procesados": 0, "omitidos": 0, "errores": [], "alumnos": []}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                zf.extractall(tmp_path)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="El archivo ZIP está corrupto o no es válido")

        # Iterar sobre carpetas del ZIP (cada carpeta = código de alumno)
        for carpeta in sorted(tmp_path.iterdir()):
            if not carpeta.is_dir():
                continue

            codigo = carpeta.name.strip()

            # Buscar alumno por código
            alumno = db.query(models.Alumno).filter(
                models.Alumno.codigo == codigo,
                models.Alumno.activo == True,
            ).first()

            if not alumno:
                resultados["omitidos"] += 1
                resultados["errores"].append(f"Código '{codigo}': alumno no encontrado o inactivo")
                continue

            # Copiar fotos al directorio definitivo
            fotos_dest = Path(settings.PHOTOS_DIR) / str(alumno.id)
            fotos_dest.mkdir(parents=True, exist_ok=True)

            fotos_copiadas = 0
            for foto in carpeta.iterdir():
                if foto.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                    shutil.copy2(foto, fotos_dest / foto.name)
                    fotos_copiadas += 1

            if fotos_copiadas == 0:
                resultados["errores"].append(f"'{codigo}': no contiene fotos JPG/PNG")
                continue

            alumno.encoding_valido = False
            resultados["procesados"] += 1
            resultados["alumnos"].append({
                "codigo": codigo,
                "nombre": alumno.nombre_completo(),
                "fotos": fotos_copiadas,
            })

        db.commit()

    # Entrenar automáticamente si se solicitó
    if entrenar and resultados["procesados"] > 0:
        from server.api.routes.reconocimiento import get_active_recognizer
        recognizer = get_active_recognizer(db)

        entrenados = 0
        for info in resultados["alumnos"]:
            alumno = db.query(models.Alumno).filter(
                models.Alumno.codigo == info["codigo"]
            ).first()
            if alumno:
                fotos_dir = Path(settings.PHOTOS_DIR) / str(alumno.id)
                enc_path  = Path(settings.ENCODINGS_DIR) / f"alumno_{alumno.id}.pkl"
                ok = recognizer.entrenar(alumno.id, str(fotos_dir), str(enc_path))
                if ok:
                    alumno.encoding_path   = str(enc_path)
                    alumno.encoding_valido = True
                    entrenados += 1
        db.commit()
        resultados["entrenados"] = entrenados

    return {
        "mensaje":      f"{resultados['procesados']} alumnos procesados exitosamente",
        "procesados":   resultados["procesados"],
        "omitidos":     resultados["omitidos"],
        "errores":      resultados["errores"][:20],  # Máximo 20 errores en respuesta
        "alumnos":      resultados["alumnos"][:50],  # Máximo 50 en respuesta
    }
