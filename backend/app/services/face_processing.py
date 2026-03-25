from __future__ import annotations

import math

import cv2
import numpy as np


_FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
_EYE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
_SMILE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_smile.xml")


def _decode_image(processed_bytes: bytes) -> np.ndarray | None:
    image_array = np.frombuffer(processed_bytes, dtype=np.uint8)
    return cv2.imdecode(image_array, cv2.IMREAD_COLOR)


def _largest_face(faces) -> tuple[int, int, int, int] | None:
    if len(faces) == 0:
        return None
    return tuple(max(faces, key=lambda row: row[2] * row[3]))


def _round_point(x: float, y: float) -> dict:
    return {"x": round(float(x), 2), "y": round(float(y), 2)}


def _normalized_point(x: float, y: float, *, width: int, height: int) -> dict:
    return {
        "x": round(float(x) / float(width), 4),
        "y": round(float(y) / float(height), 4),
    }


def _point_payload(
    *,
    x: float,
    y: float,
    source: str,
    confidence: float,
    width: int,
    height: int,
) -> dict:
    return {
        "point": _round_point(x, y),
        "normalized": _normalized_point(x, y, width=width, height=height),
        "source": source,
        "confidence": round(float(confidence), 3),
    }


def _detect_eyes(roi_gray, *, face_x: int, face_y: int, face_width: int, face_height: int) -> list[tuple[float, float]]:
    detections = _EYE_CASCADE.detectMultiScale(
        roi_gray,
        scaleFactor=1.08,
        minNeighbors=5,
        minSize=(20, 20),
    )
    eyes: list[tuple[float, float]] = []
    for eye_x, eye_y, eye_width, eye_height in detections:
        center_x = face_x + eye_x + (eye_width / 2.0)
        center_y = face_y + eye_y + (eye_height / 2.0)
        if center_y > face_y + (face_height * 0.65):
            continue
        eyes.append((center_x, center_y))

    eyes.sort(key=lambda item: item[0])
    unique_eyes: list[tuple[float, float]] = []
    for center in eyes:
        if not unique_eyes:
            unique_eyes.append(center)
            continue
        previous = unique_eyes[-1]
        if abs(previous[0] - center[0]) < face_width * 0.1 and abs(previous[1] - center[1]) < face_height * 0.1:
            continue
        unique_eyes.append(center)
    return unique_eyes


def _detect_mouth_center(roi_gray, *, face_x: int, face_y: int, face_width: int, face_height: int) -> tuple[float, float] | None:
    lower_half = roi_gray[int(face_height * 0.45) :, :]
    detections = _SMILE_CASCADE.detectMultiScale(
        lower_half,
        scaleFactor=1.6,
        minNeighbors=20,
        minSize=(max(30, int(face_width * 0.2)), max(18, int(face_height * 0.08))),
    )
    if len(detections) == 0:
        return None

    mouth_x, mouth_y, mouth_width, mouth_height = max(detections, key=lambda row: row[2] * row[3])
    absolute_y = face_y + int(face_height * 0.45) + mouth_y + (mouth_height / 2.0)
    absolute_x = face_x + mouth_x + (mouth_width / 2.0)
    return absolute_x, absolute_y


def extract_landmark_snapshot(*, processed_bytes: bytes) -> dict:
    decoded = _decode_image(processed_bytes)
    if decoded is None:
        return {
            "version": "coarse-v1",
            "face_count": 0,
            "image_size": None,
            "face_bbox": None,
            "landmarks": {},
            "quality": {
                "coverage": "none",
                "detected_feature_count": 0,
                "reason": "decode_failed",
            },
        }

    height, width = decoded.shape[:2]
    gray = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)
    faces = _FACE_CASCADE.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(80, 80),
    )
    primary_face = _largest_face(faces)
    if primary_face is None:
        return {
            "version": "coarse-v1",
            "face_count": 0,
            "image_size": {"width": width, "height": height},
            "face_bbox": None,
            "landmarks": {},
            "quality": {
                "coverage": "none",
                "detected_feature_count": 0,
                "reason": "no_face_detected",
            },
        }

    face_x, face_y, face_width, face_height = primary_face
    roi_gray = gray[face_y : face_y + face_height, face_x : face_x + face_width]
    eye_points = _detect_eyes(
        roi_gray,
        face_x=face_x,
        face_y=face_y,
        face_width=face_width,
        face_height=face_height,
    )
    mouth_center = _detect_mouth_center(
        roi_gray,
        face_x=face_x,
        face_y=face_y,
        face_width=face_width,
        face_height=face_height,
    )

    left_eye_source = "cascade"
    right_eye_source = "cascade"
    left_eye_confidence = 0.82
    right_eye_confidence = 0.82
    if len(eye_points) >= 2:
        left_eye = eye_points[0]
        right_eye = eye_points[-1]
    else:
        left_eye = (face_x + (face_width * 0.32), face_y + (face_height * 0.38))
        right_eye = (face_x + (face_width * 0.68), face_y + (face_height * 0.38))
        if len(eye_points) == 1:
            detected_eye = eye_points[0]
            if detected_eye[0] <= face_x + (face_width / 2.0):
                left_eye = detected_eye
                left_eye_source = "cascade"
                left_eye_confidence = 0.82
                right_eye_source = "heuristic"
                right_eye_confidence = 0.42
            else:
                right_eye = detected_eye
                right_eye_source = "cascade"
                right_eye_confidence = 0.82
                left_eye_source = "heuristic"
                left_eye_confidence = 0.42
        else:
            left_eye_source = "heuristic"
            right_eye_source = "heuristic"
            left_eye_confidence = 0.35
            right_eye_confidence = 0.35

    if mouth_center is None:
        mouth_center = (face_x + (face_width / 2.0), face_y + (face_height * 0.75))
        mouth_source = "heuristic"
        mouth_confidence = 0.38
    else:
        mouth_source = "cascade"
        mouth_confidence = 0.7

    nose_tip_x = (left_eye[0] + right_eye[0] + (mouth_center[0] * 1.2)) / 3.2
    nose_tip_y = (left_eye[1] + right_eye[1] + (mouth_center[1] * 1.4)) / 3.4
    chin_center = (face_x + (face_width / 2.0), face_y + (face_height * 0.94))
    forehead_center = (face_x + (face_width / 2.0), face_y + (face_height * 0.16))
    left_cheek = (face_x + (face_width * 0.18), face_y + (face_height * 0.58))
    right_cheek = (face_x + (face_width * 0.82), face_y + (face_height * 0.58))
    jaw_left = (face_x + (face_width * 0.14), face_y + (face_height * 0.88))
    jaw_right = (face_x + (face_width * 0.86), face_y + (face_height * 0.88))

    eye_distance = math.dist(left_eye, right_eye)
    eye_line_angle_deg = math.degrees(math.atan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0]))

    landmarks = {
        "left_eye": _point_payload(
            x=left_eye[0],
            y=left_eye[1],
            source=left_eye_source,
            confidence=left_eye_confidence,
            width=width,
            height=height,
        ),
        "right_eye": _point_payload(
            x=right_eye[0],
            y=right_eye[1],
            source=right_eye_source,
            confidence=right_eye_confidence,
            width=width,
            height=height,
        ),
        "nose_tip": _point_payload(
            x=nose_tip_x,
            y=nose_tip_y,
            source="derived",
            confidence=0.56,
            width=width,
            height=height,
        ),
        "mouth_center": _point_payload(
            x=mouth_center[0],
            y=mouth_center[1],
            source=mouth_source,
            confidence=mouth_confidence,
            width=width,
            height=height,
        ),
        "chin_center": _point_payload(
            x=chin_center[0],
            y=chin_center[1],
            source="derived",
            confidence=0.5,
            width=width,
            height=height,
        ),
        "forehead_center": _point_payload(
            x=forehead_center[0],
            y=forehead_center[1],
            source="derived",
            confidence=0.44,
            width=width,
            height=height,
        ),
        "left_cheek": _point_payload(
            x=left_cheek[0],
            y=left_cheek[1],
            source="derived",
            confidence=0.41,
            width=width,
            height=height,
        ),
        "right_cheek": _point_payload(
            x=right_cheek[0],
            y=right_cheek[1],
            source="derived",
            confidence=0.41,
            width=width,
            height=height,
        ),
        "jaw_left": _point_payload(
            x=jaw_left[0],
            y=jaw_left[1],
            source="derived",
            confidence=0.39,
            width=width,
            height=height,
        ),
        "jaw_right": _point_payload(
            x=jaw_right[0],
            y=jaw_right[1],
            source="derived",
            confidence=0.39,
            width=width,
            height=height,
        ),
    }

    return {
        "version": "coarse-v1",
        "face_count": len(faces),
        "image_size": {"width": width, "height": height},
        "face_bbox": {
            "x": int(face_x),
            "y": int(face_y),
            "width": int(face_width),
            "height": int(face_height),
            "normalized": {
                "x": round(float(face_x) / float(width), 4),
                "y": round(float(face_y) / float(height), 4),
                "width": round(float(face_width) / float(width), 4),
                "height": round(float(face_height) / float(height), 4),
            },
        },
        "landmarks": landmarks,
        "quality": {
            "coverage": "coarse",
            "detected_feature_count": len(landmarks),
            "eye_line_angle_deg": round(float(eye_line_angle_deg), 2),
            "eye_distance_px": round(float(eye_distance), 2),
            "landmark_profile": "enhanced_coarse",
            "mesh_ready": False,
        },
    }


def build_deidentified_capture(*, processed_bytes: bytes, landmark_snapshot: dict | None = None) -> tuple[bytes | None, dict]:
    decoded = _decode_image(processed_bytes)
    if decoded is None:
        return None, {
            "metadata_removed": True,
            "deidentification_applied": False,
            "method": "metadata_only",
            "reason": "decode_failed",
        }

    snapshot = landmark_snapshot or extract_landmark_snapshot(processed_bytes=processed_bytes)
    face_bbox = snapshot.get("face_bbox") or {}
    if not face_bbox:
        return None, {
            "metadata_removed": True,
            "deidentification_applied": False,
            "method": "metadata_only",
            "reason": "face_bbox_missing",
        }

    height, width = decoded.shape[:2]
    face_x = int(face_bbox["x"])
    face_y = int(face_bbox["y"])
    face_width = int(face_bbox["width"])
    face_height = int(face_bbox["height"])

    padding_x = max(10, int(face_width * 0.12))
    padding_y = max(10, int(face_height * 0.16))
    start_x = max(0, face_x - padding_x)
    end_x = min(width, face_x + face_width + padding_x)
    start_y = max(0, face_y - padding_y)
    end_y = min(height, face_y + face_height + padding_y)

    face_region = decoded[start_y:end_y, start_x:end_x]
    downsampled_width = max(18, (end_x - start_x) // 10)
    downsampled_height = max(18, (end_y - start_y) // 10)
    pixelated = cv2.resize(face_region, (downsampled_width, downsampled_height), interpolation=cv2.INTER_LINEAR)
    pixelated = cv2.resize(pixelated, (end_x - start_x, end_y - start_y), interpolation=cv2.INTER_NEAREST)
    decoded[start_y:end_y, start_x:end_x] = pixelated

    landmarks = snapshot.get("landmarks") or {}
    left_eye = (landmarks.get("left_eye") or {}).get("point")
    right_eye = (landmarks.get("right_eye") or {}).get("point")
    nose_tip = (landmarks.get("nose_tip") or {}).get("point")
    mouth_center = (landmarks.get("mouth_center") or {}).get("point")
    eye_bar_applied = False
    feature_mask_applied = False
    if left_eye and right_eye:
        eye_bar_height = max(8, int(face_height * 0.12))
        bar_padding = max(6, int(face_width * 0.06))
        bar_start_x = max(0, int(min(left_eye["x"], right_eye["x"])) - bar_padding)
        bar_end_x = min(width, int(max(left_eye["x"], right_eye["x"])) + bar_padding)
        bar_center_y = int((left_eye["y"] + right_eye["y"]) / 2.0)
        bar_start_y = max(0, bar_center_y - (eye_bar_height // 2))
        bar_end_y = min(height, bar_center_y + (eye_bar_height // 2))
        cv2.rectangle(decoded, (bar_start_x, bar_start_y), (bar_end_x, bar_end_y), (0, 0, 0), thickness=-1)
        eye_bar_applied = True

    if nose_tip and mouth_center:
        center_x = int((float(nose_tip["x"]) + float(mouth_center["x"])) / 2.0)
        center_y = int((float(nose_tip["y"]) + float(mouth_center["y"])) / 2.0)
        axes = (
            max(18, int(face_width * 0.22)),
            max(22, int(face_height * 0.2)),
        )
        cv2.ellipse(decoded, (center_x, center_y), axes, 0, 0, 360, (0, 0, 0), thickness=-1)
        feature_mask_applied = True

    success, encoded = cv2.imencode(".jpg", decoded, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not success:
        return None, {
            "metadata_removed": True,
            "deidentification_applied": False,
            "method": "metadata_only",
            "reason": "encode_failed",
        }

    privacy_snapshot = {
        "metadata_removed": True,
        "deidentification_applied": True,
        "method": "pixelate_face_region_with_feature_mask",
        "eye_bar_applied": eye_bar_applied,
        "feature_mask_applied": feature_mask_applied,
        "masked_region": {
            "x": start_x,
            "y": start_y,
            "width": end_x - start_x,
            "height": end_y - start_y,
        },
        "landmark_keys": sorted(list(landmarks.keys())),
    }
    return encoded.tobytes(), privacy_snapshot
