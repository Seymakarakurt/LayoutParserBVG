import json
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

LABEL_DIR = BASE_DIR / "data" / "annotations" / "labels"


def main():
    print("Annotation Validation")
    print("=====================")

    label_files = sorted(LABEL_DIR.glob("*.json"))

    print(f"\nJSON-Dateien: " f"{len(label_files)}")

    class_counter = Counter()

    images_with_annotations = 0
    images_without_annotations = 0

    total_boxes = 0

    empty_files = []
    multiple_station_files = []

    for label_file in label_files:

        with open(
            label_file,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        annotations = data.get(
            "annotations",
            [],
        )

        if annotations:
            images_with_annotations += 1
        else:
            images_without_annotations += 1
            empty_files.append(
                data.get(
                    "image",
                    label_file.name,
                )
            )

        station_count = 0

        for annotation in annotations:

            label = annotation.get("label")

            bbox = annotation.get("bbox")

            if not label:
                print(f"FEHLER: Kein Label in " f"{label_file.name}")
                continue

            if not bbox or len(bbox) != 4:
                print(f"FEHLER: Ungültige Box in " f"{label_file.name}")
                continue

            class_counter[label] += 1
            total_boxes += 1

            if label == "STATION_FIELD":
                station_count += 1

        if station_count > 1:
            multiple_station_files.append(
                {
                    "image": data.get(
                        "image",
                        label_file.name,
                    ),
                    "count": station_count,
                }
            )

    print(f"\nBilder mit Annotationen: " f"{images_with_annotations}")

    print(f"Bilder ohne Annotationen: " f"{images_without_annotations}")

    print(f"\nBounding Boxes insgesamt: " f"{total_boxes}")

    print("\nAnnotationen pro Klasse:")

    print("-------------------------")

    for label, count in sorted(class_counter.items()):
        print(f"{label:25} " f"{count}")

    print("-------------------------")

    print("\nBilder OHNE Annotation:")

    print("-------------------------")

    if empty_files:

        for filename in empty_files:
            print(filename)

    else:
        print("Keine.")

    print("-------------------------")

    print("\nBilder mit mehreren " "STATION_FIELD-Boxen:")

    print("-------------------------")

    if multiple_station_files:

        for item in multiple_station_files:

            print(f"{item['image']} " f"-> {item['count']} Boxen")

    else:
        print("Keine.")

    print("-------------------------")

    print("\nValidierung abgeschlossen.")


if __name__ == "__main__":
    main()
