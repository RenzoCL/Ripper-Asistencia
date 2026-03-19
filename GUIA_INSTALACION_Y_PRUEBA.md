# GUIA_INSTALACION_Y_PRUEBA.md
# Guía paso a paso: Instalar y probar el sistema hasta Fase 2

> Esta guía asume que estás probando TODO en **una sola PC** (modo desarrollo).  
> Para producción en red LAN, ver la sección final.

---

## ✅ Pre-requisitos

| Requisito | Versión mínima | Cómo verificar |
|---|---|---|
| Python | 3.10 o superior | `python --version` |
| pip | Cualquiera reciente | `pip --version` |
| Git | Cualquiera | `git --version` |
| Webcam | Cualquier USB | Verificar en el administrador de dispositivos |

---

## PASO 1 — Clonar el repositorio

```bash
git clone https://github.com/TU-USUARIO/colegio-asistencia.git
cd colegio-asistencia
```

---

## PASO 2 — Crear entorno virtual

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux / Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

Verificar que el entorno está activo (debe aparecer `(venv)` en la terminal).

---

## PASO 3 — Instalar dependencias del sistema (SOLO Linux)

En Windows esto no es necesario. En Ubuntu/Debian ejecutar ANTES del pip install:

```bash
sudo apt-get update
sudo apt-get install -y \
    build-essential cmake \
    libopenblas-dev liblapack-dev \
    libx11-dev libgtk-3-dev \
    python3-dev python3-tk \
    chromium-browser
```

---

## PASO 4 — Instalar dependencias Python

### Opción A: Instalación completa (con reconocimiento facial HOG/CNN)

```bash
# Primero instalar cmake y dlib (pueden tardar 5-15 min en compilar)
pip install cmake
pip install dlib

# Luego el resto
pip install -r requirements.txt
```

### Opción B: Instalación mínima (solo LBPH, más rápido)

Si no quieres esperar la compilación de dlib:

```bash
# Instalar todo excepto face-recognition
pip install fastapi uvicorn[standard] python-multipart sqlalchemy
pip install pydantic pydantic-settings email-validator
pip install python-jose[cryptography] passlib bcrypt==4.0.1
pip install opencv-contrib-python numpy Pillow
pip install httpx python-dotenv aiofiles
pip install pytest pytest-asyncio

# face-recognition NO instalado → el sistema usará LBPH automáticamente
```

### Verificar instalación

```bash
python -c "import fastapi; print('FastAPI OK')"
python -c "import cv2; print('OpenCV OK:', cv2.__version__)"
python -c "import sqlalchemy; print('SQLAlchemy OK')"
python -c "import cv2; print('LBPH OK' if hasattr(cv2, 'face') else 'ERROR: necesitas opencv-contrib-python')"
python -c "import face_recognition; print('face_recognition OK')"  # Solo si instalaste dlib
```

---

## PASO 5 — Configurar el archivo .env

```bash
# Copiar la plantilla
cp .env.example .env
```

Abrir `.env` con cualquier editor y configurar:

```env
# Mínimo necesario para arrancar:
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
SECRET_KEY=mi_clave_secreta_cambiar_en_produccion_12345

# Si usas LBPH (sin dlib):
DEFAULT_RECOGNITION_MODEL=LBPH

# Si tienes dlib instalado:
DEFAULT_RECOGNITION_MODEL=HOG

# Telegram (opcional para las pruebas iniciales, dejar vacío):
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID_PORTERIA=
TELEGRAM_CHAT_ID_ADMIN=
```

---

## PASO 6 — Ejecutar setup inicial

```bash
python scripts/setup/setup_inicial.py
```

Deberías ver:
```
✅ Python 3.x.x
✅ Directorios creados
✅ FastAPI
✅ SQLAlchemy
✅ OpenCV
✅ Usuario admin creado (usuario: admin / contraseña: admin1234)
✅ Configuración inicial verificada
```

---

## PASO 7 — Iniciar el servidor

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

Deberías ver:
```
INFO:     🏫 Iniciando Colegio Asistencia v1.0...
INFO:     ✅ Esquema de base de datos verificado/creado
INFO:     ✅ Configuración inicial verificada
INFO:     🚀 Servidor listo para recibir conexiones
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

## PASO 8 — Probar la API con Swagger UI

Abrir en el navegador:
```
http://localhost:8000/docs
```

Verás la documentación interactiva de todos los endpoints.

---

## 🧪 PRUEBAS PASO A PASO

### Prueba 1: Verificar que el servidor responde

```bash
curl http://localhost:8000/health
```
Respuesta esperada:
```json
{"status": "ok", "timestamp": "...", "version": "1.0.0"}
```

### Prueba 2: Login con el usuario admin

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin1234"}'
```

Respuesta esperada:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "usuario": {"username": "admin", "rol": "ADMIN", ...}
}
```

Guardar el `access_token` para las siguientes pruebas.

### Prueba 3: Crear un alumno

```bash
TOKEN="pegar_aqui_el_access_token"

curl -X POST http://localhost:8000/api/alumnos/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "codigo": "2024001",
    "nombres": "Juan Carlos",
    "apellidos": "Pérez Gómez",
    "grado": "3",
    "seccion": "A",
    "turno": "MAÑANA"
  }'
```

### Prueba 4: Ver el reporte del día

```bash
curl -X GET http://localhost:8000/api/admin/reportes/diario \
  -H "Authorization: Bearer $TOKEN"
```

### Prueba 5: Ejecutar los tests automáticos

En otra terminal (con el venv activo, servidor NO necesita estar corriendo):

```bash
pytest tests/ -v
```

Resultado esperado:
```
tests/server/test_auth.py::TestLogin::test_login_exitoso_admin         PASSED
tests/server/test_auth.py::TestLogin::test_login_password_incorrecta   PASSED
tests/server/test_auth.py::TestProteccionRoles::test_admin_puede_crear_alumno  PASSED
...
tests/server/test_attendance.py::TestReglaCincoMinutos::test_rescan_en_menos_de_5min_activa_popup PASSED
...
25 passed in X.XXs
```

### Prueba 6: Probar la UI del cliente (Portería)

Con el servidor corriendo en otra terminal:

```bash
# Instalar dependencias del cliente si no están
pip install -r requirements_cliente.txt

# Ejecutar la UI
python client/ui/porteria_app.py
```

Verás la pantalla de login. Ingresar `admin` / `admin1234`.

---

## 🤖 Prueba del Reconocimiento Facial (Fase 2)

### Paso 1: Subir fotos de un alumno

```bash
# Necesitas al menos 3 fotos JPG del alumno
# Subir foto 1
curl -X POST http://localhost:8000/api/alumnos/1/fotos \
  -H "Authorization: Bearer $TOKEN" \
  -F "fotos=@foto1.jpg" \
  -F "fotos=@foto2.jpg" \
  -F "fotos=@foto3.jpg"
```

### Paso 2: Entrenar el encoding del alumno

```bash
curl -X POST http://localhost:8000/api/reconocimiento/entrenar/1 \
  -H "Authorization: Bearer $TOKEN"
```

### Paso 3: Verificar el modelo activo

```bash
curl http://localhost:8000/api/admin/config/modelo_ia_activo \
  -H "Authorization: Bearer $TOKEN"
```

### Paso 4: Probar el scan desde la UI

Con el cliente de portería abierto, el sistema escaneará automáticamente con la webcam.
Al reconocer al alumno, verás su nombre en el panel derecho y una notificación en Telegram
(si está configurado).

### Paso 5: Cambiar el modelo de IA (opcional)

```bash
# Cambiar a LBPH (para PCs antiguas)
curl -X POST http://localhost:8000/api/reconocimiento/modelo/LBPH \
  -H "Authorization: Bearer $TOKEN"

# Cambiar de vuelta a HOG (default)
curl -X POST http://localhost:8000/api/reconocimiento/modelo/HOG \
  -H "Authorization: Bearer $TOKEN"
```

---

## 📱 Configurar Telegram (Fase 2)

1. Abrir Telegram y buscar `@BotFather`
2. Enviar `/newbot` y seguir las instrucciones
3. Copiar el token que te da BotFather
4. Para obtener tu chat_id: buscar `@userinfobot` en Telegram y enviarle cualquier mensaje
5. Editar `.env`:
   ```env
   TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   TELEGRAM_CHAT_ID_PORTERIA=123456789
   TELEGRAM_CHAT_ID_ADMIN=123456789
   ```
6. Reiniciar el servidor
7. Probar:
   ```bash
   curl -X POST "http://localhost:8000/api/admin/notificaciones/test" \
     -H "Authorization: Bearer $TOKEN"
   ```

---

## 🌐 Despliegue en Red LAN (Producción)

### En el servidor (PC más potente):

```bash
# Obtener la IP local del servidor
ipconfig    # Windows
ip addr     # Linux

# Iniciar el servidor (reemplazar con la IP real)
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

### En cada PC cliente (portería/aulas):

```bash
# Crear archivo .env en la carpeta del proyecto
echo "SERVER_URL=http://192.168.1.100:8000" > .env

# Instalar solo dependencias del cliente
pip install -r requirements_cliente.txt

# Ejecutar la UI
python client/ui/porteria_app.py
```

---

## ❗ Problemas Comunes

| Error | Causa | Solución |
|---|---|---|
| `ModuleNotFoundError: cv2.face` | Tienes `opencv-python` en vez de `opencv-contrib-python` | `pip uninstall opencv-python && pip install opencv-contrib-python` |
| `ERROR: Could not build dlib` | Faltan compiladores C++ | Ver PASO 3 o usar Opción B (solo LBPH) |
| `bcrypt is not installed` | Conflicto de versión bcrypt | `pip install bcrypt==4.0.1` |
| `UNIQUE constraint failed: alumno.codigo` | El código del alumno ya existe | Usar un código diferente |
| `Connection refused` en el cliente | Servidor no está corriendo | Iniciar el servidor primero |
| `401 Unauthorized` | Token expirado (8h) | Volver a hacer login |
| `No module named 'server'` | No estás en la raíz del proyecto | `cd colegio-asistencia` primero |
| `tkinter not found` | Linux sin tkinter | `sudo apt-get install python3-tk` |
