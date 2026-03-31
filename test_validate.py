import cv2
import yaml
import time
from src.scanner.omr import detect_mark
from src.scanner.validate import validate_extraction
from src.scanner.logger import log_run, get_summary
from src.scanner.qualtrics_mapper import build_import_file, load_survey_config

start_time = time.time()

# ── Step 1: Detect marks ──────────────────────────────────────────────────────
print("=" * 60)
print("Step 1 — Detecting marks")
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
    extraction[field['paper_id']] = result
    print(f"  {field['paper_id']}  →  "
          f"{result.get('value')}  "
          f"(confidence: {result.get('confidence', 0):.2f})")

# ── Step 2: Validate ──────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Step 2 — Validating extracted values")
print("=" * 60)

survey_config = load_survey_config('config/surveys/test_survey.yaml')

validation = validate_extraction(
    form_id       = "form_0001",
    extraction    = extraction,
    survey_config = survey_config,
    flagged_path  = "data/flagged/flagged_fields.csv",
)

print(f"  Total fields:   {validation['summary']['total']}")
print(f"  Clean:          {validation['summary']['clean']}")
print(f"  Flagged:        {validation['summary']['flagged']}")
print(f"  Flag rate:      {validation['summary']['flag_rate_pct']}%")

if validation['flagged']:
    print(f"\n  Flagged fields:")
    for f in validation['flagged']:
        print(f"    {f['field_id']}  →  {f['reason']}")
else:
    print(f"\n  No fields flagged — all values passed validation")

# ── Step 3: Build Qualtrics file ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("Step 3 — Building Qualtrics import file")
print("=" * 60)

clean_extraction = validation['clean']

success = build_import_file(
    extractions   = [clean_extraction],
    survey_config = survey_config,
    template_path = 'qualtrics_templates/maize_community_survey_template.xlsx',
    output_path   = 'data/output/test_survey_import.xlsx',
    batch_date    = '2026-03-21',
)

# ── Step 4: Log the run ───────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Step 4 — Logging the run")
print("=" * 60)

runtime = round(time.time() - start_time, 2)

log_run(
    survey_id                   = "test_survey",
    forms_processed             = 1,
    fields_extracted            = validation['summary']['total'],
    fields_flagged              = validation['summary']['flagged'],
    qualtrics_validation_passed = success,
    pipeline_runtime_sec        = runtime,
    operator                    = "developer",
)

# ── Step 5: Show summary ──────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Step 5 — Run summary")
print("=" * 60)

summary = get_summary()
for key, value in summary.items():
    print(f"  {key}: {value}")

print(f"\n  Pipeline completed in {runtime} seconds")
if success:
    print("  File ready: data/output/test_survey_import.xlsx")