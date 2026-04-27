"""
Show all option scores for every field to understand
the ink delta score distribution.
"""
import cv2
import numpy as np
import sys, yaml
sys.path.insert(0, '.')

from src.scanner.omr import (
    load_blank_reference,
    get_blank_reference,
    _score_ink_delta,
    _extract_blank_roi,
    _compute_option_radius,
    _parse_centers,
)

blank_path = "data/scans/papertrail_test_survey/archive/CamScanner 4-24-26 22.47_preprocessed.jpg"
load_blank_reference("test", blank_path)
blank_img  = get_blank_reference("test")
filled_img = cv2.imread(
    "data/processed/CamScanner 4-25-26 16.25_page01.jpg",
    cv2.IMREAD_GRAYSCALE
)

with open("config/surveys/papertrail_test_survey.yaml") as f:
    config = yaml.safe_load(f)

fields = config.get("fields", [])

print(f"{'Field':<12} {'Win':>4}  {'Scores'}")
print("-" * 70)

for field in fields:
    fid     = field["paper_id"]
    regions = field.get("regions", {})
    if not regions:
        continue

    centers = _parse_centers(regions)
    r       = _compute_option_radius(centers)

    scores = {}
    for val, (cx, cy) in centers.items():
        x1 = max(0, cx - r)
        y1 = max(0, cy - r)
        x2 = min(filled_img.shape[1], cx + r)
        y2 = min(filled_img.shape[0], cy + r)
        f_roi     = filled_img[y1:y2, x1:x2]
        blank_roi = _extract_blank_roi(blank_img, filled_img, cx, cy, r)
        scores[val] = _score_ink_delta(f_roi, blank_roi) \
            if blank_roi is not None else 0.0

    winner  = max(scores, key=scores.get)
    win_val = scores[winner]
    second  = sorted(scores.values(), reverse=True)[1]
    gap     = win_val - second

    score_str = "  ".join(f"{v}:{scores[v]:.3f}" for v in sorted(scores))
    print(f"{fid:<12} → {winner}  gap={gap:.3f}  [{score_str}]")
