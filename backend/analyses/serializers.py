from collections.abc import Mapping
from pathlib import Path

from rest_framework import serializers

from .models import AnalysisJob, PersonPrediction

MAX_VIDEO_BYTES = 64 * 1024 * 1024


class RestrictedInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unexpected = set(data) - set(self.fields)
        if unexpected:
            raise serializers.ValidationError(
                {field: "이 필드는 쓸 수 없습니다." for field in sorted(unexpected)}
            )
        return super().to_internal_value(data)


class JobMetadataSerializer(RestrictedInput):
    title = serializers.CharField(max_length=120, required=False, allow_blank=True)
    memo = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class JobCreateSerializer(JobMetadataSerializer):
    video = serializers.FileField(write_only=True)

    def validate_video(self, video):
        if Path(video.name).suffix.lower() != ".mp4":
            raise serializers.ValidationError("MP4 파일을 선택하세요.")
        if video.size > MAX_VIDEO_BYTES:
            raise serializers.ValidationError("영상은 최대 64 MiB까지 업로드할 수 있습니다.")
        return video


class PersonPredictionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonPrediction
        fields = ("track_id", "action_label", "confidence", "status", "observed_frames", "valid_frames")


class JobReadSerializer(serializers.ModelSerializer):
    predictions = PersonPredictionSerializer(many=True, read_only=True)

    class Meta:
        model = AnalysisJob
        fields = ("id", "title", "memo", "original_filename", "status", "result_status",
                  "error_message", "frames_read", "processing_time_sec",
                  "created_at", "finished_at", "predictions")