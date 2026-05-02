"""
Debug what moondream actually says for a single row crop.
"""
import base64
import requests
import cv2
import yaml

with open("config/surveys/papertrail_test_survey.yaml") as f:
    config = yaml.safe_load(f)

fields = config.get("fields", [])
img    = cv2.imread(
    "data/processed/CamScanner 4-24-26 22.42_page01.jpg"
)

# Test just T_Q1
field   = fields[0]
regions = field.get("regions", {})
xs      = [r["x"] for r in regions.values() if "x" in r]
ys      = [r["y"] for r in regions.values() if "y" in r]

margin  = 80
x1 = max(0,            min(xs) - margin)
y1 = max(0,            min(ys) - margin)
x2 = min(img.shape[1], max(xs) + margin)
y2 = min(img.shape[0], max(ys) + margin)

crop = img[y1:y2, x1:x2]
cv2.imwrite("debug_crop_q1.jpg", crop)
print(f"Crop size: {crop.shape}")

_, buf   = cv2.imencode(".jpg", crop)
img_b64  = base64.b64encode(buf).decode()

# Try a simpler prompt
for prompt in [
    "What number is circled?",
    "Which number has a circle drawn around it? Just say the number.",
    "Describe what you see in this image.",
]:
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
    print(f"\nPrompt: {prompt}")
    print(f"Response: {raw}")
