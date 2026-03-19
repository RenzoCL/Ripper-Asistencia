"""
scripts/setup/reentrenar_lbph.py
==================================
Reentrenamiento BATCH del modelo LBPH.

Por qué LBPH necesita reentrenamiento batch:
  - A diferencia de HOG/CNN (que guardan embeddings por alumno),
    LBPH necesita ser entrenado con TODOS los alumnos juntos en un
    solo modelo .yml.
  - Por eso, cada vez que se agrega o modifica un alumno, hay que
    reentrenar con todos los alumnos activos.

Cuándo ejecutar:
  - Después de registrar nuevos alumnos con fotos.
  - Al inicio del año escolar con las fotos actualizadas.
  - Nunca durante el horario escolar (tarda unos minutos y bloquea el modelo).

Uso:
    python scripts/setup/reentrenar_lbph.py
    python scripts/setup/reentrenar_lbph.py --solo-grado 3A
"""

import sys
import os
import pickle
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
except ImportError:
    print("❌ OpenCV no instalado. Ejecutar: pip install opencv-python")
    sys.exit(1)

PHOTOS_DIR   = Path(os.getenv("PHOTOS_DIR", "./server/data/photos"))
ENCODINGS_DIR = Path(os.getenv("ENCODINGS_DIR", "./server/data/encodings"))


def cargar_imagenes_alumnos(solo_grado: str = None):
    """
    Carga todas las imágenes de alumnos activos desde el directorio de fotos.
    Retorna listas paralelas de (imágenes en escala de grises, etiquetas int).
    """
    from server.db.database import SessionLocal
    from server.db import models

    db = SessionLocal()

    try:
        query = db.query(models.Alumno).filter(models.Alumno.activo == True)
        if solo_grado:
            query = query.filter(models.Alumno.grado == solo_grado)
        alumnos = query.all()

        # Mapa: label_int → alumno_id (LBPH usa etiquetas numéricas)
        label_map = {}     # {label_int: alumno_id}
        imagenes  = []
        etiquetas = []

        print(f"Procesando {len(alumnos)} alumnos...")

        for idx, alumno in enumerate(alumnos):
            fotos_dir = PHOTOS_DIR / str(alumno.id)
            if not fotos_dir.exists():
                logger.warning("Sin fotos: Alumno %s (%s)", alumno.codigo, alumno.nombre_completo())
                continue

            fotos_cargadas = 0
            for img_path in fotos_dir.glob("*.jpg"):
                img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue

                # Redimensionar a tamaño estándar para LBPH
                img = cv2.resize(img, (200, 200))
                imagenes.append(img)
                etiquetas.append(idx)  # Usar índice como etiqueta
                fotos_cargadas += 1

            if fotos_cargadas > 0:
                label_map[idx] = alumno.id
                print(f"   ✅ {alumno.codigo} — {alumno.nombre_completo()}: {fotos_cargadas} foto(s)")
            else:
                logger.warning("Fotos sin rostros: %s", alumno.nombre_completo())

    finally:
        db.close()

    return imagenes, etiquetas, label_map


def entrenar_y_guardar(imagenes, etiquetas, label_map):
    """
    Entrena el modelo LBPH y guarda el .yml y el mapa de etiquetas.
    """
    if not imagenes:
        print("❌ No hay imágenes para entrenar")
        return False

    print(f"\n🧠 Entrenando LBPH con {len(imagenes)} imágenes de {len(label_map)} alumnos...")

    recognizer = cv2.face.LBPHFaceRecognizer_create(
        radius=1,
        neighbors=8,
        grid_x=8,
        grid_y=8,
    )
    recognizer.train(imagenes, np.array(etiquetas))

    ENCODINGS_DIR.mkdir(parents=True, exist_ok=True)

    model_path  = ENCODINGS_DIR / "lbph_model.yml"
    labels_path = ENCODINGS_DIR / "lbph_labels.pkl"

    recognizer.save(str(model_path))
    with open(labels_path, "wb") as f:
        pickle.dump(label_map, f)

    print(f"✅ Modelo guardado: {model_path} ({model_path.stat().st_size / 1024:.1f} KB)")
    print(f"✅ Labels guardadas: {labels_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Reentrenar modelo LBPH")
    parser.add_argument("--solo-grado", help="Filtrar por grado (ej: '3A')", default=None)
    args = parser.parse_args()

    print("🏫 COLEGIO ASISTENCIA — Reentrenamiento LBPH")
    print("=" * 50)
    print("⚠️  AVISO: Este proceso puede tardar varios minutos.")
    print("   Ejecutar fuera del horario escolar.")
    print()

    imagenes, etiquetas, label_map = cargar_imagenes_alumnos(args.solo_grado)

    if not imagenes:
        print("❌ No se encontraron imágenes. Verificar directorio de fotos.")
        sys.exit(1)

    exito = entrenar_y_guardar(imagenes, etiquetas, label_map)

    if exito:
        print(f"\n🎉 Reentrenamiento completado. {len(label_map)} alumnos en el modelo.")
        print("   Reiniciar el servidor para aplicar el nuevo modelo:")
        print("   (O esperar al próximo scan — el caché se invalida automáticamente)")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
