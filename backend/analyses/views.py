from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.reverse import reverse

from .models import AnalysisJob
from .serializers import JobCreateSerializer, JobMetadataSerializer, JobReadSerializer
from .services import submit_analysis


class AnalysisJobViewSet(viewsets.ModelViewSet):
    serializer_class = JobReadSerializer

    def get_queryset(self):
        return AnalysisJob.objects.filter(user=self.request.user).prefetch_related("predictions")

    def get_serializer_class(self):
        if self.action == "create":
            return JobCreateSerializer
        if self.action in ("update", "partial_update"):
            return JobMetadataSerializer
        return JobReadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = submit_analysis(request.user, **serializer.validated_data)
        detail_url = reverse("analysis-detail", args=[job.pk], request=request)
        return Response(JobReadSerializer(job).data, status=status.HTTP_201_CREATED,
                        headers={"Location": detail_url})

    def update(self, request, *args, **kwargs):
        job = self.get_object()
        serializer = self.get_serializer(data=request.data, partial=kwargs.get("partial", False))
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(job, field, value)
        if serializer.validated_data:
            job.save(update_fields=list(serializer.validated_data))
        return Response(JobReadSerializer(job).data)

    def perform_destroy(self, instance):
        if instance.status in (AnalysisJob.State.PENDING, AnalysisJob.State.STARTED):
            raise ValidationError("분석이 끝난 뒤 삭제할 수 있습니다.")
        instance.delete()
