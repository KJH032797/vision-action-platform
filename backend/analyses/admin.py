from django.contrib import admin

from .models import AnalysisJob, PersonPrediction


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "status", "created_at")
    list_filter = ("status",)
    readonly_fields = ("user", "video", "original_filename", "status", "result_status",
                       "error_message", "frames_read", "processing_time_sec", "finished_at")

    def has_add_permission(self, request):
        return False


@admin.register(PersonPrediction)
class PersonPredictionAdmin(admin.ModelAdmin):
    list_display = ("job", "track_id", "action_label", "confidence", "status")
    readonly_fields = ("job", "track_id", "action_label", "confidence", "status",
                       "observed_frames", "valid_frames")

    def has_add_permission(self, request):
        return False