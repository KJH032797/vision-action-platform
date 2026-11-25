from math import isfinite
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
import httpx

from .comparison import COMPARISON_TYPE, receive_comparison
from .models import AnalysisJob, PersonPrediction
from .video_formats import VIDEO_MIME


class AnalysisFailure(Exception):
    pass


def send_video(job, video, filename, mode):
    url = settings.FASTAPI_BASE_URL.rstrip("/") + "/predict/video"
    mime = VIDEO_MIME[Path(filename).suffix.lower()]
    with httpx.stream(
        "POST", url, files={"file": (filename, video, mime)},
        data={"mode": mode, "comparison": "true"},
        timeout=settings.FASTAPI_TIMEOUT_SECONDS,
    ) as response:
        if response.is_success and response.headers.get("content-type") == COMPARISON_TYPE:
            return receive_comparison(job, response)
        # Ordinary JSON errors and the pre-comparison FastAPI response still work.
        response.read()
        if response.status_code == 415:
            detail = response.json().get("detail", {})
            if isinstance(detail, dict) and detail.get("code") == "VIDEO_FORMAT_MISMATCH":
                raise AnalysisFailure("VIDEO_FORMAT_MISMATCH: 파일 확장자와 실제 영상 형식이 다릅니다.")
            raise AnalysisFailure("UNSUPPORTED_VIDEO_FORMAT: 지원 영상 형식으로 다시 올려 주세요.")
        if response.status_code == 422:
            raise AnalysisFailure("INVALID_VIDEO: 지원되지 않는 코덱이거나 영상이 손상돼 읽지 못했습니다.")
        if response.status_code == 413:
            raise AnalysisFailure("VIDEO_LIMIT_EXCEEDED: 업로드 영상의 크기, 길이 또는 추적량이 한도를 넘었습니다. 60초 이내의 짧은 영상으로 다시 올려 주세요.")
        response.raise_for_status()
        return response.json()


def set_phase(job, phase):
    AnalysisJob.objects.filter(pk=job.pk).update(phase=phase)


def request_prediction(job):
    set_phase(job, AnalysisJob.Phase.ANALYZING)
    if not job.video:
        raise AnalysisFailure("CAMERA_FILE_MISSING: 분석할 녹화 파일이 없습니다.")
    mode = "upload" if job.input_type == AnalysisJob.Source.UPLOAD else "webcam"
    with job.video.open("rb") as video:
        return send_video(job, video, job.original_filename, mode)


def valid_number(value, minimum=0, maximum=None):
    return (type(value) in (int, float) and isfinite(value) and value >= minimum
            and (maximum is None or value <= maximum))


def result_rows(job, payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected a result object")
    result = payload.get("status")
    frames = payload.get("frames_read")
    elapsed = payload.get("processing_time_sec")
    predictions = payload.get("predictions")
    if (result not in ("OK", "NO_PERSON", "NO_TRACKS")
            or type(frames) is not int or frames <= 0 or not valid_number(elapsed)
            or not isinstance(predictions, list) or (result == "OK") != bool(predictions)):
        raise ValueError("Unexpected result fields")

    rows = []
    seen = set()
    for item in predictions:
        track_id = item["track_id"]
        status = item["status"]
        label = item["action_label"]
        confidence = item["confidence"]
        observed = item["observed_frames"]
        valid = item["valid_frames"]
        if (type(track_id) is not int or track_id < 0 or track_id in seen
                or status not in ("PREDICTED", "LOW_CONFIDENCE", "INSUFFICIENT_POSE", "INSUFFICIENT_DURATION")
                or not isinstance(label, str) or not 0 < len(label) <= 40
                or (label == "UNKNOWN") != (status != "PREDICTED")
                or (confidence is not None and not valid_number(confidence, maximum=1))
                or (confidence is None) != (status in ("INSUFFICIENT_POSE", "INSUFFICIENT_DURATION"))
                or type(observed) is not int or type(valid) is not int
                or not 0 <= valid <= observed <= frames):
            raise ValueError("Invalid track payload")
        seen.add(track_id)
        rows.append(PersonPrediction(job=job, track_id=track_id, status=status,
                    action_label=label, confidence=confidence, observed_frames=observed,
                    valid_frames=valid))
    return result, frames, elapsed, rows


def save_success(job, result, frames, elapsed, rows):
    # Save the result rows and the final job state together.
    with transaction.atomic():
        PersonPrediction.objects.bulk_create(rows)
        job.status = AnalysisJob.State.SUCCESS
        job.result_status = result
        job.frames_read = frames
        job.processing_time_sec = elapsed
        job.finished_at = timezone.now()
        job.save(update_fields=[
            "status", "result_status", "frames_read", "processing_time_sec", "finished_at"
        ])


def save_failure(job, message):
    job.status = AnalysisJob.State.FAILURE
    job.error_message = message
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error_message", "finished_at"])


def create_job(user, *, input_type=AnalysisJob.Source.UPLOAD, video=None, title="", memo=""):
    return AnalysisJob.objects.create(
        user=user, input_type=input_type, video=video if video is not None else "",
        original_filename=Path(video.name).name if video is not None else "", title=title, memo=memo
    )


def run_analysis(job_id):
    # Claim the pending job atomically. Duplicate deliveries cannot run it twice.
    claimed = AnalysisJob.objects.filter(
        pk=job_id, status=AnalysisJob.State.PENDING
    ).update(status=AnalysisJob.State.STARTED)
    if not claimed:
        return
    job = AnalysisJob.objects.get(pk=job_id)
    try:
        result = result_rows(job, request_prediction(job))
    except AnalysisFailure as error:
        save_failure(job, str(error))
    except httpx.TimeoutException:
        save_failure(job, "AI 서비스 응답 시간이 초과됐습니다.")
    except httpx.HTTPStatusError as error:
        save_failure(job, f"AI 서비스가 HTTP {error.response.status_code}을 반환했습니다.")
    except (httpx.RequestError, OSError):
        save_failure(job, "영상 파일 또는 AI 서비스에 연결할 수 없습니다.")
    except (ValueError, KeyError, TypeError):
        save_failure(job, "AI 서비스 응답 형식이 예상과 다릅니다.")
    else:
        save_success(job, *result)


def submit_analysis(user, **data):
    if settings.ANALYSIS_MODE == "sync":
        # Keep the previous flow available for an explicit local demo.
        job = create_job(user, **data)
        if job.input_type == AnalysisJob.Source.IP_WEBCAM:
            save_failure(job, "CAMERA_REQUIRES_WORKER: 카메라는 Celery 실행 모드에서 사용할 수 있습니다.")
        else:
            run_analysis(job.pk)
        job.refresh_from_db()
        return job

    with transaction.atomic():
        job = create_job(user, **data)
        transaction.on_commit(lambda: enqueue_analysis(job))
    return job


def enqueue_analysis(job):
    # Pass only the DB identifier. The worker opens its shared upload file.
    from kombu.exceptions import OperationalError
    from .tasks import analyze_video

    try:
        analyze_video.apply_async(args=(job.pk,), retry=False)
    except OperationalError:
        message = "분석 대기열에 연결할 수 없습니다."
        finished = timezone.now()
        updated = AnalysisJob.objects.filter(
            pk=job.pk, status=AnalysisJob.State.PENDING
        ).update(status=AnalysisJob.State.FAILURE, error_message=message, finished_at=finished)
        if updated:
            job.status = AnalysisJob.State.FAILURE
            job.error_message = message
            job.finished_at = finished
