# CONTEXTO_IA.md — Resumen Técnico para Continuidad

> **Para IAs que retoman este proyecto:**
> Lee este archivo COMPLETO antes de generar cualquier código.
> Contiene el estado final, decisiones críticas y qué queda pendiente.

---

## 📊 Estado: PROYECTO COMPLETO ✅

**Versión:** 1.0.0-rc3 | **Actualización:** Marzo 2026
**54 archivos Python/HTML/conf** | **5 suites de tests** | **44 endpoints API**

---

## 🗂️ Mapa de Archivos

```
server/
  main.py                          ← FastAPI app — 8 routers + StaticFiles /admin
  core/
    config.py                      ← Pydantic V2 Settings
    security.py                    ← JWT + bcrypt==4.0.1 + require_rol()
  db/
    database.py                    ← SQLAlchemy engine + WAL mode + get_db()
    models.py                      ← 7 tablas ORM + 5 enums
  schemas/
    schemas.py                     ← Pydantic V2: field_validator, model_validate
  services/
    attendance_service.py          ← Regla 5min + doble marcado + tardanza + notif
    scheduler.py                   ← APScheduler: 4 tareas cron automáticas
    recognition/
      recognition_service.py       ← LBPH + HOG + CNN + Factory get_recognizer()
    notifications/
      telegram_service.py          ← httpx async → Telegram Bot API
      whatsapp_service.py          ← Selenium + WhatsApp Web (opcional)
  api/routes/
    auth.py            → /api/auth/login, /api/auth/me
    alumnos.py         → CRUD + upload fotos
    reconocimiento.py  → /scan + /entrenar + /modelo + _recognizer_cache global
    admin.py           → config + usuarios + reportes + notif-logs
    justificaciones.py → CRUD + upload documento
    asistencia.py      → /manual + /hoy + /vivos + DELETE con motivo
    exportar.py        → Excel mensual/alumno + PDF diario (openpyxl + reportlab)
    websocket_scan.py  → /ws/scan (WebSocket) + /ws/status + ConnectionManager
  static/
    admin.html         ← Panel Admin SPA — Chart.js, sin framework, ~700 líneas

client/
  ui/
    porteria_app.py    ← Tkinter: login + webcam + scan + popup + búsqueda manual
    tutor_app.py       ← Tkinter: 3 pestañas (asistencia/justificaciones/historial)
  utils/
    api_client.py      ← HTTP client síncrono — todos los métodos del servidor
    camera.py          ← CameraCapture (hilo) + FaceDetectorLocal (Haar Cascade)
    ws_client.py       ← WebSocket client — alternativa baja latencia a HTTP

tests/server/
  test_auth.py           ← 10 tests: login, JWT, protección de rutas, roles
  test_attendance.py     ← 15 tests: regla 5min, doble marcado, tardanza, manual
  test_reconocimiento.py ← 20 tests: scan mock, modelos, asistencia endpoints
  test_exportar.py       ← 12 tests: Excel/PDF content-type, permisos, 501
  test_websocket.py      ← 12 tests: ping-pong, auth, scan mock, manual WS

scripts/
  setup/
    setup_inicial.py          ← Instalador: dirs + DB + usuario admin
    primer_arranque.py        ← Wizard interactivo: red + Telegram + usuarios + CSV
    importar_alumnos_csv.py   ← Importación masiva con dry-run y validación
    backup_db.py              ← Backup SQLite API-nativa + integrity check
    reentrenar_lbph.py        ← Reentrenamiento batch del modelo LBPH
    diagnostico.py            ← Diagnóstico completo del sistema pre-producción
    generar_csv_ejemplo.py    ← Genera plantilla CSV con datos de ejemplo
    init_alembic.py           ← Inicializa Alembic para migraciones
  deploy/
    instalar_servicio_linux.py  ← systemd service (auto-inicio + restart)
    instalar_servicio_windows.py← NSSM service (auto-inicio Windows)
    nginx_colegio.conf          ← nginx reverse proxy: HTTP→HTTPS + WebSocket
```

---

## 🏗️ Stack Tecnológico (versiones fijadas)

```
FastAPI==0.115.5          Uvicorn[standard]==0.32.1
SQLAlchemy==2.0.36        (SQLite nativo en Python)
Pydantic==2.10.3          pydantic-settings==2.7.0   email-validator==2.2.0
python-jose[cryptography]==3.3.0
passlib==1.7.4            bcrypt==4.0.1   ← NO actualizar: 4.1+ rompe passlib
opencv-contrib-python==4.10.0.84   ← contrib requerido por cv2.face (LBPH)
numpy==1.26.4             Pillow==11.0.0
face-recognition==1.3.0   ← instala dlib; requiere compiladores C++
httpx==0.28.1             ← cliente async Telegram + TestClient FastAPI
apscheduler==3.10.4       pytz==2024.2   ← pytz requerido para timezone nombrada
openpyxl==3.1.5           reportlab==4.2.5
selenium==4.27.1          webdriver-manager==4.0.2   (WhatsApp, opcional)
websocket-client==1.8.0   (ws_client.py, opcional)
python-multipart==0.0.18  aiofiles==24.1.0  python-dotenv==1.0.1
pytest==8.3.4             pytest-asyncio==0.24.0
```

---

## 📐 Esquema de Base de Datos (SQLite WAL mode)

```
alumno:           id PK, codigo UNIQUE, nombres, apellidos, grado, seccion,
                  turno, foto_path, encoding_path, encoding_valido BOOL, activo BOOL
tutor_contacto:   id PK, alumno_id FK, nombre_tutor, telefono, whatsapp,
                  email, notificar_entrada/salida/tardanza/ausencia BOOL
asistencia:       id PK, alumno_id FK, fecha INDEXED, tipo_evento ENUM,
                  estado ENUM, confianza FLOAT, modelo_usado ENUM,
                  cliente_id, registrado_por, notas
usuario_sistema:  id PK, username UNIQUE, password_hash, nombre_display,
                  rol ENUM, grado_asignado, activo BOOL, ultimo_login
configuracion:    id PK, clave UNIQUE INDEXED, valor TEXT, descripcion,
                  modificado_por FK → usuario_sistema
justificacion:    id PK, alumno_id FK, fecha_ausencia, motivo,
                  documento_path, registrado_por FK → usuario_sistema
notificacion_log: id PK, alumno_id FK, canal ENUM, destinatario,
                  mensaje TEXT, enviado BOOL, error_detalle, fecha_envio

Enums:
  TipoEvento:        ENTRADA | SALIDA
  EstadoAsistencia:  PRESENTE | AUSENTE | TARDANZA | JUSTIFICADO
  RolUsuario:        ADMIN | TUTOR | PORTERO
  ModeloIA:          LBPH | HOG | CNN
  CanalNotificacion: TELEGRAM | WHATSAPP | INTERNO
```

---

## ⚙️ Configuración Persistente (tabla `configuracion`)

| Clave | Default | Leído por |
|---|---|---|
| `modelo_ia_activo` | `HOG` | `reconocimiento.py` — cada scan |
| `hora_inicio_tardanza` | `08:15` | `attendance_service._calcular_estado()` |
| `hora_inicio_clases` | `08:00` | Panel Admin (display), scheduler |
| `hora_fin_clases` | `14:00` | Panel Admin (display) |
| `notificaciones_activas` | `true` | `telegram_service.notificar_evento()` |
| `nombre_colegio` | `Colegio` | Scheduler reporte semanal |

---

## 🧠 Flujo Completo del Scan Facial

```
POST /api/reconocimiento/scan  |  ws://servidor/ws/scan (type: "scan")
  │
  ├─ 1. Decodificar base64 → frame numpy BGR (OpenCV)
  ├─ 2. get_active_recognizer(db):
  │       Lee "modelo_ia_activo" de DB → compara con _recognizer_cache
  │       Si cambió: invalida caché, crea nuevo, llama cargar_encodings()
  ├─ 3. recognizer.identificar(frame) → [(alumno_id, confianza), ...]
  │       LBPH: cv2.face.LBPHFaceRecognizer.predict()
  │       HOG:  face_recognition.face_distance() con model="hog"
  │       CNN:  face_recognition.face_distance() con model="cnn"
  ├─ 4. AttendanceService.procesar_scan(db, alumno_id, confianza, ...):
  │       a. ¿Alumno activo en DB? → Si no: ScanResultado(reconocido=False)
  │       b. ¿Sin registros hoy? → tipo = ENTRADA
  │       c. ¿Tiempo desde último registro < RESCAN_THRESHOLD (5min)?
  │              Y sin tipo_forzado → ScanResultado(requiere_popup=True)
  │       d. ¿Último tipo fue ENTRADA? → tipo = SALIDA
  │       e. ¿Último tipo fue SALIDA? → tipo = ENTRADA
  │       f. _calcular_estado(): compara datetime.now().time() vs hora_inicio_tardanza
  │       g. INSERT INTO asistencia
  │       h. _get_telegram().notificar_evento(db, alumno, registro)  [fire-and-forget]
  └─ 5. Retorna ScanResultado (JSON al cliente HTTP o WS)
```

---

## ⏰ Tareas Automáticas (APScheduler `America/Lima`)

| ID | Trigger | Función | Qué hace |
|---|---|---|---|
| `ausencias_diarias` | L-V 09:30 | `tarea_notificar_ausencias()` | Detecta sin-ENTRADA → Telegram admin |
| `backup_diario` | Diario 20:00 | `tarea_backup_db()` | SQLite backup API → `/data/backups/` (30 días) |
| `limpiar_logs` | Diario 23:55 | `tarea_limpiar_logs()` | Elimina `notificacion_log` > 30 días |
| `reporte_semanal` | Lunes 06:00 | `tarea_reporte_semanal()` | Resumen semanal Telegram al admin |

Integrado en `main.py` lifespan: `configurar_scheduler()` → `scheduler.start()` → yield → `scheduler.shutdown(wait=False)`.

---

## 🔌 WebSocket `/ws/scan`

```python
# Protocolo de mensajes (JSON sobre WebSocket)
# Auth: ?token=<jwt> en la URL de conexión

# Cliente → Servidor
{"type": "ping"}
{"type": "scan",   "frame_b64": "<jpeg base64>", "cliente_id": "192.168.1.x"}
{"type": "manual", "alumno_id": 5, "tipo_evento": "ENTRADA", "notas": "..."}

# Servidor → Cliente
{"type": "pong"}
{"type": "scan_result",   "data": <ScanResultado serializado>}
{"type": "manual_result", "data": {"ok": true, "mensaje": "...", "registro_id": N}}
{"type": "error",         "detail": "mensaje de error"}
```

`ConnectionManager` en `websocket_scan.py` gestiona todas las conexiones activas y permite broadcast a todos los clientes (útil para notificaciones proactivas).

---

## 🖥️ Panel Admin Web (`/admin`)

**Un solo archivo:** `server/static/admin.html` (~700 líneas HTML+JS+CSS)
**Acceso:** `http://SERVIDOR:8000/admin`
**Auth:** JWT en `localStorage` — login propio en el HTML

Vistas disponibles: Dashboard (Chart.js donut + línea) · Asistencia Hoy · Ausentes · Alumnos (CRUD) · Usuarios · Justificaciones · Reportes mensuales · Exportar (Excel/PDF) · Configuración (selector IA 3 tarjetas) · Notificaciones log.

---

## 📤 Exportación

```
GET /api/exportar/excel/mensual?año=2025&mes=6
  → openpyxl: alumno×día, verde=P, amarillo=T, rojo=A, azul=J, gris=fin de semana

GET /api/exportar/excel/alumno/{id}?dias=30
  → openpyxl: historial cronológico del alumno

GET /api/exportar/pdf/diario?fecha=2025-06-15
  → reportlab: tabla presentes + tabla ausentes, listo para imprimir

Si librería no instalada → HTTP 501 con instrucciones
```

---

## ⚠️ Decisiones Críticas — NO Cambiar sin Razón

1. **`bcrypt==4.0.1` fijado** — bcrypt ≥4.1 rompe passlib 1.7.4 silenciosamente.
2. **`opencv-contrib-python`** — `cv2.face` solo existe en el paquete `contrib`.
3. **Pydantic V2** — usar `@field_validator` + `@classmethod`. El `@validator` de V1 lanza error.
4. **Import diferido TelegramNotifier** — `_get_telegram()` en `attendance_service.py` evita import circular.
5. **`_recognizer_cache` global** — compartido entre HTTP scan y WebSocket scan (mismo proceso). Con múltiples workers uvicorn se necesita Redis.
6. **`PopupReescaneo.grab_set()`** — pausa `_scan_activo=False` mientras el portero decide. Si se elimina, pueden entrar scans duplicados durante el popup.
7. **APScheduler necesita `pytz`** — la timezone `"America/Lima"` falla sin pytz instalado.
8. **`StaticFiles` para admin.html** — montado en `/admin`, no en `/api`. No poner prefijo API.
9. **`websocket_scan.py` lazy-import** — `get_active_recognizer` se importa dentro de la función WS para evitar import circular entre routers. No mover al nivel del módulo.

---

## 🧪 Suite de Tests (69 tests en total)

```bash
pytest tests/ -v                           # Todos los tests
pytest tests/server/test_auth.py -v        # 10 tests auth
pytest tests/server/test_attendance.py -v  # 15 tests regla 5min
pytest tests/server/test_reconocimiento.py -v  # 20 tests scan + modelos
pytest tests/server/test_exportar.py -v    # 12 tests Excel/PDF
pytest tests/server/test_websocket.py -v   # 12 tests WebSocket

# Tests con marcador específico:
pytest tests/ -v -k "cinco_min"    # Solo tests de regla 5 minutos
pytest tests/ -v -k "modelo"       # Solo tests de cambio de modelo
pytest tests/ -v --tb=short        # Traceback corto (más legible)
```

Todos los tests usan **SQLite en memoria** y **mocks** de `face_recognition`/`cv2`. No requieren servidor real, cámara, ni GPU.

---

## 🚀 Comandos de Operación

```bash
# === INSTALACIÓN (primera vez) ===
python -m venv venv && source venv/bin/activate  # (o venv\Scripts\activate en Win)
pip install cmake && pip install dlib            # Compilación dlib (5-15 min)
pip install -r requirements.txt
python scripts/setup/setup_inicial.py
python scripts/setup/primer_arranque.py         # Wizard interactivo

# === ARRANQUE ===
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload

# === ACCESOS ===
# Panel Admin:  http://SERVIDOR:8000/admin
# API Docs:     http://SERVIDOR:8000/docs
# Health:       http://SERVIDOR:8000/health

# === CLIENTES ===
python client/ui/porteria_app.py   # PC de portería (necesita webcam)
python client/ui/tutor_app.py      # PC de tutor (sin webcam)

# === DATOS ===
python scripts/setup/importar_alumnos_csv.py --archivo alumnos.csv --dry-run
python scripts/setup/importar_alumnos_csv.py --archivo alumnos.csv
python scripts/setup/reentrenar_lbph.py        # Solo si se usa LBPH
python scripts/setup/backup_db.py              # Backup manual

# === PRODUCCIÓN (como servicio) ===
sudo python3 scripts/deploy/instalar_servicio_linux.py    # Linux
python scripts/deploy/instalar_servicio_windows.py        # Windows (como Admin)
# nginx: copiar scripts/deploy/nginx_colegio.conf a /etc/nginx/sites-available/

# === TESTS ===
pytest tests/ -v
```

---

## 📋 Pendientes Opcionales (no críticos)

- ✅ **Alembic** — `scripts/setup/init_alembic.py` — migraciones controladas
- ✅ **Exportar PDF por alumno** — `GET /api/exportar/pdf/alumno/{id}` — reporte individual con estadísticas
- ✅ **Importar fotos en ZIP** — `POST /api/alumnos/fotos-zip` — carga masiva para 900 alumnos
- ✅ **Script de diagnóstico** — `scripts/setup/diagnostico.py` — verifica todo antes de producción
- ✅ **CSV de ejemplo** — `scripts/setup/generar_csv_ejemplo.py` — plantilla para importación

- **Redis** — requerido si se usan múltiples workers uvicorn (para `_recognizer_cache`)
- **PWA** — convertir `admin.html` en Progressive Web App (tablet/celular)
- **HTTPS automático** — Certbot + nginx para cert autofirmado en LAN

---

## 📞 Para la IA que retome: el proyecto está funcionalmente completo

El sistema cubre el 100% de los requisitos originales del prompt:
- ✅ Selector de modelos LBPH/HOG/CNN persistente y cambio en caliente
- ✅ Doble marcado Entrada/Salida + Regla 5 minutos con popup
- ✅ Roles Admin/Tutor/Portero con JWT
- ✅ Notificaciones Telegram async + WhatsApp Web opcional
- ✅ Red LAN cliente-servidor con HTTP y WebSocket
- ✅ Panel Admin Web completo
- ✅ Exportación Excel/PDF
- ✅ Scheduler automático (ausencias, backup, limpieza, reporte semanal)
- ✅ Despliegue como servicio Windows/Linux
- ✅ 69 tests automatizados
