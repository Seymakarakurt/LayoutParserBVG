"""Streamlit host for the HTML review interface and local Python workspace."""

from pathlib import Path
import json
import os
import base64

import requests
import streamlit as st
import streamlit.components.v1 as components

from workspace import Workspace

ROOT = Path(__file__).resolve().parent

BACKEND_URL = os.environ.get("BVG_BACKEND_URL", "http://127.0.0.1:8000")


st.set_page_config(
    page_title="BVG Plan Archive",
    page_icon="🟡",
    layout="wide",
    initial_sidebar_state="collapsed",
)


st.markdown(
    """
    <style>
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stSidebar"],
    [data-testid="stDecoration"],
    #MainMenu,
    footer {
        display:none!important
    }

    html,
    body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {
        margin:0!important;
        padding:0!important;
        overflow:hidden!important
    }

    .block-container,
    [data-testid="stMainBlockContainer"] {
        padding:0!important;
        margin:0!important;
        max-width:none!important;
        width:100%!important
    }

    [data-testid="stVerticalBlock"] {
        gap:0!important
    }

    iframe {
        display:block!important;
        width:100%!important;
        height:100dvh!important;
        border:0!important
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# WORKSPACE

workspace = Workspace(ROOT / "local_jobs")


# CUSTOM FRONTEND COMPONENT

component = components.declare_component("bvg_plan_review", path=str(ROOT / "ui"))


# SESSION STATE

s = st.session_state

defaults = {
    "job_id": None,
    "selected": None,
    "page_index": 0,
    "ack": None,
    "error": None,
    "download": None,
    "view": "overview",
}

for key, value in defaults.items():

    if key not in s:

        s[key] = value


# AKTUELLEN JOB LADEN

job = None

if s.job_id:

    try:

        job = workspace.load(s.job_id)

    except (FileNotFoundError, OSError, ValueError):

        # Falls ein Job gelöscht wurde,
        # darf die Session nicht weiter
        # auf den alten Job zeigen.
        s.job_id = None
        s.selected = None
        s.page_index = 0
        s.view = "overview"

        job = None


# PREVIEW

preview = None
preview_error = None

if job and job["documents"] and job["processing_status"] != "uploading":

    document_ids = [document["id"] for document in job["documents"]]

    if s.selected not in document_ids:

        s.selected = job["documents"][0]["id"]

    cache_key = (job["id"], s.selected, s.page_index)

    if s.get("preview_key") != cache_key:

        try:

            s["preview_data"] = workspace.preview(job, s.selected, s.page_index)

            s["preview_error"] = None

        except Exception as exc:

            s["preview_data"] = None

            s["preview_error"] = f"Preview unavailable: " f"{exc}"

        s["preview_key"] = cache_key

    preview = s.get("preview_data")

    preview_error = s.get("preview_error")


# ÖFFENTLICHE JOB-DATEN FÜR UI

public_job = json.loads(json.dumps(job)) if job else None

if public_job:

    for doc in public_job["documents"]:

        doc.pop("original_result", None)

        doc.pop("stored", None)


# LOGO

logo_path = next(
    (
        ROOT / name
        for name in ("BVG_logo.png", "bvg_logo.png")
        if (ROOT / name).is_file()
    ),
    None,
)

logo_url = None

if logo_path:

    logo_url = (
        "data:image/png;base64," + base64.b64encode(logo_path.read_bytes()).decode()
    )


# JOB-LISTE

jobs = workspace.list_jobs()


# FRONTEND KOMPONENTE

value = component(
    logo_url=logo_url,
    job=public_job,
    jobs=jobs,
    next_job_number=(workspace.next_job_number()),
    selected=s.selected,
    preview=preview,
    preview_error=preview_error,
    ack=s.ack,
    error=s.error,
    download=s.download,
    view=s.view,
    key="review_ui",
    default=None,
)


# EVENTS VERARBEITEN

if value and value.get("id") != s.ack:

    event = value

    s.error = None
    s.download = None

    try:

        kind = event["type"]

        payload = event.get("payload") or {}

        # UPLOAD STARTEN

        if kind == "begin_upload":

            job = workspace.begin_upload()

            s.job_id = job["id"]
            s.selected = None
            s.page_index = 0
            s.view = "upload"

        # JOB DIREKT ERSTELLEN

        elif kind == "create":

            job = workspace.create(payload.get("name"), payload["files"])

            s.job_id = job["id"]

            s.selected = job["documents"][0]["id"] if job["documents"] else None

            s.page_index = 0
            s.view = "review"

            if payload.get("mode") == "backend":

                workspace.start_backend(job, BACKEND_URL)

        # JOB ÖFFNEN

        elif kind == "open":

            job = workspace.load(payload["job_id"])

            s.job_id = job["id"]

            s.selected = job["documents"][0]["id"] if job["documents"] else None

            s.page_index = 0
            s.view = "review"

        # JOB LÖSCHEN

        elif kind == "delete_job":

            deleted_job_id = payload["job_id"]

            workspace.delete_job(deleted_job_id)

            # Falls aktuell genau dieser
            # Job geöffnet war:
            if s.job_id == deleted_job_id:

                s.job_id = None
                s.selected = None
                s.page_index = 0

                # Preview-Cache ebenfalls leeren
                s.pop("preview_key", None)

                s.pop("preview_data", None)

                s.pop("preview_error", None)

            s.view = "overview"

        # DISMISS

        elif kind == "dismiss":

            pass

        # AKTIONEN INNERHALB EINES JOBS

        elif job:

            # Navigation und Bestätigung
            # können aktuelle Eingaben
            # mitsenden.
            if payload.get("draft"):

                draft = payload["draft"]

                workspace.update(job, draft["doc_id"], draft["values"])

            # UPLOAD CHUNK

            if kind == "upload_chunk":

                workspace.upload_chunk(
                    job,
                    payload["token"],
                    payload["name"],
                    int(payload["size"]),
                    int(payload["offset"]),
                    payload["data"],
                )

            # UPLOAD ABSCHLIESSEN

            elif kind == "finish_upload":

                workspace.finish_upload(job)

                s.selected = job["documents"][0]["id"]

                s.page_index = 0
                s.view = "review"

                if payload.get("mode") == "backend":

                    workspace.start_backend(job, BACKEND_URL)

            # UPLOAD STOPPEN

            elif kind == "stop_upload":

                workspace.stop_upload(job)

            # DOKUMENT AUSWÄHLEN

            elif kind == "select":

                workspace.document(job, payload["doc_id"])

                s.selected = payload["doc_id"]

                s.page_index = 0

            # TIFF-SEITE

            elif kind == "page":

                s.page_index = int(payload["page"])

            # SPEICHERN

            elif kind == "save":

                workspace.update(
                    job,
                    payload["doc_id"],
                    payload["values"],
                    payload.get("review_status"),
                )

            elif kind == "station_suggestion":

                workspace.apply_station_suggestion(
                    job,
                    payload["doc_id"],
                    payload.get("decision"),
                )

            # EXPORT

            elif kind == "export":

                s.download = {
                    **workspace.export(job, payload["format"], payload["scope"]),
                    "id": event["id"],
                }

            # IMPORT

            elif kind == "import":

                if len(payload["text"].encode("utf-8")) > 10 * 1024 * 1024:

                    raise ValueError("JSON limit: 10 MB.")

                imported = json.loads(payload["text"])

                records = (
                    imported.get("results") if isinstance(imported, dict) else imported
                )

                workspace.merge_results(job, records)

            # BACKEND-PROCESSING STARTEN

            elif kind == "process":

                workspace.start_backend(job, BACKEND_URL)

            # BACKEND STATUS ABFRAGEN

            elif kind == "poll":

                try:

                    workspace.poll_backend(job)

                except requests.RequestException:

                    job["processing_status"] = "connection_error"

                    workspace.save(job)

                    raise

            # PROCESSING FORTSETZEN

            elif kind == "resume":

                job["processing_status"] = "processing"

                workspace.save(job)

            # UNBEKANNTE AKTION

            else:

                raise ValueError("Unsupported action.")

        # KEIN JOB OFFEN

        else:

            raise ValueError("Open or create " "a job first.")

    except Exception as exc:

        s.error = str(exc)

    # EVENT BESTÄTIGEN

    s.ack = event["id"]

    st.rerun()
