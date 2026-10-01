"""Client for the local plan-analysis API."""

import csv
import io
import mimetypes
import time
import uuid
from urllib3.fields import RequestField
from urllib.parse import quote, urlparse

import requests

# Same formats as backend/api/main.py SUPPORTED_SUFFIXES. PDF is not processed.
ALLOWED_SUFFIXES = {
    ".tif",
    ".tiff",
    ".png",
    ".jpg",
    ".jpeg",
}

FIELDS = (
    "filename",
    "station",
    "line",
    "plan_number",
    "status",
)


def local_base_url(value):
    """Keep plan uploads on a backend running on this computer."""

    url = value.strip().rstrip("/")

    parsed = urlparse(url)

    if parsed.scheme != "http" or parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError(
            "Backend URL must use " "http://localhost or " "http://127.0.0.1."
        )

    if (
        parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "Enter only the backend origin, " "for example " "http://127.0.0.1:8000."
        )

    return url


def submit_documents(
    base_url,
    uploads,
):

    if not uploads:
        raise ValueError("Select at least one plan.")

    body = MultipartFiles(uploads)

    response = requests.post(
        (f"{base_url}" f"/api/documents/process"),
        data=body,
        headers={"Content-Type": "multipart/form-data; " "boundary=" + body.boundary},
        timeout=120,
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(
        payload,
        dict,
    ) or not payload.get("job_id"):
        raise ValueError("Backend did not return " "a job_id.")

    return str(payload["job_id"])


class MultipartFiles:
    """Stream one file at a time."""

    def __init__(
        self,
        uploads,
    ):

        self.boundary = uuid.uuid4().hex

        self.parts = []

        self.ending = ("--" + self.boundary + "--\r\n").encode()

        self.length = len(self.ending)

        for upload in uploads:

            suffix = (
                "."
                + upload.name.rsplit(
                    ".",
                    1,
                )[-1].lower()
            )

            if suffix not in ALLOWED_SUFFIXES:

                raise ValueError(
                    "The processing API "
                    "accepts TIFF, PNG and JPEG: "
                    f"{upload.name}"
                )

            mime = mimetypes.guess_type(upload.name)[0] or "application/octet-stream"

            field = RequestField(
                name="files",
                data=None,
                filename=upload.name,
            )

            field.make_multipart(content_type=mime)

            header = ("--" + self.boundary + "\r\n" + field.render_headers()).encode(
                "utf-8"
            )

            self.parts.append(
                (
                    header,
                    upload,
                )
            )

            self.length += len(header) + upload.size + 2

    def __len__(
        self,
    ):

        return self.length

    def __iter__(
        self,
    ):

        for (
            header,
            upload,
        ) in self.parts:

            yield header

            if hasattr(
                upload,
                "open",
            ):

                with upload.open() as stream:

                    while True:

                        chunk = stream.read(1024 * 1024)

                        if not chunk:
                            break

                        yield chunk

            else:

                with io.BytesIO(upload.getvalue()) as stream:

                    while True:

                        chunk = stream.read(1024 * 1024)

                        if not chunk:
                            break

                        yield chunk

            yield b"\r\n"

        yield self.ending


def wait_for_results(
    base_url,
    job_id,
    max_seconds=180,
    on_update=None,
):
    """Poll backend until processing is completed."""

    job_path = quote(
        job_id,
        safe="",
    )

    deadline = time.monotonic() + max_seconds

    while time.monotonic() < deadline:

        response = requests.get(
            (f"{base_url}" f"/api/jobs/" f"{job_path}"),
            timeout=15,
        )

        response.raise_for_status()

        job = response.json()

        status = str(
            job.get(
                "status",
                "",
            )
        ).lower()

        if on_update:
            on_update(job)

        if status in {
            "failed",
            "error",
            "cancelled",
        }:

            raise RuntimeError(job.get("message") or ("Backend job " f"{status}."))

        if status == "completed":

            results = requests.get(
                (f"{base_url}" f"/api/jobs/" f"{job_path}" f"/results"),
                timeout=30,
            )

            results.raise_for_status()

            data = results.json()

            if not isinstance(
                data,
                dict,
            ) or not isinstance(
                data.get("results"),
                list,
            ):

                raise ValueError("Backend results " "must contain a " "results list.")

            return data["results"]

        time.sleep(2)

    raise TimeoutError("Processing is still running. " "Check the backend job log.")


def field_value(
    record,
    key,
):
    """Accept flat or nested values."""

    value = record.get(key)

    if isinstance(
        value,
        dict,
    ):
        return value.get("value")

    return value


def result_rows(
    results,
):

    rows = []

    for record in results:

        rows.append(
            {
                "filename": record.get("filename") or record.get("document_id") or "",
                "station": field_value(
                    record,
                    "station",
                )
                or "",
                "line": field_value(
                    record,
                    "line",
                )
                or "",
                "plan_number": field_value(
                    record,
                    "plan_number",
                )
                or "",
                "status": record.get("status") or "",
            }
        )

    return rows


def csv_bytes(
    results,
):

    output = io.StringIO()

    writer = csv.DictWriter(
        output,
        fieldnames=FIELDS,
    )

    writer.writeheader()

    for row in result_rows(results):

        writer.writerow(
            {
                key: (
                    "'" + value
                    if (
                        isinstance(
                            value,
                            str,
                        )
                        and value[:1]
                        in (
                            "=",
                            "+",
                            "-",
                            "@",
                            "\t",
                            "\r",
                        )
                    )
                    else value
                )
                for key, value in row.items()
            }
        )

    return output.getvalue().encode("utf-8-sig")
