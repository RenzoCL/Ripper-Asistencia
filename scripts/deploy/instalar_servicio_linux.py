#!/usr/bin/env python3
"""
scripts/deploy/instalar_servicio_linux.py
==========================================
Instala el servidor como servicio systemd en Linux.

El servicio:
  - Se inicia automáticamente al arrancar el servidor.
  - Se reinicia solo si crashea.
  - Escribe logs en /var/log/colegio-asistencia/.
  - Corre bajo el usuario actual (no root).

Uso:
    sudo python3 scripts/deploy/instalar_servicio_linux.py
    sudo python3 scripts/deploy/instalar_servicio_linux.py --desinstalar

Comandos útiles post-instalación:
    sudo systemctl status  colegio-asistencia
    sudo systemctl restart colegio-asistencia
    sudo journalctl -u colegio-asistencia -f   # Ver logs en vivo
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path

NOMBRE_SERVICIO = "colegio-asistencia"
DESCRIPCION     = "Colegio Asistencia — Sistema de Reconocimiento Facial"


def obtener_info() -> dict:
    """Detecta rutas del entorno actual."""
    proyecto_dir = Path(__file__).parent.parent.parent.resolve()
    
    # Detectar Python del venv si existe
    venv_python = proyecto_dir / "venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path(sys.executable)
    
    # Detectar uvicorn del venv
    venv_uvicorn = venv_python.parent / "uvicorn"
    if not venv_uvicorn.exists():
        result = subprocess.run(["which", "uvicorn"], capture_output=True, text=True)
        venv_uvicorn = Path(result.stdout.strip()) if result.returncode == 0 else Path("uvicorn")

    # Usuario actual
    usuario = os.environ.get("SUDO_USER", os.environ.get("USER", "ubuntu"))

    return {
        "proyecto_dir": proyecto_dir,
        "python":       venv_python,
        "uvicorn":      venv_uvicorn,
        "usuario":      usuario,
        "grupo":        usuario,
    }


def generar_unit_file(info: dict) -> str:
    """Genera el contenido del archivo .service de systemd."""
    return f"""[Unit]
Description={DESCRIPCION}
After=network.target
Wants=network-online.target

[Service]
Type=exec
User={info['usuario']}
Group={info['grupo']}
WorkingDirectory={info['proyecto_dir']}
Environment="PATH={info['python'].parent}:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=-{info['proyecto_dir']}/.env

ExecStart={info['uvicorn']} server.main:app \\
    --host 0.0.0.0 \\
    --port 8000 \\
    --workers 1 \\
    --log-level info \\
    --access-log

# Reiniciar automáticamente si falla (esperar 5 segundos)
Restart=on-failure
RestartSec=5s

# Tiempo máximo de inicio
TimeoutStartSec=30

# Logs
StandardOutput=journal
StandardError=journal
SyslogIdentifier={NOMBRE_SERVICIO}

[Install]
WantedBy=multi-user.target
"""


def instalar(info: dict):
    """Instala y activa el servicio systemd."""
    print(f"\n📦 Instalando servicio: {NOMBRE_SERVICIO}")
    print(f"   Proyecto: {info['proyecto_dir']}")
    print(f"   Python:   {info['python']}")
    print(f"   Usuario:  {info['usuario']}")

    unit_content = generar_unit_file(info)
    unit_path    = Path(f"/etc/systemd/system/{NOMBRE_SERVICIO}.service")

    # Escribir archivo .service
    unit_path.write_text(unit_content)
    print(f"\n✅ Archivo de servicio creado: {unit_path}")

    # Crear directorio de logs
    log_dir = Path(f"/var/log/{NOMBRE_SERVICIO}")
    log_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["chown", info["usuario"], str(log_dir)], check=True)

    # Recargar systemd y habilitar el servicio
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", NOMBRE_SERVICIO], check=True)
    subprocess.run(["systemctl", "start",  NOMBRE_SERVICIO], check=True)

    print(f"\n🚀 Servicio iniciado y habilitado para inicio automático.")
    print(f"\nComandos útiles:")
    print(f"  sudo systemctl status  {NOMBRE_SERVICIO}")
    print(f"  sudo systemctl restart {NOMBRE_SERVICIO}")
    print(f"  sudo systemctl stop    {NOMBRE_SERVICIO}")
    print(f"  sudo journalctl -u {NOMBRE_SERVICIO} -f")

    # Mostrar estado
    subprocess.run(["systemctl", "status", NOMBRE_SERVICIO, "--no-pager"])


def desinstalar():
    """Detiene y elimina el servicio systemd."""
    print(f"\n🗑️  Desinstalando servicio: {NOMBRE_SERVICIO}")

    subprocess.run(["systemctl", "stop",    NOMBRE_SERVICIO], check=False)
    subprocess.run(["systemctl", "disable", NOMBRE_SERVICIO], check=False)

    unit_path = Path(f"/etc/systemd/system/{NOMBRE_SERVICIO}.service")
    if unit_path.exists():
        unit_path.unlink()
        print(f"✅ Archivo eliminado: {unit_path}")

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    print("✅ Servicio desinstalado correctamente.")


def main():
    if os.geteuid() != 0:
        print("❌ Este script requiere permisos de superusuario.")
        print("   Ejecutar con: sudo python3 scripts/deploy/instalar_servicio_linux.py")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Gestión del servicio systemd")
    parser.add_argument("--desinstalar", action="store_true", help="Eliminar el servicio")
    args = parser.parse_args()

    if args.desinstalar:
        desinstalar()
    else:
        info = obtener_info()
        instalar(info)


if __name__ == "__main__":
    main()
