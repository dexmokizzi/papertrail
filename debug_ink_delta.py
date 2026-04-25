"""
Debug ink delta scores for T_Q1 to understand why all options
score equally high.
"""
import cv2
import numpy as np
import sys
sys.path.insert(0, '.')

from src.scanner.omr import (
    load_blank_reference,
    get_blank_reference,
    _score_ink_delta,
    _extract_blank_roi,
    _score_region,
)

# Load blank reference
blank_path = "data/scans/papertrail_test_survey/archive/CamScanner 4-24-26 22.47_blank_ref.jpg"
load_blank_reference("test", blank_path)
blank_img = get_blank_reference("test")

# Load filled scan
filled_img = cv2.imread(
    "data/processed/CamScanner 4-24-26 22.42_page01.jpg",
    cv2.IMREAD_GRAYSCALE
)

print(f"Blank size:  {blank_img.shape}")
print(f"Filled size: {filled_img.shape}")

# T_Q1 center points from YAML calibration
# These were calibrated on the blank scan
centers_q1 = {
    '1': (1428, 628),
    '2': (1662, 636),
    '3': (1860, 628),
    '4': (2036, 632),
}

r = 61  # dynamic radius for this survey

print("\n=== T_Q1 ink delta scores ===")
for val, (cx, cy) in centers_q1.items():
    # Filled ROI
    x1 = max(0, cx - r)
    y1 = max(0, cy - r)
    x2 = min(filled_img.shape[1], cx + r)
    y2 = min(filled_img.shape[0], cy + r)
    filled_roi = filled_img[y1:y2, x1:x2]

    # Blank ROI
    blank_roi = _extract_blank_roi(blank_img, filled_img, cx, cy, r)

    if blank_roi is not None:
        delta_score = _score_ink_delta(filled_roi, blank_roi)
        shape_score = _score_region(filled_roi, "circled_number")
        print(f"  Option {val}: ink_delta={delta_score:.3f}  shape={shape_score:.3f}")

        # Save diff image for visual inspection
        blank_resized = cv2.resize(
            blank_roi, (filled_roi.shape[1], filled_roi.shape[0]),
            interpolation=cv2.INTER_LINEAR
        )
        diff = cv2.absdiff(filled_roi, blank_resized)
        _, mask = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        cv2.imwrite(f"debug_q1_option{val}_filled.jpg", filled_roi)
        cv2.imwrite(f"debug_q1_option{val}_blank.jpg", blank_resized)
        cv2.imwrite(f"debug_q1_option{val}_diff.jpg", mask)
    else:
        print(f"  Option {val}: blank_roi is None")

print("\nDebug images saved to project root")