from dataclasses import dataclass
import math
from threading import Lock

import cv2
import numpy as np

from services.action_inference import classify_window
from src.common import resolve_device
from src.realtime_utils import TimedFeatureBuffer, frame_feature_from_keypoints
from verify_stage1 import ROOT, read_json


class InvalidVideo(ValueError):
    pass


@dataclass
class TrackState:
    window: TimedFeatureBuffer
    last_seen: float
    observed_frames: int = 0
    valid_frames: int = 0
    latest_ready: tuple | None = None
    next_sample: float = 0.0


def tracked_features(result, keypoint_threshold):
    boxes = result.boxes
    if boxes is None or boxes.id is None:
        return {}
    ids = boxes.id.int().cpu().tolist()
    keypoints = result.keypoints
    if keypoints is None or keypoints.conf is None:
        return dict.fromkeys(ids)

    points = keypoints.xy.cpu().numpy()
    scores = keypoints.conf.cpu().numpy()
    if len(points) != len(ids) or len(scores) != len(ids):
        return dict.fromkeys(ids)

    features = {}
    for track_id, xy, confidence in zip(ids, points, scores):
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

    def analyze(self, path):
        # YOLO's predictor and ByteTrack are mutable. Never share their state
        # between simultaneous requests or consecutive videos.
        with self.lock:
            for tracker in getattr(self.pose.predictor, "trackers", []):
                tracker.reset()
            return self.read_video(path)

    def read_video(self, path):
        capture = cv2.VideoCapture(str(path))
        states = {}
        frame_count = 0
        detected = False
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not capture.isOpened() or not math.isfinite(fps) or fps <= 0:
                raise InvalidVideo("Could not open the video or read its frame rate.")

            while True:
                ok, frame = capture.read()
                if not ok:
                    break
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
                features = tracked_features(result, self.config["keypoint_confidence"])
                self.update_tracks(states, features, timestamp)
                frame_count += 1
        finally:
            capture.release()

        if frame_count == 0:
            raise InvalidVideo("The video has no decodable frames.")
        predictions = [self.summarize(track_id, state) for track_id, state in sorted(states.items())]
        status = "OK" if predictions else ("NO_TRACKS" if detected else "NO_PERSON")
        return {"status": status, "frames_read": frame_count, "predictions": predictions}

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

    def summarize(self, track_id, state):
        outcome = {
            "track_id": track_id,
            "observed_frames": state.observed_frames,
            "valid_frames": state.valid_frames,
        }
        if state.latest_ready is None:
            return outcome | {"status": "INSUFFICIENT_POSE", "action_label": "UNKNOWN", "confidence": None}
        return outcome | classify_window(
            self.classifier, state.latest_ready, self.steps, self.runtime["confidence_threshold"]
        )
