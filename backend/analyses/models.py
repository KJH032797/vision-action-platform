from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from .video_formats import VIDEO_MIME


def upload_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in VIDEO_MIME:
        raise ValueError("Unsupported stored video extension")
    return f"uploads/{uuid4().hex}{suffix}"


class AnalysisJob(models.Model):
    class Source(models.TextChoices):
        UPLOAD = "UPLOAD", "영상 업로드"
        IP_WEBCAM = "IP_WEBCAM", "IP Webcam"

    class State(models.TextChoices):
        PENDING = "PENDING"
        STARTED = "STARTED"
        SUCCESS = "SUCCESS"
        FAILURE = "FAILURE"

    class Phase(models.TextChoices):
        CONNECTING = "CONNECTING", "카메라 연결 중"
        CAPTURING = "CAPTURING", "영상 수집 중"
        ANALYZING = "ANALYZING", "AI 분석 중"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=120, blank=True)
    memo = models.TextField(max_length=2000, blank=True)
    input_type = models.CharField(max_length=12, choices=Source.choices, default=Source.UPLOAD)
    video = models.FileField(upload_to=upload_path, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    phase = models.CharField(max_length=10, choices=Phase.choices, blank=True)
    result_status = models.CharField(max_length=20, blank=True)
    error_message = models.CharField(max_length=255, blank=True)
    frames_read = models.PositiveIntegerField(null=True)
    processing_time_sec = models.FloatField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ("-created_at", "-pk")


class PersonPrediction(models.Model):
    job = models.ForeignKey(AnalysisJob, on_delete=models.CASCADE, related_name="predictions")
    track_id = models.PositiveIntegerField()
    action_label = models.CharField(max_length=40)
    confidence = models.FloatField(null=True)
    status = models.CharField(max_length=24)
    observed_frames = models.PositiveIntegerField()
    valid_frames = models.PositiveIntegerField()

    class Meta:
        ordering = ("track_id",)
        constraints = [
            models.UniqueConstraint(fields=("job", "track_id"), name="analysis_unique_track"),
        ]


@receiver(post_delete, sender=AnalysisJob)
def remove_private_upload(sender, instance, using, **kwargs):
    if instance.video:
        storage, name = instance.video.storage, instance.video.name
        transaction.on_commit(lambda: storage.delete(name), using=using, robust=True)

class CameraSession(models.Model):
    class State(models.TextChoices):
        REQUESTED = "REQUESTED"
        CONNECTING = "CONNECTING"
        LIVE = "LIVE"
        STOPPING = "STOPPING"
        CLOSED = "CLOSED"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    browser_session = models.CharField(max_length=40)
    state = models.CharField(max_length=10, choices=State.choices, default=State.REQUESTED)
    active = models.BooleanField(default=True)
    touched_at = models.DateTimeField(default=timezone.now)
    worker_seen = models.DateTimeField(default=timezone.now)
    recording_job = models.ForeignKey(AnalysisJob, null=True, blank=True, on_delete=models.SET_NULL)
    error_message = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("active",), condition=models.Q(active=True),
                                    name="analysis_single_active_camera")
        ]
