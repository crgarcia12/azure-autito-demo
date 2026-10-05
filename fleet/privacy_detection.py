from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import math
from pathlib import Path

import cv2
import numpy as np

from fleet.config import ROOT
from fleet.insurance import IncidentError

FACE_MODEL_PATH = ROOT / "fleet" / "models" / "face_detection_yunet_2023mar.onnx"
FACE_MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
TEXT_MODEL_PATH = ROOT / "fleet" / "models" / "text_detection_en_ppocrv3_2023may.onnx"
TEXT_MODEL_SHA256 = "03f550c6b406fda8bf54bd8327815f6c7e2edd98cea02348c93d879254366587"


@dataclass(frozen=True)
class DetectedRegion:
    left: float
    top: float
    right: float
    bottom: float
    confidence: float


@lru_cache(maxsize=2)
def verified_model(path: Path, expected_sha256: str) -> str:
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise IncidentError("A privacy detector model is missing or damaged. No privacy-cleared image can be produced.", 503)
    return str(path)


def decode_image(normalized_image: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(normalized_image, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if image is None:
        raise IncidentError("The privacy detector could not read the normalized photograph.", 400)
    return image


def detect_faces(normalized_image: bytes) -> list[DetectedRegion]:
    image = decode_image(normalized_image)
    height, width = image.shape[:2]
    try:
        detector = cv2.FaceDetectorYN.create(verified_model(FACE_MODEL_PATH, FACE_MODEL_SHA256), "", (width, height), 0.7, 0.3, 5000)
        _, detections = detector.detect(image)
    except cv2.error as error:
        raise IncidentError("Face detection failed. The photograph cannot be shared without privacy review.", 503) from error
    if detections is None:
        return []
    faces = []
    for row in detections:
        x, y, w, h, confidence = (float(row[index]) for index in (0, 1, 2, 3, 14))
        if not all(math.isfinite(value) for value in (x, y, w, h, confidence)) or w <= 0 or h <= 0:
            raise IncidentError("The face detector returned invalid image coordinates.", 502)
        left, top, right, bottom = max(0, x), max(0, y), min(width, x + w), min(height, y + h)
        if left >= right or top >= bottom:
            raise IncidentError("The detected face lies outside the photograph.", 502)
        faces.append(DetectedRegion(left, top, right, bottom, confidence))
    return faces


def detect_text(normalized_image: bytes) -> list[DetectedRegion]:
    image = decode_image(normalized_image)
    height, width = image.shape[:2]
    size = 736
    scale = min(size / width, size / height)
    resized_width, resized_height = round(width * scale), round(height * scale)
    left, top = (size - resized_width) // 2, (size - resized_height) // 2
    resized = cv2.resize(image, (resized_width, resized_height))
    canvas = cv2.copyMakeBorder(resized, top, size - resized_height - top, left, size - resized_width - left,
                               cv2.BORDER_CONSTANT, value=(0, 0, 0))
    try:
        detector = cv2.dnn_TextDetectionModel_DB(verified_model(TEXT_MODEL_PATH, TEXT_MODEL_SHA256))
        detector.setBinaryThreshold(.3)
        detector.setPolygonThreshold(.5)
        detector.setUnclipRatio(2.0)
        detector.setMaxCandidates(200)
        detector.setInputSize((size, size))
        detector.setInputMean((123.675, 116.28, 103.53))
        detector.setInputScale(1.0 / 255.0 / np.array([.229, .224, .225]))
        polygons, confidences = detector.detect(canvas)
    except cv2.error as error:
        raise IncidentError("Text detection failed. The photograph cannot be shared without privacy review.", 503) from error
    regions = []
    for polygon, confidence in zip(polygons, confidences):
        points = polygon.astype(float)
        if not np.isfinite(points).all() or not math.isfinite(float(confidence)):
            raise IncidentError("The text detector returned invalid image coordinates.", 502)
        # Undo letterboxing using each actual resize ratio, including rounding of the shorter edge.
        points[:, 0] = (points[:, 0] - left) * width / resized_width
        points[:, 1] = (points[:, 1] - top) * height / resized_height
        x1, y1 = max(0, float(points[:, 0].min())), max(0, float(points[:, 1].min()))
        x2, y2 = min(width, float(points[:, 0].max())), min(height, float(points[:, 1].max()))
        if x1 < x2 and y1 < y2:
            regions.append(DetectedRegion(x1, y1, x2, y2, float(confidence)))
    return regions
