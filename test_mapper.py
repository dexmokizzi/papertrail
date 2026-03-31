import cv2
import yaml
from src.scanner.omr import detect_mark
from src.qualtrics_mapper import build_import_file, load_survey_config

# ── Step 1: Load image and detect marks ───────────────────────────────────────
print("=" * 60)
print("Step 1 — Detecting marks from scan")
print("=" * 60)

image = cv2.imread(
    'data/processed/CamScanner 3-21-26 14.29.jpg',
    cv2.IMREAD_GRAYSCALE
)

with open('config/surveys/test_survey.yaml', 'r') as f:
    config = yaml.safe_load(f)

extraction = {}
for field in config['fields']:
    field['mark_type'] = 'circled_number'
    result = detect_mark(image, field)
    extraction[field['paper_id']] = result.get('value')
    print(f"  {field['paper_id']}  →  {result.get('value')}  "
          f"(confidence: {result.get('confidence', 0):.2f})")

print(f"\n  Extraction complete: {extraction}")

# ── Step 2: Build Qualtrics import file ───────────────────────────────────────
print("\n" + "=" * 60)
print("Step 2 — Building Qualtrics import file")
print("=" * 60)

survey_config = load_survey_config('config/surveys/test_survey.yaml')

success = build_import_file(
    extractions   = [extraction],
    survey_config = survey_config,
    template_path = 'qualtrics_templates/maize_community_survey_template.xlsx',
    output_path   = 'data/output/test_survey_import.xlsx',
    batch_date    = '2026-03-21',
)

if success:
    print("\n  SUCCESS — file is ready to import into Qualtrics")
    print("  Location: data/output/test_survey_import.xlsx")
else:
    print("\n  FAILED — check errors above")