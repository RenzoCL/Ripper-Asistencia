"""
scripts/deploy/instalar_servicio_windows.py
=============================================
Instala el servidor como servicio de Windows usando NSSM
(Non-Sucking Service Manager).

NSSM es gratuito y permite correr cualquier ejecutable como servicio.
Descarga: https://nssm.cc/download

El servicio:
  - Se inicia automáticamente al arrancar Windows.
  - Se reinicia solo si crashea.
  - Corre en background sin ventana de terminal.

Pre-requisitos:
  1. Descargar nssm.exe de https://nssm.cc/download
  2. Copiar nssm.exe a C:\\Windows\\System32\\ (o a la carpeta del proyecto)
  3. Ejecutar este script como Administrador:
     python scripts\\deploy\\instalar_servicio_windows.py

Uso:
    python scripts\\deploy\\instalar_servicio_windows.py
    python scripts\\deploy\\instalar_servicio_windows.py --desinstalar
    python scripts\\deploy\\instalar_servicio_windows.py --iniciar
    python scripts\\deploy\\instalar_servicio_windows.py --detener
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path

NOMBRE_SERVICIO = "ColegioAsistencia"
DESCRIPCION     = "Colegio Asistencia - Sistema de Reconocimiento Facial"


def verificar_admin():
    """Verifica que el script corre como Administrador."""
    try:
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("❌ Este script requiere permisos de Administrador.")
            print("   Clic derecho → 'Ejecutar como administrador'")
            sys.exit(1)
    except AttributeError:
        pass  # No es Windows, continuar


def encontrar_nssm() -> Path:
    """Busca nssm.exe en ubicaciones comunes."""
    buscar_en = [
        Path("nssm.exe"),                              # Carpeta actual
        Path("scripts/deploy/nssm.exe"),               # Junto a este script
        Path(r"C:\Windows\System32\nssm.exe"),
        Path(r"C:\nssm\nssm.exe"),
    ]
    for p in buscar_en:
        if p.exists():
            return p

    print("❌ nssm.exe no encontrado.")
    print("   Descargar de: https://nssm.cc/download")
    print("   Copiar nssm.exe a la carpeta del proyecto o a C:\\Windows\\System32\\")
    sys.exit(1)


def obtener_info() -> dict:
    """Detecta rutas del entorno actual."""
    proyecto_dir = Path(__file__).parent.parent.parent.resolve()

    # Detectar uvicorn del venv
    venv_uvicorn = proyecto_dir / "venv" / "Scripts" / "uvicorn.exe"
    if not venv_uvicorn.exists():
        # Buscar uvicorn en PATH
        result = subprocess.run(["where", "uvicorn"], capture_output=True, text=True, shell=True)
        if result.returncode == 0:
            venv_uvicorn = Path(result.stdout.strip().split("\n")[0])
        else:
            print("❌ uvicorn no encontrado. Ejecutar: pip install uvicorn")
            sys.exit(1)

    return {
        "proyecto_dir": proyecto_dir,
        "uvicorn":      venv_uvicorn,
        "nssm":         encontrar_nssm(),
    }


def nssm(info: dict, *args) -> subprocess.CompletedProcess:
    """Ejecuta un comando nssm."""
    cmd = [str(info["nssm"])] + list(args)
    print(f"   > {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True)


def instalar(info: dict):
    """Instala el servicio Windows con NSSM."""
    print(f"\n📦 Instalando servicio: {NOMBRE_SERVICIO}")
    print(f"   Proyecto: {info['proyecto_dir']}")
    print(f"   uvicorn:  {info['uvicorn']}")

    # Instalar servicio
    nssm(info, "install", NOMBRE_SERVICIO, str(info["uvicorn"]))

    # Argumentos de uvicorn
    args = "server.main:app --host 0.0.0.0 --port 8000 --workers 1"
    nssm(info, "set", NOMBRE_SERVICIO, "AppParameters", args)

    # Directorio de trabajo (CRÍTICO — Python necesita encontrar el módulo server)
    nssm(info, "set", NOMBRE_SERVICIO, "AppDirectory", str(info["proyecto_dir"]))

    # Descripción del servicio
    nssm(info, "set", NOMBRE_SERVICIO, "Description", DESCRIPCION)

    # Tipo de inicio: Automatic
    nssm(info, "set", NOMBRE_SERVICIO, "Start", "SERVICE_AUTO_START")

    # Reiniciar si falla (después de 5 segundos)
    nssm(info, "set", NOMBRE_SERVICIO, "AppRestartDelay", "5000")
    nssm(info, "set", NOMBRE_SERVICIO, "AppThrottle", "1500")

    # Logs
    log_dir = info["proyecto_dir"] / "server" / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    nssm(info, "set", NOMBRE_SERVICIO, "AppStdout", str(log_dir / "service_stdout.log"))
    nssm(info, "set", NOMBRE_SERVICIO, "AppStderr", str(log_dir / "service_stderr.log"))
    nssm(info, "set", NOMBRE_SERVICIO, "AppRotateFiles", "1")
    nssm(info, "set", NOMBRE_SERVICIO, "AppRotateBytes", "10485760")  # 10 MB

    # Iniciar el servicio ahora
    result = nssm(info, "start", NOMBRE_SERVICIO)

    if result.returncode == 0:
        print(f"\n✅ Servicio '{NOMBRE_SERVICIO}' instalado e iniciado.")
    else:
        print(f"\n⚠️  Servicio instalado pero no pudo iniciarse: {result.stderr}")

    print(f"\nComandos útiles:")
    print(f"  sc query {NOMBRE_SERVICIO}")
    print(f"  net start {NOMBRE_SERVICIO}")
    print(f"  net stop  {NOMBRE_SERVICIO}")
    print(f"  {info['nssm']} edit {NOMBRE_SERVICIO}   (abrir GUI de configuración)")


def desinstalar(info: dict):
    """Detiene y elimina el servicio."""
    print(f"\n🗑️  Desinstalando servicio: {NOMBRE_SERVICIO}")
    nssm(info, "stop",   NOMBRE_SERVICIO)
    nssm(info, "remove", NOMBRE_SERVICIO, "confirm")
    print(f"✅ Servicio '{NOMBRE_SERVICIO}' eliminado.")


def main():
    if sys.platform != "win32":
        print("❌ Este script es solo para Windows.")
        print("   En Linux/Mac usar: scripts/deploy/instalar_servicio_linux.py")
        sys.exit(1)

    verificar_admin()

    parser = argparse.ArgumentParser()
    parser.add_argument("--desinstalar", action="store_true")
    parser.add_argument("--iniciar",     action="store_true")
    parser.add_argument("--detener",     action="store_true")
    args = parser.parse_args()

    info = obtener_info()

    if args.desinstalar:
        desinstalar(info)
    elif args.iniciar:
        nssm(info, "start", NOMBRE_SERVICIO)
    elif args.detener:
        nssm(info, "stop",  NOMBRE_SERVICIO)
    else:
        instalar(info)


if __name__ == "__main__":
    main()
