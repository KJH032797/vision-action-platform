from dataclasses import dataclass, field
import math
from threading import Lock
from typing import Literal

import cv2
import numpy as np

from services.action_inference import classify_window
from src.common import resolve_device
from src.realtime_utils import TimedFeatureBuffer, frame_feature_from_keypoints
from verify_stage1 import MODEL_DIR, ROOT, read_json


class InvalidVideo(ValueError):
    pass


AnalysisMode = Literal["upload", "webcam"]
MAX_UPLOAD_SECONDS = 60
MAX_UPLOAD_FRAMES = 3600
MAX_UPLOAD_OBSERVATIONS = 32_768


class VideoLimitExceeded(ValueError):
    pass


@dataclass
class UploadTrack:
    observed_frames: int = 0
    valid: list[tuple[int, np.ndarray]] = field(default_factory=list)


@dataclass
class TrackState:
    window: TimedFeatureBuffer
    last_seen: float
    observed_frames: int = 0
    valid_frames: int = 0
    latest_ready: tuple | None = None
    next_sample: float = 0.0


def tracked_poses(result):
    boxes = result.boxes
    if boxes is None or boxes.id is None:
        return (), ()
    ids = boxes.id.int().cpu().tolist()
    keypoints = result.keypoints
    if keypoints is None or keypoints.conf is None:
        return (), ids

    points = keypoints.xy.cpu().numpy()
    scores = keypoints.conf.cpu().numpy()
    if len(points) != len(ids) or len(scores) != len(ids):
        return (), ids

    return tuple(zip(ids, points, scores)), ids


def features_from_poses(poses, ids, keypoint_threshold):
    features = dict.fromkeys(ids)
    for track_id, xy, confidence in poses:
        # Use confidence for the shoulders, hips and limbs used by the angles
        # and normalization. Keep the original 38-D feature values and order.
        usable = confidence.shape == (17,) and np.all(confidence[5:] >= keypoint_threshold)
        features[track_id] = frame_feature_from_keypoints(xy) if usable else None
    return features


class VideoAnalyzer:
    def __init__(self, pose, classifier, steps, config):
        self.pose = pose
        self.classifier = classifier
        self.steps = steps
        self.config = config
        self.device = resolve_device(config["device"])
        self.runtime = read_json(ROOT / "configs/day07_realtime.json")
        self.upload_min_frames = read_json(MODEL_DIR / "rf_training_info.json")["min_valid_frames"]
        tracking = read_json(ROOT / "configs/day08_multi_person.json")
        self.tracker = tracking["tracker"]
        self.lost_timeout = float(tracking["lost_timeout_seconds"])
        self.lock = Lock()
        self.detected_in_frame = False
        # Runs before Ultralytics adds its tracking callback. It distinguishes a
        # detection without an assigned Track ID from a frame with no people.
        self.pose.add_callback("on_predict_postprocess_end", self.observe_detections)

    def observe_detections(self, predictor):
        self.detected_in_frame = any(
            result.boxes is not None and len(result.boxes) > 0
            for result in predictor.results
        )

    def analyze(self, path, mode: AnalysisMode = "webcam", preview=None):
        # YOLO's predictor and ByteTrack are mutable. Never share their state
        # between simultaneous requests or consecutive videos.
        with self.lock:
            for tracker in getattr(self.pose.predictor, "trackers", []):
                tracker.reset()
            return self.read_video(path, mode, preview)

    def read_video(self, path, mode: AnalysisMode, preview=None):
        try:
            capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
        except cv2.error as error:
            raise InvalidVideo("Could not open the video decoder.") from error
        states = {}
        upload_tracks = {}
        observations = 0
        frame_count = 0
        detected = False
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not capture.isOpened() or not math.isfinite(fps) or fps <= 0:
                raise InvalidVideo("Could not open the video or read its frame rate.")

            expected_frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            sar_num = capture.get(cv2.CAP_PROP_SAR_NUM)
            sar_den = capture.get(cv2.CAP_PROP_SAR_DEN)
            sar = sar_num / sar_den if sar_num > 0 and sar_den > 0 else 1
            while True:
                try:
                    ok, frame = capture.read()
                except cv2.error as error:
                    raise InvalidVideo("Could not decode the video frames.") from error
                if not ok:
                    break
                if mode == "upload":
                    self.check_upload_length(frame_count + 1, fps)
                timestamp = frame_count / fps
                self.detected_in_frame = False
                result = self.pose.track(
                    source=frame,
                    persist=True,
                    tracker=self.tracker,
                    device=self.device,
                    imgsz=self.config["image_size"],
                    conf=self.config["person_confidence"],
                    verbose=False,
                )[0]
                detected |= self.detected_in_frame
                poses, ids = tracked_poses(result)
                threshold = self.config["keypoint_confidence"]
                features = features_from_poses(poses, ids, threshold)
                if preview is not None:
                    preview.write(frame, poses, threshold, capture.get(cv2.CAP_PROP_POS_MSEC), fps, sar)
                if mode == "upload":
                    observations += len(features)
                    if observations > MAX_UPLOAD_OBSERVATIONS:
                        raise VideoLimitExceeded("Too many tracked observations in the MP4.")
                    self.update_upload_tracks(upload_tracks, features, frame_count)
                else:
                    self.update_tracks(states, features, timestamp)
                frame_count += 1
        finally:
            capture.release()

        # Indexed containers report a frame count. Catch premature EOF without
        # trusting approximate counts from WebM or Matroska.
        if (path.suffix in (".mp4", ".mov", ".avi")
                and math.isfinite(expected_frames) and expected_frames > 0
                and expected_frames - frame_count > max(2, expected_frames * 0.03)):
            raise InvalidVideo("Video decoding stopped before the expected end of the file.")
        if frame_count == 0:
            raise InvalidVideo("The video has no decodable frames.")
        if mode == "upload":
            predictions = [self.summarize_upload(key, track, fps) for key, track in sorted(upload_tracks.items())]
        else:
            predictions = [self.summarize(track_id, state) for track_id, state in sorted(states.items())]
        status = "OK" if predictions else ("NO_TRACKS" if detected else "NO_PERSON")
        return {"status": status, "frames_read": frame_count, "predictions": predictions}

    @staticmethod
    def check_upload_length(frames, fps):
        if frames > MAX_UPLOAD_FRAMES or frames / fps > MAX_UPLOAD_SECONDS:
            raise VideoLimitExceeded("Upload must be at most 60 seconds and 3600 frames.")

    @staticmethod
    def update_upload_tracks(tracks, features, frame_index):
        for track_id, feature in features.items():
            track = tracks.setdefault(track_id, UploadTrack())
            track.observed_frames += 1
            if feature is not None:
                track.valid.append((frame_index, feature))

    def summarize_upload(self, track_id, track, fps):
        outcome = {"track_id": track_id, "observed_frames": track.observed_frames,
                   "valid_frames": len(track.valid)}
        if len(track.valid) < max(2, self.upload_min_frames):
            return outcome | self.unknown()
        indices, features = zip(*track.valid)
        times = np.asarray(indices, dtype=np.float64) / fps
        # Match Day06: keep the actual observation gaps between the first and
        # last valid poses, with no extrapolation before or after them.
        span = indices[-1] - indices[0] + 1
        if (len(indices) / span < self.runtime["min_valid_feature_ratio"]
                or np.max(np.diff(times)) > self.lost_timeout + 1e-9):
            return outcome | self.unknown()
        return outcome | classify_window(
            self.classifier, (np.stack(features), times), self.steps,
            self.runtime["confidence_threshold"],
        )

    @staticmethod
    def unknown(status="INSUFFICIENT_POSE"):
        return {"status": status, "action_label": "UNKNOWN", "confidence": None}


    def update_tracks(self, states, features, timestamp):
        for track_id, feature in features.items():
            state = states.get(track_id)
            if state is None:
                state = TrackState(TimedFeatureBuffer(self.runtime["window_seconds"]), timestamp)
                states[track_id] = state
            elif timestamp - state.last_seen > self.lost_timeout:
                state.window.items.clear()
                state.next_sample = timestamp
            state.last_seen = timestamp
            state.observed_frames += 1
            state.valid_frames += feature is not None

        for track_id, state in states.items():
            if timestamp - state.last_seen > self.lost_timeout:
                state.window.items.clear()
                continue
            state.window.append(timestamp, features.get(track_id))
            if track_id in features and timestamp >= state.next_sample and state.window.is_ready(self.runtime):
                state.latest_ready = state.window.valid_matrix_and_times()
                state.next_sample = timestamp + self.runtime["prediction_interval_sec"]

    def final_window_has_pose_but_is_short(self, window):
        required = self.runtime["window_seconds"] * self.runtime["min_window_fill_ratio"]
        if (window.duration() >= required
                or window.valid_ratio() < self.runtime["min_valid_feature_ratio"]):
            return False
        return sum(feature is not None for _, feature in window.items) >= self.runtime["min_valid_features"]


    def summarize(self, track_id, state):
        outcome = {
            "track_id": track_id,
            "observed_frames": state.observed_frames,
            "valid_frames": state.valid_frames,
        }
        if state.latest_ready is None:
            if self.final_window_has_pose_but_is_short(state.window):
                return outcome | self.unknown("INSUFFICIENT_DURATION")
            return outcome | self.unknown()
        return outcome | classify_window(
            self.classifier, state.latest_ready, self.steps, self.runtime["confidence_threshold"]
        )
