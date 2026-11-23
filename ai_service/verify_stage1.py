"""Verify the local Day06 artifacts before wiring them into the AI service."""

import hashlib
import json
from pathlib import Path
import sys
import warnings

import joblib
import sklearn
from sklearn.exceptions import InconsistentVersionWarning
from sklearn.ensemble import RandomForestClassifier
from ultralytics import YOLO

from src.common import load_config
from src.realtime_utils import validate_runtime_config
from src.sequence_utils import FRAME_FEATURE_NAMES, sequence_feature_names


ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models"
MODEL_FILE = MODEL_DIR / "rf_action_baseline.joblib"
POSE_FILE = MODEL_DIR / "yolo11n-pose.pt"
DAY06_SHA256 = "da6377a69acadca10c02fd5376500a10a2edfe1bde5d4953f2c7a133a5896dac"
POSE_SHA256 = "869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0"
ACTION_CLASSES = {
    "bend_return", "drink_return", "leg_raise_lower",
    "sit_stand", "walk_turn_walk", "wave",
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_digest(path, expected):
    # Check the known local artifact before deserializing it.
    with path.open("rb") as file:
        actual = hashlib.file_digest(file, "sha256").hexdigest()
    require(actual == expected, f"Unexpected SHA-256: {path}")


def load_models():
    training = read_json(MODEL_DIR / "rf_training_info.json")
    columns = read_json(MODEL_DIR / "rf_feature_columns.json")
    baseline = read_json(ROOT / "configs/day06_baseline.json")
    validate_runtime_config(read_json(ROOT / "configs/day07_realtime.json"))

    steps = training["sequence_steps"]
    frame_width = len(FRAME_FEATURE_NAMES)
    input_width = steps * frame_width
    require(steps == baseline["sequence_steps"] == 30, "Expected 30 sequence steps")
    require(frame_width == 38 and training["feature_count"] == input_width == 1140,
            "Expected 38 features per step and 1140 total")
    require(columns == sequence_feature_names(steps),
            "Feature names or order differ from Day06")

    verify_digest(MODEL_FILE, DAY06_SHA256)
    with warnings.catch_warnings():
        warnings.simplefilter("error", InconsistentVersionWarning)
        model = joblib.load(MODEL_FILE)
    require(isinstance(model, RandomForestClassifier), "Expected a Random Forest classifier")
    require(model.n_features_in_ == input_width, "Model input width differs")
    classes = list(map(str, model.classes_))
    require(len(classes) == len(ACTION_CLASSES) and set(classes) == ACTION_CLASSES
            and classes == training["classes"], "Model classes or their order differ")

    config = load_config()
    require((ROOT / config["pose_model"]).resolve() == POSE_FILE,
            "Pose config does not point to the local Day06 weight")
    verify_digest(POSE_FILE, POSE_SHA256)
    pose = YOLO(str(POSE_FILE), task="pose")
    keypoint_shape = tuple(pose.model.yaml["kpt_shape"])
    require(keypoint_shape == (17, 3), "Expected COCO17 pose weights")


    return pose, model, steps, config


def main():
    pose, model, steps, _ = load_models()
    frame_width = len(FRAME_FEATURE_NAMES)
    columns = sequence_feature_names(steps)
    classes = list(map(str, model.classes_))
    keypoint_shape = tuple(pose.model.yaml["kpt_shape"])
    print(f"Python: {sys.executable} ({sys.version.split()[0]})")
    print(f"scikit-learn: {sklearn.__version__} ({sklearn.__file__})")
    print(f"Random Forest input: {model.n_features_in_} = {steps} x {frame_width}")
    print(f"Ordered feature names: {len(columns)} matched ({columns[0]} ... {columns[-1]})")
    print(f"Classes ({len(classes)}): {', '.join(classes)}")
    print(f"Local YOLO Pose weights loaded: kpt_shape={keypoint_shape}")
    print("Stage 1 artifact verification: PASS")


if __name__ == "__main__":
    main()
