import numpy as np

from src.sequence_utils import flatten_sequence, resample_sequence


def classify_window(model, samples, steps, confidence_threshold):
    features, times = samples
    sequence = resample_sequence(features, times, target_steps=steps)
    row = flatten_sequence(sequence).reshape(1, -1)
    probabilities = model.predict_proba(row)[0]
    best = int(np.argmax(probabilities))
    confidence = float(probabilities[best])
    accepted = confidence >= confidence_threshold
    return {
        "status": "PREDICTED" if accepted else "LOW_CONFIDENCE",
        "action_label": str(model.classes_[best]) if accepted else "UNKNOWN",
        "confidence": confidence,
    }
