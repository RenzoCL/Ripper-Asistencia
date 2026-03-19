"""
client/ui/tutor_app.py  (CustomTkinter edition)
=================================================
Rediseño visual del panel de tutor.
Estilo: SaaS educativo profesional — claro, limpio, con sidebar lateral.

Dependencias:
    pip install customtkinter

Mantiene exactamente las mismas funcionalidades del original:
  - Login propio con verificación de servidor
  - Vista de asistencia del día (grado asignado)
  - Registro manual de entrada/salida por doble clic
  - Creación de justificaciones con formulario
  - Historial de asistencia por alumno
  - Auto-refresh cada 30 segundos
  - Reloj en tiempo real
"""

import os
import sys
import threading
import logging
from datetime import datetime
from typing import Optional, Dict, List

import customtkinter as ctk
from tkinter import messagebox, simpledialog
import tkinter as tk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from client.utils.api_client import ColegioAPIClient, APIError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Paleta — Modo claro profesional (SaaS)
# ─────────────────────────────────────────────
BG_APP     = "#f0f4f8"   # Fondo de página
BG_WHITE   = "#ffffff"   # Superficie principal
BG_SURFACE = "#f8fafc"   # Superficie secundaria (inputs, rows hover)
BG_SIDEBAR = "#ffffff"   # Sidebar

BORDER     = "#e2e8f0"   # Borde suave
BORDER2    = "#cbd5e1"   # Borde más visible

TXT_PRI    = "#1e293b"   # Texto principal
TXT_SEC    = "#64748b"   # Texto secundario
TXT_HINT   = "#94a3b8"   # Hints / labels

BLUE       = "#1e40af"   # Acento principal
BLUE_LIGHT = "#eff6ff"   # Fondo azul claro
BLUE_MID   = "#3b82f6"   # Azul medio (hover)

GREEN      = "#16a34a"
GREEN_BG   = "#dcfce7"
GREEN_TXT  = "#15803d"

RED        = "#dc2626"
RED_BG     = "#fee2e2"
RED_TXT    = "#b91c1c"

AMBER      = "#ca8a04"
AMBER_BG   = "#fef9c3"
AMBER_TXT  = "#a16207"

SALIDA_BG  = "#dbeafe"
SALIDA_TXT = "#1d4ed8"

NAV_ACTIVE_BG  = "#eff6ff"
NAV_ACTIVE_TXT = "#1e40af"
NAV_HOVER_BG   = "#f8fafc"
NAV_NORMAL_TXT = "#64748b"

FONT_TOPBAR  = ("Segoe UI", 13, "bold")
FONT_CLOCK   = ("Consolas", 20, "bold")
FONT_STAT    = ("Segoe UI", 26, "bold")
FONT_TITLE   = ("Segoe UI", 12, "bold")
FONT_NAV     = ("Segoe UI", 11, "bold")
FONT_BODY    = ("Segoe UI", 11)
FONT_SMALL   = ("Segoe UI", 10)
FONT_LABEL   = ("Segoe UI", 9)
FONT_MONO    = ("Consolas", 11)

W, H = 1050, 660

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


# ─────────────────────────────────────────────────────────── #
#  Helper: separador
# ─────────────────────────────────────────────────────────── #
def _sep(parent, orient="h", **pack_kw):
    if orient == "h":
        ctk.CTkFrame(parent, height=1, fg_color=BORDER, corner_radius=0).pack(fill="x", **pack_kw)
    else:
        ctk.CTkFrame(parent, width=1, fg_color=BORDER, corner_radius=0).pack(fill="y", **pack_kw)


# ─────────────────────────────────────────────────────────── #
#  LoginWindow (tutor)
# ─────────────────────────────────────────────────────────── #
class LoginWindow:
    """Pantalla de login limpia y profesional para el rol tutor."""

    def __init__(self, on_success):
        self.on_success = on_success
        self.api = ColegioAPIClient()

        self.root = ctk.CTk()
        self.root.title("Colegio Asistencia — Panel Tutor")
        self.root.geometry("440x460")
        self.root.configure(fg_color=BG_APP)
        self.root.resizable(False, False)
        self.root.eval("tk::PlaceWindow . center")

        self._build()
        self.root.mainloop()

    def _build(self):
        # ── Logo / título ──
        top = ctk.CTkFrame(self.root, fg_color="transparent")
        top.pack(pady=(40, 0))

        pill = ctk.CTkLabel(
            top, text="CA",
            font=("Segoe UI", 13, "bold"),
            fg_color=BLUE, text_color="#ffffff",
            corner_radius=6, width=40, height=28
        )
        pill.pack()

        ctk.CTkLabel(top, text="Panel del Tutor",
                     font=("Segoe UI", 18, "bold"), text_color=TXT_PRI).pack(pady=(10, 2))
        ctk.CTkLabel(top, text="Colegio Asistencia · Sistema de Gestión",
                     font=FONT_SMALL, text_color=TXT_HINT).pack()

        # ── Card formulario ──
        card = ctk.CTkFrame(
            self.root, fg_color=BG_WHITE,
            border_color=BORDER, border_width=1, corner_radius=10
        )
        card.pack(padx=44, pady=24, fill="x")

        ctk.CTkLabel(card, text="Usuario", font=FONT_SMALL,
                     text_color=TXT_SEC, anchor="w").pack(anchor="w", padx=20, pady=(20, 2))
        self.entry_user = ctk.CTkEntry(
            card, font=FONT_BODY, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
            text_color=TXT_PRI, placeholder_text="nombre de usuario", height=36
        )
        self.entry_user.pack(fill="x", padx=20)
        self.entry_user.focus()

        ctk.CTkLabel(card, text="Contraseña", font=FONT_SMALL,
                     text_color=TXT_SEC, anchor="w").pack(anchor="w", padx=20, pady=(12, 2))
        self.entry_pass = ctk.CTkEntry(
            card, font=FONT_BODY, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
            text_color=TXT_PRI, show="●", placeholder_text="••••••••", height=36
        )
        self.entry_pass.pack(fill="x", padx=20)

        self.lbl_status = ctk.CTkLabel(
            card, text="", font=FONT_SMALL, text_color=TXT_HINT
        )
        self.lbl_status.pack(pady=(10, 18))

        # ── Botón ──
        self.btn = ctk.CTkButton(
            self.root, text="Ingresar al sistema  →",
            font=("Segoe UI", 12, "bold"),
            fg_color=BLUE, hover_color=BLUE_MID,
            text_color="#ffffff", corner_radius=7, height=40,
            command=self._login
        )
        self.btn.pack(padx=44, fill="x")

        self.root.bind("<Return>", lambda _: self._login())
        threading.Thread(target=self._ping, daemon=True).start()

    def _ping(self):
        ok = self.api.ping()
        txt = "● Servidor disponible" if ok else "● Servidor no disponible"
        col = GREEN if ok else RED
        self.root.after(0, lambda: self.lbl_status.configure(text=txt, text_color=col))

    def _login(self):
        user = self.entry_user.get().strip()
        pwd  = self.entry_pass.get().strip()
        if not user or not pwd:
            self.lbl_status.configure(text="⚠ Completa usuario y contraseña", text_color=AMBER)
            return
        self.lbl_status.configure(text="Conectando...", text_color=TXT_HINT)
        self.root.update()
        try:
            u = self.api.login(user, pwd)
            self.root.destroy()
            self.on_success(self.api, u)
        except APIError as e:
            try:
                self.lbl_status.configure(text=f"✕ {e.detalle}", text_color=RED)
            except Exception:
                pass
        except Exception as e:
            try:
                self.lbl_status.configure(text=f"✕ Error: {e}", text_color=RED)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────── #
#  TutorApp — ventana principal
# ─────────────────────────────────────────────────────────── #
class TutorApp:
    """
    Ventana principal del tutor con sidebar de navegación lateral.
    Secciones: Asistencia Hoy | Justificaciones | Historial
    """

    SECCIONES = ["asistencia", "justificaciones", "historial"]

    def __init__(self, api: ColegioAPIClient, usuario: Dict):
        self.api     = api
        self.usuario = usuario
        self.grado   = usuario.get("grado_asignado") or ""
        self._seccion_actual = "asistencia"
        self._datos_asistencia: List[Dict] = []
        self._resultados_busqueda_just: List[Dict] = []

        self.root = ctk.CTk()
        self.root.title(f"Colegio Asistencia — Tutor: {usuario.get('nombre_display', '')}")
        self.root.geometry(f"{W}x{H}")
        self.root.configure(fg_color=BG_APP)
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

        self._build()
        self._load_initial()
        self._loop_clock()
        self._auto_refresh()

        self.root.mainloop()

    # ──────────────────────────────── layout ────────────── #

    def _build(self):
        self._build_topbar()

        body = ctk.CTkFrame(self.root, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_sidebar(body)
        self._build_content_area(body)

    # ── Topbar ──────────────────────────────────────────── #

    def _build_topbar(self):
        bar = ctk.CTkFrame(
            self.root, fg_color=BG_WHITE,
            border_color=BORDER, border_width=1,
            corner_radius=0, height=52
        )
        bar.pack(fill="x")
        bar.pack_propagate(False)

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left", padx=18)

        pill = ctk.CTkLabel(
            left, text="CA",
            font=("Segoe UI", 11, "bold"),
            fg_color=BLUE, text_color="#ffffff",
            corner_radius=5, width=32, height=22
        )
        pill.pack(side="left")

        ctk.CTkFrame(left, width=1, fg_color=BORDER, corner_radius=0).pack(
            side="left", fill="y", padx=12, pady=10
        )

        ctk.CTkLabel(
            left, text="Panel del Tutor",
            font=FONT_TOPBAR, text_color=TXT_PRI
        ).pack(side="left")

        ctk.CTkLabel(
            left, text=f"  ·  {self.grado or 'Todos los grados'}",
            font=FONT_BODY, text_color=TXT_HINT
        ).pack(side="left")

        # Derecha
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.pack(side="right", padx=18)

        self.lbl_clock = ctk.CTkLabel(
            right, text="00:00:00",
            font=FONT_CLOCK, text_color=BLUE
        )
        self.lbl_clock.pack(side="right", padx=(12, 0))

        # Avatar con iniciales
        nombre = self.usuario.get("nombre_display", "?")
        iniciales = "".join(p[0].upper() for p in nombre.split()[:2])
        ctk.CTkLabel(
            right,
            text=iniciales,
            font=("Segoe UI", 12, "bold"),
            fg_color=BLUE_LIGHT,
            text_color=BLUE,
            corner_radius=17,
            width=34, height=34,
        ).pack(side="right")

        info = ctk.CTkFrame(right, fg_color="transparent")
        info.pack(side="right", padx=(0, 10))
        ctk.CTkLabel(info, text=nombre, font=("Segoe UI", 11, "bold"),
                     text_color=TXT_PRI, anchor="e").pack(anchor="e")
        ctk.CTkLabel(info, text="Tutor de aula", font=FONT_LABEL,
                     text_color=TXT_HINT, anchor="e").pack(anchor="e")

    # ── Sidebar ──────────────────────────────────────────── #

    def _build_sidebar(self, parent):
        sb = ctk.CTkFrame(
            parent, fg_color=BG_WHITE,
            border_color=BORDER, border_width=1,
            corner_radius=0, width=195
        )
        sb.grid(row=0, column=0, sticky="nsew")
        sb.pack_propagate(False)

        # Etiqueta sección
        ctk.CTkLabel(
            sb, text="MENÚ",
            font=("Segoe UI", 8, "bold"),
            text_color=TXT_HINT
        ).pack(anchor="w", padx=16, pady=(18, 6))

        nav_items = [
            ("asistencia",      "📋  Asistencia hoy",    BLUE),
            ("justificaciones", "📄  Justificaciones",   GREEN),
            ("historial",       "📈  Historial alumno",  AMBER),
        ]

        self._nav_btns = {}
        for key, label, color in nav_items:
            btn = ctk.CTkButton(
                sb, text=label,
                font=FONT_NAV,
                anchor="w",
                fg_color=NAV_ACTIVE_BG if key == self._seccion_actual else "transparent",
                hover_color=NAV_ACTIVE_BG,
                text_color=NAV_ACTIVE_TXT if key == self._seccion_actual else NAV_NORMAL_TXT,
                corner_radius=7,
                height=36,
                command=lambda k=key: self._switch(k)
            )
            btn.pack(fill="x", padx=8, pady=2)
            self._nav_btns[key] = btn

        _sep(sb, pady=(8, 8))

        # Botón cerrar sesión al fondo
        ctk.CTkButton(
            sb, text="↩  Cerrar sesión",
            font=FONT_SMALL,
            anchor="w",
            fg_color="transparent",
            hover_color="#fee2e2",
            text_color=RED,
            corner_radius=7,
            height=34,
            command=self.root.destroy
        ).pack(fill="x", padx=8, side="bottom", pady=(0, 12))

    # ── Área de contenido ─────────────────────────────────── #

    def _build_content_area(self, parent):
        self._content = ctk.CTkFrame(parent, fg_color=BG_APP, corner_radius=0)
        self._content.grid(row=0, column=1, sticky="nsew")

        self._frames: Dict[str, ctk.CTkFrame] = {}
        for s in self.SECCIONES:
            f = ctk.CTkFrame(self._content, fg_color=BG_APP, corner_radius=0)
            f.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._frames[s] = f

        self._build_asistencia(self._frames["asistencia"])
        self._build_justificaciones(self._frames["justificaciones"])
        self._build_historial(self._frames["historial"])

        self._frames["asistencia"].lift()

    def _switch(self, key: str):
        self._seccion_actual = key
        for k, btn in self._nav_btns.items():
            if k == key:
                btn.configure(fg_color=NAV_ACTIVE_BG, text_color=NAV_ACTIVE_TXT)
            else:
                btn.configure(fg_color="transparent", text_color=NAV_NORMAL_TXT)
        self._frames[key].lift()

    # ================================================================== #
    #  SECCIÓN 1 — ASISTENCIA HOY
    # ================================================================== #

    def _build_asistencia(self, parent):
        # ── Fila de stats ──
        stats_row = ctk.CTkFrame(parent, fg_color="transparent")
        stats_row.pack(fill="x", padx=16, pady=(16, 0))
        stats_row.columnconfigure((0, 1, 2, 3), weight=1)

        self.stat_total    = self._stat_card(stats_row, "Total alumnos", "—", BLUE,  0)
        self.stat_pres     = self._stat_card(stats_row, "Presentes",     "—", GREEN, 1)
        self.stat_aus      = self._stat_card(stats_row, "Ausentes",      "—", RED,   2)
        self.stat_tard     = self._stat_card(stats_row, "Tardanzas",     "—", AMBER, 3)

        # ── Tabla card ──
        card = ctk.CTkFrame(
            parent, fg_color=BG_WHITE,
            border_color=BORDER, border_width=1, corner_radius=9
        )
        card.pack(fill="both", expand=True, padx=16, pady=12)

        # Header de la tabla
        hdr = ctk.CTkFrame(card, fg_color=BG_WHITE, corner_radius=0, height=46)
        hdr.pack(fill="x", padx=0)
        hdr.pack_propagate(False)

        self.lbl_fecha_asist = ctk.CTkLabel(
            hdr, text="Lista de asistencia",
            font=FONT_TITLE, text_color=TXT_PRI
        )
        self.lbl_fecha_asist.pack(side="left", padx=16)

        ctk.CTkButton(
            hdr, text="↻  Actualizar",
            font=FONT_SMALL, fg_color=BLUE, hover_color=BLUE_MID,
            text_color="#ffffff", corner_radius=6, height=30, width=110,
            command=self._load_asistencia
        ).pack(side="right", padx=12)

        self.entry_buscar_asist = ctk.CTkEntry(
            hdr, font=FONT_SMALL, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
            text_color=TXT_PRI, placeholder_text="Filtrar alumno...",
            height=30, width=160
        )
        self.entry_buscar_asist.pack(side="right", padx=(0, 8))
        self.entry_buscar_asist.bind("<KeyRelease>", lambda _: self._filtrar_tabla())

        _sep(card)

        # Encabezado de columnas
        col_hdr = ctk.CTkFrame(card, fg_color=BG_SURFACE, corner_radius=0, height=30)
        col_hdr.pack(fill="x")
        col_hdr.pack_propagate(False)
        for txt, w in [("Alumno", 260), ("Grado", 80), ("Hora entrada", 110), ("Estado", 110), ("Acciones", 120)]:
            ctk.CTkLabel(col_hdr, text=txt.upper(), font=("Segoe UI", 9, "bold"),
                         text_color=TXT_HINT, width=w, anchor="w").pack(side="left", padx=(10 if txt=="Alumno" else 4, 0))

        _sep(card)

        # Área scrollable de filas
        self.scroll_asist = ctk.CTkScrollableFrame(
            card, fg_color=BG_WHITE, corner_radius=0,
            scrollbar_button_color=BORDER
        )
        self.scroll_asist.pack(fill="both", expand=True)

        self._filas_asist: List[ctk.CTkFrame] = []

    def _stat_card(self, parent, label: str, val: str, color: str, col: int) -> ctk.CTkLabel:
        card = ctk.CTkFrame(
            parent, fg_color=BG_WHITE,
            border_color=BORDER, border_width=1, corner_radius=9
        )
        card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0))
        lbl = ctk.CTkLabel(card, text=val, font=FONT_STAT, text_color=color)
        lbl.pack(pady=(14, 2))
        ctk.CTkLabel(card, text=label.upper(), font=("Segoe UI", 9),
                     text_color=TXT_HINT).pack(pady=(0, 12))
        return lbl

    def _render_fila(self, alumno_nombre: str, grado: str, hora: str,
                     estado: str, registro_id: int, alumno_id: int):
        """Crea una fila de la tabla de asistencia."""
        fila = ctk.CTkFrame(
            self.scroll_asist, fg_color=BG_WHITE,
            corner_radius=0, height=44
        )
        fila.pack(fill="x")
        fila.pack_propagate(False)

        # Nombre
        ctk.CTkLabel(fila, text=alumno_nombre, font=("Segoe UI", 11, "bold"),
                     text_color=TXT_PRI, width=260, anchor="w").pack(side="left", padx=(10, 0))

        # Grado
        ctk.CTkLabel(fila, text=grado, font=FONT_BODY,
                     text_color=TXT_SEC, width=80, anchor="w").pack(side="left", padx=4)

        # Hora
        ctk.CTkLabel(fila, text=hora if hora else "—", font=FONT_MONO,
                     text_color=TXT_SEC if hora else TXT_HINT, width=110, anchor="w").pack(side="left", padx=4)

        # Badge de estado
        badge_cfg = {
            "PRESENTE":  (GREEN_BG,   GREEN_TXT,  "Presente"),
            "TARDANZA":  (AMBER_BG,   AMBER_TXT,  "Tardanza"),
            "AUSENTE":   (RED_BG,     RED_TXT,    "Ausente"),
            "SALIDA":    (SALIDA_BG,  SALIDA_TXT, "Salida"),
        }
        bg, fg, txt_badge = badge_cfg.get(estado.upper(), (BG_SURFACE, TXT_SEC, estado))
        ctk.CTkLabel(
            fila, text=txt_badge, font=("Segoe UI", 10, "bold"),
            fg_color=bg, text_color=fg,
            corner_radius=20, width=90, height=22
        ).pack(side="left", padx=4)

        # Botón de acción
        if estado.upper() == "AUSENTE":
            btn_txt = "Justificar"
            btn_cmd = lambda aid=alumno_id, n=alumno_nombre: self._quick_justify(aid, n)
            btn_col = AMBER
        else:
            btn_txt = "Registrar"
            btn_cmd = lambda aid=alumno_id, n=alumno_nombre: self._quick_register(aid, n)
            btn_col = BLUE

        ctk.CTkButton(
            fila, text=btn_txt,
            font=("Segoe UI", 10, "bold"),
            fg_color=BLUE_LIGHT, hover_color="#dbeafe",
            text_color=BLUE if btn_col == BLUE else AMBER,
            corner_radius=5, height=26, width=90,
            command=btn_cmd
        ).pack(side="left", padx=4)

        _sep(fila.master)  # línea separadora entre filas — se coloca en el padre (scroll)
        self._filas_asist.append(fila)

    def _filtrar_tabla(self):
        termino = self.entry_buscar_asist.get().strip().lower()
        for fila in self.scroll_asist.winfo_children():
            fila.pack_forget()
        for fila in self.scroll_asist.winfo_children():
            fila.pack(fill="x")

        # Recargar solo los datos ya cargados filtrados
        self._render_asistencia(
            [r for r in self._datos_asistencia
             if termino in r.get("nombre", "").lower()]
        )

    def _quick_register(self, alumno_id: int, nombre: str):
        tipo = simpledialog.askstring(
            "Registro rápido",
            f"Registrar para: {nombre}\n\nEscribir ENTRADA o SALIDA:",
            parent=self.root
        )
        if tipo and tipo.upper() in ["ENTRADA", "SALIDA"]:
            def _send():
                try:
                    self.api._post("/api/asistencia/manual", json={
                        "alumno_id": alumno_id,
                        "tipo_evento": tipo.upper(),
                        "notas": f"Registro manual tutor {self.usuario.get('username', '')}",
                    })
                    self.root.after(0, lambda: (
                        messagebox.showinfo("✓ Registrado", f"{tipo.upper()} guardada para {nombre}"),
                        self._load_asistencia()
                    ))
                except APIError as e:
                    self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            threading.Thread(target=_send, daemon=True).start()

    def _quick_justify(self, alumno_id: int, nombre: str):
        motivo = simpledialog.askstring(
            "Justificar ausencia",
            f"Motivo de ausencia para:\n{nombre}",
            parent=self.root
        )
        if motivo:
            def _send():
                try:
                    self.api._post("/api/justificaciones/", json={
                        "alumno_id": alumno_id,
                        "fecha_ausencia": datetime.now().strftime("%Y-%m-%dT00:00:00"),
                        "motivo": motivo,
                    })
                    self.root.after(0, lambda: (
                        messagebox.showinfo("✓ Guardado", "Justificación registrada"),
                        self._load_asistencia()
                    ))
                except APIError as e:
                    self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            threading.Thread(target=_send, daemon=True).start()

    # ================================================================== #
    #  SECCIÓN 2 — JUSTIFICACIONES
    # ================================================================== #

    def _build_justificaciones(self, parent):
        # ── Formulario ──
        form_card = ctk.CTkFrame(
            parent, fg_color=BG_WHITE,
            border_color=BORDER, border_width=1, corner_radius=9
        )
        form_card.pack(fill="x", padx=16, pady=(16, 0))

        ctk.CTkLabel(form_card, text="Nueva justificación",
                     font=FONT_TITLE, text_color=TXT_PRI).pack(anchor="w", padx=16, pady=(14, 10))
        _sep(form_card)

        grid = ctk.CTkFrame(form_card, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=14)
        grid.columnconfigure((0, 1, 2), weight=1)

        # ID alumno
        ctk.CTkLabel(grid, text="ID del alumno", font=FONT_SMALL,
                     text_color=TXT_SEC, anchor="w").grid(row=0, column=0, sticky="w")
        self.entry_just_id = ctk.CTkEntry(
            grid, font=FONT_BODY, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
            text_color=TXT_PRI, placeholder_text="ej. 42", height=34
        )
        self.entry_just_id.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(2, 0))

        # Fecha
        ctk.CTkLabel(grid, text="Fecha de ausencia", font=FONT_SMALL,
                     text_color=TXT_SEC, anchor="w").grid(row=0, column=1, sticky="w")
        self.entry_just_fecha = ctk.CTkEntry(
            grid, font=FONT_BODY, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
            text_color=TXT_PRI, height=34
        )
        self.entry_just_fecha.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.entry_just_fecha.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(2, 0))

        # Botón guardar (label spacer invisible — mismo color que fondo)
        ctk.CTkLabel(grid, text="", font=FONT_SMALL, text_color=BG_WHITE, fg_color="transparent").grid(row=0, column=2)
        ctk.CTkButton(
            grid, text="Guardar justificación",
            font=("Segoe UI", 11, "bold"),
            fg_color=GREEN, hover_color="#15803d",
            text_color="#ffffff", corner_radius=6, height=34,
            command=self._crear_justificacion
        ).grid(row=1, column=2, sticky="ew", pady=(2, 0))

        # Motivo (fila completa)
        ctk.CTkLabel(grid, text="Motivo de la ausencia", font=FONT_SMALL,
                     text_color=TXT_SEC, anchor="w").grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 2))
        self.entry_just_motivo = ctk.CTkEntry(
            grid, font=FONT_BODY, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
            text_color=TXT_PRI, placeholder_text="Describa el motivo de la ausencia...", height=34
        )
        self.entry_just_motivo.grid(row=3, column=0, columnspan=3, sticky="ew")

        # ── Tabla de justificaciones ──
        list_card = ctk.CTkFrame(
            parent, fg_color=BG_WHITE,
            border_color=BORDER, border_width=1, corner_radius=9
        )
        list_card.pack(fill="both", expand=True, padx=16, pady=12)

        list_hdr = ctk.CTkFrame(list_card, fg_color=BG_WHITE, corner_radius=0, height=46)
        list_hdr.pack(fill="x")
        list_hdr.pack_propagate(False)
        ctk.CTkLabel(list_hdr, text="Justificaciones registradas",
                     font=FONT_TITLE, text_color=TXT_PRI).pack(side="left", padx=16)
        ctk.CTkButton(
            list_hdr, text="↻  Actualizar",
            font=FONT_SMALL, fg_color=BLUE, hover_color=BLUE_MID,
            text_color="#ffffff", corner_radius=6, height=28, width=100,
            command=self._load_justificaciones
        ).pack(side="right", padx=12)

        _sep(list_card)

        # Encabezados columnas
        col_hdr2 = ctk.CTkFrame(list_card, fg_color=BG_SURFACE, corner_radius=0, height=28)
        col_hdr2.pack(fill="x")
        col_hdr2.pack_propagate(False)
        for txt, w in [("Alumno ID", 100), ("Fecha ausencia", 130), ("Motivo", 380), ("Registrado", 120)]:
            ctk.CTkLabel(col_hdr2, text=txt.upper(), font=("Segoe UI", 9, "bold"),
                         text_color=TXT_HINT, width=w, anchor="w").pack(side="left", padx=(12 if txt=="Alumno ID" else 4, 0))
        _sep(list_card)

        self.scroll_just = ctk.CTkScrollableFrame(
            list_card, fg_color=BG_WHITE, corner_radius=0,
            scrollbar_button_color=BORDER
        )
        self.scroll_just.pack(fill="both", expand=True)

    def _render_just_fila(self, j: Dict):
        fila = ctk.CTkFrame(self.scroll_just, fg_color=BG_WHITE, corner_radius=0, height=38)
        fila.pack(fill="x")
        fila.pack_propagate(False)

        ctk.CTkLabel(fila, text=str(j.get("alumno_id", "—")), font=FONT_BODY,
                     text_color=TXT_PRI, width=100, anchor="w").pack(side="left", padx=(12, 0))
        ctk.CTkLabel(fila, text=str(j.get("fecha_ausencia", ""))[:10], font=FONT_MONO,
                     text_color=TXT_SEC, width=130, anchor="w").pack(side="left", padx=4)
        ctk.CTkLabel(fila, text=str(j.get("motivo", ""))[:55], font=FONT_BODY,
                     text_color=TXT_PRI, width=380, anchor="w").pack(side="left", padx=4)
        ctk.CTkLabel(fila, text=str(j.get("fecha_registro", ""))[:10], font=FONT_MONO,
                     text_color=TXT_HINT, width=120, anchor="w").pack(side="left", padx=4)
        _sep(fila.master)

    # ================================================================== #
    #  SECCIÓN 3 — HISTORIAL
    # ================================================================== #

    def _build_historial(self, parent):
        # ── Buscador ──
        search_card = ctk.CTkFrame(
            parent, fg_color=BG_WHITE,
            border_color=BORDER, border_width=1, corner_radius=9
        )
        search_card.pack(fill="x", padx=16, pady=(16, 0))

        row_s = ctk.CTkFrame(search_card, fg_color="transparent")
        row_s.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(row_s, text="ID del alumno:", font=FONT_BODY,
                     text_color=TXT_SEC).pack(side="left")
        self.entry_hist_id = ctk.CTkEntry(
            row_s, font=FONT_BODY, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
            text_color=TXT_PRI, placeholder_text="ej. 15",
            height=34, width=90
        )
        self.entry_hist_id.pack(side="left", padx=(8, 16))

        ctk.CTkLabel(row_s, text="Últimos días:", font=FONT_BODY,
                     text_color=TXT_SEC).pack(side="left")
        self.entry_hist_dias = ctk.CTkEntry(
            row_s, font=FONT_BODY, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
            text_color=TXT_PRI, height=34, width=70
        )
        self.entry_hist_dias.insert(0, "30")
        self.entry_hist_dias.pack(side="left", padx=8)

        ctk.CTkButton(
            row_s, text="Ver historial",
            font=("Segoe UI", 11, "bold"),
            fg_color=BLUE, hover_color=BLUE_MID,
            text_color="#ffffff", corner_radius=6, height=34, width=130,
            command=self._load_historial
        ).pack(side="left", padx=12)

        self.lbl_hist_nombre = ctk.CTkLabel(
            row_s, text="", font=FONT_SMALL, text_color=TXT_HINT
        )
        self.lbl_hist_nombre.pack(side="left", padx=8)

        # ── Tabla historial ──
        hist_card = ctk.CTkFrame(
            parent, fg_color=BG_WHITE,
            border_color=BORDER, border_width=1, corner_radius=9
        )
        hist_card.pack(fill="both", expand=True, padx=16, pady=12)

        col_hdr3 = ctk.CTkFrame(hist_card, fg_color=BG_SURFACE, corner_radius=0, height=30)
        col_hdr3.pack(fill="x")
        col_hdr3.pack_propagate(False)
        for txt, w in [("Fecha", 110), ("Día", 90), ("Tipo", 90), ("Estado", 110), ("Hora", 80), ("Registrado por", 180)]:
            ctk.CTkLabel(col_hdr3, text=txt.upper(), font=("Segoe UI", 9, "bold"),
                         text_color=TXT_HINT, width=w, anchor="w").pack(side="left", padx=(12 if txt=="Fecha" else 4, 0))
        _sep(hist_card)

        self.scroll_hist = ctk.CTkScrollableFrame(
            hist_card, fg_color=BG_WHITE, corner_radius=0,
            scrollbar_button_color=BORDER
        )
        self.scroll_hist.pack(fill="both", expand=True)

    def _render_hist_fila(self, r: Dict):
        try:
            dt = datetime.fromisoformat(r["fecha"].replace("Z", ""))
            fecha_str = dt.strftime("%Y-%m-%d")
            dia_str   = dt.strftime("%a")
            hora_str  = dt.strftime("%H:%M")
        except Exception:
            fecha_str = dia_str = hora_str = r.get("fecha", "")[:10]

        tipo   = r.get("tipo", "")
        estado = r.get("estado", "")

        badge_cfg = {
            "ENTRADA": (GREEN_BG,  GREEN_TXT,  "Entrada"),
            "SALIDA":  (SALIDA_BG, SALIDA_TXT, "Salida"),
        }
        badge_est = {
            "PRESENTE": (GREEN_BG,  GREEN_TXT,  "Presente"),
            "TARDANZA": (AMBER_BG,  AMBER_TXT,  "Tardanza"),
            "AUSENTE":  (RED_BG,    RED_TXT,    "Ausente"),
        }

        fila = ctk.CTkFrame(self.scroll_hist, fg_color=BG_WHITE, corner_radius=0, height=38)
        fila.pack(fill="x")
        fila.pack_propagate(False)

        ctk.CTkLabel(fila, text=fecha_str, font=FONT_MONO, text_color=TXT_PRI,
                     width=110, anchor="w").pack(side="left", padx=(12, 0))
        ctk.CTkLabel(fila, text=dia_str, font=FONT_BODY, text_color=TXT_SEC,
                     width=90, anchor="w").pack(side="left", padx=4)

        # Badge tipo
        tbg, tfg, tlbl = badge_cfg.get(tipo.upper(), (BG_SURFACE, TXT_SEC, tipo))
        ctk.CTkLabel(fila, text=tlbl, font=("Segoe UI", 10, "bold"),
                     fg_color=tbg, text_color=tfg,
                     corner_radius=20, width=78, height=22).pack(side="left", padx=4)

        # Badge estado
        ebg, efg, elbl = badge_est.get(estado.upper(), (BG_SURFACE, TXT_SEC, estado))
        ctk.CTkLabel(fila, text=elbl, font=("Segoe UI", 10, "bold"),
                     fg_color=ebg, text_color=efg,
                     corner_radius=20, width=90, height=22).pack(side="left", padx=4)

        ctk.CTkLabel(fila, text=hora_str, font=FONT_MONO, text_color=TXT_SEC,
                     width=80, anchor="w").pack(side="left", padx=4)
        ctk.CTkLabel(fila, text=r.get("registrado_por", "—"), font=FONT_BODY,
                     text_color=TXT_HINT, width=180, anchor="w").pack(side="left", padx=4)

        _sep(fila.master)

    # ================================================================== #
    #  CARGA DE DATOS
    # ================================================================== #

    def _load_initial(self):
        self._load_asistencia()
        self._load_justificaciones()

    def _load_asistencia(self):
        def fetch():
            try:
                data    = self.api._get("/api/asistencia/hoy")
                alumnos = self.api._get("/api/alumnos/?limit=200")
                ids_grado = {
                    a["id"] for a in (alumnos or [])
                    if not self.grado or (a["grado"] + a["seccion"]) == self.grado
                }
                filtrados = [r for r in (data or []) if r.get("alumno_id") in ids_grado]
                self.root.after(0, lambda: self._render_asistencia(filtrados))
            except Exception as e:
                logger.error("Error cargando asistencia: %s", e)

        threading.Thread(target=fetch, daemon=True).start()

    def _render_asistencia(self, registros: List[Dict]):
        self._datos_asistencia = registros

        # Limpiar filas anteriores
        for w in self.scroll_asist.winfo_children():
            w.destroy()
        self._filas_asist.clear()

        presentes = sum(1 for r in registros if r.get("tipo_evento") == "ENTRADA")
        tardanzas = sum(1 for r in registros if r.get("estado") == "TARDANZA")
        ausentes  = sum(1 for r in registros if r.get("tipo_evento") == "AUSENTE" or not r.get("tipo_evento"))

        self.stat_total.configure(text=str(len(registros)))
        self.stat_pres.configure(text=str(presentes))
        self.stat_aus.configure(text=str(ausentes))
        self.stat_tard.configure(text=str(tardanzas))

        fecha_hoy = datetime.now().strftime("%A %d %b %Y")
        self.lbl_fecha_asist.configure(text=f"Asistencia — {fecha_hoy}")

        for r in registros:
            hora = ""
            if r.get("fecha"):
                try:
                    dt = datetime.fromisoformat(r["fecha"].replace("Z", ""))
                    hora = dt.strftime("%H:%M")
                except Exception:
                    pass
            self._render_fila(
                alumno_nombre=r.get("nombre", "—"),
                grado=r.get("grado", ""),
                hora=hora,
                estado=r.get("estado", r.get("tipo_evento", "—")),
                registro_id=r.get("id", 0),
                alumno_id=r.get("alumno_id", 0),
            )

    def _load_justificaciones(self):
        def fetch():
            try:
                data = self.api._get("/api/justificaciones/?limit=60")
                self.root.after(0, lambda: self._render_justificaciones(data or []))
            except Exception as e:
                logger.error("Error cargando justificaciones: %s", e)

        threading.Thread(target=fetch, daemon=True).start()

    def _render_justificaciones(self, data: List[Dict]):
        for w in self.scroll_just.winfo_children():
            w.destroy()
        for j in data:
            self._render_just_fila(j)

    def _crear_justificacion(self):
        alumno_id = self.entry_just_id.get().strip()
        fecha     = self.entry_just_fecha.get().strip()
        motivo    = self.entry_just_motivo.get().strip()

        if not alumno_id or not fecha or not motivo:
            messagebox.showwarning("Campos requeridos", "Completa todos los campos.", parent=self.root)
            return

        def _send():
            try:
                self.api._post("/api/justificaciones/", json={
                    "alumno_id": int(alumno_id),
                    "fecha_ausencia": f"{fecha}T00:00:00",
                    "motivo": motivo,
                })
                self.root.after(0, lambda: (
                    messagebox.showinfo("✓ Guardado", "Justificación registrada exitosamente."),
                    self.entry_just_id.delete(0, "end"),
                    self.entry_just_motivo.delete(0, "end"),
                    self._load_justificaciones(),
                ))
            except APIError as e:
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))

        threading.Thread(target=_send, daemon=True).start()

    def _load_historial(self):
        alumno_id = self.entry_hist_id.get().strip()
        dias      = self.entry_hist_dias.get().strip() or "30"
        if not alumno_id:
            messagebox.showwarning("", "Ingresa el ID del alumno.", parent=self.root)
            return

        def fetch():
            try:
                data = self.api._get(f"/api/admin/reportes/historial/{alumno_id}?dias={dias}")
                self.root.after(0, lambda: self._render_historial(data))
            except APIError as e:
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))

        threading.Thread(target=fetch, daemon=True).start()

    def _render_historial(self, data: Dict):
        for w in self.scroll_hist.winfo_children():
            w.destroy()
        if not data:
            return

        nombre  = data.get("alumno", "")
        grado   = data.get("grado", "")
        total   = data.get("total_registros", 0)
        self.lbl_hist_nombre.configure(
            text=f"{nombre}  ·  {grado}  ·  {total} registros",
            text_color=BLUE
        )

        for r in data.get("registros", []):
            self._render_hist_fila(r)

    # ================================================================== #
    #  LOOPS
    # ================================================================== #

    def _loop_clock(self):
        self.lbl_clock.configure(text=datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._loop_clock)

    def _auto_refresh(self):
        self._load_asistencia()
        self.root.after(30_000, self._auto_refresh)


# ─────────────────────────────────────────────────────────── #
#  Punto de entrada
# ─────────────────────────────────────────────────────────── #
def iniciar_tutor():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    def on_success(api: ColegioAPIClient, usuario: Dict):
        TutorApp(api, usuario)

    LoginWindow(on_success)


if __name__ == "__main__":
    iniciar_tutor()