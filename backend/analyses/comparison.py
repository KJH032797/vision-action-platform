"""Receive optional preview files without making them part of the prediction result."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.db import transaction
import httpx

from .models import AnalysisJob, preview_names


COMPARISON_TYPE = "application/vnd.vision-action.comparison"
CHUNK_BYTES = 1024 * 1024
MAX_METADATA_BYTES = 8 * CHUNK_BYTES
MAX_PREVIEW_BYTES = 96 * CHUNK_BYTES


def receive_comparison(job, response):
    chunks = response.iter_bytes()
    header = bytearray()
    for chunk in chunks:
        head, marker, tail = chunk.partition(b"\n")
        if len(header) + len(head) > MAX_METADATA_BYTES:
            raise ValueError("Analysis metadata exceeds its limit")
        header.extend(head)
        if marker:
            break
    else:
        raise ValueError("Analysis metadata is missing")

    metadata = json.loads(header)
    result = metadata["result"]
    status = metadata.get("media_status")
    sizes = metadata.get("sizes")
    expected = {"READY": 2, "NO_POSE": 1, "UNAVAILABLE": 0}
    try:
        if (status not in expected or not isinstance(sizes, list) or len(sizes) != expected[status]
                or any(type(size) is not int or not 0 < size <= MAX_PREVIEW_BYTES for size in sizes)):
            raise ValueError("Invalid preview sizes")
        if sizes:
            store_previews(job, chunks, tail, sizes, status)
        else:
            AnalysisJob.objects.filter(pk=job.pk).update(media_status=status)
    except (ValueError, OSError, httpx.RequestError):
        # The first record was received. Keep it even if a preview is interrupted.
        AnalysisJob.objects.filter(pk=job.pk).update(media_status="UNAVAILABLE")
    return result


def store_previews(job, chunks, tail, sizes, status):
    storage = job.video.storage
    destinations = [Path(storage.path(name)) for name in preview_names(job.video.name)]
    with TemporaryDirectory(prefix=".comparison-", dir=destinations[0].parent) as directory:
        staged = []
        for index, size in enumerate(sizes):
            path = Path(directory) / f"{index}.mp4"
            with path.open("wb") as output:
                while size:
                    if not tail:
                        tail = next(chunks, b"")
                        if not tail:
                            raise ValueError("Preview transfer ended early")
                    count = min(size, len(tail))
                    output.write(tail[:count])
                    tail = tail[count:]
                    size -= count
            staged.append(path)
        if tail or next(chunks, b""):
            raise ValueError("Preview transfer exceeded advertised sizes")

        published = []
        try:
            # Keep publication and job deletion ordered. Only install complete files.
            with transaction.atomic():
                current = AnalysisJob.objects.select_for_update().filter(pk=job.pk).first()
                if current is None or current.video.name != job.video.name:
                    return
                for path, destination in zip(staged, destinations):
                    path.replace(destination)
                    published.append(destination)
                current.media_status = status
                current.save(update_fields=["media_status"])
        except Exception:
            for destination in published:
                destination.unlink(missing_ok=True)
            raise
