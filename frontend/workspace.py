"""Local files, review state, previews and exports. No OCR/model code."""

import base64
import csv
import io
import json
import uuid
import shutil
import stat
import zipfile

from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps
import requests

# Große Plan-Scans (wie im Backend) dürfen für die Vorschau
# geladen werden. Pillow blockiert sonst mit "decompression bomb".
Image.MAX_IMAGE_PIXELS = None

from api_client import (
    ALLOWED_SUFFIXES,
    local_base_url,
    submit_documents,
)

FIELDS = (
    "station",
    "line",
    "plan_number",
)

CHUNK_BYTES = 4 * 1024 * 1024


def now():

    return datetime.now(timezone.utc).isoformat()


def new_id():

    return uuid.uuid4().hex


class Workspace:

    def __init__(
        self,
        root,
    ):

        self.root = Path(root)

        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

    # JOB-ORDNER

    def directory(
        self,
        job_id,
    ):

        if (
            not isinstance(
                job_id,
                str,
            )
            or len(job_id) != 32
            or any(c not in "0123456789abcdef" for c in job_id)
        ):

            raise ValueError("Invalid job ID.")

        return self.root / job_id

    # JOB SPEICHERN

    def save(
        self,
        job,
    ):

        folder = self.directory(job["id"])

        folder.mkdir(exist_ok=True)

        job["updated_at"] = now()

        temp = folder / "job.tmp"

        temp.write_text(
            json.dumps(
                job,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        temp.replace(folder / "job.json")

    # VORHANDENE JOB-NUMMERN

    def existing_job_numbers(
        self,
    ):

        numbers = []

        for path in self.root.glob("*/job.json"):

            try:

                job = json.loads(path.read_text(encoding="utf-8"))

                number = job.get("number")

                if isinstance(
                    number,
                    int,
                ):

                    numbers.append(number)

            except (
                OSError,
                ValueError,
                json.JSONDecodeError,
            ):

                continue

        return numbers

    # NÄCHSTE JOB-NUMMER

    def next_job_number(
        self,
    ):

        numbers = self.existing_job_numbers()

        if not numbers:

            return 1

        return max(numbers) + 1

    # JOB LADEN

    def load(
        self,
        job_id,
    ):

        job_path = self.directory(job_id) / "job.json"

        job = json.loads(job_path.read_text(encoding="utf-8"))

        # Alte Jobs ohne Nummer
        # bekommen beim ersten Laden
        # automatisch eine Nummer.
        if "number" not in job:

            job["number"] = self.next_job_number()

            job["name"] = "J" + str(job["number"])

            self.save(job)

        return job

    # JOBS AUFLISTEN

    def list_jobs(
        self,
    ):

        jobs = []

        paths = sorted(
            self.root.glob("*/job.json"),
            key=lambda p: p.stat().st_mtime,
        )

        for path in paths:

            try:

                job = self.load(path.parent.name)

                jobs.append(
                    {
                        k: job[k]
                        for k in (
                            "id",
                            "number",
                            "name",
                            "created_at",
                            "updated_at",
                            "processing_status",
                        )
                    }
                )

                jobs[-1]["total"] = len(job["documents"])

                jobs[-1]["reviewed"] = sum(
                    d["review_status"] == "reviewed" for d in job["documents"]
                )

                progress = job.get("progress") or {}

                jobs[-1]["processed"] = int(progress.get("processed") or 0)

            except (
                ValueError,
                KeyError,
                OSError,
            ):

                continue

        return sorted(
            jobs,
            key=lambda j: j["updated_at"],
            reverse=True,
        )

    # JOB LÖSCHEN

    def delete_job(
        self,
        job_id,
    ):

        folder = self.directory(job_id)

        if not folder.exists():

            raise FileNotFoundError("Job not found.")

        shutil.rmtree(folder)

    # NEUEN UPLOAD BEGINNEN

    def begin_upload(
        self,
        name=None,
    ):

        job_id = new_id()

        number = self.next_job_number()

        job = {
            "id": job_id,
            "number": number,
            "name": ("J" + str(number)),
            "created_at": now(),
            "processing_status": "uploading",
            "backend_id": None,
            "backend_url": None,
            "documents": [],
            "incoming": {},
            "skipped_files": 0,
        }

        self.save(job)

        return job

    # PROGRAMMATISCHER UPLOAD

    def create(
        self,
        name,
        files,
    ):

        if not files:

            raise ValueError("Choose at least one file.")

        names = [str(f["name"]) for f in files]

        if len(set(names)) != len(names):

            raise ValueError("Duplicate file paths " "in one job are not supported.")

        job = self.begin_upload(name)

        for item in files:

            raw = base64.b64decode(
                item["data"],
                validate=True,
            )

            token = new_id()

            for offset in range(
                0,
                max(
                    len(raw),
                    1,
                ),
                CHUNK_BYTES,
            ):

                chunk = raw[offset : offset + CHUNK_BYTES]

                self.upload_chunk(
                    job,
                    token,
                    item["name"],
                    len(raw),
                    offset,
                    base64.b64encode(chunk).decode(),
                )

        self.finish_upload(job)

        return job

    # DATEINAMEN SICHERN

    @staticmethod
    def clean_relative_name(
        name,
    ):

        name = str(name).replace(
            "\\",
            "/",
        )

        path = PurePosixPath(name)

        if (
            not name
            or not path.parts
            or any(
                c in name
                for c in (
                    "\r",
                    "\n",
                )
            )
            or path.is_absolute()
            or ".." in path.parts
            or ":" in path.parts[0]
            or "\x00" in name
        ):

            raise ValueError("Invalid file path " "inside the upload.")

        return str(path)

    # UPLOAD-CHUNK

    def upload_chunk(
        self,
        job,
        token,
        name,
        size,
        offset,
        encoded,
    ):

        if job["processing_status"] != "uploading":

            raise ValueError("This job is not " "accepting uploads.")

        token = str(token).replace(
            "-",
            "",
        )

        if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):

            raise ValueError("Invalid upload token.")

        name = self.clean_relative_name(name)

        if Path(name).suffix.lower() not in (ALLOWED_SUFFIXES | {".zip"}):

            raise ValueError(f"Unsupported file type: " f"{name}")

        raw = base64.b64decode(
            encoded,
            validate=True,
        )

        if (
            len(raw) > CHUNK_BYTES
            or size <= 0
            or offset < 0
            or (offset + len(raw)) > size
        ):

            raise ValueError("Invalid upload chunk.")

        current = job["incoming"].setdefault(
            token,
            {
                "name": name,
                "size": size,
                "received": 0,
            },
        )

        if (
            current["name"] != name
            or current["size"] != size
            or current["received"] != offset
        ):

            raise ValueError(
                "Upload offset does not match. " "Please upload this file again."
            )

        if shutil.disk_usage(self.root).free < len(raw):

            raise ValueError("There is not enough " "disk space for the upload.")

        target = self.directory(job["id"]) / (token + ".upload")

        with target.open("ab") as handle:

            handle.write(raw)

        current["received"] += len(raw)

        self.save(job)

        if current["received"] == size:

            self.add_uploaded_path(
                job,
                name,
                target,
            )

            target.unlink(missing_ok=True)

            del job["incoming"][token]

            self.save(job)

    # DATEI / ZIP HINZUFÜGEN

    def add_uploaded_path(
        self,
        job,
        name,
        source,
    ):

        existing = {d["filename"] for d in job["documents"]}

        folder = self.directory(job["id"])

        added = []
        created = []

        def add(
            filename,
            stream,
        ):

            if filename in existing:

                raise ValueError(f"Duplicate file path: " f"{filename}")

            existing.add(filename)

            doc_id = new_id()

            stored = doc_id + Path(filename).suffix.lower()

            target = folder / stored

            created.append(target)

            with target.open("wb") as output:

                shutil.copyfileobj(
                    stream,
                    output,
                    length=(1024 * 1024),
                )

            added.append(
                {
                    "id": doc_id,
                    "filename": filename,
                    "stored": stored,
                    "review_status": "unreviewed",
                    "values": {key: None for key in FIELDS},
                    "original_values": {key: None for key in FIELDS},
                    "confidence": {key: None for key in FIELDS},
                    "manually_changed": {key: False for key in FIELDS},
                    "evidence": None,
                    "bbox": None,
                    "station_suggestion": None,
                    "processing_error": None,
                    "original_result": None,
                }
            )

        try:

            if Path(name).suffix.lower() == ".zip":

                with zipfile.ZipFile(source) as archive:

                    plans = []
                    skipped = 0

                    for info in archive.infolist():

                        if info.is_dir():

                            continue

                        relative = self.clean_relative_name(info.filename)

                        if (
                            "__MACOSX" in PurePosixPath(relative).parts
                            or Path(relative).suffix.lower() not in ALLOWED_SUFFIXES
                        ):

                            skipped += 1

                            continue

                        if stat.S_ISLNK(info.external_attr >> 16) or (
                            info.flag_bits & 1
                        ):

                            raise ValueError(
                                "ZIP links and "
                                "password-protected entries "
                                "are not supported."
                            )

                        plans.append(
                            (
                                info,
                                str(PurePosixPath(name).with_suffix("") / relative),
                            )
                        )

                    if not plans:

                        raise ValueError("The ZIP contains " "no supported plan files.")

                    total_size = sum(info.file_size for info, _ in plans)

                    if total_size > shutil.disk_usage(self.root).free:

                        raise ValueError(
                            "There is not enough " "disk space to unpack " "this ZIP."
                        )

                    for info, filename in plans:

                        with archive.open(info) as stream:

                            add(
                                filename,
                                stream,
                            )

                    job["skipped_files"] += skipped

            else:

                with source.open("rb") as stream:

                    add(
                        name,
                        stream,
                    )

        except Exception:

            for target in created:

                target.unlink(missing_ok=True)

            raise

        job["documents"].extend(added)

    # UPLOAD ABSCHLIESSEN

    def finish_upload(
        self,
        job,
    ):

        if job.get("incoming"):

            raise ValueError("Some files have not " "finished uploading.")

        if not job["documents"]:

            raise ValueError("Choose at least one " "supported plan file.")

        job["processing_status"] = "manual"

        self.save(job)

    # UPLOAD ABBRECHEN

    def stop_upload(
        self,
        job,
    ):

        for token in job.get(
            "incoming",
            {},
        ):

            (self.directory(job["id"]) / (token + ".upload")).unlink(missing_ok=True)

        job["incoming"] = {}

        job["processing_status"] = "manual" if job["documents"] else "upload_failed"

        self.save(job)

    # DOKUMENT HOLEN

    def document(
        self,
        job,
        doc_id,
    ):

        return next(d for d in job["documents"] if d["id"] == doc_id)

    # DOKUMENT AKTUALISIEREN

    def update(
        self,
        job,
        doc_id,
        values,
        review_status=None,
    ):

        doc = self.document(
            job,
            doc_id,
        )

        changed = False

        for key in FIELDS:

            value = str(values.get(key) or "").strip() or None

            if value is not None and len(value) > 1000:

                raise ValueError("A field value exceeds " "1,000 characters.")

            changed |= value != doc["values"][key]

            doc["values"][key] = value

            doc["manually_changed"][key] = value != doc["original_values"][key]

        suggestion = doc.get("station_suggestion") or {}

        if suggestion.get("name") and doc["values"].get("station") == suggestion.get("name"):

            doc["station_suggestion"] = None

        if changed:

            doc["review_status"] = "unreviewed"

            doc.pop(
                "reviewed_at",
                None,
            )

        if review_status is not None:

            if review_status not in {
                "reviewed",
                "unresolved",
                "unreviewed",
            }:

                raise ValueError("Invalid review status.")

            doc["review_status"] = review_status

            if review_status == "reviewed":

                doc["reviewed_at"] = now()

        self.save(job)

    def apply_station_suggestion(
        self,
        job,
        doc_id,
        decision,
    ):

        doc = self.document(
            job,
            doc_id,
        )

        suggestion = doc.get("station_suggestion") or {}

        name = suggestion.get("name")

        if decision == "accept" and name:

            doc["values"]["station"] = name

            doc["manually_changed"]["station"] = name != doc["original_values"].get(
                "station"
            )

            doc["review_status"] = "unreviewed"

            doc.pop(
                "reviewed_at",
                None,
            )

        elif decision != "dismiss":

            raise ValueError("Invalid suggestion decision.")

        doc["station_suggestion"] = None

        self.save(job)

    # VORSCHAU

    def preview(
        self,
        job,
        doc_id,
        page=0,
    ):

        doc = self.document(
            job,
            doc_id,
        )

        path = self.directory(job["id"]) / doc["stored"]

        with Image.open(path) as original:

            count = getattr(
                original,
                "n_frames",
                1,
            )

            page = max(
                0,
                min(
                    int(page),
                    count - 1,
                ),
            )

            original.seek(page)

            image = ImageOps.exif_transpose(original).convert("RGB")

            image.thumbnail(
                (
                    6000,
                    6000,
                )
            )

        out = io.BytesIO()

        image.save(
            out,
            format="PNG",
        )

        return {
            "url": (
                "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()
            ),
            "page": page,
            "pages": count,
        }

    # BACKEND-ERGEBNISSE ÜBERNEHMEN

    def merge_results(
        self,
        job,
        records,
    ):

        if not isinstance(
            records,
            list,
        ) or any(
            not isinstance(
                record,
                dict,
            )
            for record in records
        ):

            raise ValueError("Results must be " "a list of objects.")

        by_name = {}

        for record in records:

            name = record.get("filename") or record.get("document_id")

            if name in by_name:

                raise ValueError(f"Duplicate result " f"filename: {name}")

            by_name[name] = record

        known = {d["filename"] for d in job["documents"]}

        if set(by_name) - known:

            raise ValueError(
                "Result filenames must "
                "match the uploaded filenames "
                "exactly, including leading zeros."
            )

        for doc in job["documents"]:

            result = by_name.get(doc["filename"])

            if result is None:

                doc["processing_error"] = "No result returned " "for this file."

                continue

            doc["original_result"] = result

            for key in FIELDS:

                raw = result.get(key)

                value = (
                    raw.get("value")
                    if isinstance(
                        raw,
                        dict,
                    )
                    else raw
                )

                value = str(value) if value is not None else None

                score = (
                    raw.get("confidence")
                    if isinstance(
                        raw,
                        dict,
                    )
                    else None
                )

                doc["original_values"][key] = value

                doc["confidence"][key] = (
                    score
                    if (
                        isinstance(
                            score,
                            (
                                int,
                                float,
                            ),
                        )
                        and not isinstance(
                            score,
                            bool,
                        )
                    )
                    else None
                )

                if not doc["manually_changed"][key]:

                    doc["values"][key] = value

            suggestion = result.get("station_suggestion")

            if (
                isinstance(
                    suggestion,
                    dict,
                )
                and isinstance(
                    suggestion.get("name"),
                    str,
                )
                and suggestion.get("name").strip()
                and suggestion.get("name").strip() != (doc["values"].get("station") or "")
            ):

                doc["station_suggestion"] = {
                    "name": suggestion["name"].strip()[:200],
                    "read_text": str(suggestion.get("read_text") or "")[:500],
                    "similarity": (
                        float(suggestion["similarity"])
                        if isinstance(
                            suggestion.get("similarity"),
                            (
                                int,
                                float,
                            ),
                        )
                        and not isinstance(
                            suggestion.get("similarity"),
                            bool,
                        )
                        else None
                    ),
                }

            else:

                doc["station_suggestion"] = None

            doc["evidence"] = result.get("evidence")

            doc["bbox"] = result.get("bbox")

            doc["processing_error"] = (
                result.get(
                    "message",
                    "Processing failed.",
                )
                if result.get("status")
                in (
                    "error",
                    "failed",
                )
                else None
            )

            doc["review_status"] = "unreviewed"

            doc.pop(
                "reviewed_at",
                None,
            )

        self.save(job)

    # BACKEND STARTEN

    def start_backend(
        self,
        job,
        address,
    ):

        if job["processing_status"] == "processing":

            raise ValueError("This job is already processing.")

        address = local_base_url(address)

        uploads = []

        for doc in job["documents"]:

            uploads.append(
                DiskUpload(
                    doc["filename"],
                    (self.directory(job["id"]) / doc["stored"]),
                )
            )

        backend_id = submit_documents(
            address,
            uploads,
        )

        job.update(
            backend_id=backend_id,
            backend_url=address,
            processing_status="processing",
            progress={},
        )

        self.save(job)

    # BACKEND STATUS

    def poll_backend(
        self,
        job,
    ):

        if job["processing_status"] != "processing":

            return

        from urllib.parse import quote

        path = (
            job["backend_url"]
            + "/api/jobs/"
            + quote(
                job["backend_id"],
                safe="",
            )
        )

        response = requests.get(
            path,
            timeout=15,
        )

        response.raise_for_status()

        status = response.json()

        job["progress"] = status

        if status.get("status") == "completed":

            response = requests.get(
                path + "/results",
                timeout=30,
            )

            response.raise_for_status()

            self.merge_results(
                job,
                response.json().get("results"),
            )

            job["processing_status"] = "completed"

        elif status.get("status") in (
            "error",
            "failed",
            "cancelled",
        ):

            job["processing_status"] = str(status["status"])

            job["backend_error"] = status.get("message") or job["processing_status"]

        self.save(job)

    # EXPORT

    def export(
        self,
        job,
        fmt,
        scope="reviewed",
    ):

        if fmt not in (
            "csv",
            "json",
        ) or scope not in (
            "reviewed",
            "all",
        ):

            raise ValueError("Invalid export selection.")

        docs = [
            d
            for d in job["documents"]
            if (scope == "all" or d["review_status"] == "reviewed")
        ]

        if not docs:

            raise ValueError("No documents match " "the export selection.")

        if fmt == "json":

            data = {
                "job_number": ("J" + str(job["number"])),
                "job_name": ("J" + str(job["number"])),
                "exported_at": now(),
                "scope": scope,
                "results": [
                    {
                        "filename": d["filename"],
                        **d["values"],
                        "review_status": d["review_status"],
                        "reviewed_at": d.get("reviewed_at"),
                        "original_values": d["original_values"],
                        "ocr_confidence": d["confidence"],
                        "manually_changed": d["manually_changed"],
                        "evidence": d["evidence"],
                        "bbox": d["bbox"],
                        "processing_error": d["processing_error"],
                    }
                    for d in docs
                ],
            }

            raw = json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ).encode()

            mime = "application/json"

        else:

            out = io.StringIO(newline="")

            writer = csv.DictWriter(
                out,
                fieldnames=[
                    "filename",
                    *FIELDS,
                    "review_status",
                    "manually_changed",
                ],
            )

            writer.writeheader()

            for doc in docs:

                row = {
                    "filename": doc["filename"],
                    **doc["values"],
                    "review_status": doc["review_status"],
                    "manually_changed": ",".join(
                        key for key in FIELDS if doc["manually_changed"][key]
                    ),
                }

                writer.writerow({key: csv_safe(value) for (key, value) in row.items()})

            raw = out.getvalue().encode("utf-8-sig")

            mime = "text/csv;charset=utf-8"

        return {
            "filename": ("plan_metadata." + fmt),
            "mime": mime,
            "data": base64.b64encode(raw).decode(),
        }


# UPLOAD-OBJEKT


class Upload:

    def __init__(
        self,
        name,
        raw,
    ):

        self.name = name

        self.raw = raw

        self.size = len(raw)

    def getvalue(
        self,
    ):

        return self.raw


# CSV-SICHERHEIT


def csv_safe(
    value,
):

    text = "" if value is None else str(value)

    return (
        "'" + text
        if (
            text.lstrip()[:1]
            in (
                "=",
                "+",
                "-",
                "@",
            )
            or text[:1]
            in (
                "\t",
                "\r",
                "\n",
            )
        )
        else text
    )


# DATEI VON DISK AN API SENDEN


class DiskUpload:

    def __init__(
        self,
        name,
        path,
    ):

        self.name = name

        self.path = path

        self.size = path.stat().st_size

    def open(
        self,
    ):

        return self.path.open("rb")
