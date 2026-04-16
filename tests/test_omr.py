import cv2
import yaml
from src.scanner.omr import detect_mark

image = cv2.imread(
    'data/processed/CamScanner 3-21-26 14.29.jpg',
    cv2.IMREAD_GRAYSCALE
)

with open('config/surveys/test_survey.yaml', 'r') as f:
    config = yaml.safe_load(f)

print(f"{'Field':<8} {'Detected':<10} {'Confidence':<12} {'Scores'}")
print("-" * 70)

for field in config['fields']:
    field['mark_type'] = 'circled_number'
    result = detect_mark(image, field)
    scores = result.get('all_scores', {})
    score_str = "  ".join(
        f"{v}:{s:.2f}" for v, s in sorted(scores.items())
    )
    flag  = f"  [{result.get('flag','')}]" if result.get('flag') else ""
    value = result.get('value', '-')
    conf  = result.get('confidence', 0.0)
    print(f"{field['paper_id']:<8} {str(value):<10} "
          f"{conf:<12.2f} {score_str}{flag}")