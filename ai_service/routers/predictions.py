import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile

from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from services.wipe_video import WipeVideo
from services.pose_pipeline import AnalysisMode, InvalidVideo, VideoLimitExceeded
from services.video_formats import VIDEO_SUFFIXES, detect_container


router = APIRouter()
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


@router.post("/predict/video")
def predict_video(
    request: Request, file: UploadFile,
    mode: Annotated[AnalysisMode, Form(description=(
        "webcam (default): original 5-second rolling window with 4-second minimum. "
        "upload: full clip per Track ID (MP4, MOV, MKV, WebM, AVI), up to 60 seconds and 3600 frames."
    ))] = "webcam",
    comparison: Annotated[bool, Form()] = False,
):
    started = perf_counter()
    analyzer = request.app.state.analyzer
    if analyzer is None:
        raise HTTPException(503, detail={"code": "MODELS_UNAVAILABLE"})
    suffix = Path(file.filename or "").suffix.lower()
    allowed = VIDEO_SUFFIXES if mode == "upload" else (".mp4",)
    if suffix not in allowed:
        raise HTTPException(415, detail={"code": "UNSUPPORTED_VIDEO_FORMAT"})

    # UploadFile is spooled by FastAPI. Copy bounded chunks to a private local
    # file for OpenCV, without using the client-provided filename as a path.
    directory = TemporaryDirectory(prefix="vision-action-")
    preview = None
    transferred = False
    try:
        path = Path(directory.name) / f"upload{suffix}"
        size = 0
        with path.open("wb") as destination:
            while chunk := file.file.read(CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, detail={"code": "UPLOAD_TOO_LARGE"})
                destination.write(chunk)

        container = detect_container(path)
        if container is None:
            raise HTTPException(422, detail={
                "code": "INVALID_VIDEO", "message": "The video container is damaged or unsupported."
            })
        if container != suffix:
            raise HTTPException(415, detail={"code": "VIDEO_FORMAT_MISMATCH"})

        try:
            if comparison:
                preview = WipeVideo(directory.name, path)
            result = analyzer.analyze(path, mode, preview) if preview else analyzer.analyze(path, mode)
        except VideoLimitExceeded as error:
            raise HTTPException(
                413, detail={"code": "VIDEO_LIMIT_EXCEEDED", "message": str(error)}
            ) from error
        except InvalidVideo as error:
            raise HTTPException(
                422, detail={"code": "INVALID_VIDEO", "message": str(error)}
            ) from error

        result["mode"] = mode
        if not comparison:
            result["processing_time_sec"] = round(perf_counter() - started, 4)
            return result

        status = preview.finish()
        result["processing_time_sec"] = round(perf_counter() - started, 4)
        files = {"READY": preview.paths, "NO_POSE": preview.paths[:1]}.get(status, [])
        try:
            sizes = [path.stat().st_size for path in files]
        except OSError:
            status, files, sizes = "UNAVAILABLE", [], []
        # Send the small inference result before the optional binary previews.
        header = json.dumps({"result": result, "media_status": status, "sizes": sizes}).encode() + b"\n"

        def stream():
            try:
                yield header
                for path in files:
                    with path.open("rb") as video:
                        while chunk := video.read(CHUNK_BYTES):
                            yield chunk
            finally:
                directory.cleanup()

        response = StreamingResponse(
            stream(), media_type="application/vnd.vision-action.comparison",
            background=BackgroundTask(directory.cleanup),
        )
        transferred = True
        return response
    finally:
        if not transferred:
            if preview is not None:
                preview.abort()
            directory.cleanup()
