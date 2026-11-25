"""Serve private video with single byte ranges so browser seeking works."""
from pathlib import Path
import re

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .models import AnalysisJob, preview_names


PLAYABLE_TYPES = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}
CHUNK_BYTES = 256 * 1024


def assets(job):
    if not job.video:
        return {}, False
    storage, name = job.video.storage, job.video.name
    original, overlay = preview_names(name)
    sources = {}
    try:
        raw_exists = storage.exists(name)
        content_type = PLAYABLE_TYPES.get(Path(name).suffix.lower())
        if content_type and raw_exists:
            sources["source"] = sources["original"] = (name, content_type)
        if job.media_status in ("READY", "NO_POSE") and storage.exists(original):
            sources["original"] = (original, "video/mp4")
            if job.media_status == "READY" and storage.exists(overlay):
                sources["overlay"] = (overlay, "video/mp4")
        return sources, raw_exists
    except OSError:
        return sources, False


def playback_context(job):
    sources, raw_exists = assets(job)
    if "overlay" in sources:
        reason = ""
    elif job.status in (AnalysisJob.State.PENDING, AnalysisJob.State.STARTED):
        reason = "분석이 끝나면 영상 결과를 확인할 수 있습니다."
    elif "original" in sources:
        reason = {
            "NO_POSE": "표시할 수 있는 추적 관절이 없어 원본만 제공합니다.",
            "UNAVAILABLE": "추적 영상 생성 또는 저장에 실패해 원본만 제공합니다.",
            "READY": "저장된 추적 영상이 없어 원본만 제공합니다.",
        }.get(job.media_status, "이 작업에는 추적 영상이 저장되어 있지 않습니다.")
    elif not raw_exists:
        reason = "저장된 원본 영상이 없습니다."
    else:
        reason = "이 영상 형식은 브라우저용 변환본이 있어야 재생할 수 있습니다."
    return {
        "can_play_original": "original" in sources, "can_compare": "overlay" in sources,
        "can_fallback_source": "source" in sources and sources["source"] != sources["original"],
        "playback_reason": reason,
    }


def byte_range(value, size):
    # This endpoint serves a single range. Bound the numeric input before int().
    match = re.fullmatch(r"bytes=([0-9]{0,19})-([0-9]{0,19})", value)
    if not match or not size or not any(match.groups()):
        raise ValueError
    first, last = match.groups()
    if not first:
        if int(last) == 0:
            raise ValueError
        return max(0, size - int(last)), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start > end:
        raise ValueError
    return start, end


class VideoSlice:
    def __init__(self, video, start, length):
        self.video = video
        self.remaining = length
        video.seek(start)

    def __iter__(self):
        return self

    def __next__(self):
        data = self.video.read(min(CHUNK_BYTES, self.remaining))
        if not data:
            raise StopIteration
        self.remaining -= len(data)
        return data

    def close(self):
        self.video.close()


@login_required
@require_safe
@never_cache
def analysis_video(request, pk, kind):
    job = get_object_or_404(AnalysisJob.objects.filter(user=request.user), pk=pk)
    sources, _ = assets(job)
    source = sources.get(kind)
    if source is None:
        raise Http404
    name, content_type = source
    storage = job.video.storage
    try:
        size = storage.size(name)
    except OSError as error:
        raise Http404 from error
    value = request.headers.get("Range")
    partial = value is not None
    try:
        start, end = byte_range(value, size) if partial else (0, size - 1)
    except ValueError:
        return HttpResponse(status=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
    length = end - start + 1
    status = 206 if partial else 200
    if request.method == "HEAD":
        response = HttpResponse(status=status, content_type=content_type)
    else:
        try:
            video = storage.open(name, "rb")
            try:
                stream = VideoSlice(video, start, length)
            except Exception:
                video.close()
                raise
        except OSError as error:
            raise Http404 from error
        response = StreamingHttpResponse(stream, status=status, content_type=content_type)
    response["Accept-Ranges"] = "bytes"
    response["Content-Length"] = length
    response["X-Content-Type-Options"] = "nosniff"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    if partial:
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    return response
