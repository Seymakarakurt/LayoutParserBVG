import json
from pathlib import Path

import torch

from PIL import Image

from torch.utils.data import Dataset

from torchvision.transforms import functional as F

# PFADE

BASE_DIR = Path(__file__).resolve().parent.parent

IMAGE_DIR = BASE_DIR / "data" / "annotations_tiled" / "images"

LABEL_DIR = BASE_DIR / "data" / "annotations_tiled" / "labels"


# KLASSEN

CLASS_TO_ID = {
    "STATION_FIELD": 1,
    "LINE_FIELD": 2,
    "PLAN_NUMBER_FIELD": 3,
}


# DATASET


class TiledLayoutDataset(Dataset):

    def __init__(self):

        self.label_files = sorted(LABEL_DIR.glob("*.json"))

        if not self.label_files:

            raise RuntimeError("Keine Tile-Annotationen gefunden.")

    def __len__(self):

        return len(self.label_files)

    def __getitem__(
        self,
        index,
    ):

        label_path = self.label_files[index]

        with open(
            label_path,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        image_path = IMAGE_DIR / data["image"]

        if not image_path.exists():

            raise FileNotFoundError(f"Bild nicht gefunden: " f"{image_path}")

        image = Image.open(image_path).convert("RGB")

        image_tensor = F.to_tensor(image)

        boxes = []

        labels = []

        for annotation in data.get(
            "annotations",
            [],
        ):

            label_name = annotation["label"]

            if label_name not in CLASS_TO_ID:

                raise ValueError(f"Unbekannte Klasse: " f"{label_name}")

            x1, y1, x2, y2 = annotation["bbox"]

            if x2 <= x1 or y2 <= y1:

                raise ValueError(
                    f"Ungültige Bounding Box "
                    f"in {label_path.name}: "
                    f"{annotation['bbox']}"
                )

            boxes.append(
                [
                    float(x1),
                    float(y1),
                    float(x2),
                    float(y2),
                ]
            )

            labels.append(CLASS_TO_ID[label_name])

        # Positive oder negative Tiles

        if boxes:

            boxes_tensor = torch.tensor(
                boxes,
                dtype=torch.float32,
            )

            labels_tensor = torch.tensor(
                labels,
                dtype=torch.int64,
            )

            area = (boxes_tensor[:, 2] - boxes_tensor[:, 0]) * (
                boxes_tensor[:, 3] - boxes_tensor[:, 1]
            )

        else:

            boxes_tensor = torch.zeros(
                (
                    0,
                    4,
                ),
                dtype=torch.float32,
            )

            labels_tensor = torch.zeros(
                (0,),
                dtype=torch.int64,
            )

            area = torch.zeros(
                (0,),
                dtype=torch.float32,
            )

        target = {
            "boxes": boxes_tensor,
            "labels": labels_tensor,
            "image_id": torch.tensor(
                [index],
                dtype=torch.int64,
            ),
            "area": area,
            "iscrowd": torch.zeros(
                (len(boxes_tensor),),
                dtype=torch.int64,
            ),
        }

        return (
            image_tensor,
            target,
        )


# TEST


def main():

    print("Tiled Dataset Test")

    print("==================")

    dataset = TiledLayoutDataset()

    print(f"\nTiles im Dataset: " f"{len(dataset)}")

    total_boxes = 0

    negative_tiles = 0

    class_counts = {
        1: 0,
        2: 0,
        3: 0,
    }

    for index in range(len(dataset)):

        image, target = dataset[index]

        labels = target["labels"]

        total_boxes += len(labels)

        if len(labels) == 0:

            negative_tiles += 1

        for label in labels.tolist():

            class_counts[label] += 1

    print(f"Bounding Boxes insgesamt: " f"{total_boxes}")

    print(f"Negative Tiles: " f"{negative_tiles}")

    print()

    print(f"STATION_FIELD: " f"{class_counts[1]}")

    print(f"LINE_FIELD: " f"{class_counts[2]}")

    print(f"PLAN_NUMBER_FIELD: " f"{class_counts[3]}")

    print("\nDataset erfolgreich geladen.")


if __name__ == "__main__":
    main()
