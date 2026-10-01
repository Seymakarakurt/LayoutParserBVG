import argparse
import json
from pathlib import Path

from PIL import Image

# KONFIGURATION

BASE_DIR = Path(__file__).resolve().parent.parent

WORKING_DIR = BASE_DIR / "data" / "working" / "images"

MAX_SIDE = 5000

SUPPORTED_EXTENSIONS = {
    ".tif",
    ".tiff",
    ".png",
    ".jpg",
    ".jpeg",
}

Image.MAX_IMAGE_PIXELS = None


# BILD VERKLEINERN


def resize_image(image):

    original_width = image.width
    original_height = image.height

    longest_side = max(
        original_width,
        original_height,
    )

    if longest_side <= MAX_SIDE:

        return (
            image,
            1.0,
            1.0,
        )

    scale = MAX_SIDE / longest_side

    new_width = round(original_width * scale)

    new_height = round(original_height * scale)

    resized = image.resize(
        (
            new_width,
            new_height,
        ),
        Image.Resampling.LANCZOS,
    )

    scale_x = new_width / original_width

    scale_y = new_height / original_height

    return (
        resized,
        scale_x,
        scale_y,
    )


# EINEN PLAN VORBEREITEN


def prepare_plan(
    source_path,
):

    source_path = source_path.resolve()

    if not source_path.exists():

        raise FileNotFoundError(f"Datei nicht gefunden: " f"{source_path}")

    if source_path.suffix.lower() not in SUPPORTED_EXTENSIONS:

        raise ValueError("Nicht unterstütztes Format: " f"{source_path.suffix}")

    WORKING_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ORIGINAL ÖFFNEN

    with Image.open(source_path) as image:

        # Bei TIFF-Dateien erste Seite.
        image.seek(0)

        original_width = image.width

        original_height = image.height

        image = image.convert("RGB")

        (
            prepared_image,
            scale_x,
            scale_y,
        ) = resize_image(image)

        # 5000px-ARBEITSBILD

        working_filename = source_path.stem + ".png"

        working_path = WORKING_DIR / working_filename

        prepared_image.save(
            working_path,
            format="PNG",
            optimize=True,
        )

    # METADATEN

    metadata = {
        "original_filename": source_path.name,
        "original_path": str(source_path),
        "training_filename": working_filename,
        "original_width": original_width,
        "original_height": original_height,
        "training_width": prepared_image.width,
        "training_height": prepared_image.height,
        "scale_x": scale_x,
        "scale_y": scale_y,
    }

    metadata_path = working_path.with_suffix(".meta.json")

    with open(
        metadata_path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            metadata,
            file,
            indent=4,
            ensure_ascii=False,
        )

    return (
        source_path,
        working_path,
        metadata,
    )


# MAIN


def main():

    parser = argparse.ArgumentParser(
        description=("Bereitet einen einzelnen " "Originalplan für die Analyse vor.")
    )

    parser.add_argument(
        "image",
        type=str,
        help=("Pfad zum Originalplan"),
    )

    args = parser.parse_args()

    source_path = Path(args.image)

    (
        source_path,
        working_path,
        metadata,
    ) = prepare_plan(source_path)

    print()
    print("PLAN-VORBEREITUNG")

    print("==================")

    print(f"\nOriginal:")

    print(source_path)

    print("\nOriginalgröße:")

    print(f"{metadata['original_width']} " f"x " f"{metadata['original_height']}")

    print("\nArbeitsbild:")

    print(working_path)

    print("\nArbeitsgröße:")

    print(f"{metadata['training_width']} " f"x " f"{metadata['training_height']}")

    print("\nSkalierung:")

    print(f"X = " f"{metadata['scale_x']:.6f}")

    print(f"Y = " f"{metadata['scale_y']:.6f}")

    print("\nMetadaten:")

    print(working_path.with_suffix(".meta.json"))

    print("\nVorbereitung abgeschlossen.")


if __name__ == "__main__":
    main()
