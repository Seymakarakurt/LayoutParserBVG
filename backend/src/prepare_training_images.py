import json
from pathlib import Path

from PIL import Image

# KONFIGURATION

BASE_DIR = Path(__file__).resolve().parent.parent

RAW_DIR = BASE_DIR / "data" / "raw"

OUTPUT_DIR = BASE_DIR / "data" / "annotations" / "images"

METADATA_FILE = BASE_DIR / "data" / "annotations" / "image_metadata.json"


# Maximale Seitenlänge der Trainingsbilder.
#
# Beispiel:
# 18000 x 12000
# wird ungefähr zu
# 5000 x 3333
MAX_SIDE = 5000


# Unsere Baupläne sind vertrauenswürdige lokale Dateien.
#
# Pillow besitzt normalerweise ein Schutzlimit für
# extrem große Bilder. Da einige historische Pläne dieses
# Limit überschreiten, deaktivieren wir es für dieses
# lokale Vorbereitungsskript.
Image.MAX_IMAGE_PIXELS = None


def find_image_files():
    """
    Findet alle unterstützten Bilddateien im raw-Ordner.
    """

    supported_extensions = {
        ".tif",
        ".tiff",
        ".png",
        ".jpg",
        ".jpeg",
    }

    files = []

    for file_path in RAW_DIR.iterdir():

        if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
            files.append(file_path)

    return sorted(files)


def resize_image(image):
    """
    Verkleinert ein Bild proportional,
    falls seine längste Seite größer
    als MAX_SIDE ist.

    Das Seitenverhältnis bleibt erhalten.
    """

    original_width = image.width
    original_height = image.height

    longest_side = max(
        original_width,
        original_height,
    )

    # Bild ist bereits klein genug
    if longest_side <= MAX_SIDE:

        return (
            image,
            1.0,
            1.0,
        )

    scale = MAX_SIDE / longest_side

    new_width = round(original_width * scale)

    new_height = round(original_height * scale)

    resized_image = image.resize(
        (
            new_width,
            new_height,
        ),
        Image.Resampling.LANCZOS,
    )

    scale_x = new_width / original_width

    scale_y = new_height / original_height

    return (
        resized_image,
        scale_x,
        scale_y,
    )


def prepare_image(file_path):
    """
    Lädt einen Original-Bauplan,
    konvertiert ihn nach RGB,
    verkleinert ihn gegebenenfalls
    und speichert ihn als PNG.
    """

    with Image.open(file_path) as image:

        # Bei TIFFs verwenden wir zunächst
        # die erste Seite / den ersten Frame.
        image.seek(0)

        original_width = image.width
        original_height = image.height

        image = image.convert("RGB")

        (
            prepared_image,
            scale_x,
            scale_y,
        ) = resize_image(image)

        output_filename = file_path.stem + ".png"

        output_path = OUTPUT_DIR / output_filename

        prepared_image.save(
            output_path,
            format="PNG",
            optimize=True,
        )

        metadata = {
            "original_filename": file_path.name,
            "training_filename": output_filename,
            "original_width": original_width,
            "original_height": original_height,
            "training_width": prepared_image.width,
            "training_height": prepared_image.height,
            "scale_x": scale_x,
            "scale_y": scale_y,
        }

        return metadata


def main():

    print("Training Image Preparation")

    print("==========================")

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    image_files = find_image_files()

    if not image_files:

        print("\nKeine Bilddateien " "in data/raw gefunden.")

        return

    print(f"\nGefundene Bilder: " f"{len(image_files)}")

    print(f"Maximale Seitenlänge: " f"{MAX_SIDE} Pixel")

    print()

    metadata_list = []

    for index, file_path in enumerate(
        image_files,
        start=1,
    ):

        print(f"[{index}/{len(image_files)}] " f"{file_path.name}")

        try:

            metadata = prepare_image(file_path)

            metadata_list.append(metadata)

            print(
                "    Original: "
                f"{metadata['original_width']} "
                "x "
                f"{metadata['original_height']}"
            )

            print(
                "    Training: "
                f"{metadata['training_width']} "
                "x "
                f"{metadata['training_height']}"
            )

            print("    Skalierung: " f"{metadata['scale_x']:.4f}")

            print("    -> " f"{metadata['training_filename']}")

        except Exception as error:

            print("    FEHLER:")

            print(f"    {error}")

        print()

    # Metadaten speichern

    with open(
        METADATA_FILE,
        "w",
        encoding="utf-8",
    ) as metadata_file:

        json.dump(
            metadata_list,
            metadata_file,
            indent=4,
            ensure_ascii=False,
        )

    print("==========================")

    print("Vorbereitung abgeschlossen.")

    print(f"\nErzeugte Bilder: " f"{len(metadata_list)}")

    print("\nTrainingsbilder:")

    print(OUTPUT_DIR)

    print("\nSkalierungsinformationen:")

    print(METADATA_FILE)


if __name__ == "__main__":
    main()
