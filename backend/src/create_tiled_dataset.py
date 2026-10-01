import json
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

# KONFIGURATION

BASE_DIR = Path(__file__).resolve().parent.parent

SOURCE_IMAGE_DIR = BASE_DIR / "data" / "annotations" / "images"

SOURCE_LABEL_DIR = BASE_DIR / "data" / "annotations" / "labels"

OUTPUT_BASE_DIR = BASE_DIR / "data" / "annotations_tiled"

OUTPUT_IMAGE_DIR = OUTPUT_BASE_DIR / "images"

OUTPUT_LABEL_DIR = OUTPUT_BASE_DIR / "labels"


TILE_SIZE = 1600

OVERLAP = 400

STRIDE = TILE_SIZE - OVERLAP

NEGATIVE_TILES_PER_IMAGE = 1

RANDOM_SEED = 42


TARGET_CLASSES = {
    "STATION_FIELD",
    "LINE_FIELD",
    "PLAN_NUMBER_FIELD",
}


Image.MAX_IMAGE_PIXELS = None


# NORMALE TILE-POSITIONEN


def generate_positions(
    image_size,
):

    if image_size <= TILE_SIZE:
        return [0]

    positions = list(
        range(
            0,
            image_size - TILE_SIZE + 1,
            STRIDE,
        )
    )

    last_position = image_size - TILE_SIZE

    if positions[-1] != last_position:

        positions.append(last_position)

    return positions


# BOX-FUNKTIONEN


def calculate_area(
    bbox,
):

    x1, y1, x2, y2 = bbox

    return max(
        0,
        x2 - x1,
    ) * max(
        0,
        y2 - y1,
    )


def calculate_intersection(
    bbox,
    tile_box,
):

    box_x1, box_y1, box_x2, box_y2 = bbox

    tile_x1, tile_y1, tile_x2, tile_y2 = tile_box

    x1 = max(
        box_x1,
        tile_x1,
    )

    y1 = max(
        box_y1,
        tile_y1,
    )

    x2 = min(
        box_x2,
        tile_x2,
    )

    y2 = min(
        box_y2,
        tile_y2,
    )

    if x2 <= x1 or y2 <= y1:

        return None

    return [
        x1,
        y1,
        x2,
        y2,
    ]


def calculate_coverage(
    bbox,
    tile_box,
):

    original_area = calculate_area(bbox)

    if original_area <= 0:
        return 0.0

    intersection = calculate_intersection(
        bbox,
        tile_box,
    )

    if intersection is None:
        return 0.0

    intersection_area = calculate_area(intersection)

    return intersection_area / original_area


# BESTES NORMALES TILE FINDEN


def find_best_tile(
    bbox,
    tile_positions,
):

    best_tile = None

    best_coverage = -1.0

    for tile_x, tile_y in tile_positions:

        tile_box = [
            tile_x,
            tile_y,
            tile_x + TILE_SIZE,
            tile_y + TILE_SIZE,
        ]

        coverage = calculate_coverage(
            bbox,
            tile_box,
        )

        if coverage > best_coverage:

            best_coverage = coverage

            best_tile = (
                tile_x,
                tile_y,
            )

    return (
        best_tile,
        best_coverage,
    )


# CUSTOM TILE FÜR ABGESCHNITTENE BOX


def calculate_fitted_start(
    box_start,
    box_end,
    image_size,
):

    box_size = box_end - box_start

    if box_size > TILE_SIZE:

        raise ValueError("Bounding Box ist größer " "als TILE_SIZE.")

    if image_size <= TILE_SIZE:
        return 0

    # Tile möglichst um die Bounding Box
    # zentrieren.
    box_center = (box_start + box_end) / 2

    desired_start = int(round(box_center - TILE_SIZE / 2))

    # Damit die Box vollständig im Tile liegt:
    minimum_start = max(
        0,
        box_end - TILE_SIZE,
    )

    maximum_start = min(
        box_start,
        image_size - TILE_SIZE,
    )

    fitted_start = max(
        minimum_start,
        min(
            desired_start,
            maximum_start,
        ),
    )

    return int(fitted_start)


def create_fitted_tile_position(
    bbox,
    image_width,
    image_height,
):

    x1, y1, x2, y2 = bbox

    tile_x = calculate_fitted_start(
        x1,
        x2,
        image_width,
    )

    tile_y = calculate_fitted_start(
        y1,
        y2,
        image_height,
    )

    return (
        tile_x,
        tile_y,
    )


# BOX INS TILE-KOORDINATENSYSTEM


def convert_bbox_to_tile(
    bbox,
    tile_x,
    tile_y,
):

    x1, y1, x2, y2 = bbox

    return [
        int(x1 - tile_x),
        int(y1 - tile_y),
        int(x2 - tile_x),
        int(y2 - tile_y),
    ]


# NEGATIVE TILES


def tile_intersects_any_annotation(
    tile_x,
    tile_y,
    annotations,
):

    tile_box = [
        tile_x,
        tile_y,
        tile_x + TILE_SIZE,
        tile_y + TILE_SIZE,
    ]

    for annotation in annotations:

        intersection = calculate_intersection(
            annotation["bbox"],
            tile_box,
        )

        if intersection is not None:
            return True

    return False


# OUTPUT-ORDNER


def prepare_output_directories():

    if OUTPUT_BASE_DIR.exists():

        shutil.rmtree(OUTPUT_BASE_DIR)

    OUTPUT_IMAGE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_LABEL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


# EINEN PLAN VERARBEITEN


def process_document(
    label_path,
    rng,
):

    with open(
        label_path,
        "r",
        encoding="utf-8",
    ) as file:

        data = json.load(file)

    image_name = data["image"]

    image_path = SOURCE_IMAGE_DIR / image_name

    if not image_path.exists():

        raise FileNotFoundError(f"Bild nicht gefunden: " f"{image_path}")

    annotations = data.get(
        "annotations",
        [],
    )

    for annotation in annotations:

        if annotation["label"] not in TARGET_CLASSES:

            raise ValueError(f"Unbekannte Klasse: " f"{annotation['label']}")

    image = Image.open(image_path).convert("RGB")

    x_positions = generate_positions(image.width)

    y_positions = generate_positions(image.height)

    # Normales Raster
    regular_tile_positions = [
        (
            tile_x,
            tile_y,
        )
        for tile_y in y_positions
        for tile_x in x_positions
    ]

    # Diese Liste darf später durch
    # speziell verschobene Tiles ergänzt werden.
    available_tile_positions = list(regular_tile_positions)

    assignments = defaultdict(list)

    coverage_values = []

    custom_tile_count = 0

    # Jede Annotation genau einem Tile zuordnen

    for annotation in annotations:

        bbox = annotation["bbox"]

        (
            best_tile,
            best_coverage,
        ) = find_best_tile(
            bbox,
            available_tile_positions,
        )

        # Falls normales Raster die Box abschneidet:
        # spezielles Tile erzeugen.

        if best_coverage < 1.0:

            fitted_tile = create_fitted_tile_position(
                bbox,
                image.width,
                image.height,
            )

            if fitted_tile not in available_tile_positions:

                available_tile_positions.append(fitted_tile)

                custom_tile_count += 1

            best_tile = fitted_tile

            tile_x, tile_y = best_tile

            fitted_tile_box = [
                tile_x,
                tile_y,
                tile_x + TILE_SIZE,
                tile_y + TILE_SIZE,
            ]

            best_coverage = calculate_coverage(
                bbox,
                fitted_tile_box,
            )

        if best_tile is None:

            raise RuntimeError(f"Keine Tile-Zuordnung " f"für {image_name}")

        # Nach der Korrektur MUSS die Box
        # vollständig enthalten sein.
        if best_coverage < 0.999999:

            raise RuntimeError(
                f"Bounding Box konnte nicht "
                f"vollständig in Tile gelegt werden.\n"
                f"Bild: {image_name}\n"
                f"Box: {bbox}\n"
                f"Coverage: {best_coverage}"
            )

        tile_x, tile_y = best_tile

        converted_bbox = convert_bbox_to_tile(
            bbox,
            tile_x,
            tile_y,
        )

        assignments[best_tile].append(
            {
                "label": annotation["label"],
                "bbox": converted_bbox,
            }
        )

        coverage_values.append(best_coverage)

    # Negative Tiles

    negative_candidates = []

    for (
        tile_x,
        tile_y,
    ) in regular_tile_positions:

        if (
            tile_x,
            tile_y,
        ) in assignments:

            continue

        intersects = tile_intersects_any_annotation(
            tile_x,
            tile_y,
            annotations,
        )

        if not intersects:

            negative_candidates.append(
                (
                    tile_x,
                    tile_y,
                )
            )

    rng.shuffle(negative_candidates)

    selected_negative_tiles = negative_candidates[:NEGATIVE_TILES_PER_IMAGE]

    selected_positions = list(assignments.keys())

    selected_positions.extend(selected_negative_tiles)

    # Tiles speichern

    source_stem = Path(image_name).stem

    created_tiles = []

    for tile_index, (
        tile_x,
        tile_y,
    ) in enumerate(
        selected_positions,
        start=1,
    ):

        crop_x2 = min(
            image.width,
            tile_x + TILE_SIZE,
        )

        crop_y2 = min(
            image.height,
            tile_y + TILE_SIZE,
        )

        tile_image = image.crop(
            (
                tile_x,
                tile_y,
                crop_x2,
                crop_y2,
            )
        )

        tile_filename = (
            f"{source_stem}"
            f"__tile_"
            f"{tile_index:03d}"
            f"_x{tile_x}"
            f"_y{tile_y}"
            f".png"
        )

        tile_image_path = OUTPUT_IMAGE_DIR / tile_filename

        tile_image.save(tile_image_path)

        tile_annotations = assignments.get(
            (
                tile_x,
                tile_y,
            ),
            [],
        )

        tile_label_data = {
            "image": tile_filename,
            "width": tile_image.width,
            "height": tile_image.height,
            "source_image": image_name,
            "tile_x": tile_x,
            "tile_y": tile_y,
            "annotations": tile_annotations,
        }

        tile_label_path = OUTPUT_LABEL_DIR / (Path(tile_filename).stem + ".json")

        with open(
            tile_label_path,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                tile_label_data,
                file,
                indent=4,
                ensure_ascii=False,
            )

        created_tiles.append(tile_label_data)

    minimum_coverage = min(coverage_values) if coverage_values else None

    return (
        created_tiles,
        minimum_coverage,
        custom_tile_count,
    )


# STATISTIK


def calculate_statistics(
    all_tiles,
):

    class_counter = Counter()

    positive_tiles = 0
    negative_tiles = 0

    for tile in all_tiles:

        annotations = tile["annotations"]

        if annotations:
            positive_tiles += 1

        else:
            negative_tiles += 1

        for annotation in annotations:

            class_counter[annotation["label"]] += 1

    return (
        positive_tiles,
        negative_tiles,
        class_counter,
    )


# MAIN


def main():

    print("Sauberen Tile-Datensatz erstellen")

    print("================================")

    print(f"\nTile-Größe: " f"{TILE_SIZE} × {TILE_SIZE}")

    print(f"Overlap: " f"{OVERLAP}")

    print(f"Stride: " f"{STRIDE}")

    print("\nRegel:")

    print("Jede Original-Annotation wird " "genau einem Tile zugeordnet.")

    print("Falls nötig, wird das Tile " "automatisch verschoben.")

    prepare_output_directories()

    rng = random.Random(RANDOM_SEED)

    label_files = sorted(SOURCE_LABEL_DIR.glob("*.json"))

    all_tiles = []

    global_minimum_coverage = 1.0

    total_custom_tiles = 0

    for index, label_path in enumerate(
        label_files,
        start=1,
    ):

        (
            tiles,
            minimum_coverage,
            custom_tile_count,
        ) = process_document(
            label_path,
            rng,
        )

        all_tiles.extend(tiles)

        total_custom_tiles += custom_tile_count

        if minimum_coverage is not None:

            global_minimum_coverage = min(
                global_minimum_coverage,
                minimum_coverage,
            )

        print(
            f"{index:02d}/"
            f"{len(label_files):02d} "
            f"{label_path.name} "
            f"-> "
            f"{len(tiles)} Tiles"
        )

    (
        positive_tiles,
        negative_tiles,
        class_counter,
    ) = calculate_statistics(all_tiles)

    total_boxes = sum(class_counter.values())

    print("\n================================")

    print("ERGEBNIS")

    print("================================")

    print(f"\nOriginalpläne: " f"{len(label_files)}")

    print(f"Gespeicherte Tiles: " f"{len(all_tiles)}")

    print(f"Positive Tiles: " f"{positive_tiles}")

    print(f"Negative Tiles: " f"{negative_tiles}")

    print(f"Speziell verschobene Tiles: " f"{total_custom_tiles}")

    print(f"\nBounding Boxes insgesamt: " f"{total_boxes}")

    print("\nBounding Boxes pro Klasse:")

    for class_name in [
        "STATION_FIELD",
        "LINE_FIELD",
        "PLAN_NUMBER_FIELD",
    ]:

        print(f"{class_name:25} " f"{class_counter[class_name]}")

    print("\nSchlechteste Box-Abdeckung " "im zugeordneten Tile:")

    print(f"{global_minimum_coverage:.2%}")


if __name__ == "__main__":
    main()
