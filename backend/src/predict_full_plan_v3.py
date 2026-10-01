import argparse
import json
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont
from torchvision.transforms import functional as F
from torchvision.models.detection import fasterrcnn_resnet50_fpn
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
from torchvision.ops import nms

# PFADE

BASE_DIR = Path(__file__).resolve().parent.parent

MODEL_PATH = BASE_DIR / "models" / "layout_detector_v3.pth"

OUTPUT_DIR = BASE_DIR / "data" / "output" / "full_plan_predictions"


# KLASSEN

CLASS_NAMES = [
    "__background__",
    "STATION_FIELD",
    "LINE_FIELD",
    "PLAN_NUMBER_FIELD",
]


# MODELLPARAMETER

MIN_SIZE = 800
MAX_SIZE = 1333


# TILE-PARAMETER

TILE_WIDTH = 1600
TILE_HEIGHT = 1600

STRIDE_X = 300
STRIDE_Y = 1000


# SCORE-THRESHOLDS

CLASS_THRESHOLDS = {
    "STATION_FIELD": 0.30,
    "LINE_FIELD": 0.01,
    "PLAN_NUMBER_FIELD": 0.30,
}


# ARTEFAKT-FILTER

# Extrem kleine Boxen können keine sinnvollen
# Station-/Linien-/Plannummer-Felder sein.

MIN_BOX_WIDTH = 8
MIN_BOX_HEIGHT = 8

# Nähe zum Tile-Rand
EDGE_MARGIN = 2

# Wenn eine Box am Tile-Rand liegt UND zusätzlich
# sehr schmal/klein ist, wird sie verworfen.
EDGE_SMALL_WIDTH = 20
EDGE_SMALL_HEIGHT = 20


# NMS

NMS_IOU_THRESHOLD = 0.30


Image.MAX_IMAGE_PIXELS = None


# DEVICE


def get_device():

    if torch.backends.mps.is_available():
        return torch.device("mps")

    return torch.device("cpu")


# MODELL


def create_model():

    model = fasterrcnn_resnet50_fpn(
        weights=None,
        weights_backbone=None,
        min_size=MIN_SIZE,
        max_size=MAX_SIZE,
    )

    in_features = model.roi_heads.box_predictor.cls_score.in_features

    model.roi_heads.box_predictor = FastRCNNPredictor(
        in_features,
        len(CLASS_NAMES),
    )

    # LINE_FIELD soll auch bei sehr niedriger
    # Confidence als Kandidat erhalten bleiben.
    model.roi_heads.score_thresh = 0.01

    return model


def load_model(device):

    if not MODEL_PATH.exists():

        raise FileNotFoundError(f"V3-Modell nicht gefunden: {MODEL_PATH}")

    model = create_model()

    state_dict = torch.load(
        MODEL_PATH,
        map_location="cpu",
    )

    model.load_state_dict(state_dict)

    model.to(device)

    model.eval()

    return model


# TILE-POSITIONEN


def generate_positions(
    full_size,
    tile_size,
    stride,
):

    if full_size <= tile_size:
        return [0]

    positions = list(
        range(
            0,
            full_size - tile_size + 1,
            stride,
        )
    )

    last_position = full_size - tile_size

    if positions[-1] != last_position:

        positions.append(last_position)

    return positions


# ARTEFAKT-PRÜFUNG


def check_artifact(
    local_box,
    tile_width,
    tile_height,
):

    x1, y1, x2, y2 = local_box

    width = x2 - x1
    height = y2 - y1

    # 1. Extrem kleine Prediction

    if width < MIN_BOX_WIDTH or height < MIN_BOX_HEIGHT:

        return True, "too_small"

    # 2. Liegt Prediction direkt am Tile-Rand?

    touches_left = x1 <= EDGE_MARGIN

    touches_right = x2 >= tile_width - EDGE_MARGIN

    touches_top = y1 <= EDGE_MARGIN

    touches_bottom = y2 >= tile_height - EDGE_MARGIN

    touches_edge = touches_left or touches_right or touches_top or touches_bottom

    # Kleine Prediction direkt am Rand:
    # sehr wahrscheinlich Tile-Artefakt.

    if touches_edge and (width < EDGE_SMALL_WIDTH or height < EDGE_SMALL_HEIGHT):

        return True, "tile_edge"

    return False, None


# TILE PREDICTION


def predict_tile(
    model,
    tile,
    device,
    offset_x,
    offset_y,
):

    tensor = F.to_tensor(tile).to(device)

    with torch.no_grad():

        output = model([tensor])[0]

    predictions = []

    artifact_stats = {
        "too_small": 0,
        "tile_edge": 0,
    }

    boxes = output["boxes"].detach().cpu()

    labels = output["labels"].detach().cpu()

    scores = output["scores"].detach().cpu()

    tile_width, tile_height = tile.size

    for (
        box,
        label_id,
        score,
    ) in zip(
        boxes,
        labels,
        scores,
    ):

        class_id = int(label_id)

        if class_id <= 0 or class_id >= len(CLASS_NAMES):
            continue

        class_name = CLASS_NAMES[class_id]

        score_value = float(score)

        threshold = CLASS_THRESHOLDS[class_name]

        if score_value < threshold:
            continue

        local_box = box.tolist()

        # Artefakte entfernen

        is_artifact, reason = check_artifact(
            local_box=local_box,
            tile_width=tile_width,
            tile_height=tile_height,
        )

        if is_artifact:

            artifact_stats[reason] += 1

            continue

        global_box = [
            local_box[0] + offset_x,
            local_box[1] + offset_y,
            local_box[2] + offset_x,
            local_box[3] + offset_y,
        ]

        predictions.append(
            {
                "label": class_name,
                "score": score_value,
                "bbox": global_box,
                "tile_origin": [
                    offset_x,
                    offset_y,
                ],
            }
        )

    return (
        predictions,
        artifact_stats,
    )


# NMS


def apply_classwise_nms(
    predictions,
):

    final_predictions = []

    for class_name in CLASS_NAMES[1:]:

        class_predictions = [
            prediction
            for prediction in predictions
            if prediction["label"] == class_name
        ]

        if not class_predictions:
            continue

        boxes = torch.tensor(
            [prediction["bbox"] for prediction in class_predictions],
            dtype=torch.float32,
        )

        scores = torch.tensor(
            [prediction["score"] for prediction in class_predictions],
            dtype=torch.float32,
        )

        keep_indices = nms(
            boxes,
            scores,
            NMS_IOU_THRESHOLD,
        )

        for keep_index in keep_indices.tolist():

            final_predictions.append(class_predictions[keep_index])

    final_predictions.sort(
        key=lambda prediction: prediction["score"],
        reverse=True,
    )

    return final_predictions


# FONT


def get_font(size):

    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]

    for font_path in font_paths:

        if Path(font_path).exists():

            try:

                return ImageFont.truetype(
                    font_path,
                    size,
                )

            except Exception:
                pass

    return ImageFont.load_default()


# PREVIEW


def draw_predictions(
    image,
    predictions,
):

    result = image.copy()

    draw = ImageDraw.Draw(result)

    font = get_font(30)

    class_colors = {
        "STATION_FIELD": "red",
        "LINE_FIELD": "blue",
        "PLAN_NUMBER_FIELD": "green",
    }

    for prediction in predictions:

        label = prediction["label"]

        score = prediction["score"]

        x1, y1, x2, y2 = prediction["bbox"]

        color = class_colors[label]

        draw.rectangle(
            (
                x1,
                y1,
                x2,
                y2,
            ),
            outline=color,
            width=5,
        )

        label_text = f"{label} " f"{score:.3f}"

        draw.text(
            (
                x1,
                max(
                    0,
                    y1 - 35,
                ),
            ),
            label_text,
            fill=color,
            font=font,
        )

    return result


# FULL PLAN PREDICTION


def run_full_plan_prediction(
    image_path,
):

    print("Full Plan Prediction V3")

    print("=======================")

    device = get_device()

    print(f"\nGerät: {device}")

    print(f"Bild: {image_path}")

    print(f"\nTile Size: " f"{TILE_WIDTH} x {TILE_HEIGHT}")

    print(f"Stride X: {STRIDE_X}")

    print(f"Stride Y: {STRIDE_Y}")

    print("\nArtefakt-Filter:")

    print(f"Min. Box-Breite: " f"{MIN_BOX_WIDTH}px")

    print(f"Min. Box-Höhe: " f"{MIN_BOX_HEIGHT}px")

    print("\nLade V3-Modell...")

    model = load_model(device)

    print("V3-Modell geladen.")

    image = Image.open(image_path).convert("RGB")

    width, height = image.size

    print(f"\nBildgröße: " f"{width} x {height}")

    x_positions = generate_positions(
        width,
        TILE_WIDTH,
        STRIDE_X,
    )

    y_positions = generate_positions(
        height,
        TILE_HEIGHT,
        STRIDE_Y,
    )

    print(f"X-Positionen: " f"{len(x_positions)}")

    print(f"Y-Positionen: " f"{len(y_positions)}")

    total_tiles = len(x_positions) * len(y_positions)

    print(f"Tiles insgesamt: " f"{total_tiles}")

    all_predictions = []

    total_too_small = 0
    total_tile_edge = 0

    tile_number = 0

    for y in y_positions:

        for x in x_positions:

            tile_number += 1

            x2 = min(
                x + TILE_WIDTH,
                width,
            )

            y2 = min(
                y + TILE_HEIGHT,
                height,
            )

            tile = image.crop(
                (
                    x,
                    y,
                    x2,
                    y2,
                )
            )

            (
                predictions,
                artifact_stats,
            ) = predict_tile(
                model=model,
                tile=tile,
                device=device,
                offset_x=x,
                offset_y=y,
            )

            all_predictions.extend(predictions)

            total_too_small += artifact_stats["too_small"]

            total_tile_edge += artifact_stats["tile_edge"]

            print(
                f"Tile "
                f"{tile_number:03d}/"
                f"{total_tiles:03d} "
                f"| x={x:4d} "
                f"| y={y:4d} "
                f"| Predictions="
                f"{len(predictions)}"
                f" | Filtered="
                f"{sum(artifact_stats.values())}"
            )

    # FILTER STATISTIK

    print("\nArtefakte entfernt:")

    print(f"Zu kleine Boxen: " f"{total_too_small}")

    print(f"Tile-Rand-Artefakte: " f"{total_tile_edge}")

    # NMS

    print("\nPredictions vor NMS: " f"{len(all_predictions)}")

    final_predictions = apply_classwise_nms(all_predictions)

    print("Predictions nach NMS: " f"{len(final_predictions)}")

    # AUSGABE

    print("\nErgebnisse:")

    if not final_predictions:

        print("Keine Predictions gefunden.")

    for (
        index,
        prediction,
    ) in enumerate(
        final_predictions,
        start=1,
    ):

        rounded_box = [
            round(
                value,
                1,
            )
            for value in prediction["bbox"]
        ]

        print(
            f"{index:03d}. "
            f"{prediction['label']} "
            f"| Score "
            f"{prediction['score']:.3f} "
            f"| Box "
            f"{rounded_box}"
        )

    # OUTPUT

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    stem = image_path.stem

    json_path = OUTPUT_DIR / f"{stem}_v3_predictions.json"

    preview_path = OUTPUT_DIR / f"{stem}_v3_predictions.png"

    output_data = {
        "image": image_path.name,
        "image_width": width,
        "image_height": height,
        "tile_width": TILE_WIDTH,
        "tile_height": TILE_HEIGHT,
        "stride_x": STRIDE_X,
        "stride_y": STRIDE_Y,
        "thresholds": CLASS_THRESHOLDS,
        "artifact_filter": {
            "min_box_width": MIN_BOX_WIDTH,
            "min_box_height": MIN_BOX_HEIGHT,
            "edge_margin": EDGE_MARGIN,
            "edge_small_width": EDGE_SMALL_WIDTH,
            "edge_small_height": EDGE_SMALL_HEIGHT,
            "removed_too_small": total_too_small,
            "removed_tile_edge": total_tile_edge,
        },
        "nms_iou_threshold": NMS_IOU_THRESHOLD,
        "predictions_before_nms": len(all_predictions),
        "predictions_after_nms": len(final_predictions),
        "predictions": final_predictions,
    }

    with open(
        json_path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            output_data,
            file,
            indent=4,
            ensure_ascii=False,
        )

    preview = draw_predictions(
        image,
        final_predictions,
    )

    preview.save(preview_path)

    print("\nJSON gespeichert:")

    print(json_path)

    print("\nPreview gespeichert:")

    print(preview_path)


# CLI


def main():

    parser = argparse.ArgumentParser(
        description=("V3 Layout Detection " "auf einem vollständigen Plan.")
    )

    parser.add_argument(
        "image",
        type=str,
        help="Pfad zum Planbild",
    )

    args = parser.parse_args()

    image_path = Path(args.image)

    if not image_path.exists():

        raise FileNotFoundError(f"Bild nicht gefunden: " f"{image_path}")

    run_full_plan_prediction(image_path)


if __name__ == "__main__":
    main()
