import json
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# PFADE

BASE_DIR = Path(__file__).resolve().parent.parent

ANALYZE_SCRIPT = BASE_DIR / "src" / "analyze_plan.py"

API_JOBS_DIR = BASE_DIR / "data" / "api_jobs"

EXTRACTED_DIR = BASE_DIR / "data" / "output" / "extracted"


# EINSTELLUNGEN

SUPPORTED_SUFFIXES = {
    ".tif",
    ".tiff",
    ".png",
    ".jpg",
    ".jpeg",
}

# Ein Plan nach dem anderen. Die Schritte schreiben in gemeinsame Ordner.
PIPELINE_LOCK = threading.Lock()


# FASTAPI

app = FastAPI(
    title="BVG Plan Analyzer API",
    version="1.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# JOBS IM SPEICHER

jobs = {}


# HILFSFUNKTIONEN


def save_job(job_id):

    job = jobs[job_id]

    job_dir = API_JOBS_DIR / job_id

    job_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    job_file = job_dir / "job.json"

    with open(
        job_file,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            job,
            file,
            ensure_ascii=False,
            indent=2,
        )


def load_saved_jobs():

    if not API_JOBS_DIR.is_dir():

        return

    for job_file in API_JOBS_DIR.glob("*/job.json"):

        try:

            with open(
                job_file,
                "r",
                encoding="utf-8",
            ) as file:

                job = json.load(file)

        except (
            OSError,
            json.JSONDecodeError,
        ):

            continue

        job_id = job.get("job_id")

        if not job_id:

            continue

        if job.get("status") in {
            "queued",
            "processing",
        }:

            job["status"] = "failed"

            job["current_file"] = None

            job["message"] = (
                "Der Auftrag wurde abgebrochen, "
                "weil das Backend neu gestartet wurde."
            )

            jobs[job_id] = job

            save_job(job_id)

            continue

        jobs[job_id] = job


load_saved_jobs()


def print_recorded_times(
    log_path,
    filename,
):

    if not log_path.exists():

        return

    layout_time = None

    ocr_time = None

    with open(
        log_path,
        "r",
        encoding="utf-8",
    ) as log_file:

        for line in log_file:

            line = line.strip()

            if line.startswith("LAUFZEIT Layout-Erkennung:"):

                layout_time = line.split(":", 1)[1].split("|", 1)[0].strip()

            elif line.startswith("LAUFZEIT Texterkennung:"):

                ocr_time = line.split(":", 1)[1].split("|", 1)[0].strip()

    if not layout_time and not ocr_time:

        return

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # In das Backend-Terminal schreiben, neben den 200-Meldungen.
    print("", file=sys.stderr, flush=True)
    print(
        f"[{stamp}] {filename} fertig",
        file=sys.stderr,
        flush=True,
    )

    if layout_time:

        print(
            f"time for layout detection: {layout_time}",
            file=sys.stderr,
            flush=True,
        )

    if ocr_time:

        print(
            f"ocr time: {ocr_time}",
            file=sys.stderr,
            flush=True,
        )

    print("", file=sys.stderr, flush=True)


def run_pipeline_for_file(
    job_id,
    file_info,
):

    stored_path = Path(file_info["stored_path"])

    original_filename = file_info["filename"]

    stem = stored_path.stem

    log_dir = API_JOBS_DIR / job_id / "logs"

    log_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_path = log_dir / f"{stem}.log"

    # Alte Ergebnisdatei löschen

    extracted_json = EXTRACTED_DIR / (f"{stem}" f"_ocr_original_extracted.json")

    if extracted_json.exists():
        extracted_json.unlink()

    # Pipeline starten

    with PIPELINE_LOCK:

        with open(
            log_path,
            "w",
            encoding="utf-8",
        ) as log_file:

            process = subprocess.run(
                [
                    sys.executable,
                    str(ANALYZE_SCRIPT),
                    str(stored_path),
                ],
                cwd=BASE_DIR,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )

    # Laufzeiten nur hier ausgeben, nicht an das Frontend.
    print_recorded_times(
        log_path,
        original_filename,
    )

    # Fehler

    if process.returncode != 0:

        return {
            "filename": original_filename,
            "station": None,
            "line": None,
            "plan_number": None,
            "status": "error",
            "message": ("Die Pipeline konnte " "die Datei nicht verarbeiten."),
        }

    if not extracted_json.exists():

        return {
            "filename": original_filename,
            "station": None,
            "line": None,
            "plan_number": None,
            "status": "error",
            "message": ("Die Ergebnisdatei wurde " "nicht erzeugt."),
        }

    # Ergebnis laden

    with open(
        extracted_json,
        "r",
        encoding="utf-8",
    ) as result_file:

        result = json.load(result_file)

    # Extraktion speichert station_name, die API gibt station zurück.
    return {
        "filename": original_filename,
        "station": result.get("station_name"),
        "station_suggestion": result.get("station_suggestion"),
        "line": result.get("line"),
        "plan_number": result.get("plan_number"),
        "status": "success",
    }


def process_job(job_id):

    job = jobs[job_id]

    job["status"] = "processing"
    job["processed"] = 0
    job["failed"] = 0
    job["current_file"] = None

    save_job(job_id)

    try:

        for file_info in job["files"]:

            job["current_file"] = file_info["filename"]

            save_job(job_id)

            result = run_pipeline_for_file(
                job_id,
                file_info,
            )

            job["results"].append(result)

            job["processed"] += 1

            if result.get("status") != "success":
                job["failed"] += 1

            save_job(job_id)

        job["current_file"] = None
        job["status"] = "completed"

        save_job(job_id)

    except Exception as exc:

        job["status"] = "failed"
        job["message"] = str(exc)

        save_job(job_id)


# TEST-ENDPOINT


@app.get("/")
def root():

    return {
        "status": "ok",
        "message": ("BVG Plan Analyzer API läuft"),
    }


# 1. DOKUMENTE HOCHLADEN


@app.post("/api/documents/process")
async def submit_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
):

    if not files:

        raise HTTPException(
            status_code=400,
            detail=("Es wurden keine Dateien " "hochgeladen."),
        )

    job_id = uuid.uuid4().hex

    job_dir = API_JOBS_DIR / job_id

    upload_dir = job_dir / "uploads"

    upload_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    stored_files = []

    seen_names = set()

    for index, upload in enumerate(
        files,
        start=1,
    ):

        original_filename = upload.filename or f"document_{index}"

        if original_filename in seen_names:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Doppelte Dateinamen "
                    "werden nicht unterstützt: "
                    f"{original_filename}"
                ),
            )

        seen_names.add(original_filename)

        suffix = Path(original_filename).suffix.lower()

        if suffix == ".pdf":

            raise HTTPException(
                status_code=415,
                detail="PDF wird nicht verarbeitet.",
            )

        if suffix not in SUPPORTED_SUFFIXES:

            raise HTTPException(
                status_code=415,
                detail=("Nicht unterstütztes " "Dateiformat: " f"{original_filename}"),
            )

        # Eigener interner Dateiname,
        # damit sich Uploads verschiedener Jobs
        # nicht gegenseitig überschreiben.
        stored_filename = f"{job_id}_" f"{index:03d}" f"{suffix}"

        stored_path = upload_dir / stored_filename

        with open(
            stored_path,
            "wb",
        ) as buffer:

            shutil.copyfileobj(
                upload.file,
                buffer,
            )

        await upload.close()

        stored_files.append(
            {
                "filename": original_filename,
                "stored_path": str(stored_path),
            }
        )

    jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "total": len(stored_files),
        "processed": 0,
        "failed": 0,
        "current_file": None,
        "files": stored_files,
        "results": [],
        "message": None,
    }

    save_job(job_id)

    # Verarbeitung beginnt erst,
    # nachdem die HTTP-Antwort zurückging.
    background_tasks.add_task(
        process_job,
        job_id,
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "documents": len(stored_files),
    }


# 2. JOB-STATUS


@app.get("/api/jobs/{job_id}")
def get_job_status(
    job_id: str,
):

    job = jobs.get(job_id)

    if job is None:

        raise HTTPException(
            status_code=404,
            detail="Job nicht gefunden.",
        )

    return {
        "job_id": job_id,
        "status": job["status"],
        "total": job["total"],
        "processed": job["processed"],
        "failed": job["failed"],
        "current_file": job["current_file"],
        "message": job.get("message"),
    }


# 3. ERGEBNISSE


@app.get("/api/jobs/{job_id}/results")
def get_job_results(
    job_id: str,
):

    job = jobs.get(job_id)

    if job is None:

        raise HTTPException(
            status_code=404,
            detail="Job nicht gefunden.",
        )

    if job["status"] != "completed":

        raise HTTPException(
            status_code=409,
            detail=("Job ist noch nicht " "abgeschlossen."),
        )

    return {
        "job_id": job_id,
        "results": job["results"],
    }
