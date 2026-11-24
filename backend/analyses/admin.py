from django.contrib import admin

from .models import AnalysisJob, PersonPrediction


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "input_type", "title", "status", "created_at")
    list_filter = ("status", "input_type")
    search_fields = ("user__username",)
    readonly_fields = ("user", "input_type", "video", "original_filename", "status", "phase", "result_status",
                       "error_message", "frames_read", "processing_time_sec", "finished_at")

    def has_add_permission(self, request):
        return False


@admin.register(PersonPrediction)
class PersonPredictionAdmin(admin.ModelAdmin):
    list_display = ("job", "track_id", "action_label", "confidence", "status")
    list_filter = ("status", "job__input_type")
    search_fields = ("job__user__username",)
    readonly_fields = ("job", "track_id", "action_label", "confidence", "status",
                       "observed_frames", "valid_frames")

    def has_add_permission(self, request):
        return False

admin.site.site_header = "Vision Action 관리"
admin.site.site_title = "Vision Action 관리"
admin.site.index_title = "서비스 관리"
