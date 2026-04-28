"""
Debug centroid scores for all fields on both scans.
"""
import cv2
import numpy as np
import sys
import yaml
sys.path.insert(0, '.')

from src.scanner.omr import (
    load_blank_reference,
    get_blank_reference,
    _score_by_ink_centroid,
    _parse_centers,
)

blank_path = "data/scans/papertrail_test_survey/archive/CamScanner 4-24-26 22.47_preprocessed.jpg"
load_blank_reference("test", blank_path)
blank_img = get_blank_reference("test")

with open("config/surveys/papertrail_test_survey.yaml") as f:
    config = yaml.safe_load(f)

fields = config.get("fields", [])

for scan, label, known in [
    ("data/processed/CamScanner 4-24-26 22.42_page01.jpg",
     "Scan 1", [4,3,2,3,3,3,1,1,2,4]),
    ("data/processed/CamScanner 4-25-26 16.25_page01.jpg",
     "Scan 2", [3,2,3,1,3,1,3,2,1,4]),
]:
    img = cv2.imread(scan, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print(f"Could not load {scan}")
        continue

    print(f"\n=== {label} ===")
    print(f"{'Field':<12} {'Win':>4} {'Exp':>4} {'Score':>6} {'OK'}")
    print("-" * 45)

    for i, field in enumerate(fields):
        fid     = field["paper_id"]
        regions = field.get("regions", {})
        if not regions:
            continue

        centers = _parse_centers(regions)
        scores  = _score_by_ink_centroid(img, centers, blank_img)

        winner   = max(scores, key=scores.get)
        win_score = scores[winner]
        expected = str(known[i])
        correct  = "✅" if winner == expected else "❌"

        print(f"{fid:<12} {winner:>4} {expected:>4} {win_score:>6.3f} {correct}")
