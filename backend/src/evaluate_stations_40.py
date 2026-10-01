"""Run the existing BVG pipeline for station names only.

Place this file in backend/src and run it from the backend directory.
The trained multiclass detector still computes its normal class scores, but only
STATION_FIELD predictions are passed to OCR and information extraction. This
avoids OCR work for LINE_FIELD and PLAN_NUMBER_FIELD and leaves the application
pipeline unchanged.
"""

import argparse
import csv
import json
import subprocess
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from openpyxl import Workbook

import predict_full_plan_v3 as detector

BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "src"
DEFAULT_INPUT_DIR = BASE_DIR / "data" / "annotations" / "images"
WORKING_DIR = BASE_DIR / "data" / "working" / "images"
ANNOTATION_IMAGES_DIR = BASE_DIR / "data" / "annotations" / "images"
METADATA_FILE = BASE_DIR / "data" / "annotations" / "image_metadata.json"

PREPARE_SCRIPT = SRC_DIR / "prepare_single_plan.py"
OCR_SCRIPT = SRC_DIR / "ocr_prediction_candidates_original.py"
EXTRACTION_SCRIPT = SRC_DIR / "extract_station_only.py"

PREDICTION_DIR = BASE_DIR / "data" / "output" / "full_plan_predictions"
OCR_DIR = BASE_DIR / "data" / "output" / "ocr_candidates_original"
EXTRACTED_DIR = BASE_DIR / "data" / "output" / "extracted"
EVALUATION_DIR = BASE_DIR / "data" / "output" / "evaluation" / "station_only"
FILTERED_PREDICTION_DIR = EVALUATION_DIR / "station_predictions"
LOG_DIR = EVALUATION_DIR / "logs"
CSV_FILE = EVALUATION_DIR / "station_results_40.csv"
EXCEL_FILE = EVALUATION_DIR / "station_results_40.xlsx"

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def resolve_input_dir(value):
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    path = path.resolve()
    if not path.is_dir():
        raise NotADirectoryError(f"Input directory not found: {path}")
    return path


def load_original_filename_mapping():
    if not METADATA_FILE.exists():
        return {}
    with METADATA_FILE.open("r", encoding="utf-8") as file:
        metadata = json.load(file)
    return {
        item["training_filename"]: item.get("original_filename")
        or item["training_filename"]
        for item in metadata
        if item.get("training_filename")
    }


def is_inside(path, directory):
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def prepare_if_needed(image_path, log):
    if is_inside(image_path, WORKING_DIR) or is_inside(
        image_path, ANNOTATION_IMAGES_DIR
    ):
        return image_path

    subprocess.run(
        [sys.executable, str(PREPARE_SCRIPT), str(image_path)],
        cwd=BASE_DIR,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        check=True,
    )
    working_path = WORKING_DIR / f"{image_path.stem}.png"
    if not working_path.exists():
        raise FileNotFoundError(f"Working image was not created: {working_path}")
    return working_path


def run_script(script, arguments, log):
    subprocess.run(
        [sys.executable, str(script), *map(str, arguments)],
        cwd=BASE_DIR,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        check=True,
    )


def filter_station_predictions(source_path, target_path):
    with source_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    all_predictions = data.get("predictions", [])
    station_predictions = [
        prediction
        for prediction in all_predictions
        if prediction.get("label") == "STATION_FIELD"
    ]

    filtered = dict(data)
    filtered["station_only"] = True
    filtered["original_predictions_after_nms"] = len(all_predictions)
    filtered["discarded_non_station_predictions"] = (
        len(all_predictions) - len(station_predictions)
    )
    filtered["predictions_after_nms"] = len(station_predictions)
    filtered["predictions"] = station_predictions

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("w", encoding="utf-8") as file:
        json.dump(filtered, file, indent=4, ensure_ascii=False)

    return len(all_predictions), len(station_predictions)


def value_found(value):
    return value is not None and str(value).strip() not in {"", "None", "null"}


def save_results(results, total, successful, failed, found):
    fieldnames = [
        "filename",
        "station_pipeline",
        "station_suggestion",
        "suggestion_similarity",
        "station_found",
        "station_boxes",
        "discarded_non_station_boxes",
        "layout_seconds",
        "ocr_and_extraction_seconds",
        "total_seconds",
        "status",
        "error",
    ]

    with CSV_FILE.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Station results"
    sheet.append(fieldnames)
    for result in results:
        sheet.append([result[field] for field in fieldnames])

    summary = workbook.create_sheet("Summary")
    summary.append(["Metric", "Count"])
    summary.append(["Images processed", total])
    summary.append(["Successfully processed", successful])
    summary.append(["Errors", failed])
    summary.append(["Station value found", found])
    summary.append(["Station value missing", total - found])
    summary.append([])
    summary.append(
        [
            "Note",
            "Found/missing is coverage, not correctness against ground truth.",
        ]
    )

    workbook.save(EXCEL_FILE)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate up to 40 images using station detections only."
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help="Folder containing the images (default: data/annotations/images).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="Maximum number of images to process (default: 40). Use 0 for all.",
    )
    args = parser.parse_args()

    input_dir = resolve_input_dir(args.input_dir)
    images = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if args.limit > 0:
        images = images[: args.limit]
    if not images:
        raise RuntimeError(f"No supported images found in {input_dir}")

    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    FILTERED_PREDICTION_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    filename_mapping = load_original_filename_mapping()

    print("=" * 60)
    print("STATION-ONLY EVALUATION")
    print("=" * 60)
    print(f"Input:  {input_dir}")
    print(f"Images: {len(images)}")
    if len(images) != 40:
        print(f"Notice: this run contains {len(images)} images, not exactly 40.")

    # Load the trained model once and reuse it for every image.
    device = detector.get_device()
    print(f"Device: {device}")
    print("Loading trained detector once...")
    model = detector.load_model(device)
    original_load_model = detector.load_model
    detector.load_model = lambda requested_device: model

    results = []
    successful = 0
    failed = 0
    station_found_count = 0
    run_started = time.perf_counter()

    try:
        for index, image_path in enumerate(images, start=1):
            display_name = filename_mapping.get(image_path.name, image_path.name)
            print(f"\n[{index:02d}/{len(images):02d}] {display_name}", flush=True)
            item_started = time.perf_counter()
            log_path = LOG_DIR / f"{image_path.stem}.log"
            row = {
                "filename": display_name,
                "station_pipeline": "",
                "station_suggestion": "",
                "suggestion_similarity": "",
                "station_found": "No",
                "station_boxes": 0,
                "discarded_non_station_boxes": 0,
                "layout_seconds": "",
                "ocr_and_extraction_seconds": "",
                "total_seconds": "",
                "status": "ERROR",
                "error": "",
            }

            try:
                with log_path.open("w", encoding="utf-8") as log:
                    working_path = prepare_if_needed(image_path, log)
                    stem = working_path.stem
                    prediction_json = (
                        PREDICTION_DIR / f"{stem}_v3_predictions.json"
                    )
                    station_prediction_json = (
                        FILTERED_PREDICTION_DIR
                        / f"{stem}_station_predictions.json"
                    )
                    ocr_json = OCR_DIR / f"{stem}_ocr_original.json"
                    extracted_json = (
                        EXTRACTED_DIR / f"{stem}_ocr_original_extracted.json"
                    )

                    for stale_path in (ocr_json, extracted_json):
                        if stale_path.exists():
                            stale_path.unlink()

                    layout_started = time.perf_counter()
                    with redirect_stdout(log), redirect_stderr(log):
                        detector.run_full_plan_prediction(working_path)
                    layout_seconds = time.perf_counter() - layout_started
                    if not prediction_json.exists():
                        raise FileNotFoundError(
                            f"Prediction JSON was not created: {prediction_json}"
                        )

                    all_count, station_count = filter_station_predictions(
                        prediction_json, station_prediction_json
                    )

                    ocr_started = time.perf_counter()
                    run_script(
                        OCR_SCRIPT,
                        [working_path, station_prediction_json],
                        log,
                    )
                    if not ocr_json.exists():
                        raise FileNotFoundError(
                            f"OCR JSON was not created: {ocr_json}"
                        )

                    run_script(EXTRACTION_SCRIPT, [ocr_json], log)
                    ocr_seconds = time.perf_counter() - ocr_started
                    if not extracted_json.exists():
                        raise FileNotFoundError(
                            f"Extraction JSON was not created: {extracted_json}"
                        )

                    with extracted_json.open("r", encoding="utf-8") as file:
                        extracted = json.load(file)

                station = extracted.get("station_name")
                suggestion = extracted.get("station_suggestion")
                suggestion_name = (
                    suggestion.get("name", "")
                    if isinstance(suggestion, dict)
                    else (suggestion or "")
                )
                suggestion_similarity = (
                    suggestion.get("similarity", "")
                    if isinstance(suggestion, dict)
                    else ""
                )
                found = value_found(station)
                successful += 1
                station_found_count += int(found)
                row.update(
                    {
                        "station_pipeline": station or "",
                        "station_suggestion": suggestion_name,
                        "suggestion_similarity": suggestion_similarity,
                        "station_found": "Yes" if found else "No",
                        "station_boxes": station_count,
                        "discarded_non_station_boxes": all_count
                        - station_count,
                        "layout_seconds": round(layout_seconds, 2),
                        "ocr_and_extraction_seconds": round(ocr_seconds, 2),
                        "status": "OK",
                    }
                )
                print(
                    f"  Station: {station!r} | station boxes: {station_count} "
                    f"| layout: {layout_seconds:.1f}s | OCR+extract: {ocr_seconds:.1f}s"
                )

            except Exception as error:
                failed += 1
                row["error"] = f"{type(error).__name__}: {error}"
                with log_path.open("a", encoding="utf-8") as log:
                    log.write("\n\nSTATION-ONLY RUN ERROR\n")
                    traceback.print_exc(file=log)
                print(f"  ERROR: {row['error']}")

            row["total_seconds"] = round(time.perf_counter() - item_started, 2)
            results.append(row)
            save_results(
                results,
                total=len(results),
                successful=successful,
                failed=failed,
                found=station_found_count,
            )
    finally:
        detector.load_model = original_load_model

    elapsed = time.perf_counter() - run_started
    print("\n" + "=" * 60)
    print("STATION-ONLY EVALUATION COMPLETE")
    print("=" * 60)
    print(f"Processed:      {len(results)}")
    print(f"Successful:     {successful}")
    print(f"Errors:         {failed}")
    print(f"Station found:  {station_found_count}/{len(results)}")
    print(f"Elapsed:        {elapsed / 60:.1f} minutes")
    print(f"CSV:            {CSV_FILE}")
    print(f"Excel:          {EXCEL_FILE}")
    print(f"Logs:           {LOG_DIR}")
    print(
        "\nReminder: 'station found' measures coverage. Compare the station values "
        "with ground truth to calculate accuracy."
    )


if __name__ == "__main__":
    main()
