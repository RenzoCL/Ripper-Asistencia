"""
client/ui/porteria_app_qt.py
=============================
App de portería rediseñada con PyQt6.

Ventajas sobre Tkinter:
  - OpenCV corre en el mismo proceso sin overhead de IPC
  - QThread para captura de cámara sin bloquear la UI
  - Animaciones fluidas con QPropertyAnimation y QGraphicsEffect
  - Notificaciones visuales con overlay animado sobre el feed
  - Look moderno con QSS (Qt Style Sheets)

Instalación:
    pip install PyQt6 PyQt6-Qt6 opencv-contrib-python

Uso:
    python client/ui/porteria_app_qt.py
"""

import sys
import os
import base64
import time
import logging
from datetime import datetime
from typing import Optional, Dict

import cv2
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFrame, QScrollArea,
    QGraphicsOpacityEffect, QSizePolicy, QDialog, QDialogButtonBox,
    QStackedWidget, QGridLayout, QSpacerItem
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation,
    QEasingCurve, QRect, QSize, pyqtProperty, QObject
)
from PyQt6.QtGui import (
    QImage, QPixmap, QPainter, QPen, QBrush, QColor, QFont,
    QPalette, QLinearGradient, QRadialGradient, QFontDatabase
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from client.utils.api_client import ColegioAPIClient, APIError, obtener_ip_local

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
# Paleta de colores — Dark profesional
# ──────────────────────────────────────────────────────────
COLORS = {
    "bg_primary":    "#0a0e1a",   # Fondo principal profundo
    "bg_secondary":  "#111827",   # Paneles
    "bg_card":       "#1a2235",   # Cards
    "bg_input":      "#0f1623",   # Inputs
    "bg_hover":      "#1e2d45",   # Hover states

    "border":        "#1e2d45",   # Bordes sutiles
    "border_bright": "#2d4a6e",   # Bordes activos

    "text_primary":  "#e8f0fe",   # Texto principal
    "text_secondary":"#8ba3c7",   # Texto secundario
    "text_hint":     "#4a6080",   # Hints

    "green":         "#00d68f",   # ENTRADA / éxito
    "green_dim":     "#0a3d2e",   # Fondo verde
    "red":           "#ff4757",   # SALIDA / error
    "red_dim":       "#3d0a1a",   # Fondo rojo
    "amber":         "#ffa502",   # TARDANZA
    "amber_dim":     "#3d2800",   # Fondo ámbar
    "blue":          "#2196f3",   # Info / acento
    "blue_dim":      "#0a1e3d",   # Fondo azul
    "purple":        "#7c4dff",   # Acento secundario
}

# ──────────────────────────────────────────────────────────
# QSS Global — estilos de toda la aplicación
# ──────────────────────────────────────────────────────────
QSS_GLOBAL = f"""
QMainWindow, QWidget {{
    background-color: {COLORS['bg_primary']};
    color: {COLORS['text_primary']};
    font-family: 'Segoe UI', 'Inter', sans-serif;
}}

QLabel {{
    color: {COLORS['text_primary']};
    background: transparent;
}}

QLineEdit {{
    background-color: {COLORS['bg_input']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 10px 14px;
    color: {COLORS['text_primary']};
    font-size: 14px;
    selection-background-color: {COLORS['blue']};
}}
QLineEdit:focus {{
    border: 1px solid {COLORS['blue']};
}}
QLineEdit::placeholder {{
    color: {COLORS['text_hint']};
}}

QPushButton {{
    background-color: {COLORS['bg_card']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 10px 20px;
    color: {COLORS['text_primary']};
    font-size: 13px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {COLORS['bg_hover']};
    border-color: {COLORS['border_bright']};
}}
QPushButton:pressed {{
    background-color: {COLORS['bg_input']};
}}

QPushButton#btn_primary {{
    background-color: {COLORS['blue']};
    border: none;
    color: #ffffff;
}}
QPushButton#btn_primary:hover {{
    background-color: #1976d2;
}}

QPushButton#btn_success {{
    background-color: {COLORS['green_dim']};
    border: 1px solid {COLORS['green']};
    color: {COLORS['green']};
}}
QPushButton#btn_danger {{
    background-color: {COLORS['red_dim']};
    border: 1px solid {COLORS['red']};
    color: {COLORS['red']};
}}

QScrollBar:vertical {{
    background: {COLORS['bg_secondary']};
    width: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border_bright']};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QFrame#separator {{
    background-color: {COLORS['border']};
    max-height: 1px;
}}
"""


# ══════════════════════════════════════════════════════════
# Thread de captura de cámara — sin bloquear la UI
# ══════════════════════════════════════════════════════════

class CameraThread(QThread):
    """
    Captura frames de la webcam en un hilo separado.
    Emite señales al hilo principal de la UI con cada frame.
    """
    frame_ready   = pyqtSignal(np.ndarray)  # Frame BGR listo para mostrar
    scan_ready    = pyqtSignal(bytes)        # Frame JPEG listo para enviar al servidor
    camera_error  = pyqtSignal(str)

    INTERVALO_SCAN_MS = 1200  # ms entre envíos al servidor (evita saturar)
    JPEG_QUALITY      = 82

    def __init__(self, camera_index: int = 0):
        super().__init__()
        self.camera_index = camera_index
        self._corriendo   = False
        self._ultimo_scan = 0.0
        self._detector    = None

        # Detector Haar Cascade para dibujar rectángulo en pantalla
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if os.path.exists(cascade_path):
            self._detector = cv2.CascadeClassifier(cascade_path)

    def run(self):
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW if sys.platform == "win32" else 0)

        if not cap.isOpened():
            self.camera_error.emit(f"No se pudo abrir la cámara (índice {self.camera_index})")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimiza latencia del buffer

        self._corriendo = True

        while self._corriendo:
            ret, frame = cap.read()
            if not ret:
                continue

            # Voltear horizontalmente (efecto espejo)
            frame = cv2.flip(frame, 1)

            # Detectar rostros localmente para dibujar rectángulo en tiempo real
            frame_display = self._draw_faces(frame.copy())

            # Emitir frame para la pantalla
            self.frame_ready.emit(frame_display)

            # Emitir frame para scan (throttled)
            ahora = time.time()
            if ahora - self._ultimo_scan >= self.INTERVALO_SCAN_MS / 1000.0:
                if self._hay_rostro(frame):
                    _, jpeg = cv2.imencode(
                        ".jpg", frame,
                        [cv2.IMWRITE_JPEG_QUALITY, self.JPEG_QUALITY]
                    )
                    self.scan_ready.emit(jpeg.tobytes())
                    self._ultimo_scan = ahora

        cap.release()

    def _hay_rostro(self, frame: np.ndarray) -> bool:
        if self._detector is None:
            return True  # Sin detector, siempre enviar
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._detector.detectMultiScale(gray, 1.1, 4, minSize=(60, 60))
        return len(faces) > 0

    def _draw_faces(self, frame: np.ndarray) -> np.ndarray:
        if self._detector is None:
            return frame
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._detector.detectMultiScale(gray, 1.1, 4, minSize=(60, 60))
        for (x, y, w, h) in faces:
            # Esquinas del rectángulo en lugar de rectángulo completo (look moderno)
            c = (0, 200, 140)  # color verde-azulado
            t = 2  # grosor
            l = 20  # longitud de la esquina
            cv2.line(frame, (x, y), (x+l, y), c, t)
            cv2.line(frame, (x, y), (x, y+l), c, t)
            cv2.line(frame, (x+w, y), (x+w-l, y), c, t)
            cv2.line(frame, (x+w, y), (x+w, y+l), c, t)
            cv2.line(frame, (x, y+h), (x+l, y+h), c, t)
            cv2.line(frame, (x, y+h), (x, y+h-l), c, t)
            cv2.line(frame, (x+w, y+h), (x+w-l, y+h), c, t)
            cv2.line(frame, (x+w, y+h), (x+w, y+h-l), c, t)
        return frame

    def detener(self):
        self._corriendo = False
        self.wait(2000)


# ══════════════════════════════════════════════════════════
# Thread de envío de scan al servidor
# ══════════════════════════════════════════════════════════

class ScanWorker(QThread):
    """
    Envía un frame al servidor en background.
    Nunca bloquea la UI — los resultados llegan vía señales.
    """
    resultado = pyqtSignal(dict)
    error     = pyqtSignal(str)

    def __init__(self, api: ColegioAPIClient, frame_bytes: bytes,
                 ip_cliente: str, tipo_forzado: Optional[str] = None):
        super().__init__()
        self.api          = api
        self.frame_bytes  = frame_bytes
        self.ip_cliente   = ip_cliente
        self.tipo_forzado = tipo_forzado

    def run(self):
        try:
            resultado = self.api.enviar_scan(
                self.frame_bytes, self.ip_cliente, self.tipo_forzado
            )
            self.resultado.emit(resultado)
        except APIError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Error inesperado: {e}")


# ══════════════════════════════════════════════════════════
# Widget: Feed de cámara con overlay animado
# ══════════════════════════════════════════════════════════

class CameraWidget(QLabel):
    """
    Widget que muestra el feed de la webcam.
    Incluye overlay animado cuando se reconoce un alumno.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background-color: {COLORS['bg_primary']}; border-radius: 12px;")

        # Estado del overlay de resultado
        self._overlay_text   = ""
        self._overlay_color  = QColor(0, 214, 143)   # verde
        self._overlay_alpha  = 0.0
        self._overlay_timer  = QTimer(self)
        self._overlay_timer.timeout.connect(self._fade_overlay)

        # Placeholder cuando no hay cámara
        self._mostrar_placeholder()

    def _mostrar_placeholder(self):
        placeholder = QPixmap(640, 480)
        placeholder.fill(QColor(COLORS['bg_primary']))
        p = QPainter(placeholder)
        p.setPen(QColor(COLORS['text_hint']))
        p.setFont(QFont("Segoe UI", 18))
        p.drawText(placeholder.rect(), Qt.AlignmentFlag.AlignCenter, "⏳  Iniciando cámara...")
        p.end()
        self.setPixmap(placeholder)

    def mostrar_frame(self, frame: np.ndarray):
        """Convierte frame BGR de OpenCV a QPixmap y lo muestra."""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)

        pixmap = QPixmap.fromImage(qt_image)
        pixmap = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        # Dibujar overlay encima si está activo
        if self._overlay_alpha > 0.01:
            self._draw_overlay(pixmap)

        self.setPixmap(pixmap)

    def mostrar_resultado(self, nombre: str, tipo: str, tardanza: bool = False):
        """Activa el overlay animado de resultado."""
        self._overlay_text = nombre
        if tipo == "ENTRADA":
            self._overlay_color = QColor(COLORS['amber'] if tardanza else COLORS['green'])
        else:
            self._overlay_color = QColor(COLORS['red'])
        self._overlay_alpha = 1.0
        self._overlay_timer.start(50)  # actualizar cada 50ms

    def _fade_overlay(self):
        self._overlay_alpha = max(0.0, self._overlay_alpha - 0.025)
        if self._overlay_alpha <= 0:
            self._overlay_timer.stop()

    def _draw_overlay(self, pixmap: QPixmap):
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Barra inferior con gradiente semi-transparente
        color = QColor(self._overlay_color)
        color.setAlphaF(self._overlay_alpha * 0.85)

        barra_h = 80
        rect = QRect(0, pixmap.height() - barra_h, pixmap.width(), barra_h)
        p.fillRect(rect, color)

        # Texto del nombre
        p.setPen(QColor(255, 255, 255, int(self._overlay_alpha * 255)))
        font = QFont("Segoe UI", 22, QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._overlay_text)
        p.end()


# ══════════════════════════════════════════════════════════
# Widget: Card de resultado del último reconocido
# ══════════════════════════════════════════════════════════

class ResultCard(QFrame):
    """Card animada que muestra el resultado del último reconocimiento."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("result_card")
        self.setStyleSheet(f"""
            QFrame#result_card {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
                padding: 0px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(20, 16, 20, 16)

        # Sección header
        header = QHBoxLayout()
        self.lbl_seccion = QLabel("ÚLTIMO RECONOCIDO")
        self.lbl_seccion.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")

        self.dot_estado = QLabel("●")
        self.dot_estado.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 14px;")
        header.addWidget(self.lbl_seccion)
        header.addStretch()
        header.addWidget(self.dot_estado)
        layout.addLayout(header)

        # Nombre del alumno
        self.lbl_nombre = QLabel("Esperando...")
        self.lbl_nombre.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 22px; font-weight: 700; margin-top: 4px;")
        self.lbl_nombre.setWordWrap(True)
        layout.addWidget(self.lbl_nombre)

        # Grado
        self.lbl_grado = QLabel("")
        self.lbl_grado.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        layout.addWidget(self.lbl_grado)

        # Badge de evento
        self.lbl_evento = QLabel("")
        self.lbl_evento.setStyleSheet(f"color: {COLORS['green']}; font-size: 15px; font-weight: 700; margin-top: 6px;")
        layout.addWidget(self.lbl_evento)

        # Hora
        self.lbl_hora = QLabel("")
        self.lbl_hora.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 12px;")
        layout.addWidget(self.lbl_hora)

        # Barra de confianza (visual)
        self.lbl_confianza_label = QLabel("")
        self.lbl_confianza_label.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 11px; margin-top: 4px;")
        layout.addWidget(self.lbl_confianza_label)

        # Efecto de opacidad para animación
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(1.0)

        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._anim.setDuration(300)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def actualizar(self, nombre: str, grado: str, turno: str,
                   tipo: str, estado: str, hora: str, confianza: Optional[float]):
        """Actualiza la card con flash de entrada."""
        # Flash animation: fade out → update → fade in
        self._anim.setStartValue(0.3)
        self._anim.setEndValue(1.0)

        self.lbl_nombre.setText(nombre[:30])
        self.lbl_grado.setText(f"{grado}  ·  Turno {turno}" if turno else grado)

        if tipo == "ENTRADA":
            if estado == "TARDANZA":
                color = COLORS['amber']
                icono = "⏰  ENTRADA — TARDANZA"
            else:
                color = COLORS['green']
                icono = "✓  ENTRADA REGISTRADA"
            self.dot_estado.setStyleSheet(f"color: {color}; font-size: 14px;")
        else:
            color = COLORS['red']
            icono = "✕  SALIDA REGISTRADA"
            self.dot_estado.setStyleSheet(f"color: {color}; font-size: 14px;")

        self.lbl_evento.setText(icono)
        self.lbl_evento.setStyleSheet(f"color: {color}; font-size: 15px; font-weight: 700; margin-top: 6px;")
        self.lbl_hora.setText(f"Registrado a las {hora}")

        if confianza:
            barras = int(confianza * 10)
            barra = "█" * barras + "░" * (10 - barras)
            self.lbl_confianza_label.setText(f"Confianza  {barra}  {confianza*100:.0f}%")

        self._anim.start()


# ══════════════════════════════════════════════════════════
# Widget: Stats del día
# ══════════════════════════════════════════════════════════

class StatWidget(QFrame):
    """Mini card con un número estadístico."""

    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(2)
        layout.setContentsMargins(14, 12, 14, 12)

        self.lbl_valor = QLabel("—")
        self.lbl_valor.setStyleSheet(f"color: {color}; font-size: 28px; font-weight: 700;")
        self.lbl_valor.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_label = QLabel(label.upper())
        self.lbl_label.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 9px; font-weight: 700; letter-spacing: 0.5px;")
        self.lbl_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.lbl_valor)
        layout.addWidget(self.lbl_label)

    def set_valor(self, valor: str):
        self.lbl_valor.setText(str(valor))


# ══════════════════════════════════════════════════════════
# Dialog: Popup de re-escaneo
# ══════════════════════════════════════════════════════════

class PopupReescaneo(QDialog):
    """Dialog modal para re-escaneos en < 5 minutos."""

    def __init__(self, mensaje: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Re-escaneo detectado")
        self.setFixedSize(500, 260)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint
        )
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS['bg_secondary']};
                border: 2px solid {COLORS['amber']};
                border-radius: 16px;
            }}
        """)

        self.decision = "IGNORAR"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(12)

        # Icono + título
        titulo = QLabel("⚠   RE-ESCANEO RÁPIDO")
        titulo.setStyleSheet(f"color: {COLORS['amber']}; font-size: 16px; font-weight: 700;")
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(titulo)

        # Mensaje
        msg = QLabel(mensaje)
        msg.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px; line-height: 1.4;")
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(msg)

        layout.addStretch()

        # Botones
        btns = QHBoxLayout()
        btns.setSpacing(10)

        btn_ignorar = QPushButton("Ignorar")
        btn_ignorar.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 10px 20px;
                color: {COLORS['text_secondary']};
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {COLORS['bg_hover']};
            }}
        """)
        btn_ignorar.clicked.connect(lambda: self._decidir("IGNORAR"))

        btn_salida = QPushButton("Registrar Salida")
        btn_salida.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['red_dim']};
                border: 1px solid {COLORS['red']};
                border-radius: 8px;
                padding: 10px 20px;
                color: {COLORS['red']};
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #4d1020; }}
        """)
        btn_salida.clicked.connect(lambda: self._decidir("SALIDA"))

        btn_entrada = QPushButton("Registrar Entrada")
        btn_entrada.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['green_dim']};
                border: 1px solid {COLORS['green']};
                border-radius: 8px;
                padding: 10px 20px;
                color: {COLORS['green']};
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #0d4d35; }}
        """)
        btn_entrada.clicked.connect(lambda: self._decidir("ENTRADA"))

        btns.addWidget(btn_ignorar)
        btns.addWidget(btn_salida)
        btns.addWidget(btn_entrada)
        layout.addLayout(btns)

    def _decidir(self, decision: str):
        self.decision = decision
        self.accept()


# ══════════════════════════════════════════════════════════
# Ventana de Login
# ══════════════════════════════════════════════════════════

class LoginWindow(QWidget):
    login_exitoso = pyqtSignal(object, dict)  # (api, usuario)

    def __init__(self):
        super().__init__()
        self.api = ColegioAPIClient()
        self._setup_ui()
        self._check_server()

    def _setup_ui(self):
        self.setWindowTitle("Colegio Asistencia — Portería")
        self.setFixedSize(420, 500)
        self.setStyleSheet(QSS_GLOBAL + f"""
            QWidget {{
                background-color: {COLORS['bg_primary']};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(50, 50, 50, 50)

        # Icono / logo
        ico = QLabel("🏫")
        ico.setStyleSheet("font-size: 48px; background: transparent;")
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(ico)
        layout.addSpacing(8)

        titulo = QLabel("COLEGIO ASISTENCIA")
        titulo.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 18px; font-weight: 700; letter-spacing: 1px;")
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(titulo)

        subtitulo = QLabel("Sistema de Reconocimiento Facial")
        subtitulo.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 12px;")
        subtitulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitulo)

        layout.addSpacing(32)

        # Campo usuario
        self.input_user = QLineEdit()
        self.input_user.setPlaceholderText("Usuario")
        layout.addWidget(self.input_user)
        layout.addSpacing(10)

        # Campo contraseña
        self.input_pass = QLineEdit()
        self.input_pass.setPlaceholderText("Contraseña")
        self.input_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_pass.returnPressed.connect(self._do_login)
        layout.addWidget(self.input_pass)
        layout.addSpacing(20)

        # Botón login
        self.btn_login = QPushButton("INGRESAR")
        self.btn_login.setObjectName("btn_primary")
        self.btn_login.setMinimumHeight(44)
        self.btn_login.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['blue']};
                border: none;
                border-radius: 10px;
                color: white;
                font-size: 14px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{ background-color: #1565c0; }}
            QPushButton:pressed {{ background-color: #0d47a1; }}
        """)
        self.btn_login.clicked.connect(self._do_login)
        layout.addWidget(self.btn_login)

        layout.addSpacing(14)

        # Status del servidor
        self.lbl_status = QLabel("Verificando conexión...")
        self.lbl_status.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 11px;")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_status)

        layout.addStretch()

        self.input_user.setFocus()

    def _check_server(self):
        class PingThread(QThread):
            resultado = pyqtSignal(bool)
            def __init__(self, api): super().__init__(); self.api = api
            def run(self): self.resultado.emit(self.api.ping())

        self._ping_thread = PingThread(self.api)
        self._ping_thread.resultado.connect(self._on_ping)
        self._ping_thread.start()

    def _on_ping(self, ok: bool):
        if ok:
            self.lbl_status.setText("● Servidor conectado")
            self.lbl_status.setStyleSheet(f"color: {COLORS['green']}; font-size: 11px;")
        else:
            self.lbl_status.setText("● Servidor no disponible")
            self.lbl_status.setStyleSheet(f"color: {COLORS['red']}; font-size: 11px;")

    def _do_login(self):
        user = self.input_user.text().strip()
        pwd  = self.input_pass.text().strip()

        if not user or not pwd:
            self.lbl_status.setText("⚠  Completa usuario y contraseña")
            self.lbl_status.setStyleSheet(f"color: {COLORS['amber']}; font-size: 11px;")
            return

        self.btn_login.setEnabled(False)
        self.btn_login.setText("Conectando...")

        class LoginThread(QThread):
            exito = pyqtSignal(dict)
            error = pyqtSignal(str)
            def __init__(self, api, user, pwd):
                super().__init__(); self.api = api; self.user = user; self.pwd = pwd
            def run(self):
                try:
                    self.exito.emit(self.api.login(self.user, self.pwd))
                except APIError as e:
                    self.error.emit(e.detalle)
                except Exception as e:
                    self.error.emit(str(e))

        self._login_thread = LoginThread(self.api, user, pwd)
        self._login_thread.exito.connect(self._on_login_ok)
        self._login_thread.error.connect(self._on_login_error)
        self._login_thread.start()

    def _on_login_ok(self, usuario: dict):
        self.login_exitoso.emit(self.api, usuario)
        self.close()

    def _on_login_error(self, msg: str):
        self.lbl_status.setText(f"✕  {msg}")
        self.lbl_status.setStyleSheet(f"color: {COLORS['red']}; font-size: 11px;")
        self.btn_login.setEnabled(True)
        self.btn_login.setText("INGRESAR")


# ══════════════════════════════════════════════════════════
# Ventana Principal de Portería
# ══════════════════════════════════════════════════════════

class PorteriaWindow(QMainWindow):
    """
    Ventana principal de portería con:
    - Feed de cámara 60fps con detección local de rostros
    - Panel lateral con resultado, búsqueda manual y stats
    - Overlay animado al reconocer un alumno
    - Popup modal para re-escaneos
    - Auto-refresh de token JWT
    """

    def __init__(self, api: ColegioAPIClient, usuario: Dict):
        super().__init__()
        self.api        = api
        self.usuario    = usuario
        self.ip_cliente = obtener_ip_local()

        self._scan_activo     = True
        self._scan_en_curso   = False   # evita doble scan simultáneo
        self._resultados_busq = []

        self._setup_ui()
        self._start_camera()
        self._start_timers()

    # ──────────────────────────────── UI ──────────────────── #

    def _setup_ui(self):
        self.setWindowTitle(
            f"Colegio Asistencia — Portería  ({self.usuario.get('nombre_display', '')})"
        )
        self.setMinimumSize(1200, 700)
        self.resize(1400, 820)
        self.setStyleSheet(QSS_GLOBAL)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self._build_header(root_layout)

        body = QHBoxLayout()
        body.setSpacing(12)
        body.setContentsMargins(12, 12, 12, 12)
        root_layout.addLayout(body, 1)

        self._build_camera_panel(body)
        self._build_side_panel(body)

    def _build_header(self, parent_layout):
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_secondary']};
                border-bottom: 1px solid {COLORS['border']};
            }}
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)

        # Logo + nombre
        lbl_logo = QLabel("🏫  COLEGIO ASISTENCIA")
        lbl_logo.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 14px; font-weight: 700;")
        hl.addWidget(lbl_logo)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {COLORS['border']}; margin: 14px 12px;")
        hl.addWidget(sep)

        # Usuario
        lbl_user = QLabel(f"👤  {self.usuario.get('nombre_display', 'Usuario')}")
        lbl_user.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        hl.addWidget(lbl_user)

        hl.addStretch()

        # Dot de estado del servidor
        self.dot_server = QLabel("●  Conectado")
        self.dot_server.setStyleSheet(f"color: {COLORS['green']}; font-size: 12px;")
        hl.addWidget(self.dot_server)

        # Separador
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet(f"color: {COLORS['border']}; margin: 14px 12px;")
        hl.addWidget(sep2)

        # Reloj
        self.lbl_clock = QLabel("00:00:00")
        self.lbl_clock.setStyleSheet(f"color: {COLORS['blue']}; font-size: 22px; font-weight: 700; font-family: 'Consolas', monospace;")
        hl.addWidget(self.lbl_clock)

        parent_layout.addWidget(header)

    def _build_camera_panel(self, parent_layout):
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
            }}
        """)
        vl = QVBoxLayout(panel)
        vl.setSpacing(8)
        vl.setContentsMargins(10, 10, 10, 10)

        # Feed de cámara
        self.camera_widget = CameraWidget()
        self.camera_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        vl.addWidget(self.camera_widget, 1)

        # Barra de controles
        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.lbl_cam_status = QLabel("⏳  Iniciando cámara...")
        self.lbl_cam_status.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 11px;")
        controls.addWidget(self.lbl_cam_status)

        controls.addStretch()

        self.btn_scan_toggle = QPushButton("⏸  Pausar Scan")
        self.btn_scan_toggle.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['amber_dim']};
                border: 1px solid {COLORS['amber']};
                border-radius: 8px;
                padding: 8px 16px;
                color: {COLORS['amber']};
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #4d3000; }}
        """)
        self.btn_scan_toggle.clicked.connect(self._toggle_scan)
        controls.addWidget(self.btn_scan_toggle)

        vl.addLayout(controls)
        parent_layout.addWidget(panel, 3)

    def _build_side_panel(self, parent_layout):
        side = QWidget()
        side.setFixedWidth(340)
        sl = QVBoxLayout(side)
        sl.setSpacing(12)
        sl.setContentsMargins(0, 0, 0, 0)

        # Card resultado
        self.result_card = ResultCard()
        sl.addWidget(self.result_card)

        # Stats del día
        stats_frame = QFrame()
        stats_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
            }}
        """)
        stats_vl = QVBoxLayout(stats_frame)
        stats_vl.setContentsMargins(16, 12, 16, 12)
        stats_vl.setSpacing(8)

        lbl_stats_h = QLabel("HOY")
        lbl_stats_h.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        stats_vl.addWidget(lbl_stats_h)

        stats_grid = QHBoxLayout()
        stats_grid.setSpacing(8)

        self.stat_presentes = StatWidget("Presentes", COLORS['green'])
        self.stat_ausentes  = StatWidget("Ausentes",  COLORS['red'])
        self.stat_tardanzas = StatWidget("Tardanzas", COLORS['amber'])

        stats_grid.addWidget(self.stat_presentes)
        stats_grid.addWidget(self.stat_ausentes)
        stats_grid.addWidget(self.stat_tardanzas)
        stats_vl.addLayout(stats_grid)

        btn_refresh_stats = QPushButton("↻  Actualizar")
        btn_refresh_stats.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 6px 12px;
                color: {COLORS['text_secondary']};
                font-size: 11px;
            }}
            QPushButton:hover {{ background-color: {COLORS['bg_hover']}; }}
        """)
        btn_refresh_stats.clicked.connect(self._update_stats)
        stats_vl.addWidget(btn_refresh_stats)
        sl.addWidget(stats_frame)

        # Búsqueda manual
        busqueda_frame = QFrame()
        busqueda_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
            }}
        """)
        bvl = QVBoxLayout(busqueda_frame)
        bvl.setContentsMargins(16, 12, 16, 12)
        bvl.setSpacing(8)

        lbl_busq_h = QLabel("BÚSQUEDA MANUAL")
        lbl_busq_h.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        bvl.addWidget(lbl_busq_h)

        busq_row = QHBoxLayout()
        self.input_busq = QLineEdit()
        self.input_busq.setPlaceholderText("Nombre o apellido...")
        self.input_busq.returnPressed.connect(self._buscar)
        busq_row.addWidget(self.input_busq, 1)

        btn_buscar = QPushButton("🔍")
        btn_buscar.setFixedSize(38, 38)
        btn_buscar.clicked.connect(self._buscar)
        busq_row.addWidget(btn_buscar)
        bvl.addLayout(busq_row)

        # Área de resultados de búsqueda
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(160)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                background-color: {COLORS['bg_input']};
            }}
        """)

        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setSpacing(0)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.addStretch()
        scroll.setWidget(self.list_widget)
        bvl.addWidget(scroll)

        sl.addWidget(busqueda_frame)
        sl.addStretch()

        parent_layout.addWidget(side)

    # ──────────────────────────────── Cámara y Scan ─────── #

    def _start_camera(self):
        self.cam_thread = CameraThread(camera_index=0)
        self.cam_thread.frame_ready.connect(self._on_frame)
        self.cam_thread.scan_ready.connect(self._on_scan_ready)
        self.cam_thread.camera_error.connect(self._on_camera_error)
        self.cam_thread.start()

        self.lbl_cam_status.setText("●  Cámara activa")
        self.lbl_cam_status.setStyleSheet(f"color: {COLORS['green']}; font-size: 11px;")

    def _on_frame(self, frame: np.ndarray):
        """Llamado ~30 veces/segundo desde CameraThread."""
        self.camera_widget.mostrar_frame(frame)

    def _on_scan_ready(self, frame_bytes: bytes):
        """Frame listo para enviar — throttled por CameraThread."""
        if not self._scan_activo or self._scan_en_curso:
            return

        self._scan_en_curso = True
        worker = ScanWorker(self.api, frame_bytes, self.ip_cliente)
        worker.resultado.connect(self._on_scan_resultado)
        worker.error.connect(self._on_scan_error)
        worker.finished.connect(lambda: setattr(self, '_scan_en_curso', False))
        worker.start()
        # Guardar referencia para evitar GC
        self._scan_worker = worker

    def _on_scan_resultado(self, res: dict):
        if not res.get("reconocido"):
            return

        alumno = res.get("alumno", {})
        nombre = f"{alumno.get('apellidos', '')}, {alumno.get('nombres', '')}"

        if res.get("requiere_popup"):
            self._scan_activo = False
            popup = PopupReescaneo(res.get("popup_mensaje", "Re-escaneo detectado"), self)
            if popup.exec():
                if popup.decision != "IGNORAR":
                    self._force_rescan(popup.decision, alumno.get("id"))
            self._scan_activo = True
            return

        asistencia = res.get("asistencia", {})
        tipo  = asistencia.get("tipo_evento", "ENTRADA")
        estado = asistencia.get("estado", "PRESENTE")
        conf  = asistencia.get("confianza")

        hora = ""
        if asistencia.get("fecha"):
            try:
                dt = datetime.fromisoformat(asistencia["fecha"].replace("Z",""))
                hora = dt.strftime("%H:%M:%S")
            except Exception:
                pass

        self.result_card.actualizar(
            nombre=nombre,
            grado=f"{alumno.get('grado','')}{alumno.get('seccion','')}",
            turno=alumno.get("turno", ""),
            tipo=tipo, estado=estado, hora=hora, confianza=conf,
        )

        self.camera_widget.mostrar_resultado(
            nombre.split(",")[0][:18], tipo, tardanza=(estado == "TARDANZA")
        )

        self._update_stats()

    def _on_scan_error(self, msg: str):
        self.dot_server.setText(f"●  {msg[:30]}")
        self.dot_server.setStyleSheet(f"color: {COLORS['red']}; font-size: 11px;")

    def _on_camera_error(self, msg: str):
        self.lbl_cam_status.setText(f"✕  {msg}")
        self.lbl_cam_status.setStyleSheet(f"color: {COLORS['red']}; font-size: 11px;")

    def _force_rescan(self, tipo: str, alumno_id: int):
        """Reenvía un scan con tipo forzado después del popup."""
        # Capturar frame actual
        frame_bytes = getattr(self, '_last_frame_bytes', None)
        if not frame_bytes:
            return

        worker = ScanWorker(self.api, frame_bytes, self.ip_cliente, tipo_forzado=tipo)
        worker.resultado.connect(self._on_scan_resultado)
        worker.start()
        self._force_worker = worker

    # ──────────────────────────────── Búsqueda manual ───── #

    def _buscar(self):
        term = self.input_busq.text().strip()
        if not term:
            return

        # Limpiar lista anterior
        for i in reversed(range(self.list_layout.count())):
            w = self.list_layout.itemAt(i).widget()
            if w:
                w.deleteLater()

        # Agregar placeholder
        lbl = QLabel("  Buscando...")
        lbl.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 12px; padding: 8px;")
        self.list_layout.addWidget(lbl)

        class BusqThread(QThread):
            resultado = pyqtSignal(list)
            def __init__(self, api, term): super().__init__(); self.api=api; self.term=term
            def run(self): 
                try: self.resultado.emit(self.api.buscar_alumno(self.term))
                except: self.resultado.emit([])

        self._busq_thread = BusqThread(self.api, term)
        self._busq_thread.resultado.connect(self._on_busqueda)
        self._busq_thread.start()

    def _on_busqueda(self, resultados: list):
        self._resultados_busq = resultados

        # Limpiar
        for i in reversed(range(self.list_layout.count())):
            w = self.list_layout.itemAt(i).widget()
            if w: w.deleteLater()

        if not resultados:
            lbl = QLabel("  Sin resultados")
            lbl.setStyleSheet(f"color: {COLORS['text_hint']}; font-size: 12px; padding: 8px;")
            self.list_layout.addWidget(lbl)
            return

        for i, a in enumerate(resultados):
            nombre = f"{a['apellidos']}, {a['nombres']}"
            grado  = f"{a['grado']}{a['seccion']}"
            btn = QPushButton(f"  {nombre}  —  {grado}")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-bottom: 1px solid {COLORS['border']};
                    text-align: left;
                    padding: 10px 12px;
                    color: {COLORS['text_primary']};
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: {COLORS['bg_hover']};
                }}
            """)
            btn.clicked.connect(lambda checked, idx=i: self._seleccionar_alumno(idx))
            self.list_layout.addWidget(btn)

        self.list_layout.addStretch()

    def _seleccionar_alumno(self, idx: int):
        if idx >= len(self._resultados_busq):
            return
        alumno = self._resultados_busq[idx]
        nombre = f"{alumno['apellidos']}, {alumno['nombres']}"

        # Dialog de selección de tipo
        dialog = QDialog(self)
        dialog.setWindowTitle("Registro Manual")
        dialog.setFixedSize(380, 200)
        dialog.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
            }}
            QLabel {{ color: {COLORS['text_primary']}; }}
        """)

        vl = QVBoxLayout(dialog)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(12)

        vl.addWidget(QLabel(f"Registrar para: {nombre[:30]}"))

        tipo_var = {"valor": None}

        btns_row = QHBoxLayout()
        for tipo, color, dim in [("ENTRADA", COLORS['green'], COLORS['green_dim']),
                                   ("SALIDA",  COLORS['red'],   COLORS['red_dim'])]:
            b = QPushButton(tipo)
            b.setStyleSheet(f"""
                QPushButton {{
                    background-color: {dim};
                    border: 1px solid {color};
                    border-radius: 8px;
                    padding: 12px 24px;
                    color: {color};
                    font-weight: 700;
                    font-size: 13px;
                }}
                QPushButton:hover {{ opacity: 0.8; }}
            """)
            b.clicked.connect(lambda checked, t=tipo: (tipo_var.update({"valor": t}), dialog.accept()))
            btns_row.addWidget(b)
        vl.addLayout(btns_row)

        if dialog.exec() and tipo_var["valor"]:
            self._registrar_manual_alumno(alumno["id"], nombre, tipo_var["valor"])

    def _registrar_manual_alumno(self, alumno_id: int, nombre: str, tipo: str):
        class RegThread(QThread):
            exito = pyqtSignal(dict)
            error = pyqtSignal(str)
            def __init__(self, api, aid, tipo):
                super().__init__(); self.api=api; self.aid=aid; self.tipo=tipo
            def run(self):
                try: self.exito.emit(self.api.registrar_manual(self.aid, self.tipo, "Manual portería"))
                except APIError as e: self.error.emit(e.detalle)

        self._reg_thread = RegThread(self.api, alumno_id, tipo)
        self._reg_thread.exito.connect(lambda r: self._update_stats())
        self._reg_thread.start()

    # ──────────────────────────────── Timers ──────────────── #

    def _start_timers(self):
        # Reloj
        self._timer_clock = QTimer(self)
        self._timer_clock.timeout.connect(self._update_clock)
        self._timer_clock.start(1000)

        # Stats cada 30s
        self._timer_stats = QTimer(self)
        self._timer_stats.timeout.connect(self._update_stats)
        self._timer_stats.start(30_000)

        # Ping servidor cada 30s
        self._timer_ping = QTimer(self)
        self._timer_ping.timeout.connect(self._check_server)
        self._timer_ping.start(30_000)

        # Actualización inicial inmediata
        self._update_stats()

    def _update_clock(self):
        self.lbl_clock.setText(datetime.now().strftime("%H:%M:%S"))

    def _update_stats(self):
        class StatsThread(QThread):
            resultado = pyqtSignal(dict)
            def __init__(self, api): super().__init__(); self.api=api
            def run(self):
                try: self.resultado.emit(self.api.reporte_diario())
                except: self.resultado.emit({})

        self._stats_thread = StatsThread(self.api)
        self._stats_thread.resultado.connect(self._on_stats)
        self._stats_thread.start()

    def _on_stats(self, data: dict):
        if data:
            self.stat_presentes.set_valor(data.get("presentes", "—"))
            self.stat_ausentes.set_valor(data.get("ausentes", "—"))
            self.stat_tardanzas.set_valor(data.get("tardanzas", "—"))

    def _check_server(self):
        class PingThread(QThread):
            resultado = pyqtSignal(bool)
            def __init__(self, api): super().__init__(); self.api=api
            def run(self): self.resultado.emit(self.api.ping())

        self._ping_thread = PingThread(self.api)
        self._ping_thread.resultado.connect(self._on_ping)
        self._ping_thread.start()

    def _on_ping(self, ok: bool):
        if ok:
            self.dot_server.setText("●  Conectado")
            self.dot_server.setStyleSheet(f"color: {COLORS['green']}; font-size: 12px;")
        else:
            self.dot_server.setText("●  Sin conexión")
            self.dot_server.setStyleSheet(f"color: {COLORS['red']}; font-size: 12px;")

    def _toggle_scan(self):
        self._scan_activo = not self._scan_activo
        if self._scan_activo:
            self.btn_scan_toggle.setText("⏸  Pausar Scan")
            self.btn_scan_toggle.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['amber_dim']};
                    border: 1px solid {COLORS['amber']};
                    border-radius: 8px; padding: 8px 16px;
                    color: {COLORS['amber']}; font-size: 12px; font-weight: 600;
                }}
                QPushButton:hover {{ background-color: #4d3000; }}
            """)
        else:
            self.btn_scan_toggle.setText("▶  Reanudar Scan")
            self.btn_scan_toggle.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['green_dim']};
                    border: 1px solid {COLORS['green']};
                    border-radius: 8px; padding: 8px 16px;
                    color: {COLORS['green']}; font-size: 12px; font-weight: 600;
                }}
                QPushButton:hover {{ background-color: #0d4d35; }}
            """)

    def closeEvent(self, event):
        if hasattr(self, 'cam_thread'):
            self.cam_thread.detener()
        event.accept()


# ══════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Colegio Asistencia")
    app.setOrganizationName("Colegio")

    # Fuente global
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    login = LoginWindow()

    porteria_win = None

    def on_login(api: ColegioAPIClient, usuario: dict):
        nonlocal porteria_win
        porteria_win = PorteriaWindow(api, usuario)
        porteria_win.show()

    login.login_exitoso.connect(on_login)
    login.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()