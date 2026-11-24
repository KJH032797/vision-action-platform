from urllib.parse import urlsplit

from django.conf import settings


class CameraCaptureError(Exception):
    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")


def capture_settings():
    url = settings.IP_WEBCAM_URL.strip()
    if not url:
        raise CameraCaptureError("CAMERA_NOT_CONFIGURED", "관리자가 카메라를 설정해야 합니다.")
    try:
        parsed = urlsplit(url)
        seconds = int(settings.IP_WEBCAM_CAPTURE_SECONDS)
        if parsed.scheme not in ("http", "https", "rtsp") or not parsed.hostname or parsed.port == 0 or not 5 <= seconds <= 10:
            raise ValueError
    except ValueError:
        raise CameraCaptureError("CAMERA_CONFIGURATION_INVALID", "카메라 주소 또는 수집 시간 설정을 확인하세요.") from None
    return url, seconds
