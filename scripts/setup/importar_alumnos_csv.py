"""
scripts/setup/importar_alumnos_csv.py
=======================================
Importación masiva de alumnos desde un archivo CSV.

Formato esperado del CSV (con encabezados):
    codigo,nombres,apellidos,grado,seccion,turno,nombre_tutor,telefono_tutor,whatsapp_tutor

Ejemplo de fila:
    2024001,Juan Carlos,Pérez Gómez,3,A,MAÑANA,María Gómez,51987654321,51987654321

Uso:
    python scripts/setup/importar_alumnos_csv.py --archivo alumnos.csv
    python scripts/setup/importar_alumnos_csv.py --archivo alumnos.csv --dry-run

Flags:
    --archivo   : Ruta al archivo CSV (obligatorio)
    --dry-run   : Solo valida el CSV sin guardar en DB
    --actualizar: Si el código ya existe, actualiza los datos
    --separador : Separador del CSV (default: coma)
"""

import sys
import os
import csv
import argparse
from pathlib import Path
from typing import List, Dict, Tuple

# Agregar raíz del proyecto al path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from server.db.database import SessionLocal, engine, Base
from server.db import models

# ------------------------------------------------------------------ #
# Columnas requeridas y opcionales
# ------------------------------------------------------------------ #
COLUMNAS_REQUERIDAS = ["codigo", "nombres", "apellidos", "grado", "seccion", "turno"]
COLUMNAS_OPCIONALES = ["nombre_tutor", "telefono_tutor", "whatsapp_tutor", "email_tutor"]
TURNOS_VALIDOS      = {"MAÑANA", "TARDE", "NOCHE"}


def validar_fila(fila: Dict, numero: int) -> List[str]:
    """Valida una fila del CSV y retorna lista de errores (vacía si es válida)."""
    errores = []

    # Verificar campos requeridos
    for col in COLUMNAS_REQUERIDAS:
        if not fila.get(col, "").strip():
            errores.append(f"Fila {numero}: Campo '{col}' vacío o faltante")

    # Validar turno
    turno = fila.get("turno", "").upper()
    if turno and turno not in TURNOS_VALIDOS:
        errores.append(f"Fila {numero}: Turno inválido '{turno}'. Use: {TURNOS_VALIDOS}")

    # Validar código: solo alfanumérico
    codigo = fila.get("codigo", "").strip()
    if codigo and not codigo.replace("-", "").isalnum():
        errores.append(f"Fila {numero}: Código '{codigo}' contiene caracteres inválidos")

    return errores


def importar_csv(
    archivo: str,
    dry_run: bool = False,
    actualizar: bool = False,
    separador: str = ",",
) -> Tuple[int, int, int, List[str]]:
    """
    Importa alumnos desde un CSV a la base de datos.

    Returns:
        Tuple: (insertados, actualizados, errores_count, lista_errores)
    """
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    insertados   = 0
    actualizados = 0
    errores      = []

    try:
        with open(archivo, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=separador)

            # Verificar encabezados
            if not reader.fieldnames:
                print("❌ El archivo CSV está vacío o no tiene encabezados")
                return 0, 0, 1, ["Archivo vacío"]

            campos_faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in reader.fieldnames]
            if campos_faltantes:
                msg = f"Columnas faltantes en el CSV: {campos_faltantes}"
                print(f"❌ {msg}")
                print(f"   Columnas encontradas: {list(reader.fieldnames)}")
                print(f"   Columnas requeridas:  {COLUMNAS_REQUERIDAS}")
                return 0, 0, 1, [msg]

            print(f"\n📋 Iniciando importación{'(DRY RUN — sin guardar)' if dry_run else ''}...")
            print("─" * 60)

            for numero_fila, fila in enumerate(reader, start=2):
                # Limpiar espacios en todos los valores
                fila = {k: v.strip() for k, v in fila.items() if k}

                # Validar
                errores_fila = validar_fila(fila, numero_fila)
                if errores_fila:
                    errores.extend(errores_fila)
                    for e in errores_fila:
                        print(f"   ⚠️  {e}")
                    continue

                codigo = fila["codigo"]

                if not dry_run:
                    alumno_existente = db.query(models.Alumno).filter(
                        models.Alumno.codigo == codigo
                    ).first()

                    if alumno_existente:
                        if actualizar:
                            alumno_existente.nombres   = fila["nombres"]
                            alumno_existente.apellidos = fila["apellidos"]
                            alumno_existente.grado     = fila["grado"]
                            alumno_existente.seccion   = fila["seccion"]
                            alumno_existente.turno     = fila["turno"].upper()
                            actualizados += 1
                            print(f"   🔄 Actualizado: {codigo} — {fila['apellidos']}, {fila['nombres']}")
                        else:
                            print(f"   ⏭️  Omitido (ya existe): {codigo}")
                            continue
                    else:
                        nuevo = models.Alumno(
                            codigo=codigo,
                            nombres=fila["nombres"],
                            apellidos=fila["apellidos"],
                            grado=fila["grado"],
                            seccion=fila["seccion"],
                            turno=fila["turno"].upper(),
                        )
                        db.add(nuevo)
                        db.flush()  # Para obtener el ID antes del commit

                        # Agregar contacto del tutor si existe
                        if fila.get("nombre_tutor"):
                            contacto = models.TutorContacto(
                                alumno_id=nuevo.id,
                                nombre_tutor=fila["nombre_tutor"],
                                telefono=fila.get("telefono_tutor"),
                                whatsapp=fila.get("whatsapp_tutor"),
                                email=fila.get("email_tutor"),
                            )
                            db.add(contacto)

                        insertados += 1
                        print(f"   ✅ Importado: {codigo} — {fila['apellidos']}, {fila['nombres']} ({fila['grado']}{fila['seccion']})")
                else:
                    # Dry run: solo mostrar
                    print(f"   📋 [{numero_fila}] {codigo} — {fila['apellidos']}, {fila['nombres']} ({fila['grado']}{fila['seccion']})")
                    insertados += 1  # Contar como si se insertara

            if not dry_run:
                db.commit()
                print(f"\n✅ Commit realizado en la base de datos")

    except FileNotFoundError:
        msg = f"Archivo no encontrado: {archivo}"
        print(f"❌ {msg}")
        return 0, 0, 1, [msg]
    except Exception as e:
        db.rollback()
        print(f"❌ Error durante la importación: {e}")
        return 0, 0, 1, [str(e)]
    finally:
        db.close()

    return insertados, actualizados, len(errores), errores


def main():
    parser = argparse.ArgumentParser(
        description="Importar alumnos desde CSV al sistema de asistencia"
    )
    parser.add_argument("--archivo",    required=True, help="Ruta al archivo CSV")
    parser.add_argument("--dry-run",    action="store_true", help="Validar sin guardar")
    parser.add_argument("--actualizar", action="store_true", help="Actualizar si ya existe")
    parser.add_argument("--separador",  default=",", help="Separador del CSV (default: coma)")
    args = parser.parse_args()

    print("🏫 COLEGIO ASISTENCIA — Importación de Alumnos")
    print("=" * 60)
    print(f"Archivo:    {args.archivo}")
    print(f"Modo:       {'DRY RUN (solo validar)' if args.dry_run else 'IMPORTAR'}")
    print(f"Actualizar: {'Sí' if args.actualizar else 'No'}")
    print(f"Separador:  '{args.separador}'")

    insertados, actualizados, n_errores, lista_errores = importar_csv(
        archivo=args.archivo,
        dry_run=args.dry_run,
        actualizar=args.actualizar,
        separador=args.separador,
    )

    print("\n" + "=" * 60)
    print("📊 RESUMEN")
    print("=" * 60)
    if args.dry_run:
        print(f"   ✅ Filas válidas:    {insertados}")
    else:
        print(f"   ✅ Insertados:       {insertados}")
        print(f"   🔄 Actualizados:     {actualizados}")
    print(f"   ❌ Errores:          {n_errores}")

    if lista_errores:
        print("\n⚠️  ERRORES ENCONTRADOS:")
        for e in lista_errores:
            print(f"   • {e}")

    if not args.dry_run and insertados > 0:
        print(
            f"\n💡 Próximo paso: Subir fotos y entrenar encodings para los {insertados} alumnos nuevos."
        )
        print("   POST /api/alumnos/{id}/fotos  →  Subir fotos")
        print("   POST /api/reconocimiento/entrenar/{id}  →  Generar encoding")


if __name__ == "__main__":
    main()
