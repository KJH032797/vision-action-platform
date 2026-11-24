"""Upload extensions and multipart MIME labels. FastAPI checks the actual bytes."""

VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
}
VIDEO_ACCEPT = ",".join(VIDEO_MIME)
VIDEO_FORMAT_LABEL = ", ".join(suffix[1:].upper() for suffix in VIDEO_MIME)
