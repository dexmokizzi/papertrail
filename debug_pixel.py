"""
Check actual pixel values to understand why ink delta scores 1.0 everywhere.
"""
import cv2
import numpy as np

blank_img  = cv2.imread(
    "data/scans/papertrail_test_survey/archive/CamScanner 4-24-26 22.47_blank_ref.jpg",
    cv2.IMREAD_GRAYSCALE
)
filled_img = cv2.imread(
    "data/processed/CamScanner 4-24-26 22.42_page01.jpg",
    cv2.IMREAD_GRAYSCALE
)

# Check a region we know should be BLANK on both scans
# (somewhere with no answer options — e.g. the header area)
blank_header  = blank_img[50:150, 200:600]
filled_header = filled_img[50:150, 200:600]

diff_header = cv2.absdiff(blank_header, filled_header)
_, mask_header = cv2.threshold(diff_header, 30, 255, cv2.THRESH_BINARY)
noise_ratio = np.sum(mask_header > 0) / max(mask_header.size, 1)

print(f"=== Header region (should be identical on both) ===")
print(f"Blank  pixel range: {blank_header.min()} - {blank_header.max()}")
print(f"Filled pixel range: {filled_header.min()} - {filled_header.max()}")
print(f"Mean diff: {diff_header.mean():.2f}")
print(f"Noise ratio (should be near 0): {noise_ratio:.3f}")

# Check T_Q1 option 4 region (the answer that was circled)
cx, cy, r = 2036, 632, 61
blank_roi  = blank_img[cy-r:cy+r, cx-r:cx+r]
filled_roi = filled_img[cy-r:cy+r, cx-r:cx+r]

diff = cv2.absdiff(blank_roi, filled_roi)
_, mask = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
mark_ratio = np.sum(mask > 0) / max(mask.size, 1)

print(f"\n=== T_Q1 option 4 (selected answer) ===")
print(f"Blank  pixel range: {blank_roi.min()} - {blank_roi.max()}")
print(f"Filled pixel range: {filled_roi.min()} - {filled_roi.max()}")
print(f"Mean diff: {diff.mean():.2f}")
print(f"Mark ratio: {mark_ratio:.3f}")

# Save visual comparison
cv2.imwrite("debug_header_blank.jpg", blank_header)
cv2.imwrite("debug_header_filled.jpg", filled_header)
cv2.imwrite("debug_header_diff.jpg", diff_header)
cv2.imwrite("debug_q1opt4_blank.jpg", blank_roi)
cv2.imwrite("debug_q1opt4_filled.jpg", filled_roi)
cv2.imwrite("debug_q1opt4_diff.jpg", diff)

print("\nSaved debug images")