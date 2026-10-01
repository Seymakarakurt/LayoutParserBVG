"""Extract only the station fields from an OCR-candidate JSON."""

import argparse
import json
from pathlib import Path

from extract_information_v2 import find_station, suggest_station_name

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "data" / "output" / "extracted"


def main():
    parser = argparse.ArgumentParser(
        description="Select station name and suggestion from station OCR candidates."
    )
    parser.add_argument("ocr_json", help="OCR candidate JSON")
    args = parser.parse_args()

    input_path = Path(args.ocr_json)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    with input_path.open("r", encoding="utf-8") as file:
        items = json.load(file)

    unexpected_labels = sorted(
        {
            item.get("label")
            for item in items
            if item.get("label") != "STATION_FIELD"
        },
        key=str,
    )
    if unexpected_labels:
        raise ValueError(
            "Station-only extraction received non-station labels: "
            + ", ".join(map(str, unexpected_labels))
        )

    station_candidates = find_station(items)
    station_name = station_candidates[0]["value"] if station_candidates else None
    station_suggestion = suggest_station_name(items, station_name)

    result = {
        "station_name": station_name,
        "station_suggestion": station_suggestion,
        "line": None,
        "plan_number": None,
        "station_only": True,
        "debug": {"station_candidates": station_candidates[:10]},
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{input_path.stem}_extracted.json"
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, indent=4, ensure_ascii=False)

    print("Station-only extraction")
    print(f"Station:    {station_name}")
    print(f"Suggestion: {station_suggestion}")
    print(f"JSON:       {output_path}")


if __name__ == "__main__":
    main()
