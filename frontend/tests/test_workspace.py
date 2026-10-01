"""Focused tests: review persistence, exports, previews and the backend contract."""

import base64
import csv
import io
import json
import tempfile
import threading
import zipfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from workspace import Workspace


def image_file(name="00000018.TIF", multipage=False):
    buffer = io.BytesIO()
    image = Image.new("RGB", (32, 24), "white")
    image.save(
        buffer,
        format="TIFF",
        save_all=multipage,
        append_images=[Image.new("RGB", (20, 10), "blue")] if multipage else [],
    )
    return {"name": name, "data": base64.b64encode(buffer.getvalue()).decode()}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.temp.name)
        self.job = self.ws.create(
            "Review test", [image_file(), image_file("000000018.TIF")]
        )
        self.doc = self.job["documents"][0]

    def tearDown(self):
        self.temp.cleanup()

    def test_edits_persist_and_reviewed_export_uses_corrected_values(self):
        self.ws.merge_results(
            self.job,
            [
                {
                    "filename": "00000018.TIF",
                    "station": {"value": "OCR name", "confidence": 0.6},
                }
            ],
        )
        self.ws.update(
            self.job,
            self.doc["id"],
            {"station": "Straße", "line": "", "plan_number": "0012"},
            "reviewed",
        )
        restored = self.ws.load(self.job["id"])
        result = json.loads(base64.b64decode(self.ws.export(restored, "json")["data"]))[
            "results"
        ]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["station"], "Straße")
        self.assertIsNone(result[0]["line"])
        self.assertEqual(result[0]["plan_number"], "0012")
        self.assertEqual(result[0]["original_values"]["station"], "OCR name")
        self.assertEqual(result[0]["ocr_confidence"]["station"], 0.6)
        self.assertTrue(result[0]["manually_changed"]["station"])
        self.assertEqual(restored["documents"][1]["filename"], "000000018.TIF")

    def test_edit_requires_review_again_and_all_export_labels_unreviewed(self):
        self.ws.update(self.job, self.doc["id"], {"station": "A"}, "reviewed")
        self.ws.update(self.job, self.doc["id"], {"station": "B"})
        with self.assertRaises(ValueError):
            self.ws.export(self.job, "json")
        exported = json.loads(
            base64.b64decode(self.ws.export(self.job, "json", "all")["data"])
        )
        self.assertEqual(exported["results"][0]["review_status"], "unreviewed")
        self.assertIsNone(exported["results"][0]["reviewed_at"])

    def test_csv_escapes_formulas_and_preserves_unicode_and_zeroes(self):
        self.ws.update(
            self.job,
            self.doc["id"],
            {"station": "=1+1", "line": "U2", "plan_number": "00045"},
            "reviewed",
        )
        raw = base64.b64decode(self.ws.export(self.job, "csv")["data"]).decode(
            "utf-8-sig"
        )
        row = list(csv.DictReader(io.StringIO(raw)))[0]
        self.assertEqual(row["station"], "'=1+1")
        self.assertEqual(row["filename"], "00000018.TIF")
        self.assertEqual(row["plan_number"], "00045")

    def test_new_ocr_retains_manual_correction_and_resets_review(self):
        self.ws.update(self.job, self.doc["id"], {"station": "Human value"}, "reviewed")
        self.ws.merge_results(
            self.job,
            [{"filename": self.doc["filename"], "station": "New OCR", "line": "E 37"}],
        )
        self.assertEqual(self.doc["values"]["station"], "Human value")
        self.assertEqual(self.doc["values"]["line"], "E 37")
        self.assertEqual(self.doc["original_values"]["station"], "New OCR")
        self.assertEqual(self.doc["review_status"], "unreviewed")

    def test_filenames_match_exactly_and_duplicates_rejected(self):
        with self.assertRaises(ValueError):
            self.ws.merge_results(self.job, [{"filename": "18.TIF"}])
        with self.assertRaises(ValueError):
            self.ws.create("Bad", [image_file(), image_file()])

    def test_tiff_page_preview(self):
        job = self.ws.create("Pages", [image_file(multipage=True)])
        p = self.ws.preview(job, job["documents"][0]["id"], 1)
        self.assertEqual(p["pages"], 2)
        self.assertEqual(p["page"], 1)
        image = Image.open(io.BytesIO(base64.b64decode(p["url"].split(",")[1])))
        self.assertEqual(image.size, (20, 10))

    def test_pdf_is_rejected(self):
        with self.assertRaises(ValueError):
            self.ws.create("PDF", [{"name": "plan.pdf", "data": image_file()["data"]}])

    def test_more_than_ten_files_and_persistent_job_numbers(self):
        job = self.ws.create(
            "Batch", [image_file(f"folder/{i:04}.tif") for i in range(42)]
        )
        self.assertEqual(len(job["documents"]), 42)
        another = Workspace(self.temp.name).create("Next", [image_file()])
        self.assertEqual(another["number"], job["number"] + 1)
        self.assertEqual(
            Workspace(self.temp.name).load(job["id"])["number"], job["number"]
        )

    def test_zip_nested_paths_and_non_plan_files(self):
        buf = io.BytesIO()
        raw = base64.b64decode(image_file()["data"])
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("a/plan.tif", raw)
            archive.writestr("b/plan.tif", raw)
            archive.writestr("notes.txt", "ignore")
        job = self.ws.create(
            "ZIP",
            [{"name": "plans.zip", "data": base64.b64encode(buf.getvalue()).decode()}],
        )
        self.assertEqual(
            [d["filename"] for d in job["documents"]],
            ["plans/a/plan.tif", "plans/b/plan.tif"],
        )
        self.assertEqual(job["skipped_files"], 1)
        self.assertEqual(self.ws.preview(job, job["documents"][0]["id"])["pages"], 1)

    def test_zip_path_traversal_is_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("../outside.tif", b"bad")
        with self.assertRaises(ValueError):
            self.ws.create(
                "Bad ZIP",
                [
                    {
                        "name": "bad.zip",
                        "data": base64.b64encode(buf.getvalue()).decode(),
                    }
                ],
            )
        self.assertFalse((Path(self.temp.name).parent / "outside.tif").exists())

    def test_chunk_upload_retains_bytes_and_rejects_wrong_offset(self):
        from workspace import new_id

        raw = base64.b64decode(image_file()["data"])
        job = self.ws.begin_upload("Chunks")
        token = new_id()
        middle = len(raw) // 2
        self.ws.upload_chunk(
            job,
            token,
            "folder/plan.tif",
            len(raw),
            0,
            base64.b64encode(raw[:middle]).decode(),
        )
        with self.assertRaises(ValueError):
            self.ws.upload_chunk(
                job,
                token,
                "folder/plan.tif",
                len(raw),
                0,
                base64.b64encode(raw[:middle]).decode(),
            )
        job = self.ws.load(job["id"])
        self.ws.upload_chunk(
            job,
            token,
            "folder/plan.tif",
            len(raw),
            middle,
            base64.b64encode(raw[middle:]).decode(),
        )
        self.ws.finish_upload(job)
        stored = self.ws.directory(job["id"]) / job["documents"][0]["stored"]
        self.assertEqual(stored.read_bytes(), raw)

    def test_station_suggestion_can_be_accepted_or_dismissed(self):
        self.ws.merge_results(
            self.job,
            [
                {
                    "filename": self.doc["filename"],
                    "station": "Haltestelle Kieduichstrame",
                    "station_suggestion": {
                        "name": "Friedrichstraße",
                        "read_text": "Haltestelle Kieduichstrame",
                        "similarity": 0.733,
                    },
                }
            ],
        )
        self.assertEqual(self.doc["values"]["station"], "Haltestelle Kieduichstrame")
        self.assertEqual(self.doc["station_suggestion"]["name"], "Friedrichstraße")
        self.ws.apply_station_suggestion(self.job, self.doc["id"], "accept")
        self.assertEqual(self.doc["values"]["station"], "Friedrichstraße")
        self.assertTrue(self.doc["manually_changed"]["station"])
        self.assertIsNone(self.doc["station_suggestion"])

        self.doc["values"]["station"] = None
        self.doc["manually_changed"]["station"] = False
        self.ws.merge_results(
            self.job,
            [
                {
                    "filename": self.doc["filename"],
                    "station": "Haltestelle Kieduichstrame",
                    "station_suggestion": {
                        "name": "Friedrichstraße",
                        "read_text": "Haltestelle Kieduichstrame",
                        "similarity": 0.733,
                    },
                }
            ],
        )
        self.ws.apply_station_suggestion(self.job, self.doc["id"], "dismiss")
        self.assertEqual(self.doc["values"]["station"], "Haltestelle Kieduichstrame")
        self.assertIsNone(self.doc["station_suggestion"])

    def test_backend_contract_with_http_server(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                assert b"00000018.TIF" in body
                self.reply({"job_id": "test-job"})

            def do_GET(self):
                if self.path.endswith("/results"):
                    self.reply(
                        {
                            "results": [
                                {
                                    "filename": "00000018.TIF",
                                    "station": "Backend station",
                                },
                                {"filename": "000000018.TIF", "station": None},
                            ]
                        }
                    )
                else:
                    self.reply({"status": "completed", "processed": 2, "failed": 0})

            def reply(self, value):
                body = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.ws.start_backend(
                self.job, "http://127.0.0.1:" + str(server.server_port)
            )
            self.ws.poll_backend(self.job)
            self.assertEqual(self.job["processing_status"], "completed")
            self.assertEqual(self.doc["values"]["station"], "Backend station")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
