import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output

# PFADE

BASE_DIR = Path(__file__).resolve().parent.parent

METADATA_PATH = BASE_DIR / "data" / "annotations" / "image_metadata.json"

OUTPUT_DIR = BASE_DIR / "data" / "output" / "ocr_candidates_original"

Image.MAX_IMAGE_PIXELS = None


# OCR

PSM_MODES = [
    6,
    7,
    10,
    11,
    13,
]

SCALES = [
    1,
    2,
    4,
]

# Padding bezieht sich auf das Trainingsbild.
TRAINING_PADDING_VALUES = [
    0,
    10,
    30,
]


# METADATEN


def load_metadata(training_filename):

    sidecar = (
        BASE_DIR
        / "data"
        / "working"
        / "images"
        / (f"{Path(training_filename).stem}" ".meta.json")
    )

    if sidecar.exists():

        with open(
            sidecar,
            "r",
            encoding="utf-8",
        ) as file:

            return json.load(file)

    with open(
        METADATA_PATH,
        "r",
        encoding="utf-8",
    ) as file:

        metadata = json.load(file)

    for item in metadata:

        if item["training_filename"] == training_filename:

            return item

    raise ValueError(f"Keine Metadaten für " f"{training_filename} gefunden.")


def find_original_image(
    original_filename,
    original_path=None,
):

    if original_path:

        stored = Path(original_path)

        if stored.exists():

            return stored

    raw_path = BASE_DIR / "data" / "raw" / original_filename

    if raw_path.exists():

        return raw_path

    matches = list((BASE_DIR / "data").rglob(original_filename))

    if matches:

        return matches[0]

    raise FileNotFoundError(f"Originalbild nicht gefunden: " f"{original_filename}")


# BBOX AUF ORIGINAL ZURÜCKRECHNEN


def convert_bbox_to_original(
    bbox,
    scale_x,
    scale_y,
):

    x1, y1, x2, y2 = bbox

    return [
        x1 / scale_x,
        y1 / scale_y,
        x2 / scale_x,
        y2 / scale_y,
    ]


# CROP


def create_original_crop(
    image,
    bbox,
    padding_training,
    scale_x,
    scale_y,
):

    x1, y1, x2, y2 = bbox

    # Padding aus Trainingskoordinaten
    # ebenfalls auf Originalgröße umrechnen.

    padding_x = padding_training / scale_x

    padding_y = padding_training / scale_y

    crop_x1 = max(
        0,
        int(x1 - padding_x),
    )

    crop_y1 = max(
        0,
        int(y1 - padding_y),
    )

    crop_x2 = min(
        image.width,
        int(x2 + padding_x),
    )

    crop_y2 = min(
        image.height,
        int(y2 + padding_y),
    )

    return image.crop(
        (
            crop_x1,
            crop_y1,
            crop_x2,
            crop_y2,
        )
    )


# PREPROCESSING


def prepare_variants(
    crop,
    scale,
):

    image = np.array(crop)

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_RGB2GRAY,
    )

    gray = cv2.resize(
        gray,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )

    normal = cv2.normalize(
        gray,
        None,
        0,
        255,
        cv2.NORM_MINMAX,
    )

    _, otsu = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )

    return {
        "normal": normal,
        "otsu": otsu,
    }


# OCR


def run_tesseract(
    image,
    psm,
):

    config = f"--oem 1 " f"--psm {psm}"

    data = pytesseract.image_to_data(
        image,
        lang="deu+eng",
        config=config,
        output_type=Output.DICT,
    )

    words = []

    confidences = []

    for text, confidence in zip(
        data["text"],
        data["conf"],
    ):

        text = text.strip()

        if not text:
            continue

        try:

            confidence = float(confidence)

        except Exception:
            continue

        if confidence < 0:
            continue

        words.append(text)

        confidences.append(confidence)

    text = " ".join(words).strip()

    if confidences:

        mean_confidence = sum(confidences) / len(confidences)

    else:

        mean_confidence = 0.0

    return {
        "text": text,
        "confidence": mean_confidence,
    }


# MEHRERE OCR-VARIANTEN


def run_multi_ocr(
    image,
    original_bbox,
    scale_x,
    scale_y,
):

    attempts = []

    for padding in TRAINING_PADDING_VALUES:

        crop = create_original_crop(
            image=image,
            bbox=original_bbox,
            padding_training=padding,
            scale_x=scale_x,
            scale_y=scale_y,
        )

        for scale in SCALES:

            variants = prepare_variants(
                crop,
                scale,
            )

            for (
                variant_name,
                prepared,
            ) in variants.items():

                for psm in PSM_MODES:

                    result = run_tesseract(
                        prepared,
                        psm,
                    )

                    text = result["text"]

                    confidence = result["confidence"]

                    # Kleine Auswahlbewertung.
                    # Hohe OCR-Confidence zählt am meisten.

                    length_bonus = (
                        min(
                            len(text),
                            30,
                        )
                        * 0.10
                    )

                    selection_score = confidence + length_bonus

                    attempts.append(
                        {
                            "padding_training": padding,
                            "scale": scale,
                            "preprocessing": variant_name,
                            "psm": psm,
                            "text": text,
                            "confidence": confidence,
                            "selection_score": selection_score,
                        }
                    )

    best = max(
        attempts,
        key=lambda item: item["selection_score"],
    )

    return (
        best,
        attempts,
    )


# MAIN


def main():

    parser = argparse.ArgumentParser(
        description=("OCR auf Originalauflösung " "für Layout-Predictions.")
    )

    parser.add_argument(
        "training_image",
        type=str,
        help=("Standardisiertes Trainings-/" "Arbeitsbild"),
    )

    parser.add_argument(
        "predictions",
        type=str,
        help="Prediction JSON",
    )

    args = parser.parse_args()

    training_path = Path(args.training_image)

    prediction_path = Path(args.predictions)

    # METADATEN

    metadata = load_metadata(training_path.name)

    scale_x = float(metadata["scale_x"])

    scale_y = float(metadata["scale_y"])

    original_path = find_original_image(
        metadata["original_filename"],
        metadata.get("original_path"),
    )

    print("OCR AUF ORIGINALAUFLÖSUNG")

    print("==========================")

    print(f"\nArbeitsbild: " f"{training_path.name}")

    print(f"Originalbild: " f"{original_path}")

    print(
        f"Originalgröße: "
        f"{metadata['original_width']} "
        f"x "
        f"{metadata['original_height']}"
    )

    print(
        f"Arbeitsgröße: "
        f"{metadata['training_width']} "
        f"x "
        f"{metadata['training_height']}"
    )

    # BILDER / PREDICTIONS

    original_image = Image.open(original_path).convert("RGB")

    with open(
        prediction_path,
        "r",
        encoding="utf-8",
    ) as file:

        prediction_data = json.load(file)

    predictions = prediction_data["predictions"]

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    results = []

    print(f"\nKandidaten: " f"{len(predictions)}")

    print()

    # ALLE KANDIDATEN

    for index, prediction in enumerate(
        predictions,
        start=1,
    ):

        training_bbox = prediction["bbox"]

        original_bbox = convert_bbox_to_original(
            training_bbox,
            scale_x,
            scale_y,
        )

        best, attempts = run_multi_ocr(
            image=original_image,
            original_bbox=original_bbox,
            scale_x=scale_x,
            scale_y=scale_y,
        )

        # Kontroll-Crop speichern

        preview_crop = create_original_crop(
            image=original_image,
            bbox=original_bbox,
            padding_training=10,
            scale_x=scale_x,
            scale_y=scale_y,
        )

        crop_path = OUTPUT_DIR / (
            f"{training_path.stem}_" f"{index:03d}_" f"{prediction['label']}.png"
        )

        preview_crop.save(crop_path)

        result = {
            "index": index,
            "label": prediction["label"],
            "layout_score": prediction["score"],
            "training_bbox": training_bbox,
            "original_bbox": original_bbox,
            "ocr_text": best["text"],
            "ocr_confidence": best["confidence"],
            "best_padding_training": best["padding_training"],
            "best_scale": best["scale"],
            "best_preprocessing": best["preprocessing"],
            "best_psm": best["psm"],
            "all_ocr_attempts": attempts,
        }

        results.append(result)

        print(
            f"{index:03d}. "
            f"{prediction['label']:20} "
            f"| Layout "
            f"{prediction['score']:.3f} "
            f"| OCR "
            f"{best['confidence']:.1f} "
            f"| x{best['scale']} "
            f"| PSM "
            f"{best['psm']:2d} "
            f"| "
            f"{repr(best['text'])}"
        )

    # SPEICHERN

    result_path = OUTPUT_DIR / (f"{training_path.stem}" f"_ocr_original.json")

    with open(
        result_path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            results,
            file,
            indent=4,
            ensure_ascii=False,
        )

    print("\n==========================")

    print("OCR abgeschlossen")

    print("==========================")

    print("\nJSON gespeichert:")

    print(result_path)


if __name__ == "__main__":
    main()
