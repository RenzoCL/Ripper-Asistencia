"""
client/ui/porteria_app.py  (CustomTkinter edition)
====================================================
Rediseño visual de la interfaz de Portería.
Usa CustomTkinter para lograr un look moderno tipo "dark dashboard".

Dependencias adicionales:
    pip install customtkinter pillow opencv-python

Mantiene exactamente las mismas funcionalidades del original Tkinter:
  - Login con verificación de servidor
  - Feed de webcam en tiempo real con detección de rostros
  - Reconocimiento automático + overlay con nombre
  - Popup de re-escaneo (< 5 min)
  - Búsqueda manual de alumnos
  - Registro manual de entrada/salida
  - Estadísticas del día (presentes / ausentes / tardanzas)
  - Toggle de pausa del scan
  - Verificación periódica del servidor
"""

import os
import sys
import threading
import time
import queue
import logging
from datetime import datetime
from typing import Optional, Dict

import customtkinter as ctk
from tkinter import messagebox, simpledialog
import cv2
from PIL import Image, ImageTk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from client.utils.api_client import ColegioAPIClient, APIError, obtener_ip_local
from client.utils.camera import CameraCapture, FaceDetectorLocal

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Paleta (GitHub Dark inspirada)
# ─────────────────────────────────────────────
BG_ROOT   = "#0d1117"   # Fondo principal
BG_PANEL  = "#161b22"   # Paneles / header / barra lateral
BG_CARD   = "#0d1117"   # Cards dentro del panel derecho
BG_INPUT  = "#010409"   # Input / canvas de video
BG_HOVER  = "#21262d"   # Hover de lista

BORDER    = "#21262d"   # Bordes sutiles
BORDER2   = "#30363d"   # Bordes secundarios

TXT_PRI   = "#e6edf3"   # Texto principal
TXT_SEC   = "#8b949e"   # Texto secundario / muted
TXT_HINT  = "#484f58"   # Hints / labels pequeños

GREEN     = "#3fb950"   # Entrada / presente
RED       = "#f85149"   # Salida / ausente / error
AMBER     = "#d29922"   # Tardanza / advertencia
BLUE      = "#79c0ff"   # Info / links

FG_ON_GREEN = "#010409"  # Texto sobre fondo verde

FONT_MONO  = ("Consolas", 28, "bold")   # Reloj
FONT_TITLE = ("Segoe UI", 11, "bold")
FONT_NAME  = ("Segoe UI", 17, "bold")
FONT_BODY  = ("Segoe UI", 11)
FONT_SMALL = ("Segoe UI", 9)
FONT_LABEL = ("Segoe UI", 8)

W, H = 1120, 680

# ─────────────────────────────────────────────
#  Configuración global de CustomTkinter
# ─────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


# ─────────────────────────────────────────────────────────── #
#  Helper: separador horizontal delgado
# ─────────────────────────────────────────────────────────── #
def _separador(parent, **pack_kw):
    ctk.CTkFrame(parent, height=1, fg_color=BORDER, corner_radius=0).pack(
        fill="x", **pack_kw
    )


# ─────────────────────────────────────────────────────────── #
#  LoginWindow
# ─────────────────────────────────────────────────────────── #
class LoginWindow:
    """Pantalla de login con diseño moderno oscuro."""

    def __init__(self, on_login_success):
        self.on_success = on_login_success
        self.api = ColegioAPIClient()

        self.root = ctk.CTk()
        self.root.title("Portería — Acceso")
        self.root.geometry("420x440")
        self.root.configure(fg_color=BG_ROOT)
        self.root.resizable(False, False)
        self.root.eval("tk::PlaceWindow . center")

        self._build()
        self.root.mainloop()

    def _build(self):
        # ── Encabezado ──
        top = ctk.CTkFrame(self.root, fg_color="transparent")
        top.pack(pady=(36, 0))

        ctk.CTkLabel(top, text="🏫", font=("Segoe UI Emoji", 46)).pack()
        ctk.CTkLabel(
            top, text="COLEGIO ASISTENCIA",
            font=("Segoe UI", 17, "bold"), text_color=TXT_PRI
        ).pack(pady=(4, 0))
        ctk.CTkLabel(
            top, text="Sistema de Reconocimiento Facial",
            font=FONT_BODY, text_color=TXT_SEC
        ).pack(pady=(2, 0))

        # ── Card de formulario ──
        card = ctk.CTkFrame(
            self.root, fg_color=BG_PANEL,
            border_color=BORDER, border_width=1, corner_radius=10
        )
        card.pack(padx=40, pady=22, fill="x")

        ctk.CTkLabel(card, text="Usuario", font=FONT_SMALL, text_color=TXT_SEC, anchor="w").pack(
            anchor="w", padx=20, pady=(18, 2)
        )
        self.entry_user = ctk.CTkEntry(
            card, font=FONT_BODY, fg_color=BG_INPUT,
            border_color=BORDER2, border_width=1, corner_radius=6,
            text_color=TXT_PRI, placeholder_text="nombre de usuario"
        )
        self.entry_user.pack(fill="x", padx=20)
        self.entry_user.focus()

        ctk.CTkLabel(card, text="Contraseña", font=FONT_SMALL, text_color=TXT_SEC, anchor="w").pack(
            anchor="w", padx=20, pady=(12, 2)
        )
        self.entry_pass = ctk.CTkEntry(
            card, font=FONT_BODY, fg_color=BG_INPUT,
            border_color=BORDER2, border_width=1, corner_radius=6,
            text_color=TXT_PRI, show="●", placeholder_text="••••••••"
        )
        self.entry_pass.pack(fill="x", padx=20)

        self.lbl_status = ctk.CTkLabel(
            card, text="", font=FONT_SMALL, text_color=TXT_HINT
        )
        self.lbl_status.pack(pady=(10, 16))

        # ── Botón ──
        self.btn_login = ctk.CTkButton(
            self.root, text="INGRESAR  →",
            font=("Segoe UI", 12, "bold"),
            fg_color=GREEN, hover_color="#2ea043",
            text_color=FG_ON_GREEN, corner_radius=6,
            height=38, command=self._login
        )
        self.btn_login.pack(padx=40, fill="x")

        self.root.bind("<Return>", lambda _: self._login())
        self._ping()

    def _ping(self):
        def _check():
            ok = self.api.ping()
            txt = "● Servidor conectado" if ok else "● Servidor no disponible"
            col = GREEN if ok else RED
            self.root.after(0, lambda: self.lbl_status.configure(text=txt, text_color=col))
        threading.Thread(target=_check, daemon=True).start()

    def _login(self):
        user = self.entry_user.get().strip()
        pwd  = self.entry_pass.get().strip()
        if not user or not pwd:
            self.lbl_status.configure(text="⚠ Completar usuario y contraseña", text_color=AMBER)
            return
        self.lbl_status.configure(text="Conectando...", text_color=TXT_HINT)
        self.root.update()
        try:
            usuario = self.api.login(user, pwd)
            self.root.destroy()
            self.on_success(self.api, usuario)
        except APIError as e:
            self.lbl_status.configure(text=f"✕ {e.detalle}", text_color=RED)
        except Exception as e:
            self.lbl_status.configure(text=f"✕ Error: {e}", text_color=RED)


# ─────────────────────────────────────────────────────────── #
#  PopupReescaneo
# ─────────────────────────────────────────────────────────── #
class PopupReescaneo(ctk.CTkToplevel):
    """Modal de decisión cuando se detecta un re-escaneo rápido."""

    def __init__(self, parent, mensaje: str, on_decision):
        super().__init__(parent)
        self.on_decision = on_decision
        self.title("Re-escaneo Detectado")
        self.geometry("500x230")
        self.configure(fg_color=BG_PANEL)
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width()  - 500) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 230) // 2
        self.geometry(f"+{x}+{y}")

        self._build(mensaje)

    def _build(self, msg: str):
        ctk.CTkLabel(
            self, text="⚠  RE-ESCANEO RÁPIDO",
            font=FONT_TITLE, text_color=AMBER
        ).pack(pady=(24, 6))

        ctk.CTkLabel(
            self, text=msg, font=FONT_BODY, text_color=TXT_SEC,
            wraplength=460, justify="center"
        ).pack(padx=24)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=20)

        for txt, col, hover, dec in [
            ("Ignorar",          BG_HOVER, BORDER,          "IGNORAR"),
            ("Registrar Salida", RED,      "#c53030",        "SALIDA"),
            ("Registrar Entrada",GREEN,    "#2ea043",        "ENTRADA"),
        ]:
            ctk.CTkButton(
                row, text=txt,
                font=("Segoe UI", 10, "bold"),
                fg_color=col, hover_color=hover,
                text_color=TXT_PRI if col == BG_HOVER else FG_ON_GREEN,
                corner_radius=6, height=34,
                command=lambda d=dec: self._decide(d)
            ).pack(side="left", padx=6)

    def _decide(self, d: str):
        self.destroy()
        self.on_decision(d)


# ─────────────────────────────────────────────────────────── #
#  PorteriaApp — ventana principal
# ─────────────────────────────────────────────────────────── #
class PorteriaApp:
    """Ventana principal de portería (CustomTkinter)."""

    def __init__(self, api: ColegioAPIClient, usuario: Dict):
        self.api        = api
        self.usuario    = usuario
        self.ip_cliente = obtener_ip_local()

        self.camara   = CameraCapture(camara_index=0)
        self.detector = FaceDetectorLocal()

        self._overlay_nombre: Optional[str] = None
        self._overlay_color                 = (0, 255, 0)
        self._overlay_expira                = 0.0
        self._scan_activo                   = True
        self._resultados_busqueda           = []

        self.root = ctk.CTk()
        self.root.title("Colegio Asistencia — Portería")
        self.root.geometry(f"{W}x{H}")
        self.root.configure(fg_color=BG_ROOT)
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build()
        self._start_camera()
        self._start_loops()

        self.root.mainloop()

    # ──────────────────────────────── construcción ──────── #

    def _build(self):
        self._build_header()

        body = ctk.CTkFrame(self.root, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)

        self._build_video_panel(body)
        self._build_info_panel(body)

    # ── Header ──────────────────────────────────────────── #

    def _build_header(self):
        hdr = ctk.CTkFrame(
            self.root, fg_color=BG_PANEL,
            border_color=BORDER, border_width=1, corner_radius=0, height=52
        )
        hdr.pack(fill="x", padx=10, pady=(10, 0))
        hdr.pack_propagate(False)

        # Izquierda
        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.pack(side="left", padx=14)

        ctk.CTkLabel(
            left, text="🏫  COLEGIO ASISTENCIA — PORTERÍA",
            font=FONT_TITLE, text_color=TXT_PRI
        ).pack(side="left")

        self.dot_server = ctk.CTkLabel(
            left, text="  ●  Online",
            font=FONT_SMALL, text_color=GREEN
        )
        self.dot_server.pack(side="left", padx=(16, 0))

        # Derecha
        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.pack(side="right", padx=14)

        self.lbl_clock = ctk.CTkLabel(
            right, text="00:00:00",
            font=FONT_MONO, text_color=GREEN
        )
        self.lbl_clock.pack(side="right")

        ctk.CTkLabel(
            right,
            text=f"👤  {self.usuario.get('nombre_display', 'Usuario')}",
            font=FONT_SMALL, text_color=TXT_SEC
        ).pack(side="right", padx=(0, 18))

    # ── Panel izquierdo: video ───────────────────────────── #

    def _build_video_panel(self, parent):
        frame = ctk.CTkFrame(
            parent, fg_color=BG_PANEL,
            border_color=BORDER, border_width=1, corner_radius=8
        )
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        import tkinter as tk
        self.canvas = tk.Canvas(frame, bg=BG_INPUT, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=6)

        self.lbl_cam_status = ctk.CTkLabel(
            frame, text="⏳  Iniciando cámara...",
            font=FONT_SMALL, text_color=TXT_HINT
        )
        self.lbl_cam_status.pack(pady=(0, 8))

    # ── Panel derecho: info ──────────────────────────────── #

    def _build_info_panel(self, parent):
        panel = ctk.CTkFrame(
            parent, fg_color=BG_PANEL,
            border_color=BORDER, border_width=1,
            corner_radius=8, width=310
        )
        panel.grid(row=0, column=1, sticky="nsew")
        panel.pack_propagate(False)

        inner = ctk.CTkScrollableFrame(panel, fg_color="transparent", scrollbar_button_color=BORDER2)
        inner.pack(fill="both", expand=True, padx=12, pady=12)

        # ── Último reconocido ──
        self._section_label(inner, "Último reconocido")

        self.card_result = ctk.CTkFrame(
            inner, fg_color=BG_CARD,
            border_color=BORDER, border_width=1, corner_radius=8
        )
        self.card_result.pack(fill="x", pady=(4, 12))

        self.lbl_name = ctk.CTkLabel(
            self.card_result, text="Esperando...",
            font=FONT_NAME, text_color=TXT_PRI, anchor="w"
        )
        self.lbl_name.pack(anchor="w", padx=14, pady=(14, 0))

        self.lbl_grade = ctk.CTkLabel(
            self.card_result, text="",
            font=FONT_SMALL, text_color=TXT_SEC, anchor="w"
        )
        self.lbl_grade.pack(anchor="w", padx=14)

        self.lbl_event = ctk.CTkLabel(
            self.card_result, text="",
            font=("Segoe UI", 12, "bold"), text_color=GREEN, anchor="w"
        )
        self.lbl_event.pack(anchor="w", padx=14, pady=(8, 0))

        self.lbl_event_time = ctk.CTkLabel(
            self.card_result, text="",
            font=FONT_LABEL, text_color=TXT_HINT, anchor="w"
        )
        self.lbl_event_time.pack(anchor="w", padx=14, pady=(2, 14))

        _separador(inner, pady=(0, 10))

        # ── Búsqueda manual ──
        self._section_label(inner, "Búsqueda manual")

        row_search = ctk.CTkFrame(inner, fg_color="transparent")
        row_search.pack(fill="x", pady=(4, 0))

        self.entry_search = ctk.CTkEntry(
            row_search, font=FONT_BODY, fg_color=BG_INPUT,
            border_color=BORDER2, border_width=1, corner_radius=6,
            text_color=TXT_PRI, placeholder_text="Nombre o apellido..."
        )
        self.entry_search.pack(side="left", fill="x", expand=True)
        self.entry_search.bind("<Return>", lambda _: self._buscar())

        ctk.CTkButton(
            row_search, text="🔍", width=34, height=34,
            fg_color=BG_HOVER, hover_color=BORDER,
            text_color=TXT_SEC, corner_radius=6,
            command=self._buscar
        ).pack(side="left", padx=(5, 0))

        # Listbox personalizado con CTkFrame + labels
        self.list_frame = ctk.CTkFrame(
            inner, fg_color=BG_CARD,
            border_color=BORDER, border_width=1, corner_radius=6
        )
        self.list_frame.pack(fill="x", pady=(6, 0))
        self._list_rows = []

        _separador(inner, pady=(12, 10))

        # ── Estadísticas ──
        self._section_label(inner, "Hoy")

        stats_row = ctk.CTkFrame(inner, fg_color="transparent")
        stats_row.pack(fill="x", pady=(4, 0))
        stats_row.columnconfigure((0, 1, 2), weight=1)

        self.lbl_presentes = self._stat_card(stats_row, "Presentes", "—", GREEN, 0)
        self.lbl_ausentes  = self._stat_card(stats_row, "Ausentes",  "—", RED,   1)
        self.lbl_tardanzas = self._stat_card(stats_row, "Tardanzas", "—", AMBER, 2)

        _separador(inner, pady=(12, 10))

        # ── Controles ──
        ctrl = ctk.CTkFrame(inner, fg_color="transparent")
        ctrl.pack(fill="x")
        ctrl.columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            ctrl, text="↻  Actualizar Stats",
            font=FONT_SMALL, fg_color=BG_HOVER, hover_color=BORDER,
            text_color=TXT_SEC, corner_radius=6, height=30,
            command=self._update_stats
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.btn_scan = ctk.CTkButton(
            ctrl, text="⏸  Pausar Scan",
            font=FONT_SMALL, fg_color="#2d2208", hover_color="#3d3010",
            text_color=AMBER, corner_radius=6, height=30,
            command=self._toggle_scan
        )
        self.btn_scan.grid(row=0, column=1, sticky="ew", padx=(4, 0))

    # ── Helpers de UI ─────────────────────────────────────── #

    def _section_label(self, parent, text: str):
        ctk.CTkLabel(
            parent, text=text.upper(),
            font=("Segoe UI", 8, "bold"),
            text_color=TXT_HINT, anchor="w"
        ).pack(anchor="w")

    def _stat_card(self, parent, label: str, val: str, color: str, col: int) -> ctk.CTkLabel:
        card = ctk.CTkFrame(
            parent, fg_color=BG_CARD,
            border_color=BORDER, border_width=1, corner_radius=8
        )
        card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 4, 0))
        lbl_val = ctk.CTkLabel(card, text=val, font=("Segoe UI", 22, "bold"), text_color=color)
        lbl_val.pack(pady=(10, 0))
        ctk.CTkLabel(card, text=label, font=FONT_LABEL, text_color=TXT_HINT).pack(pady=(0, 10))
        return lbl_val

    def _rebuild_list(self, items: list):
        """Reconstruye el listbox con los resultados de búsqueda."""
        for w in self._list_rows:
            w.destroy()
        self._list_rows.clear()

        for i, a in enumerate(items):
            txt = f"{a['apellidos']}, {a['nombres']}  —  {a['grado']}"
            row = ctk.CTkButton(
                self.list_frame, text=txt, anchor="w",
                font=FONT_SMALL, text_color=TXT_PRI,
                fg_color="transparent", hover_color=BG_HOVER,
                corner_radius=0, height=30,
                command=lambda idx=i: self._select_manual(idx)
            )
            row.pack(fill="x")
            if i < len(items) - 1:
                ctk.CTkFrame(self.list_frame, height=1, fg_color=BORDER, corner_radius=0).pack(fill="x")
            self._list_rows.append(row)

    # ──────────────────────────────── loops ─────────────── #

    def _start_camera(self):
        ok = self.camara.iniciar()
        if ok:
            self.lbl_cam_status.configure(text="●  Cámara activa — Enfoca el rostro", text_color=GREEN)
        else:
            self.lbl_cam_status.configure(text="✕  No se encontró la cámara", text_color=RED)

    def _start_loops(self):
        self._loop_video()
        self._loop_clock()
        self._loop_scan()
        self._loop_server_ping()
        self._update_stats()

    def _loop_video(self):
        frame = self.camara.obtener_frame()
        if frame is not None:
            nombre_ov = self._overlay_nombre if time.time() < self._overlay_expira else None
            frame_disp = self.detector.detectar_y_dibujar(
                frame, color=self._overlay_color, nombre_overlay=nombre_ov
            )
            frame_rgb = cv2.cvtColor(frame_disp, cv2.COLOR_BGR2RGB)
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            if cw > 10 and ch > 10:
                img = Image.fromarray(frame_rgb).resize((cw, ch), Image.LANCZOS)
                self._photo = ImageTk.PhotoImage(img)
                self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        self.root.after(33, self._loop_video)

    def _loop_clock(self):
        self.lbl_clock.configure(text=datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._loop_clock)

    def _loop_scan(self):
        if self._scan_activo and self.camara.activa and self.camara.debe_escanear():
            frame = self.camara.obtener_frame()
            if frame is not None and self.detector.hay_rostros(frame):
                threading.Thread(
                    target=self._scan_bg, args=(frame,), daemon=True
                ).start()
        self.root.after(200, self._loop_scan)

    def _loop_server_ping(self):
        def _check():
            ok = self.api.ping()
            txt   = "  ●  Online"  if ok else "  ●  Offline"
            color = GREEN          if ok else RED
            self.root.after(0, lambda: self.dot_server.configure(text=txt, text_color=color))
        threading.Thread(target=_check, daemon=True).start()
        self.root.after(30_000, self._loop_server_ping)

    # ──────────────────────────────── scan ──────────────── #

    def _scan_bg(self, frame):
        try:
            _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            resultado = self.api.enviar_scan(
                frame_bytes=jpeg.tobytes(), cliente_id=self.ip_cliente
            )
            self.root.after(0, lambda: self._handle_scan_result(resultado))
        except APIError as e:
            logger.warning("Error de scan: %s", e)
        except Exception as e:
            logger.error("Error inesperado: %s", e)

    def _handle_scan_result(self, res: Dict):
        if not res.get("reconocido"):
            return

        alumno = res.get("alumno", {})
        nombre = f"{alumno.get('apellidos', '')}, {alumno.get('nombres', '')}"

        if res.get("requiere_popup"):
            self._scan_activo = False
            def on_dec(d):
                self._scan_activo = True
                if d != "IGNORAR":
                    self._force_rescan(d, alumno.get("id"))
            PopupReescaneo(self.root, res.get("popup_mensaje", "Re-escaneo detectado"), on_dec)
            return

        asistencia  = res.get("asistencia", {})
        tipo_evento = asistencia.get("tipo_evento", "ENTRADA")
        estado      = asistencia.get("estado", "PRESENTE")

        if tipo_evento == "ENTRADA":
            color_ev = AMBER if estado == "TARDANZA" else GREEN
            txt_ev   = f"{'⏰' if estado == 'TARDANZA' else '✓'}  {tipo_evento} — {estado}"
        else:
            color_ev = RED
            txt_ev   = f"✕  {tipo_evento}"

        hora_ev = ""
        if asistencia.get("fecha"):
            try:
                dt = datetime.fromisoformat(asistencia["fecha"].replace("Z", ""))
                hora_ev = dt.strftime("%H:%M:%S")
            except Exception:
                pass

        self.lbl_name.configure(text=nombre[:32])
        self.lbl_grade.configure(text=f"{alumno.get('grado', '')} — {alumno.get('turno', '')}")
        self.lbl_event.configure(text=txt_ev, text_color=color_ev)
        self.lbl_event_time.configure(text=hora_ev)

        self._overlay_nombre = nombre.split(",")[0][:15]
        self._overlay_color  = (0, 200, 80)  if tipo_evento == "ENTRADA" else (248, 81, 73)
        self._overlay_expira = time.time() + 3.0

        self._update_stats()

    def _force_rescan(self, tipo: str, alumno_id: int):
        frame = self.camara.obtener_frame()
        if frame is None:
            return
        def _send():
            try:
                _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                res = self.api.enviar_scan(
                    frame_bytes=jpeg.tobytes(), cliente_id=self.ip_cliente,
                    tipo_forzado=tipo,
                )
                self.root.after(0, lambda: self._handle_scan_result(res))
            except Exception as e:
                logger.error("Error reenvío forzado: %s", e)
        threading.Thread(target=_send, daemon=True).start()

    # ──────────────────────────────── búsqueda ──────────── #

    def _buscar(self):
        term = self.entry_search.get().strip()
        if not term:
            return
        self._rebuild_list([{"apellidos": "Buscando...", "nombres": "", "grado": "", "id": -1}])

        def _search():
            try:
                res = self.api.buscar_alumno(term)
                self.root.after(0, lambda: self._show_search_results(res))
            except APIError as e:
                logger.error("Búsqueda: %s", e)

        threading.Thread(target=_search, daemon=True).start()

    def _show_search_results(self, resultados: list):
        self._resultados_busqueda = resultados
        if not resultados:
            self._rebuild_list([{"apellidos": "Sin resultados", "nombres": "", "grado": "", "id": -1}])
            return
        self._rebuild_list(resultados)

    def _select_manual(self, idx: int):
        if idx < 0 or idx >= len(self._resultados_busqueda):
            return
        alumno = self._resultados_busqueda[idx]
        nombre = f"{alumno['apellidos']}, {alumno['nombres']}"

        tipo = simpledialog.askstring(
            "Registro Manual",
            f"¿Qué registrar para {nombre}?\n\nEscribir: ENTRADA o SALIDA",
            parent=self.root,
        )
        if not tipo or tipo.upper() not in ["ENTRADA", "SALIDA"]:
            return

        tipo_up = tipo.upper()

        def _send():
            try:
                self.api.registrar_manual(
                    alumno_id=alumno["id"],
                    tipo_evento=tipo_up,
                    notas=f"Manual — portero {self.usuario.get('username', '')}",
                )
                self.root.after(0, lambda: (
                    messagebox.showinfo("Registro exitoso", f"{tipo_up} registrada para {nombre}"),
                    self._overlay_manual(nombre, tipo_up),
                    self._update_stats(),
                ))
            except APIError as e:
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))

        threading.Thread(target=_send, daemon=True).start()

    def _overlay_manual(self, nombre: str, tipo: str):
        color = GREEN if tipo == "ENTRADA" else RED
        self.lbl_name.configure(text=nombre[:32])
        self.lbl_grade.configure(text="Registro manual")
        txt = f"{'✓' if tipo == 'ENTRADA' else '✕'}  {tipo} — MANUAL"
        self.lbl_event.configure(text=txt, text_color=color)
        self.lbl_event_time.configure(text=datetime.now().strftime("%H:%M:%S"))
        self._overlay_nombre = nombre.split(",")[0][:15]
        self._overlay_color  = (0, 200, 80) if tipo == "ENTRADA" else (248, 81, 73)
        self._overlay_expira = time.time() + 3.0

    # ──────────────────────────────── stats ─────────────── #

    def _update_stats(self):
        def _get():
            try:
                rep = self.api.reporte_diario()
                self.root.after(0, lambda: (
                    self.lbl_presentes.configure(text=str(rep.get("presentes", "—"))),
                    self.lbl_ausentes.configure(text=str(rep.get("ausentes", "—"))),
                    self.lbl_tardanzas.configure(text=str(rep.get("tardanzas", "—"))),
                ))
            except Exception:
                pass
        threading.Thread(target=_get, daemon=True).start()

    # ──────────────────────────────── controles ──────────── #

    def _toggle_scan(self):
        self._scan_activo = not self._scan_activo
        if self._scan_activo:
            self.btn_scan.configure(
                text="⏸  Pausar Scan",
                fg_color="#2d2208", hover_color="#3d3010", text_color=AMBER
            )
        else:
            self.btn_scan.configure(
                text="▶  Reanudar Scan",
                fg_color="#0d2414", hover_color="#123319", text_color=GREEN
            )

    def _on_close(self):
        self.camara.detener()
        self.root.destroy()


# ─────────────────────────────────────────────────────────── #
#  Punto de entrada
# ─────────────────────────────────────────────────────────── #
def iniciar_aplicacion():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    def on_login_success(api: ColegioAPIClient, usuario: Dict):
        PorteriaApp(api, usuario)

    LoginWindow(on_login_success)


if __name__ == "__main__":
    iniciar_aplicacion()