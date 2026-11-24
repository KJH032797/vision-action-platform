from datetime import timedelta
from os import fstat

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .camera_sessions import latest_frame, recover_stale_sessions
from .models import AnalysisJob, CameraSession
from .serializers import JobMetadataSerializer
from .services import create_job


def owned_session(request, token):
    return get_object_or_404(CameraSession, pk=token, owner=request.user,
                             browser_session=request.session.session_key)


@login_required
@require_POST
@never_cache
def open_camera(request):
    if settings.ANALYSIS_MODE != "celery":
        return JsonResponse({"message": "카메라는 Worker 실행 환경에서 사용할 수 있습니다."}, status=409)
    recover_stale_sessions()
    try:
        with transaction.atomic():
            session = CameraSession.objects.create(
                owner=request.user, browser_session=request.session.session_key
            )
    except IntegrityError:
        return JsonResponse({"message": "카메라를 사용 중입니다. 다른 화면에서 끄거나 잠시 후 다시 시도하세요."}, status=409)
    urls = {
        key: reverse("camera_" + key, args=[session.pk])
        for key in ("status", "frame", "heartbeat", "close", "record")
    }
    return JsonResponse({"urls": urls}, status=202)


@login_required
@require_GET
@never_cache
def camera_status(request, token):
    recover_stale_sessions()
    session = owned_session(request, token)
    return JsonResponse({"state": session.state, "recording": bool(session.recording_job_id),
                         "message": session.error_message})


@login_required
@require_GET
@never_cache
def camera_frame(request, token):
    session = owned_session(request, token)
    if session.state == CameraSession.State.LIVE:
        try:
            with latest_frame(session.pk).open("rb") as frame:
                version = f'"{fstat(frame.fileno()).st_mtime_ns:x}"'
                if request.headers.get("If-None-Match") == version:
                    return HttpResponse(status=304, headers={"ETag": version})
                return HttpResponse(frame.read(), content_type="image/jpeg", headers={"ETag": version})
        except FileNotFoundError:
            pass
    return HttpResponse(status=204)


@login_required
@require_POST
@never_cache
def camera_heartbeat(request, token):
    session = owned_session(request, token)
    active = CameraSession.objects.filter(pk=session.pk, active=True).update(touched_at=timezone.now())
    return HttpResponse(status=204 if active else 410)


@login_required
@require_POST
@never_cache
def close_camera(request, token):
    session = owned_session(request, token)
    if not session.active:
        return HttpResponse(status=204)
    updated = CameraSession.objects.filter(pk=session.pk, active=True, recording_job__isnull=True).update(
        state=CameraSession.State.STOPPING
    )
    if not updated:
        return JsonResponse({"message": "영상 수집 중에는 카메라를 끌 수 없습니다."}, status=409)
    return HttpResponse(status=202)


@login_required
@require_POST
@never_cache
def record_camera(request, token):
    session = owned_session(request, token)
    serializer = JobMetadataSerializer(data={key: request.POST[key] for key in ("title", "memo") if key in request.POST})
    if not serializer.is_valid():
        return JsonResponse({"message": "제목이나 메모의 길이를 확인해 주세요."}, status=400)
    with transaction.atomic():
        job = create_job(request.user, input_type=AnalysisJob.Source.IP_WEBCAM, **serializer.validated_data)
        updated = CameraSession.objects.filter(
            pk=session.pk, active=True, state=CameraSession.State.LIVE, recording_job__isnull=True,
            worker_seen__gte=timezone.now() - timedelta(seconds=5),
        ).update(recording_job=job, touched_at=timezone.now())
        if not updated:
            transaction.set_rollback(True)
            return JsonResponse({"message": "카메라 연결이 준비되지 않았거나 이미 수집 중입니다."}, status=409)
    return JsonResponse({"url": reverse("analysis-detail", args=[job.pk]),
                         "detail": reverse("analysis_detail", args=[job.pk])}, status=202)
