from uuid import uuid4

from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver


def upload_path(instance, filename):
    return f"uploads/{uuid4().hex}.mp4"


class AnalysisJob(models.Model):
    class State(models.TextChoices):
        PENDING = "PENDING"
        STARTED = "STARTED"
        SUCCESS = "SUCCESS"
        FAILURE = "FAILURE"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=120, blank=True)
    memo = models.TextField(max_length=2000, blank=True)
    video = models.FileField(upload_to=upload_path)
    original_filename = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
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