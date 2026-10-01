import json
from pathlib import Path

import torch

from torch.optim.lr_scheduler import StepLR
from torch.utils.data import DataLoader

from torchvision.models.detection import (
    FasterRCNN_ResNet50_FPN_Weights,
    fasterrcnn_resnet50_fpn,
)

from torchvision.models.detection.faster_rcnn import (
    FastRCNNPredictor,
)

from tiled_layout_dataset import (
    TiledLayoutDataset,
)

# KONFIGURATION

BASE_DIR = Path(__file__).resolve().parent.parent

MODEL_DIR = BASE_DIR / "models"

MODEL_PATH = MODEL_DIR / "layout_detector_v3.pth"

CHECKPOINT_PATH = MODEL_DIR / "layout_detector_checkpoint_v3.pth"

HISTORY_PATH = MODEL_DIR / "training_history_v3.json"


# KLASSEN

CLASS_NAMES = [
    "__background__",
    "STATION_FIELD",
    "LINE_FIELD",
    "PLAN_NUMBER_FIELD",
]


# TRAININGSPARAMETER

EPOCHS = 10

BATCH_SIZE = 1

LEARNING_RATE = 0.001

MOMENTUM = 0.9

WEIGHT_DECAY = 0.0005

RANDOM_SEED = 42


# Interne Faster-R-CNN-Auflösung. Die Pläne kommen als 1600-Pixel-Kacheln.

MIN_SIZE = 800

MAX_SIZE = 1333


# DEVICE


def get_device():

    if torch.backends.mps.is_available():

        return torch.device("mps")

    return torch.device("cpu")


# MODELL


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


# COLLATE FUNCTION


def collate_fn(
    batch,
):

    return tuple(zip(*batch))


# AUF DEVICE VERSCHIEBEN


def move_to_device(
    images,
    targets,
    device,
):

    images = [image.to(device) for image in images]

    converted_targets = []

    for target in targets:

        converted_target = {}

        for key, value in target.items():

            if torch.is_tensor(value):

                converted_target[key] = value.to(device)

            else:

                converted_target[key] = value

        converted_targets.append(converted_target)

    return (
        images,
        converted_targets,
    )


# DATASET-STATISTIK


def print_dataset_statistics(
    dataset,
):

    total_boxes = 0

    negative_tiles = 0

    class_counts = {
        1: 0,
        2: 0,
        3: 0,
    }

    for index in range(len(dataset)):

        _, target = dataset[index]

        labels = target["labels"]

        total_boxes += len(labels)

        if len(labels) == 0:

            negative_tiles += 1

        for label_id in labels.tolist():

            class_counts[label_id] += 1

    print(f"Tiles: " f"{len(dataset)}")

    print(f"Bounding Boxes: " f"{total_boxes}")

    print(f"Negative Tiles: " f"{negative_tiles}")

    print()

    print(f"STATION_FIELD: " f"{class_counts[1]}")

    print(f"LINE_FIELD: " f"{class_counts[2]}")

    print(f"PLAN_NUMBER_FIELD: " f"{class_counts[3]}")


# SMOKE TEST


def smoke_test(
    model,
    optimizer,
    data_loader,
    device,
):

    print("\nTechnischer Trainingstest...")

    model.train()

    positive_batch = None

    # Ein Tile mit mindestens einer Box, sonst sagt der Test nichts.
    for (
        images,
        targets,
    ) in data_loader:

        number_of_boxes = sum(len(target["labels"]) for target in targets)

        if number_of_boxes > 0:

            positive_batch = (
                images,
                targets,
            )

            break

    if positive_batch is None:

        raise RuntimeError("Kein positives Tile " "für Smoke-Test gefunden.")

    images, targets = positive_batch

    (
        images,
        targets,
    ) = move_to_device(
        images,
        targets,
        device,
    )

    optimizer.zero_grad(set_to_none=True)

    loss_dict = model(
        images,
        targets,
    )

    total_loss = sum(loss for loss in loss_dict.values())

    total_loss.backward()

    optimizer.zero_grad(set_to_none=True)

    print("Technischer Test erfolgreich.")

    print(f"Test-Loss: " f"{total_loss.item():.4f}")

    print("\nLoss-Komponenten:")

    for (
        loss_name,
        loss_value,
    ) in loss_dict.items():

        print(f"  " f"{loss_name:25} " f"{loss_value.item():.4f}")


# EINE EPOCHE TRAINIEREN


def train_one_epoch(
    model,
    optimizer,
    data_loader,
    device,
    epoch,
):

    model.train()

    total_epoch_loss = 0.0

    number_of_batches = len(data_loader)

    for (
        batch_number,
        (
            images,
            targets,
        ),
    ) in enumerate(
        data_loader,
        start=1,
    ):

        (
            images,
            targets,
        ) = move_to_device(
            images,
            targets,
            device,
        )

        optimizer.zero_grad(set_to_none=True)

        loss_dict = model(
            images,
            targets,
        )

        total_loss = sum(loss for loss in loss_dict.values())

        total_loss.backward()

        optimizer.step()

        loss_value = total_loss.item()

        total_epoch_loss += loss_value

        print(
            f"Epoch "
            f"{epoch:02d}/{EPOCHS} "
            f"| Tile "
            f"{batch_number:03d}/"
            f"{number_of_batches:03d} "
            f"| Loss: "
            f"{loss_value:.4f}"
        )

    average_loss = total_epoch_loss / number_of_batches

    return average_loss


# CHECKPOINT


def save_checkpoint(
    model,
    optimizer,
    scheduler,
    epoch,
    average_loss,
    history,
):

    checkpoint = {
        "epoch": epoch,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict(),
        "average_loss": average_loss,
        "class_names": CLASS_NAMES,
        "min_size": MIN_SIZE,
        "max_size": MAX_SIZE,
        "history": history,
    }

    torch.save(
        checkpoint,
        CHECKPOINT_PATH,
    )


# HISTORY


def save_history(
    history,
):

    with open(
        HISTORY_PATH,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            history,
            file,
            indent=4,
            ensure_ascii=False,
        )


# MAIN


def main():

    print("LayoutParserBVG Training V3")

    print("===========================")

    torch.manual_seed(RANDOM_SEED)

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    device = get_device()

    print(f"\nGerät: " f"{device}")

    print("\nV3-Konfiguration:")

    print(f"MIN_SIZE = " f"{MIN_SIZE}")

    print(f"MAX_SIZE = " f"{MAX_SIZE}")

    print("\nLade Tile-Dataset...")

    dataset = TiledLayoutDataset()

    print_dataset_statistics(dataset)

    data_loader = DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=0,
        collate_fn=collate_fn,
    )

    print("\nErstelle " "COCO-vortrainiertes " "Faster R-CNN...")

    model = create_model()

    model.to(device)

    trainable_parameters = [
        parameter for parameter in model.parameters() if parameter.requires_grad
    ]

    optimizer = torch.optim.SGD(
        trainable_parameters,
        lr=LEARNING_RATE,
        momentum=MOMENTUM,
        weight_decay=WEIGHT_DECAY,
    )

    scheduler = StepLR(
        optimizer,
        step_size=5,
        gamma=0.1,
    )

    smoke_test(
        model=model,
        optimizer=optimizer,
        data_loader=data_loader,
        device=device,
    )

    print("\n========================")

    print("Fine-Tuning V3 startet")

    print("========================")

    history = []

    for epoch in range(
        1,
        EPOCHS + 1,
    ):

        print(f"\n--- Epoch " f"{epoch}/{EPOCHS} ---\n")

        average_loss = train_one_epoch(
            model=model,
            optimizer=optimizer,
            data_loader=data_loader,
            device=device,
            epoch=epoch,
        )

        current_learning_rate = optimizer.param_groups[0]["lr"]

        print(f"\nEpoch " f"{epoch} abgeschlossen.")

        print(f"Durchschnittlicher Loss: " f"{average_loss:.4f}")

        print(f"Learning Rate: " f"{current_learning_rate}")

        history.append(
            {
                "epoch": epoch,
                "average_loss": average_loss,
                "learning_rate": current_learning_rate,
            }
        )

        save_checkpoint(
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            epoch=epoch,
            average_loss=average_loss,
            history=history,
        )

        save_history(history)

        scheduler.step()

        print("Checkpoint gespeichert.")

    torch.save(
        model.state_dict(),
        MODEL_PATH,
    )

    print("\n========================")

    print("TRAINING V3 ABGESCHLOSSEN")

    print("========================")

    print("\nFinales Modell:")

    print(MODEL_PATH)

    print("\nTraining History:")

    print(HISTORY_PATH)

    print("\nLetzter Checkpoint:")

    print(CHECKPOINT_PATH)


if __name__ == "__main__":
    main()
