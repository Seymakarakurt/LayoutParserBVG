import json
from collections import Counter
from pathlib import Path

import torch
from PIL import Image
from torchvision.transforms import functional as F

from torchvision.models.detection import (
    FasterRCNN_ResNet50_FPN_Weights,
    fasterrcnn_resnet50_fpn,
)

from torchvision.models.detection.faster_rcnn import (
    FastRCNNPredictor,
)

# KONFIGURATION

BASE_DIR = Path(__file__).resolve().parent.parent

IMAGE_DIR = BASE_DIR / "data" / "annotations_tiled" / "images"

LABEL_DIR = BASE_DIR / "data" / "annotations_tiled" / "labels"

MODEL_PATH = BASE_DIR / "models" / "layout_detector_v3.pth"

OUTPUT_DIR = BASE_DIR / "data" / "output" / "evaluation"

REPORT_PATH = OUTPUT_DIR / "training_set_evaluation_v3.json"


# KLASSEN

CLASS_NAMES = [
    "__background__",
    "STATION_FIELD",
    "LINE_FIELD",
    "PLAN_NUMBER_FIELD",
]


# MODELLPARAMETER V3

MIN_SIZE = 800
MAX_SIZE = 1333

SCORE_THRESHOLD = 0.30
IOU_THRESHOLD = 0.50


Image.MAX_IMAGE_PIXELS = None


# DEVICE


def get_device():

    if torch.backends.mps.is_available():

        return torch.device("mps")

    return torch.device("cpu")


# MODELL ERSTELLEN


def create_model():

    num_classes = len(CLASS_NAMES)

    weights = FasterRCNN_ResNet50_FPN_Weights.DEFAULT

    model = fasterrcnn_resnet50_fpn(
        weights=weights,
        min_size=MIN_SIZE,
        max_size=MAX_SIZE,
    )

    in_features = model.roi_heads.box_predictor.cls_score.in_features

    model.roi_heads.box_predictor = FastRCNNPredictor(
        in_features,
        num_classes,
    )

    return model


# MODELL LADEN


def load_model(
    device,
):

    if not MODEL_PATH.exists():

        raise FileNotFoundError(f"V3-Modell nicht gefunden: " f"{MODEL_PATH}")

    model = create_model()

    state_dict = torch.load(
        MODEL_PATH,
        map_location="cpu",
    )

    model.load_state_dict(state_dict)

    model.to(device)

    model.eval()

    return model


# IOU


def calculate_iou(
    box_a,
    box_b,
):

    x1 = max(
        box_a[0],
        box_b[0],
    )

    y1 = max(
        box_a[1],
        box_b[1],
    )

    x2 = min(
        box_a[2],
        box_b[2],
    )

    y2 = min(
        box_a[3],
        box_b[3],
    )

    intersection_width = max(
        0,
        x2 - x1,
    )

    intersection_height = max(
        0,
        y2 - y1,
    )

    intersection_area = intersection_width * intersection_height

    area_a = max(
        0,
        box_a[2] - box_a[0],
    ) * max(
        0,
        box_a[3] - box_a[1],
    )

    area_b = max(
        0,
        box_b[2] - box_b[0],
    ) * max(
        0,
        box_b[3] - box_b[1],
    )

    union_area = area_a + area_b - intersection_area

    if union_area <= 0:
        return 0.0

    return intersection_area / union_area


# GROUND TRUTH LADEN


def load_ground_truth(
    label_path,
):

    with open(
        label_path,
        "r",
        encoding="utf-8",
    ) as file:

        data = json.load(file)

    ground_truth = []

    for annotation in data.get(
        "annotations",
        [],
    ):

        ground_truth.append(
            {
                "label": annotation["label"],
                "bbox": [float(value) for value in annotation["bbox"]],
            }
        )

    return (
        data,
        ground_truth,
    )


# PREDICTION


def run_prediction(
    model,
    image,
    device,
):

    image_tensor = F.to_tensor(image).to(device)

    with torch.no_grad():

        output = model([image_tensor])[0]

    predictions = []

    boxes = output["boxes"].detach().cpu()

    labels = output["labels"].detach().cpu()

    scores = output["scores"].detach().cpu()

    for (
        box,
        label_id,
        score,
    ) in zip(
        boxes,
        labels,
        scores,
    ):

        score_value = float(score)

        if score_value < SCORE_THRESHOLD:
            continue

        class_id = int(label_id)

        if class_id <= 0 or class_id >= len(CLASS_NAMES):
            continue

        predictions.append(
            {
                "label": CLASS_NAMES[class_id],
                "bbox": [
                    float(box[0]),
                    float(box[1]),
                    float(box[2]),
                    float(box[3]),
                ],
                "score": score_value,
            }
        )

    predictions.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return predictions


# KLASSENWEISE AUSWERTUNG


def evaluate_class(
    ground_truth,
    predictions,
    class_name,
):

    gt_boxes = [item["bbox"] for item in ground_truth if (item["label"] == class_name)]

    pred_boxes = [item for item in predictions if (item["label"] == class_name)]

    matched_gt = set()

    true_positives = 0
    false_positives = 0

    matched_ious = []

    for prediction in pred_boxes:

        best_iou = 0.0
        best_gt_index = None

        for (
            gt_index,
            gt_box,
        ) in enumerate(gt_boxes):

            if gt_index in matched_gt:
                continue

            iou = calculate_iou(
                prediction["bbox"],
                gt_box,
            )

            if iou > best_iou:

                best_iou = iou
                best_gt_index = gt_index

        if best_gt_index is not None and best_iou >= IOU_THRESHOLD:

            true_positives += 1

            matched_gt.add(best_gt_index)

            matched_ious.append(best_iou)

        else:

            false_positives += 1

    false_negatives = len(gt_boxes) - len(matched_gt)

    return {
        "tp": true_positives,
        "fp": false_positives,
        "fn": false_negatives,
        "ious": matched_ious,
    }


# KLASSENVERWECHSLUNGEN


def analyze_confusions(
    ground_truth,
    predictions,
):

    matched_gt = set()

    confusion_counter = Counter()

    correct_location_and_class = 0
    wrong_class_same_location = 0

    for prediction in predictions:

        best_iou = 0.0
        best_gt_index = None

        for (
            gt_index,
            gt_item,
        ) in enumerate(ground_truth):

            if gt_index in matched_gt:
                continue

            iou = calculate_iou(
                prediction["bbox"],
                gt_item["bbox"],
            )

            if iou > best_iou:

                best_iou = iou
                best_gt_index = gt_index

        if best_gt_index is None or best_iou < IOU_THRESHOLD:
            continue

        matched_gt.add(best_gt_index)

        ground_truth_label = ground_truth[best_gt_index]["label"]

        predicted_label = prediction["label"]

        if ground_truth_label == predicted_label:

            correct_location_and_class += 1

        else:

            wrong_class_same_location += 1

            confusion_key = f"{ground_truth_label}" f" -> " f"{predicted_label}"

            confusion_counter[confusion_key] += 1

    return {
        "correct_location_and_class": correct_location_and_class,
        "wrong_class_same_location": wrong_class_same_location,
        "confusions": confusion_counter,
    }


# METRIKEN


def calculate_metrics(
    tp,
    fp,
    fn,
):

    if (tp + fp) > 0:

        precision = tp / (tp + fp)

    else:

        precision = 0.0

    if (tp + fn) > 0:

        recall = tp / (tp + fn)

    else:

        recall = 0.0

    if (precision + recall) > 0:

        f1 = 2 * precision * recall / (precision + recall)

    else:

        f1 = 0.0

    return (
        precision,
        recall,
        f1,
    )


# MAIN


def main():

    print("V3 Tile Evaluation")

    print("==================")

    device = get_device()

    print(f"\nGerät: " f"{device}")

    print(f"Score Threshold: " f"{SCORE_THRESHOLD}")

    print(f"IoU Threshold: " f"{IOU_THRESHOLD}")

    print(f"MIN_SIZE: " f"{MIN_SIZE}")

    print(f"MAX_SIZE: " f"{MAX_SIZE}")

    print("\nLade V3-Modell...")

    model = load_model(device)

    print("V3-Modell geladen.")

    label_files = sorted(LABEL_DIR.glob("*.json"))

    print(f"\nTiles: " f"{len(label_files)}")

    class_results = {
        class_name: {
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "ious": [],
        }
        for class_name in CLASS_NAMES[1:]
    }

    confusion_total = Counter()

    correct_location_and_class = 0
    wrong_class_same_location = 0

    total_ground_truth = 0
    total_predictions = 0

    positive_tiles = 0
    negative_tiles = 0

    negative_tiles_with_predictions = 0

    per_tile_results = []

    for (
        index,
        label_path,
    ) in enumerate(
        label_files,
        start=1,
    ):

        (
            label_data,
            ground_truth,
        ) = load_ground_truth(label_path)

        image_path = IMAGE_DIR / label_data["image"]

        if not image_path.exists():

            raise FileNotFoundError(f"Bild fehlt: " f"{image_path}")

        image = Image.open(image_path).convert("RGB")

        predictions = run_prediction(
            model,
            image,
            device,
        )

        total_ground_truth += len(ground_truth)

        total_predictions += len(predictions)

        if ground_truth:

            positive_tiles += 1

        else:

            negative_tiles += 1

            if predictions:

                negative_tiles_with_predictions += 1

        tile_result = {
            "image": label_data["image"],
            "source_image": label_data.get("source_image"),
            "ground_truth_count": len(ground_truth),
            "prediction_count": len(predictions),
            "classes": {},
        }

        for class_name in CLASS_NAMES[1:]:

            result = evaluate_class(
                ground_truth,
                predictions,
                class_name,
            )

            class_results[class_name]["tp"] += result["tp"]

            class_results[class_name]["fp"] += result["fp"]

            class_results[class_name]["fn"] += result["fn"]

            class_results[class_name]["ious"].extend(result["ious"])

            tile_result["classes"][class_name] = {
                "tp": result["tp"],
                "fp": result["fp"],
                "fn": result["fn"],
            }

        confusion_result = analyze_confusions(
            ground_truth,
            predictions,
        )

        correct_location_and_class += confusion_result["correct_location_and_class"]

        wrong_class_same_location += confusion_result["wrong_class_same_location"]

        confusion_total.update(confusion_result["confusions"])

        per_tile_results.append(tile_result)

        print(
            f"{index:03d}/"
            f"{len(label_files):03d} "
            f"{label_data['image']} "
            f"| GT: "
            f"{len(ground_truth)} "
            f"| Pred: "
            f"{len(predictions)}"
        )

    # ERGEBNISSE

    print("\n=======================")

    print("ERGEBNISSE V3")

    print("=======================")

    report_classes = {}

    total_tp = 0
    total_fp = 0
    total_fn = 0

    for class_name in CLASS_NAMES[1:]:

        result = class_results[class_name]

        tp = result["tp"]

        fp = result["fp"]

        fn = result["fn"]

        (
            precision,
            recall,
            f1,
        ) = calculate_metrics(
            tp,
            fp,
            fn,
        )

        if result["ious"]:

            mean_iou = sum(result["ious"]) / len(result["ious"])

        else:

            mean_iou = 0.0

        total_tp += tp
        total_fp += fp
        total_fn += fn

        print(f"\n{class_name}")

        print("-" * len(class_name))

        print(f"TP:        " f"{tp}")

        print(f"FP:        " f"{fp}")

        print(f"FN:        " f"{fn}")

        print(f"Precision: " f"{precision:.3f}")

        print(f"Recall:    " f"{recall:.3f}")

        print(f"F1:        " f"{f1:.3f}")

        print(f"Mean IoU:  " f"{mean_iou:.3f}")

        report_classes[class_name] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(
                precision,
                4,
            ),
            "recall": round(
                recall,
                4,
            ),
            "f1": round(
                f1,
                4,
            ),
            "mean_iou": round(
                mean_iou,
                4,
            ),
        }

    (
        overall_precision,
        overall_recall,
        overall_f1,
    ) = calculate_metrics(
        total_tp,
        total_fp,
        total_fn,
    )

    print("\nGESAMT")

    print("------")

    print(f"TP:        " f"{total_tp}")

    print(f"FP:        " f"{total_fp}")

    print(f"FN:        " f"{total_fn}")

    print(f"Precision: " f"{overall_precision:.3f}")

    print(f"Recall:    " f"{overall_recall:.3f}")

    print(f"F1:        " f"{overall_f1:.3f}")

    # NEGATIVE TILES

    print("\nNEGATIVE TILES")

    print("--------------")

    print(f"Negative Tiles: " f"{negative_tiles}")

    print(
        "Negative Tiles mit "
        "mindestens einer Prediction: "
        f"{negative_tiles_with_predictions}"
    )

    # KLASSENVERWECHSLUNGEN

    print("\nKLASSENVERWECHSLUNGEN")

    print("---------------------")

    print("Richtige Position + " "richtige Klasse: " f"{correct_location_and_class}")

    print("Richtige Position, " "aber falsche Klasse: " f"{wrong_class_same_location}")

    if confusion_total:

        print("\nVerwechslungen:")

        for (
            confusion,
            count,
        ) in confusion_total.most_common():

            print(f"  " f"{confusion}: " f"{count}")

    else:

        print("\nKeine Klassenverwechslungen " f"mit IoU >= " f"{IOU_THRESHOLD}.")

    # REPORT

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    report = {
        "model": "layout_detector_v3.pth",
        "score_threshold": SCORE_THRESHOLD,
        "iou_threshold": IOU_THRESHOLD,
        "min_size": MIN_SIZE,
        "max_size": MAX_SIZE,
        "number_of_tiles": len(label_files),
        "positive_tiles": positive_tiles,
        "negative_tiles": negative_tiles,
        "negative_tiles_with_predictions": negative_tiles_with_predictions,
        "ground_truth_boxes": total_ground_truth,
        "predictions": total_predictions,
        "classes": report_classes,
        "overall": {
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            "precision": round(
                overall_precision,
                4,
            ),
            "recall": round(
                overall_recall,
                4,
            ),
            "f1": round(
                overall_f1,
                4,
            ),
        },
        "class_confusions": {
            "correct_location_and_class": correct_location_and_class,
            "wrong_class_same_location": wrong_class_same_location,
            "confusions": dict(confusion_total),
        },
        "tiles": per_tile_results,
    }

    with open(
        REPORT_PATH,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            report,
            file,
            indent=4,
            ensure_ascii=False,
        )

    print("\nReport gespeichert:")

    print(REPORT_PATH)


if __name__ == "__main__":
    main()
