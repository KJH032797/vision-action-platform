from __future__ import annotations

"""Day 7 sliding-window helpers; feature math is reused from Day 6."""
from collections import Counter, deque
import time
import numpy as np
from src.feature_utils import normalize_by_shoulder_width, selected_joint_angles
from src.sequence_utils import flatten_sequence, resample_sequence


def validate_runtime_config(config: dict) -> None:
    required = {"window_seconds", "min_window_fill_ratio", "min_valid_feature_ratio", "min_valid_features", "prediction_interval_sec", "confidence_threshold", "stabilization_buffer", "stabilization_min_votes"}
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"Runtime 설정 누락: {missing}")
    if float(config["window_seconds"]) <= 0 or float(config["prediction_interval_sec"]) <= 0:
        raise ValueError("window_seconds와 prediction_interval_sec는 0보다 커야 합니다.")
    for key in ("min_window_fill_ratio", "min_valid_feature_ratio"):
        if not 0 < float(config[key]) <= 1:
            raise ValueError(f"{key}는 0보다 크고 1 이하여야 합니다.")
    if not 0 <= float(config["confidence_threshold"]) <= 1:
        raise ValueError("confidence_threshold는 0~1이어야 합니다.")
    if int(config["min_valid_features"]) < 2 or int(config["stabilization_buffer"]) < 1:
        raise ValueError("유효 Feature 수는 2 이상, 안정화 버퍼는 1 이상이어야 합니다.")
    if not 1 <= int(config["stabilization_min_votes"]) <= int(config["stabilization_buffer"]):
        raise ValueError("stabilization_min_votes는 버퍼 크기 이하여야 합니다.")


def frame_feature_from_pose(result) -> np.ndarray | None:
    """가장 confidence가 높은 사람을 Day 6의 38-D 규칙으로 변환합니다."""
    if result.boxes is None or result.keypoints is None or len(result.boxes) == 0:
        return None
    xy = result.keypoints.xy.detach().cpu().numpy()
    box_conf = result.boxes.conf.detach().cpu().numpy()
    if len(xy) == 0:
        return None
    return frame_feature_from_keypoints(xy[int(np.argmax(box_conf[:len(xy)]))])


def frame_feature_from_keypoints(points) -> np.ndarray | None:
    if points.shape != (17, 2):
        return None
    try:
        normalized, _, _ = normalize_by_shoulder_width(points)
    except ValueError:
        return None
    angles = selected_joint_angles(points)
    values = [float(v) for point in normalized for v in point]
    values.extend(float(angles[name]) for name in ("left_elbow_angle", "right_elbow_angle", "left_knee_angle", "right_knee_angle"))
    result_array = np.asarray(values, dtype=np.float32)
    return result_array if len(result_array) == 38 and np.all(np.isfinite(result_array)) else None


class TimedFeatureBuffer:
    """시간 기준으로 오래된 프레임을 버리고 최근 Window만 보관합니다."""
    def __init__(self, window_seconds: float):
        if float(window_seconds) <= 0:
            raise ValueError("window_seconds는 0보다 커야 합니다.")
        self.window_seconds = float(window_seconds)
        self.items = deque()

    def append(self, timestamp: float, feature) -> None:
        self.items.append((float(timestamp), feature))
        cutoff = float(timestamp) - self.window_seconds
        while self.items and self.items[0][0] < cutoff:
            self.items.popleft()

    def duration(self) -> float:
        return self.items[-1][0] - self.items[0][0] if len(self.items) > 1 else 0.0

    def valid_ratio(self) -> float:
        return sum(feature is not None for _, feature in self.items) / len(self.items) if self.items else 0.0

    def valid_matrix_and_times(self):
        valid = [(stamp, feature) for stamp, feature in self.items if feature is not None]
        if not valid:
            return np.empty((0, 38), dtype=np.float32), np.asarray([], dtype=np.float32)
        return np.stack([np.asarray(feature, dtype=np.float32) for _, feature in valid]), np.asarray([stamp for stamp, _ in valid], dtype=np.float32)

    def is_ready(self, config: dict) -> bool:
        valid_count = sum(feature is not None for _, feature in self.items)
        return (self.duration() >= self.window_seconds * float(config["min_window_fill_ratio"])
                and self.valid_ratio() >= float(config["min_valid_feature_ratio"])
                and valid_count >= int(config["min_valid_features"]))


class PredictionStabilizer:
    """최근 결과의 다수결로 예측 흔들림을 줄입니다."""
    def __init__(self, buffer_size: int, min_votes: int):
        if buffer_size < 1 or not 1 <= min_votes <= buffer_size:
            raise ValueError("stabilization 설정을 확인하세요.")
        self.buffer = deque(maxlen=int(buffer_size))
        self.min_votes = int(min_votes)

    def update(self, label: str) -> str:
        self.buffer.append(str(label))
        best, votes = Counter(self.buffer).most_common(1)[0]
        return best if votes >= self.min_votes else "UNKNOWN"


class FPSMeter:
    def __init__(self):
        self.started = time.perf_counter()
        self.frames = 0

    def update(self) -> float:
        self.frames += 1
        return self.frames / max(time.perf_counter() - self.started, 1e-9)


def predict_from_window(model, feature_buffer: TimedFeatureBuffer, sequence_steps: int, confidence_threshold: float):
    features, times = feature_buffer.valid_matrix_and_times()
    sequence = resample_sequence(features, times, int(sequence_steps))
    flattened = flatten_sequence(sequence).reshape(1, -1)
    probabilities = model.predict_proba(flattened)[0]
    index = int(np.argmax(probabilities))
    raw_label, confidence = str(model.classes_[index]), float(probabilities[index])
    return (raw_label if confidence >= float(confidence_threshold) else "UNKNOWN", raw_label, confidence)
