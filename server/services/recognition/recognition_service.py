"""
server/services/recognition/recognition_service.py
===================================================
Servicio central de reconocimiento facial.

Este módulo implementa el SELECTOR DE MODELOS (Funcionalidad Crítica #1).
Los tres niveles están encapsulados en estrategias intercambiables:

  Nivel 1 – LBPH (Local Binary Pattern Histograms)
    - Librería:    OpenCV puro (cv2)
    - CPU mínima:  Pentium 4 en adelante
    - RAM:         < 100 MB
    - Velocidad:   ~50ms por frame
    - Precisión:   Media (suficiente para iluminación controlada)
    - Ideal para:  PCs con >10 años de antigüedad

  Nivel 2 – HOG (Histogram of Oriented Gradients) [DEFAULT]
    - Librería:    face_recognition (dlib HOG)
    - CPU mínima:  Dual-core moderno
    - RAM:         ~200 MB
    - Velocidad:   ~100-300ms por frame
    - Precisión:   Alta
    - Ideal para:  PCs de oficina estándar

  Nivel 3 – CNN (Convolutional Neural Network)
    - Librería:    face_recognition (dlib CNN) + CUDA opcional
    - CPU/GPU:     GPU NVIDIA recomendada (CUDA)
    - RAM:         ~500 MB + VRAM
    - Velocidad:   ~30ms con GPU / ~1-2s sin GPU
    - Precisión:   Muy alta (mejor para fotos pequeñas o ángulos difíciles)
    - Ideal para:  PC del servidor con GPU dedicada
"""

import os
import pickle
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, List

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ================================================================== #
# CLASE BASE: Interfaz común para todos los modelos
# ================================================================== #

class BaseRecognizer(ABC):
    """
    Interfaz abstracta que todos los modelos deben implementar.
    El resto del sistema solo conoce esta interfaz, no la implementación.
    Esto permite cambiar de modelo sin tocar el código de los endpoints.
    """

    @abstractmethod
    def cargar_encodings(self, encodings_dir: str) -> int:
        """
        Carga los encodings/modelos entrenados desde disco.
        Retorna el número de alumnos cargados.
        """
        pass

    @abstractmethod
    def identificar(self, frame: np.ndarray) -> List[Tuple[int, float]]:
        """
        Procesa un frame de la cámara y retorna lista de (alumno_id, confianza).
        confianza: 0.0 (ninguna certeza) a 1.0 (certeza máxima).
        """
        pass

    @abstractmethod
    def entrenar(self, alumno_id: int, fotos_dir: str, encoding_path: str) -> bool:
        """
        Extrae y guarda el encoding facial de un alumno.
        Retorna True si el entrenamiento fue exitoso.
        """
        pass


# ================================================================== #
# NIVEL 1: Reconocedor LBPH (OpenCV)
# ================================================================== #

class LBPHRecognizer(BaseRecognizer):
    """
    Reconocedor usando LBPH de OpenCV.
    Ideal para hardware muy limitado: no requiere dlib ni GPU.
    """

    def __init__(self):
        # LBPHFaceRecognizer es el reconocedor más ligero de OpenCV
        self.recognizer = cv2.face.LBPHFaceRecognizer_create()
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self.label_to_alumno_id: dict = {}  # int_label → alumno_id real
        self.entrenado = False

    def cargar_encodings(self, encodings_dir: str) -> int:
        """
        Carga el modelo LBPH serializado y el mapa de etiquetas.
        """
        model_path = Path(encodings_dir) / "lbph_model.yml"
        labels_path = Path(encodings_dir) / "lbph_labels.pkl"

        if not model_path.exists() or not labels_path.exists():
            logger.warning("No se encontró modelo LBPH entrenado en %s", encodings_dir)
            return 0

        self.recognizer.read(str(model_path))
        with open(labels_path, "rb") as f:
            self.label_to_alumno_id = pickle.load(f)

        self.entrenado = True
        n = len(self.label_to_alumno_id)
        logger.info("LBPH: %d alumnos cargados", n)
        return n

    def identificar(self, frame: np.ndarray) -> List[Tuple[int, float]]:
        if not self.entrenado:
            return []

        # Convertir a escala de grises (LBPH trabaja en gris)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)

        resultados = []
        for (x, y, w, h) in faces:
            rostro = gray[y:y+h, x:x+w]
            rostro = cv2.resize(rostro, (200, 200))

            # predict retorna (label, confidence); en LBPH, menor confidence = mejor
            label, confidence = self.recognizer.predict(rostro)

            # Convertir: LBPH confidence 0–100 → score 0.0–1.0 (invertido)
            score = max(0.0, 1.0 - (confidence / 100.0))

            if score > 0.4 and label in self.label_to_alumno_id:
                alumno_id = self.label_to_alumno_id[label]
                resultados.append((alumno_id, round(score, 3)))

        return resultados

    def entrenar(self, alumno_id: int, fotos_dir: str, encoding_path: str) -> bool:
        """
        Nota: El entrenamiento LBPH es INCREMENTAL y requiere reentrenar
        con TODOS los alumnos. Este método debe llamarse via el script
        scripts/setup/reentrenar_lbph.py que hace el batch completo.
        """
        logger.info("LBPH: Entrenamiento iniciado para alumno %d", alumno_id)
        # Implementación del batch completo está en scripts/setup/
        return True


# ================================================================== #
# NIVEL 2: Reconocedor HOG (face_recognition / dlib)
# ================================================================== #

class HOGRecognizer(BaseRecognizer):
    """
    Reconocedor usando HOG de dlib via la librería face_recognition.
    Ofrece el mejor balance entre precisión y uso de recursos.
    Este es el modelo DEFAULT del sistema.
    """

    def __init__(self, tolerance: float = 0.6):
        # tolerance: distancia máxima para considerar match (menor = más estricto)
        self.tolerance = tolerance
        self.known_encodings: List[np.ndarray] = []  # Lista de arrays de embeddings
        self.known_ids: List[int] = []               # Lista de alumno_ids correspondientes

    def cargar_encodings(self, encodings_dir: str) -> int:
        """
        Carga todos los archivos .pkl de la carpeta de encodings.
        Cada .pkl contiene el embedding facial de un alumno.
        """
        try:
            import face_recognition
        except ImportError:
            logger.error("face_recognition no instalado. Ejecutar: pip install face-recognition")
            return 0

        self.known_encodings = []
        self.known_ids = []

        enc_dir = Path(encodings_dir)
        if not enc_dir.exists():
            logger.warning("Directorio de encodings no existe: %s", encodings_dir)
            return 0

        for pkl_file in enc_dir.glob("alumno_*.pkl"):
            try:
                with open(pkl_file, "rb") as f:
                    data = pickle.load(f)
                # Formato esperado: {"alumno_id": int, "encodings": List[np.ndarray]}
                for enc in data["encodings"]:
                    self.known_encodings.append(enc)
                    self.known_ids.append(data["alumno_id"])
            except Exception as e:
                logger.error("Error cargando %s: %s", pkl_file.name, e)

        n_alumnos = len(set(self.known_ids))
        logger.info("HOG: %d encodings de %d alumnos cargados", len(self.known_ids), n_alumnos)
        return n_alumnos

    def identificar(self, frame: np.ndarray) -> List[Tuple[int, float]]:
        if not self.known_encodings:
            return []

        try:
            import face_recognition
        except ImportError:
            return []

        # HOG usa RGB; OpenCV captura en BGR → convertir
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Detectar ubicaciones de rostros con HOG (model="hog")
        face_locations = face_recognition.face_locations(rgb_frame, model="hog")

        if not face_locations:
            return []

        # Calcular encodings de los rostros detectados en el frame
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        resultados = []
        for face_enc in face_encodings:
            # Calcular distancias con todos los encodings conocidos
            distances = face_recognition.face_distance(self.known_encodings, face_enc)

            if len(distances) == 0:
                continue

            best_idx = int(np.argmin(distances))
            best_distance = distances[best_idx]

            if best_distance <= self.tolerance:
                alumno_id = self.known_ids[best_idx]
                # Convertir distancia (0–1) a score de confianza (1–0)
                confianza = round(1.0 - best_distance, 3)
                resultados.append((alumno_id, confianza))

        return resultados

    def entrenar(self, alumno_id: int, fotos_dir: str, encoding_path: str) -> bool:
        """
        Genera el archivo .pkl con los embeddings faciales de un alumno
        a partir de todas sus fotos en fotos_dir.
        """
        try:
            import face_recognition
        except ImportError:
            logger.error("face_recognition no instalado")
            return False

        encodings = []
        fotos_path = Path(fotos_dir)

        for img_file in fotos_path.glob("*.jpg"):
            image = face_recognition.load_image_file(str(img_file))
            encs = face_recognition.face_encodings(image)
            if encs:
                encodings.append(encs[0])

        if not encodings:
            logger.warning("No se encontraron rostros en las fotos del alumno %d", alumno_id)
            return False

        # Guardar encodings en .pkl
        os.makedirs(Path(encoding_path).parent, exist_ok=True)
        with open(encoding_path, "wb") as f:
            pickle.dump({"alumno_id": alumno_id, "encodings": encodings}, f)

        logger.info("HOG: Alumno %d entrenado con %d encodings", alumno_id, len(encodings))
        return True


# ================================================================== #
# NIVEL 3: Reconocedor CNN (dlib deep learning)
# ================================================================== #

class CNNRecognizer(HOGRecognizer):
    """
    Reconocedor CNN de alta precisión.
    Hereda de HOGRecognizer (misma estructura de encodings).
    La única diferencia es el modelo de detección: model="cnn" en lugar de "hog".
    """

    def identificar(self, frame: np.ndarray) -> List[Tuple[int, float]]:
        if not self.known_encodings:
            return []

        try:
            import face_recognition
        except ImportError:
            return []

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # CNN: más preciso, más lento. Usa GPU si CUDA está disponible.
        face_locations = face_recognition.face_locations(rgb_frame, model="cnn")

        if not face_locations:
            return []

        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        resultados = []
        for face_enc in face_encodings:
            distances = face_recognition.face_distance(self.known_encodings, face_enc)
            if len(distances) == 0:
                continue
            best_idx = int(np.argmin(distances))
            best_distance = distances[best_idx]
            if best_distance <= self.tolerance:
                alumno_id = self.known_ids[best_idx]
                confianza = round(1.0 - best_distance, 3)
                resultados.append((alumno_id, confianza))

        return resultados


# ================================================================== #
# FACTORY: Obtener el reconocedor correcto según config
# ================================================================== #

def get_recognizer(modelo: str, tolerance: float = 0.6) -> BaseRecognizer:
    """
    Factory function que retorna el reconocedor adecuado.
    El Panel Admin llama a esta función al cambiar el modelo activo.

    Args:
        modelo:    "LBPH", "HOG" o "CNN"
        tolerance: Solo aplica para HOG y CNN

    Returns:
        Instancia del reconocedor correspondiente.
    """
    modelo = modelo.upper()
    recognizers = {
        "LBPH": LBPHRecognizer,
        "HOG":  lambda: HOGRecognizer(tolerance=tolerance),
        "CNN":  lambda: CNNRecognizer(tolerance=tolerance),
    }
    if modelo not in recognizers:
        logger.warning("Modelo '%s' desconocido. Usando HOG por defecto.", modelo)
        modelo = "HOG"

    factory = recognizers[modelo]
    instance = factory() if callable(factory) and modelo != "LBPH" else factory()
    logger.info("Reconocedor activo: %s", modelo)
    return instance
