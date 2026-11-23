from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from routers.predictions import router
from services.pose_pipeline import VideoAnalyzer
from verify_stage1 import load_models


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.analyzer = None
    try:
        pose, classifier, steps, config = load_models()
        app.state.analyzer = VideoAnalyzer(pose, classifier, steps, config)
    except Exception:
        logging.getLogger(__name__).exception("Could not initialize inference models")
    yield
    app.state.analyzer = None


app = FastAPI(title="Vision Action Platform", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health(request: Request):
    ready = request.app.state.analyzer is not None
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ok" if ready else "unavailable", "models_ready": ready},
    )
