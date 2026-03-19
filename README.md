# 🏫 Colegio Asistencia — Sistema de Reconocimiento Facial

> Sistema profesional de asistencia escolar para **~900 alumnos**.
> Opera en **red local (LAN)**, hardware limitado y **costo cero** de software.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/SQLite-3-lightblue.svg)](https://sqlite.org)
[![Tests](https://img.shields.io/badge/tests-69-brightgreen.svg)](#-tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📐 Arquitectura

```
                        RED LOCAL (LAN)
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │            SERVIDOR CENTRAL (PC más potente)       │  │
│  │                                                   │  │
│  │  FastAPI + APScheduler    SQLite (WAL mode)       │  │
│  │  Reconocimiento: LBPH / HOG / CNN                │  │
│  │  Panel Admin Web  (/admin)                       │  │
│  │  IP: 192.168.1.100:8000                          │  │
│  └──────────────────────┬────────────────────────────┘  │
│                          │ HTTP + WebSocket              │
│          ┌───────────────┼───────────────┐              │
│          ▼               ▼               ▼              │
│    [PC Portería]   [PC Aula 1]    [PC Aula 2]          │
│    Tkinter + Cam   Tkinter + Cam  Tkinter Tutor         │
└──────────────────────────────────────────────────────────┘
                          │
                ┌─────────┴──────────┐
                │   NOTIFICACIONES   │
                │  📱 Telegram Bot   │
                │  💬 WhatsApp Web   │
                └────────────────────┘
```

---

## ✨ Funcionalidades

| Funcionalidad | Detalle |
|---|---|
| **3 modelos de IA** | LBPH (PCs antiguas) · HOG (default) · CNN (GPU) — cambio sin reiniciar |
| **Doble marcado** | Entrada → Salida automático según último registro del día |
| **Regla 5 minutos** | Re-escaneo rápido → popup al portero con decisión manual |
| **Roles** | Admin (control total) · Tutor (su aula) · Portero (monitoreo) |
| **Panel Admin Web** | Dashboard Chart.js · CRUD · Reportes · Exportar |
| **Exportación** | Excel mensual (colores) · Excel por alumno · PDF diario imprimible |
| **Notificaciones** | Telegram async + WhatsApp Web opcional |
| **Scheduler automático** | Ausencias 09:30 · Backup 20:00 · Reporte semanal lunes |
| **WebSocket** | Alternativa baja latencia al HTTP polling para la cámara |
| **Despliegue** | Servicio systemd (Linux) · NSSM (Windows) · nginx HTTPS |

---

## 🚀 Instalación rápida

### Pre-requisitos

- Python 3.10+
- En **Windows**: [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (para compilar dlib)
- En **Linux**: `sudo apt-get install build-essential cmake libopenblas-dev python3-tk`

### Pasos

```bash
# 1. Clonar
git clone https://github.com/TU-USUARIO/colegio-asistencia.git
cd colegio-asistencia

# 2. Entorno virtual
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

# 3. Dependencias (dlib puede tardar 5-15 min en compilar)
pip install cmake
pip install dlib
pip install -r requirements.txt

# 4. Setup inicial
python scripts/setup/setup_inicial.py

# 5. Asistente de primer arranque (configura red, Telegram, usuarios)
python scripts/setup/primer_arranque.py

# 6. Iniciar servidor
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

### Accesos

| URL | Qué es |
|---|---|
| `http://IP:8000/admin` | Panel Admin Web |
| `http://IP:8000/docs` | Documentación API (Swagger) |
| `http://IP:8000/health` | Estado del servidor |

**Login inicial:** `admin` / `admin1234` — **cambiar inmediatamente**.

---

## 🤖 Modelos de Reconocimiento

| Nivel | Modelo | Requisito | RAM | Velocidad | Precisión |
|---|---|---|---|---|---|
| 1 | **LBPH** | OpenCV puro | <100 MB | ~50ms | Media |
| 2 | **HOG** ✅ | dlib (CPU) | ~200 MB | ~200ms | Alta |
| 3 | **CNN** | dlib + GPU | ~500 MB | ~30ms | Muy alta |

Cambiar desde el Panel Admin → Configuración, sin reiniciar el servidor.

---

## 🖥️ Clientes

```bash
# PC de Portería (con webcam — reconocimiento automático)
python client/ui/porteria_app.py

# PC de Tutor (sin webcam — asistencia manual + justificaciones)
python client/ui/tutor_app.py
```

En cada PC cliente crear un `.env`:
```env
SERVER_URL=http://192.168.1.100:8000
```

---

## 🧪 Tests

```bash
pytest tests/ -v              # 69 tests en total
pytest tests/ -v --tb=short   # Salida compacta
```

Todos los tests usan SQLite en memoria y mocks — no requieren servidor, cámara ni GPU.

---

## 📁 Estructura del repositorio

```
colegio-asistencia/
├── server/              Backend FastAPI
│   ├── api/routes/      8 routers (auth, alumnos, scan, admin, ...)
│   ├── services/        Lógica de negocio (asistencia, IA, Telegram, scheduler)
│   ├── db/              Modelos SQLAlchemy + engine
│   └── static/          Panel Admin Web (admin.html)
├── client/              Apps de escritorio Tkinter
│   ├── ui/              porteria_app.py + tutor_app.py
│   └── utils/           api_client.py + camera.py + ws_client.py
├── tests/               69 tests automatizados
├── scripts/
│   ├── setup/           Instalación, importación CSV, backup, wizard
│   └── deploy/          systemd, NSSM, nginx
├── requirements.txt        Servidor (dlib, FastAPI, APScheduler...)
├── requirements_cliente.txt  Cliente (solo OpenCV + requests)
├── .env.example            Plantilla de variables de entorno
├── CONTEXTO_IA.md          Documentación técnica para IAs
└── GUIA_INSTALACION_Y_PRUEBA.md  Guía paso a paso para probar el sistema
```

> **Datos privados** (`server/data/` — fotos, DB, encodings) están excluidos del repositorio por `.gitignore`.

---

## 🔒 Seguridad

- Contraseñas hasheadas con **bcrypt** (nunca texto plano)
- Autenticación **JWT** con expiración de 8 horas
- **WAL mode** SQLite para lecturas/escrituras concurrentes en LAN
- **CORS** configurable (por defecto abierto para LAN)
- Panel Admin con autenticación propia (JWT en `localStorage`)
- nginx + certificado autofirmado para **HTTPS en LAN** (opcional)

---

## 🌐 Despliegue como servicio permanente

### Linux (systemd)
```bash
sudo python3 scripts/deploy/instalar_servicio_linux.py
# Comandos: sudo systemctl {start|stop|restart|status} colegio-asistencia
```

### Windows (NSSM)
```bash
# Ejecutar como Administrador:
python scripts\deploy\instalar_servicio_windows.py
```

### nginx + HTTPS
```bash
sudo cp scripts/deploy/nginx_colegio.conf /etc/nginx/sites-available/colegio
sudo ln -s /etc/nginx/sites-available/colegio /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 📄 Licencia

MIT — ver [LICENSE](LICENSE).
