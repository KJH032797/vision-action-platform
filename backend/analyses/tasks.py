from celery.exceptions import SoftTimeLimitExceeded

from config.celery import app
from .models import AnalysisJob
from .services import run_analysis, save_failure


@app.task(ignore_result=True)
def analyze_video(job_id):
    try:
        run_analysis(job_id)
    except SoftTimeLimitExceeded:
        job = AnalysisJob.objects.filter(pk=job_id, status=AnalysisJob.State.STARTED).first()
        if job is not None:
            save_failure(job, "분석 작업의 제한 시간을 초과했습니다.")
