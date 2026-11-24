import logging
import re


class QuietCameraFrames(logging.Filter):
    """Keep runserver errors without logging each successful preview poll."""

    frame_request = re.compile(r'^[\x22]?GET /camera/session/[0-9a-f-]+/frame/ HTTP/')

    def filter(self, record):
        if getattr(record, "status_code", None) not in (200, 204, 304):
            return True
        return not self.frame_request.match(record.getMessage())
