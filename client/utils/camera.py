"""
client/utils/camera.py
=======================
Módulo de captura de video con OpenCV.

Diseño:
  - La cámara corre en un HILO SEPARADO para no bloquear la UI de Tkinter.
  - El hilo de cámara actualiza un buffer compartido (frame_actual).
  - La UI lee ese buffer cada N ms con `after()` de Tkinter.
  - El hilo de reconocimiento lee el mismo buffer cada INTERVALO_SCAN ms
    y lo envía al servidor solo si el umbral de confianza está activo.

Parámetros optimizados para hardware limitado:
  - Resolución: 640x480 (suficiente para reconocimiento facial)
  - FPS captura: 30 (solo para mostrar en pantalla)
  - FPS de scan: 1 por segundo (evita saturar el servidor LAN)
"""

import cv2
import threading
import time
import logging
from typing import Optional, Callable
import numpy as np

logger = logging.getLogger(__name__)

# Resolución de captura (más baja = más rápido en PCs antiguas)
CAPTURE_WIDTH  = 640
CAPTURE_HEIGHT = 480

# Calidad JPEG para enviar al servidor (menor = menos bytes en LAN)
JPEG_QUALITY = 80

# Intervalo mínimo entre scans enviados al servidor (segundos)
INTERVALO_SCAN_SEGUNDOS = 1.5


class CameraCapture:
    """
    Gestor del ciclo de vida de la webcam.
    Thread-safe: usa locks para el buffer del frame.
    """

    def __init__(self, camara_index: int = 0):
        """
        Args:
            camara_index: Índice de la cámara (0 = primera webcam del sistema).
                          Si hay varias cámaras, usar 1, 2, etc.
        """
        self.camara_index = camara_index
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_actual: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._corriendo = False
        self._hilo: Optional[threading.Thread] = None
        self._ultimo_scan_tiempo = 0.0

    # ------------------------------------------------------------------ #
    # Control de la cámara
    # ------------------------------------------------------------------ #

    def iniciar(self) -> bool:
        """
        Abre la cámara e inicia el hilo de captura.
        Retorna True si la cámara se abrió exitosamente.
        """
        self._cap = cv2.VideoCapture(self.camara_index)

        if not self._cap.isOpened():
            logger.error("No se pudo abrir la cámara (índice %d)", self.camara_index)
            return False

        # Configurar resolución
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAPTURE_WIDTH)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
        self._cap.set(cv2.CAP_PROP_FPS, 30)

        self._corriendo = True
        self._hilo = threading.Thread(
            target=self._loop_captura,
            name="CameraThread",
            daemon=True,  # El hilo muere cuando la app cierra
        )
        self._hilo.start()
        logger.info("Cámara %d iniciada (%dx%d)", self.camara_index, CAPTURE_WIDTH, CAPTURE_HEIGHT)
        return True

    def detener(self):
        """Detiene el hilo de captura y libera la cámara."""
        self._corriendo = False
        if self._hilo:
            self._hilo.join(timeout=2)
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("Cámara detenida")

    # ------------------------------------------------------------------ #
    # Hilo de captura (corre en background)
    # ------------------------------------------------------------------ #

    def _loop_captura(self):
        """
        Loop principal de captura. Actualiza _frame_actual continuamente.
        Corre en un hilo separado; no hacer operaciones de UI aquí.
        """
        while self._corriendo:
            if self._cap and self._cap.isOpened():
                ret, frame = self._cap.read()
                if ret:
                    # Voltear horizontalmente (efecto espejo, más natural para el usuario)
                    frame = cv2.flip(frame, 1)
                    with self._lock:
                        self._frame_actual = frame
            else:
                time.sleep(0.1)  # Esperar si la cámara está ocupada

    # ------------------------------------------------------------------ #
    # Acceso al frame actual
    # ------------------------------------------------------------------ #

    def obtener_frame(self) -> Optional[np.ndarray]:
        """
        Retorna una COPIA del frame actual (thread-safe).
        Retorna None si aún no hay frames disponibles.
        """
        with self._lock:
            if self._frame_actual is None:
                return None
            return self._frame_actual.copy()

    def obtener_frame_jpeg(self, calidad: int = JPEG_QUALITY) -> Optional[bytes]:
        """
        Retorna el frame actual como bytes JPEG comprimido.
        Listo para enviar al servidor via HTTP.

        Args:
            calidad: 0-100. Menor = menos bytes pero peor imagen.
        """
        frame = self.obtener_frame()
        if frame is None:
            return None

        encode_params = [cv2.IMWRITE_JPEG_QUALITY, calidad]
        ret, buffer = cv2.imencode(".jpg", frame, encode_params)

        if not ret:
            return None
        return buffer.tobytes()

    def debe_escanear(self) -> bool:
        """
        Controla la frecuencia de envío al servidor.
        Retorna True si ha pasado suficiente tiempo desde el último scan.
        Evita saturar el servidor con requests continuos.
        """
        ahora = time.time()
        if ahora - self._ultimo_scan_tiempo >= INTERVALO_SCAN_SEGUNDOS:
            self._ultimo_scan_tiempo = ahora
            return True
        return False

    @property
    def activa(self) -> bool:
        return self._corriendo and self._cap is not None


class FaceDetectorLocal:
    """
    Detector de rostros local (SOLO para mostrar el rectángulo en pantalla).
    No hace reconocimiento: eso lo hace el servidor.
    Usa Haar Cascade (ultra ligero) para feedback visual inmediato.
    """

    def __init__(self):
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.detector = cv2.CascadeClassifier(cascade_path)

    def detectar_y_dibujar(
        self,
        frame: np.ndarray,
        color: tuple = (0, 255, 0),  # Verde por defecto
        nombre_overlay: Optional[str] = None,
    ) -> np.ndarray:
        """
        Detecta rostros y dibuja rectángulos en el frame.
        Si se provee nombre_overlay, lo muestra sobre el rectángulo.

        Retorna el frame modificado (no modifica el original).
        """
        frame_display = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        rostros = self.detector.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(60, 60),
        )

        for (x, y, w, h) in rostros:
            # Rectángulo principal
            cv2.rectangle(frame_display, (x, y), (x+w, y+h), color, 2)

            # Nombre del alumno sobre el rectángulo (si ya fue reconocido)
            if nombre_overlay:
                # Fondo semitransparente para el texto
                overlay = frame_display.copy()
                cv2.rectangle(overlay, (x, y-30), (x+w, y), color, -1)
                cv2.addWeighted(overlay, 0.6, frame_display, 0.4, 0, frame_display)

                cv2.putText(
                    frame_display,
                    nombre_overlay[:25],  # Truncar nombres muy largos
                    (x+5, y-8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    2,
                )

        return frame_display

    def hay_rostros(self, frame: np.ndarray) -> bool:
        """Retorna True si hay al menos un rostro detectado en el frame."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        rostros = self.detector.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
        return len(rostros) > 0
