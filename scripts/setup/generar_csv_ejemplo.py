"""
scripts/setup/generar_csv_ejemplo.py
======================================
Genera un archivo CSV de ejemplo con el formato exacto
que espera el sistema para importar alumnos.

Uso:
    python scripts/setup/generar_csv_ejemplo.py
    python scripts/setup/generar_csv_ejemplo.py --salida mi_colegio.csv
    python scripts/setup/generar_csv_ejemplo.py --alumnos 20

Luego abrir el CSV en Excel/LibreOffice, llenarlo con los datos reales
y ejecutar:
    python scripts/setup/importar_alumnos_csv.py --archivo mi_colegio.csv --dry-run
    python scripts/setup/importar_alumnos_csv.py --archivo mi_colegio.csv
"""

import csv
import argparse
import random
from pathlib import Path
from datetime import datetime

# Datos de ejemplo realistas para Perú
NOMBRES_MASCULINOS = [
    "Juan Carlos", "Luis Alberto", "Miguel Ángel", "Carlos Eduardo",
    "José Antonio", "Diego Alejandro", "Andrés Felipe", "Sebastián",
    "Rodrigo", "Mateo", "Santiago", "Joaquín", "Nicolás", "Emilio"
]
NOMBRES_FEMENINOS = [
    "María José", "Ana Lucía", "Valentina", "Sofía", "Isabella",
    "Camila", "Daniela", "Fernanda", "Gabriela", "Luciana",
    "Paola", "Andrea", "Karla", "Valeria", "Natalia"
]
APELLIDOS = [
    "García Quispe", "Rodríguez López", "Martínez Flores", "González Mamani",
    "López Huanca", "Pérez Condori", "Sánchez Ccama", "Torres Apaza",
    "Ramírez Cuti", "Flores Choque", "Díaz Mamani", "Mendoza Huayhua",
    "Castro Ccallo", "Vargas Ticona", "Rojas Calcina", "Morales Puma",
    "Jiménez Limachi", "Ortiz Calisaya", "Herrera Chura", "Medina Mamani"
]
TUTORES = [
    "Rosa Elena García", "Pedro Luis Rodríguez", "Carmen Rosa Martínez",
    "Jorge Alberto González", "Elena María López", "Ricardo José Pérez",
    "Mónica Patricia Sánchez", "Roberto Carlos Torres", "Silvia Andrea Ramírez"
]


def generar_alumnos(n: int = 10) -> list:
    """Genera n filas de alumnos de ejemplo."""
    alumnos = []
    grados = [(str(g), s) for g in range(1, 6) for s in ["A", "B", "C"]]

    for i in range(1, n + 1):
        es_hombre  = random.random() > 0.5
        nombres    = random.choice(NOMBRES_MASCULINOS if es_hombre else NOMBRES_FEMENINOS)
        apellidos  = random.choice(APELLIDOS)
        grado, sec = random.choice(grados)
        turno      = random.choice(["MAÑANA", "TARDE"])
        tutor      = random.choice(TUTORES)
        telefono   = f"51{random.randint(900_000_000, 999_999_999)}"
        codigo     = f"{datetime.now().year}{i:04d}"

        alumnos.append({
            "codigo":         codigo,
            "nombres":        nombres,
            "apellidos":      apellidos,
            "grado":          grado,
            "seccion":        sec,
            "turno":          turno,
            "nombre_tutor":   tutor,
            "telefono_tutor": telefono,
            "whatsapp_tutor": telefono,  # Mismo número para el ejemplo
            "email_tutor":    "",         # Opcional
        })

    return alumnos


def main():
    parser = argparse.ArgumentParser(
        description="Generar CSV de ejemplo para importación de alumnos"
    )
    parser.add_argument("--salida",   default="alumnos_ejemplo.csv",
                        help="Nombre del archivo de salida (default: alumnos_ejemplo.csv)")
    parser.add_argument("--alumnos",  type=int, default=10,
                        help="Número de alumnos de ejemplo (default: 10)")
    args = parser.parse_args()

    alumnos = generar_alumnos(args.alumnos)
    output  = Path(args.salida)

    campos = [
        "codigo", "nombres", "apellidos", "grado", "seccion", "turno",
        "nombre_tutor", "telefono_tutor", "whatsapp_tutor", "email_tutor"
    ]

    with open(output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(alumnos)

    print(f"\n✅ CSV generado: {output}")
    print(f"   Alumnos de ejemplo: {len(alumnos)}")
    print(f"\nCampos incluidos:")
    print(f"  {'Campo':<20} {'Obligatorio':<14} {'Descripción'}")
    print(f"  {'-'*60}")
    requeridos = {
        "codigo":         ("✅ SÍ",  "Código único del alumno (ej: 20240001)"),
        "nombres":        ("✅ SÍ",  "Nombres completos"),
        "apellidos":      ("✅ SÍ",  "Apellidos completos"),
        "grado":          ("✅ SÍ",  "Solo el número (ej: 3)"),
        "seccion":        ("✅ SÍ",  "Solo la letra (ej: A)"),
        "turno":          ("✅ SÍ",  "MAÑANA o TARDE"),
        "nombre_tutor":   ("⚪ No",  "Nombre del apoderado"),
        "telefono_tutor": ("⚪ No",  "Teléfono con código país (ej: 51987654321)"),
        "whatsapp_tutor": ("⚪ No",  "WhatsApp (puede ser igual al teléfono)"),
        "email_tutor":    ("⚪ No",  "Correo del apoderado"),
    }
    for campo, (req, desc) in requeridos.items():
        print(f"  {campo:<20} {req:<14} {desc}")

    print(f"\nPróximos pasos:")
    print(f"  1. Abrir '{output}' en Excel o LibreOffice Calc")
    print(f"  2. Reemplazar los datos de ejemplo con los datos reales")
    print(f"  3. Guardar como CSV con codificación UTF-8")
    print(f"  4. Validar (dry-run):")
    print(f"     python scripts/setup/importar_alumnos_csv.py --archivo {output} --dry-run")
    print(f"  5. Importar:")
    print(f"     python scripts/setup/importar_alumnos_csv.py --archivo {output}")


if __name__ == "__main__":
    main()
