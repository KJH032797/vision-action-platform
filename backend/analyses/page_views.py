from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from .models import AnalysisJob
from .playback import playback_context
from .serializers import JobCreateSerializer
from .services import submit_analysis
from .video_formats import VIDEO_ACCEPT, VIDEO_FORMAT_LABEL


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def analysis_list(request):
    form = None
    if request.method == "POST":
        # Pass only the fields in the HTML form; CSRF was checked by middleware.
        data = {"title": request.POST.get("title", ""), "memo": request.POST.get("memo", "")}
        if "input_type" in request.POST:
            data["input_type"] = request.POST["input_type"]
        if "video" in request.FILES:
            data["video"] = request.FILES["video"]
        form = JobCreateSerializer(data=data)
        if form.is_valid():
            job = submit_analysis(request.user, **form.validated_data)
            return redirect("analysis_detail", pk=job.pk)
    jobs = AnalysisJob.objects.filter(user=request.user)
    return render(request, "analyses/index.html", {
        "jobs": jobs, "form": form, "video_accept": VIDEO_ACCEPT,
        "video_formats": VIDEO_FORMAT_LABEL,
    })


@login_required
@require_safe
def analysis_detail(request, pk):
    jobs = AnalysisJob.objects.filter(user=request.user).prefetch_related("predictions")
    job = get_object_or_404(jobs, pk=pk)
    code, separator, message = job.error_message.partition(": ")
    has_code = bool(separator and code.isascii() and code.isupper() and "_" in code)
    return render(request, "analyses/detail.html", {
        "job": job,
        **playback_context(job),
        "error_code": code if has_code else "",
        "error_text": message if has_code else job.error_message,
    })
