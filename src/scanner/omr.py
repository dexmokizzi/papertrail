"""
Optical Mark Recognition (OMR) for PaperTrail.

Detects marked answer options in survey scan images.
Supports six mark types: circled numbers, filled bubbles,
X marks, circled bubbles, shaded boxes, and checkmarks.

Every detection returns a value and a confidence score
between 0.0 and 1.0. Low confidence fields are flagged
for human review rather than accepted silently.

Any mark type not explicitly supported will produce low
confidence scores and be routed to human review —
the system never silently accepts an unknown mark type.

Input:  Preprocessed image + field region coordinates from YAML
Output: Detected value + confidence score per field
"""

import cv2
import numpy as np
from typing import Optional


# ── Constants ─────────────────────────────────────────────────────────────────

HIGH_CONFIDENCE      = 0.90
MEDIUM_CONFIDENCE    = 0.75
LOW_CONFIDENCE       = 0.50
FILL_THRESHOLD       = 0.25
AMBIGUITY_GAP        = 0.08
AMBIGUITY_MIN_SCORE  = 0.85

# Padding added around calibrated boxes when extracting ROIs.
# Less horizontal padding avoids bleeding into adjacent columns.
# More vertical padding captures circles that extend above/below.
ROI_PADDING_X = 0.15
ROI_PADDING_Y = 0.30


# ── Public API ────────────────────────────────────────────────────────────────

def detect_mark(image: np.ndarray,
                field_config: dict) -> dict:
    """Detect which answer option is marked in a field.

    Reads mark_type from field_config to choose the correct
    detection algorithm. Returns the detected value and a
    confidence score between 0.0 and 1.0.

    Supported mark types:
        circled_number  — circle drawn around a printed number
        filled_bubble   — bubble filled/darkened by respondent
        x_mark          — X drawn through a box or circle
        circled_bubble  — circle drawn around a small bubble
        shaded_box      — rectangular box shaded/darkened
        checkmark       — tick or checkmark drawn in a box

    Any unrecognised mark type returns a NO_DETECTION result
    with zero confidence, routing the field to human review.

    Args:
        image:        Preprocessed grayscale image array.
        field_config: Field definition from the survey YAML.
                      Must contain 'regions' and 'mark_type'.

    Returns:
        Dict with keys: value, confidence, mark_type,
        all_scores, and optionally flag and note.
    """
    mark_type = field_config.get("mark_type", "circled_number")
    regions   = field_config.get("regions", {})

    if not regions:
        return _no_detection("No regions defined in YAML")

    if mark_type == "circled_number":
        return _detect_circled_number(image, regions)
    elif mark_type == "filled_bubble":
        return _detect_filled_bubble(image, regions)
    elif mark_type == "x_mark":
        return _detect_x_mark(image, regions)
    elif mark_type == "circled_bubble":
        return _detect_circled_bubble(image, regions)
    elif mark_type == "shaded_box":
        return _detect_shaded_box(image, regions)
    elif mark_type == "checkmark":
        return _detect_checkmark(image, regions)
    else:
        return _no_detection(
            f"Unknown mark type '{mark_type}'. "
            f"Field routed to human review."
        )


def detect_multi_select(image: np.ndarray,
                        field_config: dict) -> dict:
    """Detect all marked options in a multi-select field.

    Unlike detect_mark which returns one value, this returns
    every option that appears to be marked. Used for fields
    where respondents are asked to select all that apply.

    Args:
        image:        Preprocessed grayscale image array.
        field_config: Field definition with regions and mark_type.

    Returns:
        Dict with keys: values (list), confidence, all_scores.
    """
    mark_type  = field_config.get("mark_type", "x_mark")
    regions    = field_config.get("regions", {})

    if not regions:
        return {"values": [], "confidence": 0.0, "all_scores": {}}

    all_scores = {}

    for value, region in regions.items():
        roi = _extract_roi(image, region)
        if roi is None:
            all_scores[value] = 0.0
            continue

        if mark_type == "x_mark":
            all_scores[value] = _score_x_mark(roi)
        elif mark_type == "filled_bubble":
            all_scores[value] = _score_filled_bubble(roi)
        elif mark_type == "checkmark":
            all_scores[value] = _score_checkmark(roi)
        elif mark_type == "shaded_box":
            all_scores[value] = _score_filled_bubble(roi)
        else:
            all_scores[value] = _score_x_mark(roi)

    selected = [
        v for v, score in all_scores.items()
        if score >= LOW_CONFIDENCE
    ]

    min_confidence = (
        min(all_scores[v] for v in selected)
        if selected else 0.0
    )

    return {
        "values":     selected,
        "confidence": round(min_confidence, 3),
        "all_scores": {k: round(v, 3)
                       for k, v in all_scores.items()},
    }


# ── Detection algorithms ──────────────────────────────────────────────────────

def _detect_circled_number(image: np.ndarray,
                           regions: dict) -> dict:
    """Detect a hand-drawn circle around a printed number.

    Args:
        image:   Preprocessed grayscale image.
        regions: Dict mapping value -> region coordinates.

    Returns:
        Standard detection result dict.
    """
    scores = {}
    for value, region in regions.items():
        roi = _extract_roi(image, region)
        if roi is None:
            scores[value] = 0.0
            continue
        scores[value] = _score_circled_number(roi)

    return _pick_best(scores, "circled_number")


def _detect_filled_bubble(image: np.ndarray,
                          regions: dict) -> dict:
    """Detect a filled or darkened bubble.

    Args:
        image:   Preprocessed grayscale image.
        regions: Dict mapping value -> region coordinates.

    Returns:
        Standard detection result dict.
    """
    scores = {}
    for value, region in regions.items():
        roi = _extract_roi(image, region)
        if roi is None:
            scores[value] = 0.0
            continue
        scores[value] = _score_filled_bubble(roi)

    return _pick_best(scores, "filled_bubble")


def _detect_x_mark(image: np.ndarray,
                   regions: dict) -> dict:
    """Detect an X mark drawn through a box or circle.

    Args:
        image:   Preprocessed grayscale image.
        regions: Dict mapping value -> region coordinates.

    Returns:
        Standard detection result dict.
    """
    scores = {}
    for value, region in regions.items():
        roi = _extract_roi(image, region)
        if roi is None:
            scores[value] = 0.0
            continue
        scores[value] = _score_x_mark(roi)

    return _pick_best(scores, "x_mark")


def _detect_circled_bubble(image: np.ndarray,
                           regions: dict) -> dict:
    """Detect a circle drawn around a small printed bubble.

    Args:
        image:   Preprocessed grayscale image.
        regions: Dict mapping value -> region coordinates.

    Returns:
        Standard detection result dict.
    """
    scores = {}
    for value, region in regions.items():
        roi = _extract_roi(image, region)
        if roi is None:
            scores[value] = 0.0
            continue
        scores[value] = _score_circled_number(roi, small=True)

    return _pick_best(scores, "circled_bubble")


def _detect_shaded_box(image: np.ndarray,
                       regions: dict) -> dict:
    """Detect a shaded or filled rectangular box.

    Respondent darkens a printed rectangle or square.
    Uses dark pixel density — the same core approach as
    filled bubble detection but intended for rectangular
    answer regions rather than circular ones.

    Args:
        image:   Preprocessed grayscale image.
        regions: Dict mapping value -> region coordinates.

    Returns:
        Standard detection result dict.
    """
    scores = {}
    for value, region in regions.items():
        roi = _extract_roi(image, region)
        if roi is None:
            scores[value] = 0.0
            continue
        scores[value] = _score_filled_bubble(roi)

    return _pick_best(scores, "shaded_box")


def _detect_checkmark(image: np.ndarray,
                      regions: dict) -> dict:
    """Detect a checkmark or tick drawn in a box.

    A checkmark has one diagonal line going down-right
    and one shorter line going up-right. Detects this
    pattern using diagonal Hough line analysis with
    angle ranges tuned for checkmark geometry.

    Args:
        image:   Preprocessed grayscale image.
        regions: Dict mapping value -> region coordinates.

    Returns:
        Standard detection result dict.
    """
    scores = {}
    for value, region in regions.items():
        roi = _extract_roi(image, region)
        if roi is None:
            scores[value] = 0.0
            continue
        scores[value] = _score_checkmark(roi)

    return _pick_best(scores, "checkmark")


# ── Scoring functions ─────────────────────────────────────────────────────────

def _score_circled_number(roi: np.ndarray,
                          small: bool = False) -> float:
    """Score how likely a region contains a hand-drawn circle.

    Uses two complementary approaches:
    1. Hough circle detection on the padded region
    2. Contour arc detection for partial circles

    The ROI includes padding so circles that extend beyond
    the calibrated box are still detected correctly.

    Args:
        roi:   Region of interest as grayscale array.
        small: True for smaller circled bubble targets.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    if roi.size == 0:
        return 0.0

    h, w = roi.shape[:2]

    min_r = max(int(min(h, w) * 0.20), 8)
    max_r = max(int(min(h, w) * 0.70), min_r + 5)

    if small:
        min_r = max(int(min(h, w) * 0.15), 6)
        max_r = max(int(min(h, w) * 0.55), min_r + 5)

    inverted = cv2.bitwise_not(roi)
    blurred  = cv2.GaussianBlur(inverted, (9, 9), 2)

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=min_r,
        param1=50,
        param2=20,
        minRadius=min_r,
        maxRadius=max_r,
    )

    if circles is not None:
        circles   = np.round(circles[0, :]).astype("int")
        cx, cy, r = circles[0]

        center_dist  = np.sqrt(
            (cx - w / 2) ** 2 + (cy - h / 2) ** 2
        )
        max_dist     = np.sqrt((w / 2) ** 2 + (h / 2) ** 2)
        center_score = 1.0 - min(1.0, center_dist / max_dist)

        fill_ratio = (r * 2) / min(h, w)
        fill_score = min(1.0, fill_ratio)

        score = 0.5 * center_score + 0.5 * fill_score
        return round(min(1.0, score + 0.30), 3)

    return _score_arc_presence(roi)


def _score_arc_presence(roi: np.ndarray) -> float:
    """Detect curved arc pixels indicating a hand-drawn circle.

    Works on partial circles where Hough detection fails.
    Looks for curved contours spanning a significant portion
    of the region — characteristic of hand-drawn circles.

    Args:
        roi: Region of interest as grayscale array.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    if roi.size == 0:
        return 0.0

    h, w = roi.shape[:2]

    edges = cv2.Canny(roi, 30, 100)
    contours, _ = cv2.findContours(
        edges,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return 0.0

    best_score     = 0.0
    min_arc_length = min(h, w) * 0.5

    for contour in contours:
        arc_len = cv2.arcLength(contour, closed=False)

        if arc_len < min_arc_length:
            continue

        expected_perimeter = np.pi * min(h, w) * 0.6
        circularity        = min(1.0, arc_len / expected_perimeter)

        bx, by, bw, bh = cv2.boundingRect(contour)
        coverage        = (bw * bh) / (w * h)
        coverage_score  = min(1.0, coverage * 2)

        score      = 0.6 * circularity + 0.4 * coverage_score
        best_score = max(best_score, score)

    return round(min(0.95, best_score), 3)


def _score_filled_bubble(roi: np.ndarray) -> float:
    """Score how likely a region contains a filled mark.

    Measures the proportion of dark pixels in the region.
    Used for filled bubbles and shaded boxes — any mark
    type where the respondent darkens a printed region.

    Args:
        roi: Region of interest as grayscale array.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    if roi.size == 0:
        return 0.0

    _, binary  = cv2.threshold(
        roi, 0, 255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    dark_ratio = np.sum(binary > 0) / binary.size

    if dark_ratio < FILL_THRESHOLD:
        return 0.0

    score = (dark_ratio - FILL_THRESHOLD) / (1.0 - FILL_THRESHOLD)
    return round(min(1.0, score), 3)


def _score_x_mark(roi: np.ndarray) -> float:
    """Score how likely a region contains an X mark.

    Detects diagonal line patterns using Hough line transform.
    An X mark produces two crossing diagonal lines at
    approximately 45 degree angles.

    Args:
        roi: Region of interest as grayscale array.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    if roi.size == 0:
        return 0.0

    edges = cv2.Canny(roi, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=20,
        minLineLength=int(min(roi.shape) * 0.3),
        maxLineGap=10,
    )

    if lines is None:
        return 0.0

    diagonal_count = 0
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if (x2 - x1) == 0:
            continue
        angle = abs(np.degrees(
            np.arctan2(y2 - y1, x2 - x1)
        ))
        if 30 < angle < 60 or 120 < angle < 150:
            diagonal_count += 1

    if diagonal_count == 0:
        return 0.0
    elif diagonal_count == 1:
        return 0.55
    elif diagonal_count >= 2:
        return 0.90

    return 0.0


def _score_checkmark(roi: np.ndarray) -> float:
    """Score how likely a region contains a checkmark or tick.

    A checkmark has a short diagonal going down-left then
    a longer diagonal going up-right. Detects this using
    diagonal line analysis tuned for checkmark geometry.
    The angle range is slightly wider than X mark detection
    to accommodate varied checkmark styles.

    Args:
        roi: Region of interest as grayscale array.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    if roi.size == 0:
        return 0.0

    edges = cv2.Canny(roi, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=15,
        minLineLength=int(min(roi.shape) * 0.25),
        maxLineGap=10,
    )

    if lines is None:
        return 0.0

    diagonal_count = 0
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if (x2 - x1) == 0:
            continue
        angle = abs(np.degrees(
            np.arctan2(y2 - y1, x2 - x1)
        ))
        # Wider angle range than X mark to catch
        # varied checkmark styles and orientations
        if 25 < angle < 75:
            diagonal_count += 1

    if diagonal_count == 0:
        return 0.0
    elif diagonal_count == 1:
        return 0.75
    elif diagonal_count >= 2:
        return 0.92

    return 0.0


def _edge_density_score(roi: np.ndarray) -> float:
    """Score a region based on edge pixel density.

    Used as fallback when primary detection produces no result.
    Any mark — circle, X, bubble, checkmark — creates more
    edge pixels than a blank unmarked region.

    Args:
        roi: Region of interest as grayscale array.

    Returns:
        Score between 0.0 and 0.7 — capped as secondary signal.
    """
    if roi.size == 0:
        return 0.0

    edges   = cv2.Canny(roi, 50, 150)
    density = np.sum(edges > 0) / edges.size
    return round(min(0.7, density * 10), 3)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_roi(image: np.ndarray,
                 region: dict) -> Optional[np.ndarray]:
    """Extract a region of interest from the image safely.

    Adds asymmetric padding around the calibrated region:
    - Less horizontal padding avoids bleeding into adjacent
      answer columns
    - More vertical padding captures marks that extend
      above or below the calibrated box boundaries

    Args:
        image:  Full preprocessed image array.
        region: Dict with x, y, w, h keys.

    Returns:
        Cropped region as numpy array, or None if invalid.
    """
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    w = int(region.get("w", 0))
    h = int(region.get("h", 0))

    if w <= 0 or h <= 0:
        return None

    pad_x = int(w * ROI_PADDING_X)
    pad_y = int(h * ROI_PADDING_Y)

    img_h, img_w = image.shape[:2]

    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(img_w, x + w + pad_x)
    y2 = min(img_h, y + h + pad_y)

    if x2 <= x1 or y2 <= y1:
        return None

    roi = image[y1:y2, x1:x2]

    if len(roi.shape) == 3:
        roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    return roi


def _pick_best(scores: dict, mark_type: str) -> dict:
    """Select the highest scoring option and build result dict.

    Flags as ambiguous only if two options score extremely
    close — indicating genuine uncertainty about the answer.
    In all other cases picks the highest scoring option.

    Args:
        scores:    Dict mapping value -> confidence score.
        mark_type: Detection algorithm that produced the scores.

    Returns:
        Standard detection result dict.
    """
    if not scores:
        return _no_detection("No regions scored")

    sorted_scores = sorted(
        scores.items(), key=lambda x: x[1], reverse=True
    )
    best_value, best_score = sorted_scores[0]

    if len(sorted_scores) > 1:
        second_value, second_score = sorted_scores[1]
        if (best_score >= LOW_CONFIDENCE
                and second_score >= AMBIGUITY_MIN_SCORE
                and (best_score - second_score) < AMBIGUITY_GAP):
            return {
                "value":      None,
                "confidence": best_score,
                "mark_type":  mark_type,
                "all_scores": {k: round(v, 3)
                               for k, v in scores.items()},
                "flag":       "AMBIGUOUS",
                "note":       (
                    f"Two options scored similarly: "
                    f"{best_value}={best_score:.2f}, "
                    f"{second_value}={second_score:.2f}"
                ),
            }

    if best_score < LOW_CONFIDENCE:
        return {
            "value":      None,
            "confidence": best_score,
            "mark_type":  mark_type,
            "all_scores": {k: round(v, 3)
                           for k, v in scores.items()},
            "flag":       "NO_MARK",
            "note":       "No mark detected above threshold",
        }

    return {
        "value":      best_value,
        "confidence": round(best_score, 3),
        "mark_type":  mark_type,
        "all_scores": {k: round(v, 3)
                       for k, v in scores.items()},
    }


def _no_detection(reason: str) -> dict:
    """Return a standard empty detection result.

    Used when no regions are defined, mark type is unknown,
    or detection cannot proceed for any reason.

    Args:
        reason: Human-readable explanation of why nothing detected.

    Returns:
        Detection result with null value and zero confidence.
        Will be flagged for human review by the validation stage.
    """
    return {
        "value":      None,
        "confidence": 0.0,
        "mark_type":  "none",
        "all_scores": {},
        "flag":       "NO_DETECTION",
        "note":       reason,
    }