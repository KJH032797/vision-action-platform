"""Build two silent, browser-compatible previews from the same decoded frames."""
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np


PREVIEW_BYTES = 96 * 1024 * 1024  # Per video, below the transport cap.
TIME_BASE = Fraction(1, 90_000)
BONES = (
    (0, 1), (0, 2), (1, 3), (2, 4), (5, 6), (5, 7), (7, 9),
    (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13),
    (13, 15), (12, 14), (14, 16),
)
COLORS = ((235, 222, 45), (253, 120, 245), (70, 235, 168), (80, 180, 255))


def draw_tracks(frame, tracks, threshold):
    # Draw observed joints independently of the action classifier's result.
    drawn = False
    height, width = frame.shape[:2]
    for track_id, points, scores in tracks:
        if points.shape != (17, 2) or scores.shape != (17,):
            continue
        valid = (
            (scores >= threshold) & np.isfinite(points).all(axis=1)
            & (points[:, 0] >= 0) & (points[:, 0] < width)
            & (points[:, 1] >= 0) & (points[:, 1] < height)
        )
        if not valid.any():
            continue
        color = COLORS[track_id % len(COLORS)]
        joints = {index: tuple(map(int, points[index])) for index in np.flatnonzero(valid)}
        for a, b in BONES:
            if a in joints and b in joints:
                cv2.line(frame, joints[a], joints[b], color, 2, cv2.LINE_AA)
        for point in joints.values():
            cv2.circle(frame, point, 3, color, -1, cv2.LINE_AA)
        x, y = min(joints.values(), key=lambda point: point[1])
        cv2.putText(frame, f"Track {track_id}", (x, max(y - 8, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, .52, color, 2, cv2.LINE_AA)
        drawn = True
    return drawn


class WipeVideo:
    def __init__(self, directory, source):
        self.source = source
        directory = Path(directory)
        self.paths = [directory / "original.mp4", directory / "overlay.mp4"]
        self.outputs = []
        self.pending = {}
        self.first_ms = None
        self.last_pts = -1
        self.has_pose = False
        self.failed = False
        self.frames = 0

    def write(self, frame, tracks, threshold, timestamp_ms, fps, sar):
        if self.failed:
            return
        try:
            self._write(frame, tracks, threshold, timestamp_ms, fps, sar)
        except Exception:
            # An optional encoder failure must not halt detection or classification.
            self.abort()

    def _write(self, frame, tracks, threshold, timestamp_ms, fps, sar):
        if self.first_ms is None:
            self.first_ms = timestamp_ms
        pts = round((timestamp_ms - self.first_ms) * 90)
        if (pts <= self.last_pts or pts > 60 * 90_000 or self.frames >= 3600
                or not (1 <= fps <= 120)):
            raise ValueError("Preview timeline is unavailable or exceeds its limit")
        if not self.outputs:
            import av
            self.av = av
            self.last_frame_duration = round(90_000 / fps)
            with av.open(str(self.source)) as source:
                video = source.streams.video[0]
                self.source_end_pts = (round(video.duration * video.time_base / TIME_BASE)
                                       if video.duration is not None else None)
            height, width = frame.shape[:2]
            # Use the same bounded display geometry for both previews.
            display_width = width * sar
            scale = min(1, 1280 / max(display_width, height))
            self.size = (max(2, round(display_width * scale / 2) * 2),
                         max(2, round(height * scale / 2) * 2))
            self.input_shape = frame.shape
            for path in self.paths:
                container = av.open(str(path), "w", options={"movflags": "+faststart"})
                self.outputs.append((container, None))
                stream = container.add_stream("libx264", rate=Fraction(fps).limit_denominator(1001))
                stream.width, stream.height = self.size
                stream.pix_fmt = "yuv420p"
                stream.time_base = TIME_BASE
                stream.codec_context.time_base = TIME_BASE
                stream.options = {"preset": "ultrafast", "tune": "zerolatency", "bf": "0",
                                  "crf": "22", "maxrate": "9M", "bufsize": "9M"}
                self.outputs[-1] = container, stream
        if frame.shape != self.input_shape:
            raise ValueError("Preview frame dimensions changed")
        overlay = frame.copy()
        self.has_pose |= draw_tracks(overlay, tracks, threshold)
        for pixels, (container, stream) in zip((frame, overlay), self.outputs):
            picture = self.av.VideoFrame.from_ndarray(
                cv2.resize(pixels, self.size, interpolation=cv2.INTER_AREA), format="bgr24"
            )
            picture.pts = pts
            picture.time_base = TIME_BASE
            for packet in stream.encode(picture):
                previous = self.pending.get(stream)
                if previous is not None:
                    previous.duration = packet.pts - previous.pts
                    container.mux(previous)
                self.pending[stream] = packet
        self.last_pts = pts
        self.frames += 1
        if self.frames % 30 == 0 and any(path.stat().st_size > PREVIEW_BYTES for path in self.paths):
            raise ValueError("Preview exceeds the per-file size limit")

    def finish(self):
        if self.failed or not self.outputs:
            return "UNAVAILABLE"
        try:
            for container, stream in self.outputs:
                # No B-frames or encoder delay: we can derive each packet's
                # duration from its successor and use the source's video end.
                last = self.pending.pop(stream)
                if stream.encode():
                    raise ValueError("Preview encoder delayed a frame")
                duration = self.last_frame_duration
                if self.source_end_pts is not None:
                    duration = self.source_end_pts - last.pts
                    if not 0 < duration <= 60 * 90_000:
                        raise ValueError("Invalid source video duration")
                last.duration = duration
                container.mux(last)
                container.close()
            self.outputs.clear()
            if any(not 0 < path.stat().st_size <= PREVIEW_BYTES for path in self.paths):
                raise ValueError("Invalid preview file size")
            if not self.has_pose:
                self.paths[1].unlink()
            return "READY" if self.has_pose else "NO_POSE"
        except Exception:
            self.abort()
            return "UNAVAILABLE"

    def abort(self):
        self.failed = True
        for container, _ in self.outputs:
            try:
                container.close()
            except Exception:
                pass  # The request's temporary directory also removes partial outputs.
        self.outputs.clear()
        self.pending.clear()
