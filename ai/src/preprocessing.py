from __future__ import annotations

import cv2
import numpy as np


def enhance_low_light(image: np.ndarray, clip_limit: float = 2.0) -> np.ndarray:
    """Apply CLAHE to luminance; keep optional until baseline comparison."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, channel_a, channel_b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    enhanced = cv2.merge((clahe.apply(lightness), channel_a, channel_b))
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
