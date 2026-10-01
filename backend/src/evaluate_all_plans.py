import csv
import json
import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook

# PFADE

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_DIR = BASE_DIR / "data" / "annotations" / "images"

METADATA_FILE = BASE_DIR / "data" / "annotations" / "image_metadata.json"

ANALYZE_SCRIPT = BASE_DIR / "src" / "analyze_plan.py"

EXTRACTED_DIR = BASE_DIR / "data" / "output" / "extracted"

EVALUATION_DIR = BASE_DIR / "data" / "output" / "evaluation"

LOG_DIR = EVALUATION_DIR / "logs"

CSV_FILE = EVALUATION_DIR / "pipeline_results_40.csv"

EXCEL_FILE = EVALUATION_DIR / "pipeline_results_40.xlsx"


# HILFSFUNKTIONEN


def load_metadata():

    if not METADATA_FILE.exists():
        return {}

    with open(
        METADATA_FILE,
        "r",
        encoding="utf-8",
    ) as file:

        metadata = json.load(file)

    mapping = {}

    for item in metadata:

        training_filename = item.get("training_filename")

        original_filename = item.get("original_filename")

        if training_filename:

            mapping[training_filename] = original_filename or training_filename

    return mapping


def value_found(value):

    if value is None:
        return False

    value = str(value).strip()

    return value not in {
        "",
        "None",
        "null",
    }


# MAIN


def main():

    EVALUATION_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    metadata_mapping = load_metadata()

    images = sorted(
        [
            path
            for path in INPUT_DIR.iterdir()
            if path.suffix.lower()
            in {
                ".png",
                ".jpg",
                ".jpeg",
                ".tif",
                ".tiff",
            }
        ]
    )

    print()
    print("========================================")
    print("EVALUATION ALLER PLÄNE")
    print("========================================")

    print(f"\nGefundene Pläne: {len(images)}")

    results = []

    station_count = 0
    line_count = 0
    plan_number_count = 0
    successful_files = 0
    failed_files = 0

    for index, image_path in enumerate(
        images,
        start=1,
    ):

        print()
        print(f"[{index:02d}/{len(images):02d}] " f"{image_path.name}")

        original_filename = metadata_mapping.get(
            image_path.name,
            image_path.name,
        )

        extracted_json = EXTRACTED_DIR / (
            f"{image_path.stem}" f"_ocr_original_extracted.json"
        )

        # Alte Ergebnisse löschen,
        # damit bei einem Fehler nicht versehentlich
        # ein altes JSON ausgewertet wird.
        if extracted_json.exists():
            extracted_json.unlink()

        log_file = LOG_DIR / f"{image_path.stem}.log"

        with open(
            log_file,
            "w",
            encoding="utf-8",
        ) as log:

            process = subprocess.run(
                [
                    sys.executable,
                    str(ANALYZE_SCRIPT),
                    str(image_path),
                ],
                cwd=BASE_DIR,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )

        if process.returncode != 0 or not extracted_json.exists():

            print("   FEHLER")

            results.append(
                {
                    "Dateiname": original_filename,
                    "Station_Pipeline": "",
                    "Linie_Pipeline": "",
                    "Bauplannummer_Pipeline": "",
                    "Station_gefunden": "Nein",
                    "Linie_gefunden": "Nein",
                    "Bauplannummer_gefunden": "Nein",
                    "Status": "FEHLER",
                }
            )

            failed_files += 1
            continue

        with open(
            extracted_json,
            "r",
            encoding="utf-8",
        ) as file:

            extracted = json.load(file)

        station = extracted.get("station_name")

        line = extracted.get("line")

        plan_number = extracted.get("plan_number")

        station_found = value_found(station)

        line_found = value_found(line)

        plan_number_found = value_found(plan_number)

        if station_found:
            station_count += 1

        if line_found:
            line_count += 1

        if plan_number_found:
            plan_number_count += 1

        successful_files += 1

        print(f"   Station:     " f"{station}")

        print(f"   Linie:       " f"{line}")

        print(f"   Plannummer:  " f"{plan_number}")

        results.append(
            {
                "Dateiname": original_filename,
                "Station_Pipeline": station or "",
                "Linie_Pipeline": line or "",
                "Bauplannummer_Pipeline": plan_number or "",
                "Station_gefunden": ("Ja" if station_found else "Nein"),
                "Linie_gefunden": ("Ja" if line_found else "Nein"),
                "Bauplannummer_gefunden": ("Ja" if plan_number_found else "Nein"),
                "Status": "OK",
            }
        )

    # CSV

    fieldnames = [
        "Dateiname",
        "Station_Pipeline",
        "Linie_Pipeline",
        "Bauplannummer_Pipeline",
        "Station_gefunden",
        "Linie_gefunden",
        "Bauplannummer_gefunden",
        "Status",
    ]

    with open(
        CSV_FILE,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as csv_file:

        writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        writer.writerows(results)

    # EXCEL

    workbook = Workbook()

    worksheet = workbook.active

    worksheet.title = "Pipeline Ergebnisse"

    worksheet.append(fieldnames)

    for result in results:

        worksheet.append([result[column] for column in fieldnames])

    summary = workbook.create_sheet("Zusammenfassung")

    summary.append(
        [
            "Kennzahl",
            "Anzahl",
        ]
    )

    summary.append(
        [
            "Pläne insgesamt",
            len(images),
        ]
    )

    summary.append(
        [
            "Erfolgreich verarbeitet",
            successful_files,
        ]
    )

    summary.append(
        [
            "Fehler",
            failed_files,
        ]
    )

    summary.append(
        [
            "Stationsname gefunden",
            station_count,
        ]
    )

    summary.append(
        [
            "Linie gefunden",
            line_count,
        ]
    )

    summary.append(
        [
            "Bauplannummer gefunden",
            plan_number_count,
        ]
    )

    workbook.save(EXCEL_FILE)

    # AUSGABE

    print()
    print("========================================")
    print("EVALUATION ABGESCHLOSSEN")
    print("========================================")

    print(f"\nPläne insgesamt:       " f"{len(images)}")

    print(f"Erfolgreich:           " f"{successful_files}")

    print(f"Fehler:                " f"{failed_files}")

    print()

    print(f"Stationsname gefunden: " f"{station_count} / {len(images)}")

    print(f"Linie gefunden:        " f"{line_count} / {len(images)}")

    print(f"Bauplannummer gefunden:" f" {plan_number_count} / {len(images)}")

    print()
    print("Excel:")
    print(EXCEL_FILE)

    print()
    print("CSV:")
    print(CSV_FILE)


if __name__ == "__main__":
    main()
