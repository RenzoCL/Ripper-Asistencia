"""
scripts/setup/backup_db.py
===========================
Backup automático de la base de datos SQLite.

SQLite tiene una ventaja enorme: hacer backup = copiar el archivo .db.
Este script usa la API nativa de SQLite (backup API) que garantiza
consistencia incluso si el servidor está corriendo y escribiendo.

Configurar como tarea programada:
  Linux (cron):
    0 20 * * * /ruta/a/venv/bin/python /ruta/a/scripts/setup/backup_db.py

  Windows (Programador de tareas):
    Programa: python.exe
    Argumentos: C:\\ruta\\scripts\\setup\\backup_db.py

Retención:
  - Guarda los últimos 30 backups diarios automáticamente.
  - Los más antiguos se eliminan para no llenar el disco.
"""

import sys
import os
import shutil
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Configuración
DB_PATH      = Path(os.getenv("DATABASE_URL", "sqlite:///./server/data/asistencia.db").replace("sqlite:///", ""))
BACKUP_DIR   = Path("./server/data/backups")
MAX_BACKUPS  = int(os.getenv("MAX_BACKUPS", "30"))


def hacer_backup() -> Path:
    """
    Crea un backup de la DB usando la API de backup de SQLite.
    Más seguro que copiar el archivo directamente porque maneja WAL.

    Returns:
        Path al archivo de backup creado.
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base de datos no encontrada: {DB_PATH}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"asistencia_backup_{timestamp}.db"

    # Usar la API de backup de SQLite (thread-safe, consistente con WAL)
    conn_origen  = sqlite3.connect(str(DB_PATH))
    conn_backup  = sqlite3.connect(str(backup_path))

    try:
        conn_origen.backup(conn_backup, steps=100, progress=_progreso_backup)
        logger.info("Backup creado: %s (%.1f KB)", backup_path.name, backup_path.stat().st_size / 1024)
    finally:
        conn_origen.close()
        conn_backup.close()

    return backup_path


def _progreso_backup(status, remaining, total):
    """Callback de progreso durante el backup (solo en modo verbose)."""
    if total > 0 and remaining % 100 == 0:
        porcentaje = ((total - remaining) / total) * 100
        logger.debug("Backup: %.0f%% (%d/%d páginas)", porcentaje, total - remaining, total)


def limpiar_backups_antiguos():
    """
    Elimina los backups más antiguos si hay más de MAX_BACKUPS archivos.
    Mantiene los más recientes.
    """
    if not BACKUP_DIR.exists():
        return

    backups = sorted(
        BACKUP_DIR.glob("asistencia_backup_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,  # Más recientes primero
    )

    if len(backups) <= MAX_BACKUPS:
        logger.info("Backups existentes: %d (límite: %d) — nada que eliminar", len(backups), MAX_BACKUPS)
        return

    a_eliminar = backups[MAX_BACKUPS:]
    for backup in a_eliminar:
        backup.unlink()
        logger.info("Backup antiguo eliminado: %s", backup.name)

    logger.info("%d backups eliminados. Backups retenidos: %d", len(a_eliminar), MAX_BACKUPS)


def verificar_integridad(backup_path: Path) -> bool:
    """
    Verifica que el backup no esté corrupto usando PRAGMA integrity_check.
    Retorna True si la DB es válida.
    """
    try:
        conn = sqlite3.connect(str(backup_path))
        resultado = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        es_valido = resultado[0] == "ok"
        if es_valido:
            logger.info("✅ Verificación de integridad: OK")
        else:
            logger.error("❌ Verificación de integridad FALLIDA: %s", resultado[0])
        return es_valido
    except Exception as e:
        logger.error("Error verificando integridad: %s", e)
        return False


def main():
    print("🏫 COLEGIO ASISTENCIA — Backup de Base de Datos")
    print("=" * 50)
    print(f"Origen:    {DB_PATH}")
    print(f"Destino:   {BACKUP_DIR}")
    print(f"Retención: {MAX_BACKUPS} backups")
    print()

    try:
        # 1. Hacer el backup
        backup_path = hacer_backup()

        # 2. Verificar integridad
        valido = verificar_integridad(backup_path)
        if not valido:
            logger.error("El backup está corrupto. Revisar el disco o la DB de origen.")
            sys.exit(1)

        # 3. Limpiar backups antiguos
        limpiar_backups_antiguos()

        print(f"\n✅ Backup completado exitosamente: {backup_path.name}")
        print(f"   Tamaño: {backup_path.stat().st_size / 1024:.1f} KB")

    except Exception as e:
        logger.error("Error durante el backup: %s", e)
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
