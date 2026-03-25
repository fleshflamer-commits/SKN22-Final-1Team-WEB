from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image


MIN_FACE_SIZE_RATIO = 0.08
MIN_BRIGHTNESS = 35.0
MAX_BRIGHTNESS = 220.0
MIN_SHARPNESS = 45.0

_FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def sanitize_original_upload(*, image: Image.Image, original_ext: str) -> tuple[bytes, str]:
    ext = original_ext.lower()
    target_format = "JPEG"
    sanitized_ext = ".jpg"

    if ext == ".png":
        target_format = "PNG"
        sanitized_ext = ".png"
    elif ext == ".webp":
        target_format = "WEBP"
        sanitized_ext = ".webp"

    buffer = io.BytesIO()
    if target_format == "JPEG":
        image.convert("RGB").save(buffer, target_format, quality=95, optimize=True)
    else:
        image.save(buffer, target_format)
    return buffer.getvalue(), sanitized_ext


def validate_capture_image(*, processed_bytes: bytes) -> dict:
    image_array = np.frombuffer(processed_bytes, dtype=np.uint8)
    decoded = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if decoded is None:
        return {
            "is_valid": False,
            "status": "NEEDS_RETAKE",
            "face_count": 0,
            "reason_code": "decode_failed",
            "message": "The image could not be processed. Please take the photo again.",
        }

    gray = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    faces = _FACE_CASCADE.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(80, 80),
    )
    face_count = len(faces)

    if brightness < MIN_BRIGHTNESS:
        return {
            "is_valid": False,
            "status": "NEEDS_RETAKE",
            "face_count": face_count,
            "reason_code": "too_dark",
            "message": "The image is too dark for reliable face detection. Please retake it in a brighter place.",
        }
    if brightness > MAX_BRIGHTNESS:
        return {
            "is_valid": False,
            "status": "NEEDS_RETAKE",
            "face_count": face_count,
            "reason_code": "too_bright",
            "message": "The image is too bright for reliable face detection. Please adjust the lighting and retake it.",
        }
    if face_count == 0:
        return {
            "is_valid": False,
            "status": "NEEDS_RETAKE",
            "face_count": 0,
            "reason_code": "no_face_detected",
            "message": "No face was detected. Please look straight at the camera and retake the photo.",
        }
    if face_count > 1:
        return {
            "is_valid": False,
            "status": "NEEDS_RETAKE",
            "face_count": face_count,
            "reason_code": "multiple_faces_detected",
            "message": "More than one face was detected. Please retake the photo with only one person in frame.",
        }

    height, width = gray.shape[:2]
    x, y, face_width, face_height = faces[0]
    face_area_ratio = float(face_width * face_height) / float(width * height)
    if face_area_ratio < MIN_FACE_SIZE_RATIO:
        return {
            "is_valid": False,
            "status": "NEEDS_RETAKE",
            "face_count": face_count,
            "reason_code": "face_too_small",
            "message": "The face appears too small. Please move closer to the camera and retake the photo.",
        }
    if sharpness < MIN_SHARPNESS:
        return {
            "is_valid": False,
            "status": "NEEDS_RETAKE",
            "face_count": face_count,
            "reason_code": "too_blurry",
            "message": "The image is too blurry for reliable analysis. Please hold still and retake the photo.",
        }

    return {
        "is_valid": True,
        "status": "PENDING",
        "face_count": face_count,
        "reason_code": "ok",
        "message": "Face detection succeeded. Analysis is now in progress.",
    }
