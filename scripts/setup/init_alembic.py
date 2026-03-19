"""
scripts/setup/init_alembic.py
================================
Inicializa Alembic para migraciones controladas de la base de datos.

¿Por qué Alembic?
  SQLAlchemy con Base.metadata.create_all() solo CREA tablas nuevas.
  Si necesitas MODIFICAR una tabla existente (añadir columna, cambiar tipo),
  create_all() no hace nada. Alembic genera scripts SQL de migración
  que aplican cambios incrementales sin perder datos.

Cuándo necesitas esto:
  - Al agregar una columna nueva a una tabla existente
  - Al cambiar el tipo de datos de una columna
  - Al crear índices adicionales en producción
  - Cuando tienes datos reales en la DB y no puedes borrarla

Instalación:
  pip install alembic

Uso:
  # 1. Inicializar Alembic (una sola vez)
  python scripts/setup/init_alembic.py

  # 2. Crear una migración nueva (cuando cambias models.py)
  alembic revision --autogenerate -m "agregar_columna_turno_tarde"

  # 3. Aplicar migraciones pendientes
  alembic upgrade head

  # 4. Ver estado de migraciones
  alembic history
  alembic current
"""

import sys
import os
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

PROJECT_ROOT = Path(__file__).parent.parent.parent


def verificar_alembic():
    """Verifica que alembic esté instalado."""
    try:
        import alembic
        print(f"✅ alembic {alembic.__version__} instalado")
        return True
    except ImportError:
        print("❌ alembic no instalado")
        print("   Ejecutar: pip install alembic")
        return False


def inicializar():
    """Crea la estructura de archivos de Alembic."""
    alembic_dir = PROJECT_ROOT / "alembic"

    if alembic_dir.exists():
        print("ℹ️  Alembic ya está inicializado en ./alembic/")
        print("   Para crear una nueva migración:")
        print("   alembic revision --autogenerate -m 'descripcion'")
        return

    print("\n📦 Inicializando Alembic...")

    # Inicializar alembic
    os.chdir(PROJECT_ROOT)
    result = subprocess.run(
        ["alembic", "init", "alembic"],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"❌ Error: {result.stderr}")
        return

    print("✅ Directorio alembic/ creado")

    # Configurar alembic.ini
    alembic_ini = PROJECT_ROOT / "alembic.ini"
    content = alembic_ini.read_text()

    # Usar la URL de la DB desde .env
    content = content.replace(
        "sqlalchemy.url = driver://user:pass@localhost/dbname",
        "# La URL se lee dinámicamente desde .env en alembic/env.py\n"
        "sqlalchemy.url = sqlite:///./server/data/asistencia.db"
    )
    alembic_ini.write_text(content)
    print("✅ alembic.ini configurado")

    # Configurar alembic/env.py para usar los modelos del proyecto
    env_py = PROJECT_ROOT / "alembic" / "env.py"
    env_content = env_py.read_text()

    # Inyectar imports del proyecto
    header = '''import sys
import os
from pathlib import Path

# Agregar raíz del proyecto al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from server.db.database import Base
from server.db import models  # noqa: F401 — importar para registrar todos los modelos

'''
    # Reemplazar la metadata por defecto
    env_content = env_content.replace(
        "target_metadata = None",
        "target_metadata = Base.metadata"
    )

    # Agregar la URL dinámica desde .env
    env_content = env_content.replace(
        "config = context.config",
        '''config = context.config

# Leer URL de DB desde variable de entorno (sobreescribe alembic.ini)
db_url = os.getenv("DATABASE_URL", "sqlite:///./server/data/asistencia.db")
config.set_main_option("sqlalchemy.url", db_url)
'''
    )

    env_py.write_text(header + env_content)
    print("✅ alembic/env.py configurado con los modelos del proyecto")

    # Agregar alembic/ al .gitignore? No — los scripts de migración SÍ van al repo
    # Solo las versiones de SQLite no deben ir al repo (ya cubierto por *.db en .gitignore)

    print("\n✅ Alembic inicializado correctamente")
    print("\nFlujo de trabajo con Alembic:")
    print("  1. Modificar server/db/models.py")
    print("  2. alembic revision --autogenerate -m 'descripcion_del_cambio'")
    print("  3. Revisar el script generado en alembic/versions/")
    print("  4. alembic upgrade head   ← aplica la migración")
    print("  5. alembic downgrade -1   ← revertir si hay problemas")
    print("\nEstado actual:")
    print("  alembic current   ← versión aplicada en la DB")
    print("  alembic history   ← historial de migraciones")


def crear_primera_migracion():
    """Crea la migración inicial desde el estado actual de los modelos."""
    alembic_dir = PROJECT_ROOT / "alembic"
    if not alembic_dir.exists():
        print("❌ Alembic no inicializado. Ejecutar primero: python scripts/setup/init_alembic.py")
        return

    print("\n📝 Creando migración inicial...")
    os.chdir(PROJECT_ROOT)
    result = subprocess.run(
        ["alembic", "revision", "--autogenerate", "-m", "schema_inicial"],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        print("✅ Migración creada")
        print(result.stdout)
    else:
        print(f"❌ Error: {result.stderr}")
        print("   Asegurarse de que el servidor fue iniciado al menos una vez")
        print("   para crear la DB antes de ejecutar este comando")


def main():
    print("🏫 COLEGIO ASISTENCIA — Setup de Alembic")
    print("=" * 50)

    if not verificar_alembic():
        sys.exit(1)

    inicializar()

    alembic_versions = PROJECT_ROOT / "alembic" / "versions"
    if alembic_versions.exists() and not any(alembic_versions.iterdir()):
        print("\n¿Crear la migración inicial ahora? (requiere DB existente)")
        resp = input("  [s/N]: ").strip().lower()
        if resp in ("s", "si", "y", "yes"):
            crear_primera_migracion()


if __name__ == "__main__":
    main()
