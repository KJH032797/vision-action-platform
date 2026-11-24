from datetime import timedelta
from pathlib import Path
from time import monotonic

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.utils import timezone

from .camera_capture import CameraCaptureError
from .models import AnalysisJob, CameraSession
from .services import enqueue_analysis

IDLE_SECONDS = 12
STALE_SECONDS = 18
MAX_SESSION_SECONDS = 180
FPS = 15
PREVIEW_INTERVAL_SECONDS = 1 / 15


def latest_frame(token):
    return Path(settings.MEDIA_ROOT) / "camera" / f"{token}.jpg"


def finish_session(token, error=""):
    with transaction.atomic():
        session = CameraSession.objects.select_for_update().filter(pk=token, active=True).first()
        if session is None:
            return
        if session.recording_job_id:
            AnalysisJob.objects.filter(pk=session.recording_job_id).update(
                status=AnalysisJob.State.FAILURE, finished_at=timezone.now(),
                error_message=error or "CAMERA_CLOSED: 영상 수집이 완료되기 전에 카메라가 종료됐습니다.",
            )
        session.state = CameraSession.State.FAILED if error else CameraSession.State.CLOSED
        session.error_message = error
        session.active = False
        session.recording_job = None
        session.save(update_fields=["state", "error_message", "active", "recording_job"])


def recover_stale_sessions():
    cutoff = timezone.now() - timedelta(seconds=STALE_SECONDS)
    with transaction.atomic():
        stale = list(CameraSession.objects.select_for_update().filter(active=True, worker_seen__lt=cutoff))
        for session in stale:
            finish_session(session.pk, "CAMERA_EXPIRED: 카메라 응답 시간이 초과됐습니다. 다시 켜 주세요.")
            transaction.on_commit(lambda token=session.pk: latest_frame(token).unlink(missing_ok=True))


def save_clip(token, job, path):
    with transaction.atomic():
        session = CameraSession.objects.select_for_update().get(pk=token)
        if not session.active or session.recording_job_id != job.pk:
            return
        with path.open("rb") as file:
            job.video.save("camera.mp4", File(file), save=False)
        job.original_filename = "camera.mp4"
        job.status = AnalysisJob.State.PENDING
        job.phase = AnalysisJob.Phase.ANALYZING
        job.save(update_fields=["video", "original_filename", "status", "phase"])
        session.recording_job = None
        session.save(update_fields=["recording_job"])
        transaction.on_commit(lambda: enqueue_analysis(job))


def fit_frame(cv2, frame):
    height, width = frame.shape[:2]
    scale = min(1, 640 / max(width, height))
    size = (max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2))
    return cv2.resize(frame, size)


def stream_camera(token, url, seconds, clip_path):
    import cv2

    capture = cv2.VideoCapture()
    writer = None
    job = None
    frame_path = latest_frame(token)
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    scratch = frame_path.with_suffix(".tmp")
    previous = None
    written = 0
    next_preview = 0
    next_poll = 0
    target_frames = seconds * FPS
    session_deadline = monotonic() + MAX_SESSION_SECONDS
    try:
        if not capture.open(url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 1500,
        ]):
            raise CameraCaptureError("CAMERA_CONNECTION_FAILED", "카메라에 연결할 수 없습니다.")

        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                raise CameraCaptureError("CAMERA_READ_INTERRUPTED", "카메라 영상이 끊겼습니다.")
            now = monotonic()
            if now >= next_poll:
                session = CameraSession.objects.get(pk=token)
                if not session.active or session.state == CameraSession.State.STOPPING:
                    return
                if not session.recording_job_id and (
                    now >= session_deadline or
                    timezone.now() - session.touched_at > timedelta(seconds=IDLE_SECONDS)
                ):
                    return
                fields = {"worker_seen": timezone.now()}
                if session.state == CameraSession.State.CONNECTING:
                    fields["state"] = CameraSession.State.LIVE
                changed = CameraSession.objects.filter(
                    pk=token, active=True, state=session.state
                ).update(**fields)
                if not changed:
                    return
                next_poll = now + .2

                if session.recording_job_id and writer is None:
                    job = session.recording_job
                    job.status = AnalysisJob.State.STARTED
                    job.phase = AnalysisJob.Phase.CAPTURING
                    job.save(update_fields=["status", "phase"])
                    previous = fit_frame(cv2, frame)
                    size = (previous.shape[1], previous.shape[0])
                    writer = cv2.VideoWriter(str(clip_path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, size)
                    if not writer.isOpened():
                        raise CameraCaptureError("CAMERA_ENCODING_FAILED", "영상 파일을 만들 수 없습니다.")
                    started = monotonic()
                    written = 0

            if now >= next_preview:
                ok, jpeg = cv2.imencode(".jpg", fit_frame(cv2, frame), [cv2.IMWRITE_JPEG_QUALITY, 76])
                if ok:
                    scratch.write_bytes(jpeg.tobytes())
                    scratch.replace(frame_path)
                next_preview = now + PREVIEW_INTERVAL_SECONDS

            if writer is not None:
                due = min(target_frames, int((monotonic() - started) * FPS))
                while written < due:
                    writer.write(previous)
                    written += 1
                if written == target_frames:
                    writer.release()
                    writer = None
                    save_clip(token, job, clip_path)
                    clip_path.unlink(missing_ok=True)
                else:
                    previous = cv2.resize(frame, size)
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        scratch.unlink(missing_ok=True)
        frame_path.unlink(missing_ok=True)
