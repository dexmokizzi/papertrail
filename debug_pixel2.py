"""
Check ink delta values after preprocessing fix.
"""
import cv2
import numpy as np

# Load preprocessed blank reference
blank_img = cv2.imread(
    "data/scans/papertrail_test_survey/archive/CamScanner 4-24-26 22.47_preprocessed.jpg",
    cv2.IMREAD_GRAYSCALE
)
filled_img = cv2.imread(
    "data/processed/CamScanner 4-24-26 22.42_page01.jpg",
    cv2.IMREAD_GRAYSCALE
)

print(f"Blank  pixel range: {blank_img.min()} - {blank_img.max()}")
print(f"Filled pixel range: {filled_img.min()} - {filled_img.max()}")

# Check header region — should be near identical now
blank_header  = blank_img[50:150, 200:600]
filled_header = filled_img[50:150, 200:600]
diff_header   = cv2.absdiff(blank_header, filled_header)
_, mask = cv2.threshold(diff_header, 30, 255, cv2.THRESH_BINARY)
noise = np.sum(mask > 0) / max(mask.size, 1)
print(f"\nHeader noise ratio (should be low): {noise:.3f}")
print(f"Header mean diff: {diff_header.mean():.2f}")

# Check each option of T_Q1
centers = {
    '1': (1428, 628),
    '2': (1662, 636),
    '3': (1860, 628),
    '4': (2036, 632),
}
r = 61

print(f"\n=== T_Q1 raw ink ratios at threshold 0, 10, 20, 30 ===")
for val, (cx, cy) in centers.items():
    fx1, fy1 = max(0, cx-r), max(0, cy-r)
    fx2, fy2 = min(filled_img.shape[1], cx+r), min(filled_img.shape[0], cy+r)
    f_roi = filled_img[fy1:fy2, fx1:fx2]

    bh, bw = blank_img.shape[:2]
    fh, fw = filled_img.shape[:2]
    sx, sy = bw/fw, bh/fh
    bx1 = max(0, int((cx-r)*sx))
    by1 = max(0, int((cy-r)*sy))
    bx2 = min(bw, int((cx+r)*sx))
    by2 = min(bh, int((cy+r)*sy))
    b_roi = blank_img[by1:by2, bx1:bx2]

    b_resized = cv2.resize(b_roi, (f_roi.shape[1], f_roi.shape[0]))
    diff = cv2.absdiff(f_roi, b_resized)

    ratios = {}
    for thresh in [0, 10, 20, 30, 40]:
        _, m = cv2.threshold(diff, thresh, 255, cv2.THRESH_BINARY)
        ratios[thresh] = round(np.sum(m > 0) / max(m.size, 1), 3)

    print(f"  Option {val}: {ratios}  mean_diff={diff.mean():.1f}")

    cv2.imwrite(f"debug_v2_opt{val}_filled.jpg", f_roi)
    cv2.imwrite(f"debug_v2_opt{val}_blank.jpg", b_resized)
    cv2.imwrite(f"debug_v2_opt{val}_diff.jpg", diff)