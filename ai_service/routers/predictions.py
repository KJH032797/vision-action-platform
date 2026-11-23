from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from fastapi import APIRouter, HTTPException, Request, UploadFile

from services.pose_pipeline import InvalidVideo


router = APIRouter()
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


@router.post("/predict/video")
def predict_video(request: Request, file: UploadFile):
    started = perf_counter()
    analyzer = request.app.state.analyzer
    if analyzer is None:
        raise HTTPException(503, detail={"code": "MODELS_UNAVAILABLE"})
    if Path(file.filename or "").suffix.lower() != ".mp4":
        raise HTTPException(415, detail={"code": "MP4_REQUIRED"})

    # UploadFile is spooled by FastAPI. Copy bounded chunks to a private local
    # file for OpenCV, without using the client-provided filename as a path.
    with TemporaryDirectory(prefix="vision-action-") as directory:
        path = Path(directory) / "upload.mp4"
        size = 0
        with path.open("wb") as destination:
            while chunk := file.file.read(CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, detail={"code": "UPLOAD_TOO_LARGE"})
                destination.write(chunk)

        try:
            result = analyzer.analyze(path)
        except InvalidVideo as error:
            raise HTTPException(
                422, detail={"code": "INVALID_VIDEO", "message": str(error)}
            ) from error

    result["processing_time_sec"] = round(perf_counter() - started, 4)
    return result
