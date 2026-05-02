"""
Test moondream accuracy using individual row crops
instead of the full page image.
"""
import base64
import json
import requests
import cv2
import yaml
import time

# Load the survey config to get center points
with open("config/surveys/papertrail_test_survey.yaml") as f:
    config = yaml.safe_load(f)

fields = config.get("fields", [])

# Load the filled scan
img = cv2.imread(
    "data/processed/CamScanner 4-24-26 22.42_page01.jpg"
)

known = {
    "T_Q1":4,"T_Q2":3,"T_Q3":2,"T_Q4":3,"T_Q5":3,
    "T_Q6":3,"T_Q7":1,"T_Q8":1,"T_Q9":2,"T_Q10":4
}

correct = 0
total   = 0
start   = time.time()

print(f"{'Field':<12} {'Got':>4} {'Exp':>4} {'OK'}")
print("-" * 35)

for field in fields:
    fid     = field.get("paper_id")
    regions = field.get("regions", {})
    if not regions or fid not in known:
        continue

    # Get bounding box of all option centers for this field
    xs = [r["x"] for r in regions.values() if "x" in r]
    ys = [r["y"] for r in regions.values() if "y" in r]
    if not xs or not ys:
        continue

    margin = 80
    x1 = max(0,              min(xs) - margin)
    y1 = max(0,              min(ys) - margin)
    x2 = min(img.shape[1],   max(xs) + margin)
    y2 = min(img.shape[0],   max(ys) + margin)

    # Crop just this row
    crop = img[y1:y2, x1:x2]

    # Encode crop
    _, buf = cv2.imencode(".jpg", crop)
    img_b64 = base64.b64encode(buf).decode()

    # Ask moondream about just this one row
    vals = sorted(regions.keys())
    prompt = (
        f"This shows one row of a survey. "
        f"The answer options are {', '.join(vals)} from left to right. "
        f"Which number has been circled or marked? "
        f"Reply with just the number."
    )

    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model":  "moondream",
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
        },
        timeout=60,
    )

    raw = resp.json().get("response", "").strip()

    # Extract just the number from response
    detected = None
    for val in vals:
        if str(val) in raw:
            detected = str(val)
            break

    expected = str(known[fid])
    ok       = "✅" if detected == expected else "❌"
    if detected == expected:
        correct += 1
    total += 1

    print(f"{fid:<12} {str(detected):>4} {expected:>4} {ok}  ({raw[:30]})")

elapsed = round(time.time() - start, 1)
print(f"\n{correct}/{total} correct in {elapsed}s")
print(f"({round(elapsed/total, 1)}s per field)")
