"""
Optical Mark Recognition (OMR) for PaperTrail.

Detects marked answer options in survey scan images.
Supports six mark types: circled numbers, filled bubbles,
X marks, circled bubbles, shaded boxes, and checkmarks.

Two detection paths are available, selected by YAML format:

  Bounding box path  — regions contain x, y, w, h keys.
                       Extracts a padded ROI around each
                       declared region and scores it directly.

  Proximity path     — regions contain only x, y keys
                       (center points, no w or h).
                       Finds all marks in a search area,
                       then matches each to the nearest
                       declared center point.

Path selection is determined by YAML format only — never
by mark type. Both paths reuse the same scoring functions.
All detections return a confidence score 0.0–1.0. Fields
below threshold are flagged for human review, never silently
accepted.

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

# Circled bubble fields are physically separated options.
# A high-scoring second option almost always means the
# respondent circle extended into an adjacent region —
# not a genuine double mark. Use a tighter threshold.
CIRCLED_BUBBLE_AMBIGUITY_MIN = 0.96

# Padding added around calibrated boxes (bounding box path).
# Less horizontal padding avoids bleeding into adjacent columns.
# More vertical padding captures circles that extend above/below.
ROI_PADDING_X = 0.15
ROI_PADDING_Y = 0.30

# Margin added around the bounding box of all option center
# points when building the proximity search area (px).
PROXIMITY_MARGIN_PX = 200

# Minimum ROI dimension when building a synthetic ROI in the
# proximity path. Prevents degenerate crops on sparse layouts.
PROXIMITY_MIN_ROI_PX = 60

# Fixed window radius used by the per-option scoring approach.
# Each option center gets a square window of this radius.
# Verified at 40px on real scans — large enough to contain any
# hand-drawn circle, small enough to avoid adjacent option bleed.
PROXIMITY_OPTION_RADIUS = 40


# ── Path detection helper ─────────────────────────────────────────────────────

def _is_proximity_format(regions: dict) -> bool:
    """Check whether regions use center-point format.

    Center-point format contains only x and y keys per option.
    Bounding box format additionally contains w and h keys.
    Path selection is based solely on this format check —
    never on mark type or any other field attribute.

    Args:
        regions: Dict mapping value -> region coordinate dict.

    Returns:
        True if all regions use center-point format (no w or h).
        False if any region contains a w or h key.
    """
    if not regions:
        return False
    return all(
        "w" not in r and "h" not in r
        for r in regions.values()
        if isinstance(r, dict)
    )


# ── Public API ────────────────────────────────────────────────────────────────

def detect_mark(image: np.ndarray, field_config: dict) -> dict:
    """Detect which answer option is marked in a field.

    Selects detection path from YAML region format:
      - Bounding box path if regions contain w and h keys.
      - Proximity path if regions contain only x and y keys.

    Supported mark types for scoring:
        circled_number, filled_bubble, x_mark,
        circled_bubble, shaded_box, checkmark.

    Any unrecognised mark type returns a NO_DETECTION result
    with zero confidence, routing the field to human review.

    Args:
        image:        Preprocessed grayscale image array.
        field_config: Field definition from the survey YAML.
                      Must contain 'regions' and 'mark_type'.

    Returns:
        Dict with keys: value, confidence, mark_type,
        all_scores, path_used, and optionally flag and note.
    """
    mark_type = field_config.get("mark_type", "circled_number")
    regions   = field_config.get("regions", {})

    if not regions:
        return _no_detection("No regions defined in YAML")

    if _is_proximity_format(regions):
        return _detect_by_proximity(image, regions, mark_type)
    else:
        return _detect_by_bounding_box(image, regions, mark_type)


def detect_multi_select(image: np.ndarray,
                        field_config: dict) -> dict:
    """Detect all marked options in a multi-select field.

    Selects detection path from YAML region format, matching
    the same logic as detect_mark. Returns a list of every
    option that appears marked rather than a single value.

    An empty selection is stored as None so the field appears
    blank in output rather than as an empty list. The
    qualtrics_mapper formats a list as comma-separated string,
    e.g. [1, 3] becomes "1,3" for Qualtrics import.

    Args:
        image:        Preprocessed grayscale image array.
        field_config: Field definition with regions and mark_type.

    Returns:
        Dict with keys: value (list or None), confidence,
        mark_type, all_scores, path_used.
    """
    mark_type = field_config.get("mark_type", "x_mark")
    regions   = field_config.get("regions", {})

    if not regions:
        return {
            "value":      None,
            "confidence": 0.0,
            "mark_type":  mark_type,
            "all_scores": {},
            "path_used":  "none",
        }

    if _is_proximity_format(regions):
        return _multi_select_by_proximity(image, regions, mark_type)
    else:
        return _multi_select_by_bounding_box(image, regions, mark_type)


# ── Bounding box path ─────────────────────────────────────────────────────────

def _detect_by_bounding_box(image: np.ndarray,
                             regions: dict,
                             mark_type: str) -> dict:
    """Detect a mark using calibrated bounding box regions.

    Extracts a padded ROI around each declared region and
    scores it using the appropriate scoring function for the
    declared mark type. Selects the highest scoring option.

    Args:
        image:     Preprocessed grayscale image array.
        regions:   Dict mapping value -> {x, y, w, h} dict.
        mark_type: Scoring algorithm to use.

    Returns:
        Standard detection result dict with path_used=bbox.
    """
    scores = {}
    for value, region in regions.items():
        roi = _extract_roi(image, region)
        if roi is None:
            scores[value] = 0.0
            continue
        scores[value] = _score_region(roi, mark_type)

    ambiguity_min = (
        CIRCLED_BUBBLE_AMBIGUITY_MIN
        if mark_type == "circled_bubble"
        else AMBIGUITY_MIN_SCORE
    )
    result = _pick_best(scores, mark_type,
                        ambiguity_min=ambiguity_min)
    result["path_used"] = "bbox"
    return result


def _multi_select_by_bounding_box(image: np.ndarray,
                                   regions: dict,
                                   mark_type: str) -> dict:
    """Score all options in a multi-select field via bounding boxes.

    Args:
        image:     Preprocessed grayscale image array.
        regions:   Dict mapping value -> {x, y, w, h} dict.
        mark_type: Scoring algorithm to use.

    Returns:
        Dict with value (list or None), confidence, all_scores,
        mark_type, path_used.
    """
    all_scores = {}
    for value, region in regions.items():
        roi = _extract_roi(image, region)
        if roi is None:
            all_scores[value] = 0.0
            continue
        all_scores[value] = _score_region(roi, mark_type)

    return _build_multi_select_result(
        all_scores, mark_type, path_used="bbox"
    )


# ── Proximity path ────────────────────────────────────────────────────────────

def _detect_by_proximity(image: np.ndarray,
                          regions: dict,
                          mark_type: str) -> dict:
    """Detect a mark using per-option fixed-radius windows.

    For each declared center point, extracts a fixed-radius
    window around that point and scores it independently.
    Selects the option whose window scores highest.

    This approach is robust to any mark size — a large or
    small circle drawn around an option will always score
    highest in that option's own window, regardless of how
    far the ink extends beyond the center point.

    Args:
        image:     Preprocessed grayscale image array.
        regions:   Dict mapping value -> {x, y} center point.
        mark_type: Scoring algorithm used to score each window.

    Returns:
        Standard detection result dict with path_used=proximity.
    """
    centers = _parse_centers(regions)
    if not centers:
        return _no_detection("No valid center points in regions")

    scores = _score_per_option_windows(image, centers, mark_type)

    ambiguity_min = (
        CIRCLED_BUBBLE_AMBIGUITY_MIN
        if mark_type == "circled_bubble"
        else AMBIGUITY_MIN_SCORE
    )
    result = _pick_best(scores, mark_type,
                        ambiguity_min=ambiguity_min)
    result["path_used"] = "proximity"
    return result


def _log_proximity_search(search_area: tuple,
                           candidates: list) -> None:
    """Log proximity search results for silent failure diagnosis.

    Args:
        search_area: (x1, y1, x2, y2) search rectangle used.
        candidates:  List of (cx, cy, score) found in area.
    """
    x1, y1, x2, y2 = search_area
    print(f"      [proximity] search area: "
          f"x{x1}-{x2} y{y1}-{y2}  "
          f"candidates found: {len(candidates)}")
    if not candidates:
        print(f"      [proximity] NO_MARK — no candidates detected")


def _multi_select_by_proximity(image: np.ndarray,
                                regions: dict,
                                mark_type: str) -> dict:
    """Score all options in a multi-select field via per-option windows.

    Scores each option center independently using a fixed-radius
    window. All options scoring above LOW_CONFIDENCE are included
    in the selected list. This handles any mark size correctly
    because each option is scored in its own isolated window.

    Args:
        image:     Preprocessed grayscale image array.
        regions:   Dict mapping value -> {x, y} center point.
        mark_type: Scoring algorithm used to score each window.

    Returns:
        Dict with value (list or None), confidence, all_scores,
        mark_type, path_used.
    """
    centers    = _parse_centers(regions)
    all_scores = _score_per_option_windows(
        image, centers, mark_type
    )
    return _build_multi_select_result(
        all_scores, mark_type, path_used="proximity"
    )


# ── Proximity helpers ─────────────────────────────────────────────────────────

def _parse_centers(regions: dict) -> dict:
    """Extract center point coordinates from proximity-format regions.

    Args:
        regions: Dict mapping value -> {x, y} dict.

    Returns:
        Dict mapping value -> (x, y) tuple.
    """
    centers = {}
    for value, region in regions.items():
        if isinstance(region, dict):
            x = region.get("x")
            y = region.get("y")
            if x is not None and y is not None:
                centers[value] = (int(x), int(y))
    return centers


def _compute_option_radius(centers: dict) -> int:
    """Calculate a safe window radius from declared option spacing.

    Derives the radius dynamically from the minimum distance
    between any two declared center points. This ensures the
    window is always proportional to the actual form layout —
    wide spacing gives a larger window, tight spacing gives a
    smaller one. Works correctly for any survey layout and any
    image resolution without hardcoding.

    Falls back to PROXIMITY_OPTION_RADIUS if fewer than two
    center points are declared (single-option fields).

    Args:
        centers: Dict mapping value -> (x, y) center point.

    Returns:
        Window radius in pixels. Minimum 20px.
    """
    if len(centers) < 2:
        return PROXIMITY_OPTION_RADIUS

    points   = list(centers.values())
    min_dist = min(
        np.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)
        for i, p1 in enumerate(points)
        for p2 in points[i + 1:]
    )
    return max(20, int(min_dist * 0.35))


def _score_per_option_windows(image: np.ndarray,
                               centers: dict,
                               mark_type: str) -> dict:
    """Score each option using a fixed-radius window around its center.

    Extracts a square window of PROXIMITY_OPTION_RADIUS pixels
    around each declared center point and scores it with the
    appropriate scoring function. Each option is scored in its
    own isolated window — cross-option bleeding cannot occur.

    Args:
        image:     Full preprocessed image array.
        centers:   Dict mapping value -> (x, y) center point.
        mark_type: Scoring algorithm to apply to each window.

    Returns:
        Dict mapping value -> confidence score (0.0-1.0).
    """
    img_h, img_w = image.shape[:2]
    scores       = {}
    r            = _compute_option_radius(centers)

    for value, (cx, cy) in centers.items():
        x1  = max(0, cx - r)
        y1  = max(0, cy - r)
        x2  = min(img_w, cx + r)
        y2  = min(img_h, cy + r)
        roi = image[y1:y2, x1:x2]

        if len(roi.shape) == 3:
            roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        score        = _score_region(roi, mark_type)
        scores[value] = score

    return scores


def _build_search_area(image: np.ndarray,
                        centers: dict) -> tuple:
    """Build a search area from the bounding box of all center points.

    Expands the bounding box of all option centers by
    PROXIMITY_MARGIN_PX on every side, clamped to image bounds.

    Args:
        image:   Full preprocessed image array.
        centers: Dict mapping value -> (x, y) center point.

    Returns:
        Tuple (x1, y1, x2, y2) defining the search rectangle.
    """
    img_h, img_w = image.shape[:2]
    xs = [c[0] for c in centers.values()]
    ys = [c[1] for c in centers.values()]

    x1 = max(0, min(xs) - PROXIMITY_MARGIN_PX)
    y1 = max(0, min(ys) - PROXIMITY_MARGIN_PX)
    x2 = min(img_w, max(xs) + PROXIMITY_MARGIN_PX)
    y2 = min(img_h, max(ys) + PROXIMITY_MARGIN_PX)

    return (x1, y1, x2, y2)


def _find_candidates_in_area(image: np.ndarray,
                              search_area: tuple,
                              mark_type: str) -> list:
    """Find all mark candidates in a search area.

    Extracts the search area from the image and runs
    candidate detection appropriate to the mark type.
    Returns candidate positions in full-image coordinates.

    Args:
        image:       Full preprocessed image array.
        search_area: (x1, y1, x2, y2) search rectangle.
        mark_type:   Detection strategy to use.

    Returns:
        List of (cx, cy, score) tuples in image coordinates.
        cx, cy are the candidate center in full-image space.
    """
    x1, y1, x2, y2 = search_area
    strip = image[y1:y2, x1:x2]

    if strip.size == 0:
        return []

    if mark_type in ("circled_number", "circled_bubble"):
        local_candidates = _find_circle_candidates(
            strip, small=(mark_type == "circled_bubble")
        )
    elif mark_type == "filled_bubble":
        local_candidates = _find_bubble_candidates(strip)
    elif mark_type in ("x_mark", "checkmark"):
        local_candidates = _find_diagonal_candidates(strip)
    elif mark_type == "shaded_box":
        local_candidates = _find_bubble_candidates(strip)
    else:
        local_candidates = _find_circle_candidates(strip)

    # Convert local strip coordinates to full-image coordinates
    return [
        (cx + x1, cy + y1, score)
        for cx, cy, score in local_candidates
    ]


def _find_circle_candidates(strip: np.ndarray,
                             small: bool = False) -> list:
    """Find all circle-like marks in a strip image.

    Uses Hough circle detection with arc contour fallback.
    Returns candidate centers in strip-local coordinates.

    Args:
        strip: Cropped search area as grayscale array.
        small: True for smaller circled_bubble targets.

    Returns:
        List of (cx, cy, score) in strip-local coordinates.
    """
    if strip.size == 0:
        return []

    h, w    = strip.shape[:2]
    min_dim = min(h, w)
    min_r   = max(int(min_dim * (0.10 if small else 0.12)), 6)
    max_r   = max(int(min_dim * (0.45 if small else 0.55)),
                  min_r + 5)

    candidates = _run_hough_circles(strip, h, w, min_r, max_r)

    if not candidates:
        candidates = _find_arc_candidates(strip)

    return candidates


def _run_hough_circles(strip: np.ndarray,
                        h: int, w: int,
                        min_r: int, max_r: int) -> list:
    """Run Hough circle detection on a strip and return candidates.

    Args:
        strip: Cropped search area as grayscale array.
        h:     Strip height in pixels.
        w:     Strip width in pixels.
        min_r: Minimum circle radius to detect.
        max_r: Maximum circle radius to detect.

    Returns:
        List of (cx, cy, score) in strip-local coordinates.
    """
    inverted = cv2.bitwise_not(strip)
    blurred  = cv2.GaussianBlur(inverted, (9, 9), 2)

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=max(min_r, 20),
        param1=50,
        param2=18,
        minRadius=min_r,
        maxRadius=max_r,
    )

    if circles is None:
        return []

    candidates = []
    circles = np.round(circles[0, :]).astype("int")
    for cx, cy, r in circles:
        center_dist = np.sqrt(
            (cx - w / 2) ** 2 + (cy - h / 2) ** 2
        )
        max_dist = np.sqrt((w / 2) ** 2 + (h / 2) ** 2)
        score = max(0.0, min(1.0, 0.7 + 0.3 * (
            1.0 - center_dist / max(max_dist, 1)
        )))
        candidates.append((int(cx), int(cy), round(score, 3)))

    return candidates


def _find_arc_candidates(strip: np.ndarray) -> list:
    """Find partial circle candidates via arc contour analysis.

    Fallback for when Hough circle detection produces no results.
    Finds curved contours that span a significant portion of
    the strip — characteristic of hand-drawn circles.

    Args:
        strip: Cropped search area as grayscale array.

    Returns:
        List of (cx, cy, score) in strip-local coordinates.
    """
    if strip.size == 0:
        return []

    h, w   = strip.shape[:2]
    edges  = cv2.Canny(strip, 30, 100)
    contours, _ = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    candidates     = []
    min_arc_length = min(h, w) * 0.4

    for contour in contours:
        arc_len = cv2.arcLength(contour, closed=False)
        if arc_len < min_arc_length:
            continue

        bx, by, bw, bh = cv2.boundingRect(contour)
        cx = bx + bw // 2
        cy = by + bh // 2

        coverage  = (bw * bh) / max((w * h), 1)
        score     = round(min(0.85, coverage * 3 + 0.3), 3)
        candidates.append((cx, cy, score))

    return candidates


def _find_bubble_candidates(strip: np.ndarray) -> list:
    """Find filled bubble candidates by dark pixel density.

    Divides the strip into a grid of cells and scores each
    by dark pixel density. Returns cells above threshold
    as candidate marks.

    Args:
        strip: Cropped search area as grayscale array.

    Returns:
        List of (cx, cy, score) in strip-local coordinates.
    """
    if strip.size == 0:
        return []

    h, w = strip.shape[:2]
    cell = max(PROXIMITY_MIN_ROI_PX, min(h, w) // 4)
    candidates = []

    for row in range(0, h - cell // 2, cell // 2):
        for col in range(0, w - cell // 2, cell // 2):
            r1, r2 = row, min(row + cell, h)
            c1, c2 = col, min(col + cell, w)
            roi = strip[r1:r2, c1:c2]
            score = _score_region(roi, "filled_bubble")
            if score >= LOW_CONFIDENCE:
                cx = col + (c2 - c1) // 2
                cy = row + (r2 - r1) // 2
                candidates.append((cx, cy, score))

    return candidates


def _find_diagonal_candidates(strip: np.ndarray) -> list:
    """Find X mark or checkmark candidates by diagonal line density.

    Divides the strip into cells and scores each for diagonal
    line content. Returns cells above threshold as candidates.

    Args:
        strip: Cropped search area as grayscale array.

    Returns:
        List of (cx, cy, score) in strip-local coordinates.
    """
    if strip.size == 0:
        return []

    h, w = strip.shape[:2]
    cell = max(PROXIMITY_MIN_ROI_PX, min(h, w) // 4)
    candidates = []

    for row in range(0, h - cell // 2, cell // 2):
        for col in range(0, w - cell // 2, cell // 2):
            r1, r2 = row, min(row + cell, h)
            c1, c2 = col, min(col + cell, w)
            roi = strip[r1:r2, c1:c2]
            score = _score_region(roi, "x_mark")
            if score >= LOW_CONFIDENCE:
                cx = col + (c2 - c1) // 2
                cy = row + (r2 - r1) // 2
                candidates.append((cx, cy, score))

    return candidates


def _match_candidates_to_centers(candidates: list,
                                  centers: dict,
                                  image: np.ndarray,
                                  search_area: tuple,
                                  mark_type: str) -> dict:
    """Match detected candidates to declared option centers.

    For each candidate, finds the nearest option center by
    Euclidean distance. Assigns the candidate's score to that
    option if it beats any previously assigned score.
    Options with no nearby candidate receive score 0.0.

    Args:
        candidates:  List of (cx, cy, score) in image coordinates.
        centers:     Dict mapping value -> (x, y) center point.
        image:       Full image array (used for ROI scoring).
        search_area: (x1, y1, x2, y2) search bounds.
        mark_type:   Scoring algorithm for ROI verification.

    Returns:
        Dict mapping value -> best confidence score (0.0–1.0).
    """
    scores = {v: 0.0 for v in centers}

    for cx, cy, raw_score in candidates:
        distances = {
            v: np.sqrt((cx - px) ** 2 + (cy - py) ** 2)
            for v, (px, py) in centers.items()
        }
        sorted_opts  = sorted(distances.items(), key=lambda x: x[1])
        best_val, best_dist = sorted_opts[0]
        second_dist  = (sorted_opts[1][1]
                        if len(sorted_opts) > 1 else float("inf"))

        roi_score    = _score_candidate_roi(
            image, cx, cy, search_area, mark_type
        )
        final_score  = round(0.6 * raw_score + 0.4 * roi_score, 3)

        _log_candidate_match(
            cx, cy, best_val, best_dist, second_dist, final_score
        )

        if final_score > scores[best_val]:
            scores[best_val] = final_score

    return scores


def _log_candidate_match(cx: int, cy: int,
                          matched_option: str,
                          best_dist: float,
                          second_dist: float,
                          score: float) -> None:
    """Log a single candidate-to-center match for diagnosis.

    Args:
        cx:             Candidate center x in image coordinates.
        cy:             Candidate center y in image coordinates.
        matched_option: The option value this candidate matched.
        best_dist:      Distance to the matched center (px).
        second_dist:    Distance to the second-nearest center (px).
        score:          Final combined confidence score.
    """
    print(
        f"      [proximity] candidate ({cx},{cy}) "
        f"→ option {matched_option}  "
        f"dist={best_dist:.0f}px  "
        f"next={second_dist:.0f}px  "
        f"score={score:.2f}"
    )


def _score_candidate_roi(image: np.ndarray,
                          cx: int, cy: int,
                          search_area: tuple,
                          mark_type: str) -> float:
    """Score a synthetic ROI centred on a candidate position.

    Builds a fixed-size ROI around the candidate center point
    and scores it with the appropriate scoring function.
    Provides secondary signal to complement the position-based
    raw score from candidate detection.

    Args:
        image:       Full preprocessed image array.
        cx:          Candidate center x in image coordinates.
        cy:          Candidate center y in image coordinates.
        search_area: (x1, y1, x2, y2) to bound the ROI.
        mark_type:   Scoring algorithm to apply.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    img_h, img_w = image.shape[:2]
    half = PROXIMITY_MIN_ROI_PX

    x1 = max(0, cx - half)
    y1 = max(0, cy - half)
    x2 = min(img_w, cx + half)
    y2 = min(img_h, cy + half)

    if x2 <= x1 or y2 <= y1:
        return 0.0

    roi = image[y1:y2, x1:x2]
    if len(roi.shape) == 3:
        roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    return _score_region(roi, mark_type)


# ── Shared scoring dispatcher ─────────────────────────────────────────────────

def _score_region(roi: np.ndarray, mark_type: str) -> float:
    """Dispatch ROI scoring to the correct algorithm.

    Shared by both the bounding box path and the proximity path.
    Neither path changes HOW scoring works — only WHERE the
    ROI comes from.

    Args:
        roi:       Region of interest as grayscale array.
        mark_type: Algorithm name to apply.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    if mark_type in ("circled_number", "circled_bubble"):
        return _score_circled_number(
            roi, small=(mark_type == "circled_bubble")
        )
    elif mark_type == "filled_bubble":
        return _score_filled_bubble(roi)
    elif mark_type == "x_mark":
        return _score_x_mark(roi)
    elif mark_type == "shaded_box":
        return _score_filled_bubble(roi)
    elif mark_type == "checkmark":
        return _score_checkmark(roi)
    else:
        return _edge_density_score(roi)


# ── Scoring functions (unchanged) ─────────────────────────────────────────────

def _score_circled_number(roi: np.ndarray,
                          small: bool = False) -> float:
    """Score how likely a region contains a hand-drawn circle.

    Uses Hough circle detection first, falls back to arc
    contour detection for partial circles Hough misses.

    Args:
        roi:   Region of interest as grayscale array.
        small: True for smaller circled bubble targets.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    if roi.size == 0:
        return 0.0

    h, w  = roi.shape[:2]
    min_r = max(int(min(h, w) * (0.15 if small else 0.20)), 8)
    max_r = max(int(min(h, w) * (0.55 if small else 0.70)),
                min_r + 5)

    hough_score = _hough_circle_score(roi, h, w, min_r, max_r)
    if hough_score > 0.0:
        return hough_score

    return _score_arc_presence(roi)


def _hough_circle_score(roi: np.ndarray,
                         h: int, w: int,
                         min_r: int, max_r: int) -> float:
    """Score a region using Hough circle detection.

    Returns 0.0 if no circle is detected, so the caller
    can fall back to arc contour scoring.

    Args:
        roi:   Region of interest as grayscale array.
        h:     ROI height in pixels.
        w:     ROI width in pixels.
        min_r: Minimum circle radius to detect.
        max_r: Maximum circle radius to detect.

    Returns:
        Confidence score between 0.0 and 1.0, or 0.0 if
        no circle was detected by Hough.
    """
    inverted = cv2.bitwise_not(roi)
    blurred  = cv2.GaussianBlur(inverted, (9, 9), 2)

    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT,
        dp=1, minDist=min_r,
        param1=50, param2=20,
        minRadius=min_r, maxRadius=max_r,
    )

    if circles is None:
        return 0.0

    circles      = np.round(circles[0, :]).astype("int")
    cx, cy, r    = circles[0]
    center_dist  = np.sqrt((cx - w/2)**2 + (cy - h/2)**2)
    max_dist     = np.sqrt((w/2)**2 + (h/2)**2)
    center_score = 1.0 - min(1.0, center_dist / max(max_dist, 1))
    fill_score   = min(1.0, (r * 2) / min(h, w))

    return round(min(1.0, 0.5*center_score + 0.5*fill_score + 0.30), 3)


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
        circularity        = min(
            1.0, arc_len / max(expected_perimeter, 1)
        )

        bx, by, bw, bh = cv2.boundingRect(contour)
        coverage        = (bw * bh) / max(w * h, 1)
        coverage_score  = min(1.0, coverage * 2)

        score      = 0.6 * circularity + 0.4 * coverage_score
        best_score = max(best_score, score)

    return round(min(0.95, best_score), 3)


def _score_filled_bubble(roi: np.ndarray) -> float:
    """Score how likely a region contains a filled mark.

    Measures the proportion of dark pixels in the region.
    Used for filled bubbles and shaded boxes.

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
    dark_ratio = np.sum(binary > 0) / max(binary.size, 1)

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
    The angle range is slightly wider than X mark detection.

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
    Any mark creates more edge pixels than a blank region.

    Args:
        roi: Region of interest as grayscale array.

    Returns:
        Score between 0.0 and 0.7 — capped as secondary signal.
    """
    if roi.size == 0:
        return 0.0

    edges   = cv2.Canny(roi, 50, 150)
    density = np.sum(edges > 0) / max(edges.size, 1)
    return round(min(0.7, density * 10), 3)


# ── Bounding box ROI extraction ───────────────────────────────────────────────

def _extract_roi(image: np.ndarray,
                 region: dict) -> Optional[np.ndarray]:
    """Extract a region of interest from the image with padding.

    Adds asymmetric padding around the calibrated region:
    - Less horizontal padding avoids bleeding into adjacent columns
    - More vertical padding captures marks that extend above/below

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


# ── Result builders ───────────────────────────────────────────────────────────

def _pick_best(scores: dict,
               mark_type: str,
               ambiguity_min: float = AMBIGUITY_MIN_SCORE) -> dict:
    """Select the highest scoring option and build result dict.

    Delegates to ambiguity check and no-mark check helpers.
    Returns a clean detection result in all cases.

    Args:
        scores:        Dict mapping value -> confidence score.
        mark_type:     Detection algorithm that produced scores.
        ambiguity_min: Minimum second-option score to trigger
                       ambiguity check.

    Returns:
        Standard detection result dict.
    """
    if not scores:
        return _no_detection("No regions scored")

    sorted_scores  = sorted(
        scores.items(), key=lambda x: x[1], reverse=True
    )
    best_value, best_score = sorted_scores[0]

    if len(sorted_scores) > 1:
        second_value, second_score = sorted_scores[1]
        ambiguous = _check_ambiguity(
            best_score, best_value,
            second_score, second_value,
            ambiguity_min
        )
        if ambiguous:
            ambiguous["mark_type"]  = mark_type
            ambiguous["all_scores"] = {k: round(v, 3)
                                       for k, v in scores.items()}
            return ambiguous

    if best_score < LOW_CONFIDENCE:
        return _no_mark_result(scores, mark_type)

    return {
        "value":      best_value,
        "confidence": round(best_score, 3),
        "mark_type":  mark_type,
        "all_scores": {k: round(v, 3)
                       for k, v in scores.items()},
    }


def _check_ambiguity(best_score: float, best_value: str,
                      second_score: float, second_value: str,
                      ambiguity_min: float) -> Optional[dict]:
    """Check whether two top scores indicate ambiguous marking.

    Returns a partial result dict if ambiguous, else None.

    Args:
        best_score:    Score of the top option.
        best_value:    Value label of the top option.
        second_score:  Score of the second-best option.
        second_value:  Value label of the second-best option.
        ambiguity_min: Minimum second score to trigger flag.

    Returns:
        Partial result dict with flag=AMBIGUOUS, or None.
    """
    if (best_score >= LOW_CONFIDENCE
            and second_score >= ambiguity_min
            and (best_score - second_score) < AMBIGUITY_GAP):
        return {
            "value":      None,
            "confidence": best_score,
            "flag":       "AMBIGUOUS",
            "note":       (
                f"Two options scored similarly: "
                f"{best_value}={best_score:.2f}, "
                f"{second_value}={second_score:.2f}"
            ),
        }
    return None


def _no_mark_result(scores: dict, mark_type: str) -> dict:
    """Build a NO_MARK result when best score is below threshold.

    Args:
        scores:    Dict mapping value -> confidence score.
        mark_type: Detection algorithm used.

    Returns:
        Detection result with null value, NO_MARK flag.
    """
    best_score = max(scores.values()) if scores else 0.0
    return {
        "value":      None,
        "confidence": best_score,
        "mark_type":  mark_type,
        "all_scores": {k: round(v, 3) for k, v in scores.items()},
        "flag":       "NO_MARK",
        "note":       "No mark detected above threshold",
    }


def _build_multi_select_result(all_scores: dict,
                                mark_type: str,
                                path_used: str) -> dict:
    """Build the result dict for a multi-select detection.

    Selects all options scoring at or above LOW_CONFIDENCE.
    Returns None (not empty list) when nothing is selected
    so the field appears blank rather than as an empty value.

    Args:
        all_scores: Dict mapping value -> confidence score.
        mark_type:  Detection algorithm used.
        path_used:  'bbox' or 'proximity'.

    Returns:
        Dict with value (list or None), confidence, all_scores,
        mark_type, path_used.
    """
    selected = [
        v for v, score in all_scores.items()
        if score >= LOW_CONFIDENCE
    ]

    min_confidence = (
        min(all_scores[v] for v in selected)
        if selected else 0.0
    )

    return {
        "value":      selected if selected else None,
        "confidence": round(min_confidence, 3),
        "mark_type":  mark_type,
        "all_scores": {k: round(v, 3)
                       for k, v in all_scores.items()},
        "path_used":  path_used,
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
        "path_used":  "none",
    }


def _no_detection_with_scores(scores: dict,
                               mark_type: str) -> dict:
    """Return a NO_MARK result with zero scores for all options.

    Used when the proximity path finds no candidates at all.
    Preserves the all_scores dict so validate.py can see
    every option was checked and none registered a mark.

    Args:
        scores:    Dict mapping value -> 0.0 for each option.
        mark_type: Mark type that was being detected.

    Returns:
        Detection result with null value and zero confidence.
    """
    return {
        "value":      None,
        "confidence": 0.0,
        "mark_type":  mark_type,
        "all_scores": scores,
        "flag":       "NO_MARK",
        "note":       (
            "Proximity search found no mark candidates "
            "in the declared search area"
        ),
        "path_used":  "proximity",
    }