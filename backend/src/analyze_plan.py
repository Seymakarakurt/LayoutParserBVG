import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# PFADE

BASE_DIR = Path(__file__).resolve().parent.parent

SRC_DIR = BASE_DIR / "src"

WORKING_DIR = BASE_DIR / "data" / "working" / "images"

ANNOTATION_IMAGES_DIR = BASE_DIR / "data" / "annotations" / "images"

PREPARE_SCRIPT = SRC_DIR / "prepare_single_plan.py"

PREDICTION_SCRIPT = SRC_DIR / "predict_full_plan_v3.py"

OCR_SCRIPT = SRC_DIR / "ocr_prediction_candidates_original.py"

EXTRACTION_SCRIPT = SRC_DIR / "extract_information_v2.py"

PREDICTION_OUTPUT_DIR = BASE_DIR / "data" / "output" / "full_plan_predictions"

OCR_OUTPUT_DIR = BASE_DIR / "data" / "output" / "ocr_candidates_original"

EXTRACTED_OUTPUT_DIR = BASE_DIR / "data" / "output" / "extracted"


# COMMAND AUSFÜHREN


def run_command(command):

    subprocess.run(
        command,
        check=True,
        cwd=BASE_DIR,
    )


def format_laufzeit(seconds):

    whole_seconds = int(round(seconds))

    minutes, secs = divmod(whole_seconds, 60)

    if minutes:

        return f"{minutes} min {secs} s ({seconds:.1f} s)"

    return f"{seconds:.1f} s"


def print_laufzeit(
    step_name,
    seconds,
    finished_at,
):

    stamp = finished_at.strftime("%Y-%m-%d %H:%M:%S")

    print(
        "LAUFZEIT "
        f"{step_name}: "
        f"{format_laufzeit(seconds)}"
        f" | Ende {stamp}",
        flush=True,
    )


# PRÜFEN, OB BILD BEREITS VORBEREITET IST


def is_prepared_image(
    image_path,
):

    image_path = image_path.resolve()

    working_dir = WORKING_DIR.resolve()

    annotation_dir = ANNOTATION_IMAGES_DIR.resolve()

    try:

        image_path.relative_to(working_dir)

        return True

    except ValueError:
        pass

    try:

        image_path.relative_to(annotation_dir)

        return True

    except ValueError:
        pass

    return False


# ORIGINALPLAN VORBEREITEN


def prepare_original_plan(
    original_path,
):

    print()
    print("========================================")

    print("SCHRITT 1/4: PLAN VORBEREITEN")

    print("========================================")

    run_command(
        [
            sys.executable,
            str(PREPARE_SCRIPT),
            str(original_path),
        ]
    )

    working_path = WORKING_DIR / (original_path.stem + ".png")

    if not working_path.exists():

        raise FileNotFoundError("Arbeitsbild wurde nicht erzeugt: " f"{working_path}")

    return working_path


# MAIN


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Komplette BVG-Plananalyse: "
            "Preprocessing -> "
            "Layout Detection -> "
            "Original-OCR -> "
            "Information Extraction"
        )
    )

    parser.add_argument(
        "image",
        type=str,
        help=(
            "Pfad zum Originalplan "
            "oder zu einem bereits vorbereiteten "
            "Arbeitsbild"
        ),
    )

    args = parser.parse_args()

    # INPUT-PFAD

    input_path = Path(args.image)

    if not input_path.is_absolute():

        input_path = BASE_DIR / input_path

    input_path = input_path.resolve()

    if not input_path.exists():

        raise FileNotFoundError(f"Datei nicht gefunden: " f"{input_path}")

    print()
    print("========================================")

    print("BVG PLAN ANALYSE")

    print("========================================")

    print("\nEingabedatei:")

    print(input_path)

    # 1. PREPROCESSING

    if is_prepared_image(input_path):

        print()
        print("========================================")

        print("SCHRITT 1/4: PLAN VORBEREITEN")

        print("========================================")

        print("\nBild ist bereits vorbereitet.")

        working_path = input_path

    else:

        working_path = prepare_original_plan(input_path)

    print("\nArbeitsbild:")

    print(working_path)

    stem = working_path.stem

    # OUTPUT-PFADE

    prediction_json = PREDICTION_OUTPUT_DIR / (f"{stem}" f"_v3_predictions.json")

    ocr_json = OCR_OUTPUT_DIR / (f"{stem}" f"_ocr_original.json")

    extracted_json = EXTRACTED_OUTPUT_DIR / (f"{stem}" f"_ocr_original_extracted.json")

    # 2. LAYOUT DETECTION

    print()
    print("========================================")

    print("SCHRITT 2/4: LAYOUT DETECTION")

    print("========================================")

    layout_started = time.perf_counter()

    run_command(
        [
            sys.executable,
            str(PREDICTION_SCRIPT),
            str(working_path),
        ]
    )

    print_laufzeit(
        "Layout-Erkennung",
        time.perf_counter() - layout_started,
        datetime.now(),
    )

    if not prediction_json.exists():

        raise FileNotFoundError(
            "Prediction JSON wurde " "nicht erzeugt: " f"{prediction_json}"
        )

    # 3. OCR AUF ORIGINALAUFLÖSUNG

    print()
    print("========================================")

    print("SCHRITT 3/4: ORIGINAL-OCR")

    print("========================================")

    ocr_started = time.perf_counter()

    run_command(
        [
            sys.executable,
            str(OCR_SCRIPT),
            str(working_path),
            str(prediction_json),
        ]
    )

    print_laufzeit(
        "Texterkennung",
        time.perf_counter() - ocr_started,
        datetime.now(),
    )

    if not ocr_json.exists():

        raise FileNotFoundError("OCR JSON wurde " "nicht erzeugt: " f"{ocr_json}")

    # 4. INFORMATION EXTRACTION

    print()
    print("========================================")

    print("SCHRITT 4/4: INFORMATION EXTRACTION")

    print("========================================")

    run_command(
        [
            sys.executable,
            str(EXTRACTION_SCRIPT),
            str(ocr_json),
        ]
    )

    if not extracted_json.exists():

        raise FileNotFoundError(
            "Extraktions-JSON wurde " "nicht erzeugt: " f"{extracted_json}"
        )

    # FINALES JSON LADEN

    with open(
        extracted_json,
        "r",
        encoding="utf-8",
    ) as file:

        result = json.load(file)

    # FINALES ERGEBNIS

    print()
    print("========================================")

    print("FINALES ERGEBNIS")

    print("========================================")

    print(f"Station:     " f"{result.get('station_name')}")

    print(f"Linie:       " f"{result.get('line')}")

    print(f"Plannummer:  " f"{result.get('plan_number')}")

    print()
    print("JSON:")

    print(extracted_json)

    print()
    print("Analyse abgeschlossen.")


if __name__ == "__main__":
    main()
