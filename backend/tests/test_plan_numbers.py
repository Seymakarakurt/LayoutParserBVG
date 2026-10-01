import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import extract_information_v2 as ex


class PlanNumberFieldReadingTests(unittest.TestCase):

    def test_keeps_connected_identifier_string(self):

        cases = {
            "A318-005": "A318-005",
            "Zeichnungs-Nr.: 1925 - 8105 - 00": "1925-8105-00",
            "ZG-NR. 1744-8401-01": "1744-8401-01",
            "Σ 504. Ein. 01": "Σ504.Ein.01",
            "£504. Ein.": "Σ504.Ein",
            "D99-023x": "D99-023x",
        }

        for text, expected in cases.items():

            cleaned = ex.clean_plan_field_reading(text)

            self.assertEqual(
                cleaned,
                expected,
                msg=text,
            )

            self.assertTrue(
                ex.is_usable_plan_field_reading(cleaned),
                msg=text,
            )

    def test_rejects_non_identifiers(self):

        for text in [
            "none",
            "not readable",
            "1:50",
            "SCHNITT D-D",
            "ierte Leitung",
        ]:

            cleaned = ex.clean_plan_field_reading(text)

            self.assertFalse(
                ex.is_usable_plan_field_reading(cleaned),
                msg=text,
            )

    def test_plan_field_ocr_wins_on_saved_plans(self):

        root = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "output"
            / "ocr_candidates_original"
        )

        expected = {
            "A_318_005_ocr_original.json": "A318-005",
            "S_504_Ein_01_ocr_original.json": "Σ504.Ein",
            "G_90_a_ocr_original.json": "1925-8105-00",
        }

        for name, want in expected.items():

            path = root / name

            if not path.exists():

                self.skipTest(f"OCR-Datei fehlt: {name}")

            winner = ex.find_plan_numbers(
                json.loads(path.read_text())
            )[0]["value"]

            self.assertEqual(
                winner,
                want,
                msg=name,
            )


if __name__ == "__main__":
    unittest.main()
