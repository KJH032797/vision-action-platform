import fcntl
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from analyses.camera_capture import CameraCaptureError, capture_settings
from analyses.camera_sessions import MAX_SESSION_SECONDS, finish_session, latest_frame, recover_stale_sessions, stream_camera
from analyses.models import CameraSession


class Command(BaseCommand):
    help = "Run the camera session service beside the Celery worker."

    def add_arguments(self, parser):
        parser.add_argument("--session")
        parser.add_argument("--clip", type=Path)

    def handle(self, **options):
        if options["session"]:
            self.run_child(options["session"], options["clip"])
            return
        self.stopping = False
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        lock_path = Path(settings.MEDIA_ROOT) / ".camera.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("ab") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CommandError("The camera service is already running.") from None
            while not self.stopping:
                recover_stale_sessions()
                CameraSession.objects.filter(active=True, state=CameraSession.State.STOPPING,
                                             recording_job__isnull=True).update(
                    active=False, state=CameraSession.State.CLOSED
                )
                session = CameraSession.objects.filter(active=True, state=CameraSession.State.REQUESTED).first()
                if session is None:
                    sleep(.2)
                    continue
                changed = CameraSession.objects.filter(pk=session.pk, state=CameraSession.State.REQUESTED).update(
                    state=CameraSession.State.CONNECTING, worker_seen=timezone.now()
                )
                if changed:
                    self.serve_session(session.pk, lock)

    def stop(self, *_):
        self.stopping = True

    def serve_session(self, token, lock):
        frame = latest_frame(token)
        with TemporaryDirectory(prefix="camera-session-") as temp:
            # OpenCV can log stream addresses, so all native output is discarded.
            # The address stays in this service's environment, outside process arguments.
            args = [sys.executable, "manage.py", "camera_sessions", "--session", str(token),
                    "--clip", str(Path(temp) / "clip.mp4")]
            with subprocess.Popen(args, cwd=settings.BASE_DIR, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, pass_fds=(lock.fileno(),)) as process:
                deadline = monotonic() + MAX_SESSION_SECONDS + 20
                try:
                    while process.poll() is None and not self.stopping and monotonic() < deadline:
                        sleep(.1)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    frame.unlink(missing_ok=True)
                    frame.with_suffix(".tmp").unlink(missing_ok=True)
            # The child reports ordinary failures. This covers unexpected exit/kill.
            finish_session(token, "CAMERA_ENDED: 카메라 세션이 종료됐습니다. 다시 켜 주세요.")

    def run_child(self, token, clip):
        try:
            url, seconds = capture_settings()
            stream_camera(token, url, seconds, clip)
        except CameraCaptureError as error:
            finish_session(token, str(error))
        else:
            finish_session(token)
