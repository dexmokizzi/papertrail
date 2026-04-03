# PaperTrail — CHANGELOG

All notable changes to this project are documented here.
One entry per sprint close. Each entry records what was built,
what changed from the original plan, and one key technical lesson.

---

## Phase 2 Complete — April 2026

### What Was Built

#### Multi-page survey support
PaperTrail now handles any multi-page survey booklet. One PDF per
respondent (all pages scanned in one CamScanner session) = one row
in Qualtrics. The pipeline splits pages automatically, reads each
page against the fields assigned to that page in the survey YAML,
and combines all pages into one extraction result per respondent.

This works for any survey — single page or multi-page. The number
of pages, sections, and fields are all declared in the YAML.

#### src/scanner/extractor.py — built from stub
Groups processed page images by source PDF using filename pattern
matching (`filename_pageNN.jpg`). Detects which YAML fields belong to
which page number. Combines detections from all pages into one
extraction result per respondent. Handles missing pages gracefully —
flags all fields on a missing page rather than crashing.

#### calibration_tool.py — major upgrade
The calibration tool now handles any survey completely. No manual
YAML editing required after calibration — ever. For any new survey:

- Asks for mark type (6 options), field type (4 options), prefix,
  start number, and Qualtrics column ID for each field
- Writes a complete, pipeline-ready field definition automatically
- Auto-saves when all regions are recorded (no S key required)
- Auto-saves when window is closed with X button
- Detects duplicate field prefixes before starting — asks replace
  or skip so re-calibrating a single page is safe
- Cleans incomplete fields from previous calibration runs

Result: registering any new survey requires zero developer
involvement after the one-time calibration session.

#### omr.py — multi-algorithm fallback detection
Every mark type now tries multiple detection algorithms and takes
the strongest signal. This handles real-world respondent behaviour
across any survey — people who circle instead of marking X, use
checkmarks instead of bubbles, or make other non-standard marks.

```
x_mark:          tries x_mark, checkmark, circle, filled_bubble
filled_bubble:   tries filled_bubble, circle
circled_number:  tries circle, filled_bubble
circled_bubble:  tries circle (small), filled_bubble, x_mark
shaded_box:      tries filled_bubble, x_mark, checkmark
checkmark:       tries checkmark, x_mark, filled_bubble
```

FALLBACK_PENALTY = 0.85 applied to non-primary algorithms.

#### preprocess.py — multi-page PDF support
The preprocess_batch function now splits multi-page PDFs into
per-page images named `filename_page01.jpg` through `_pageNN.jpg`.
Each page passes through the full preprocessing pipeline independently.
Previously only the first page of a PDF was extracted.

#### run_pipeline.py — full rewrite
Single CLI entry point supporting any registered survey.

```
python run_pipeline.py --survey <any_survey_name>
python run_pipeline.py --survey <any_survey_name> --dry-run
python run_pipeline.py --survey <any_survey_name> --stage output
```

Stages: all | preprocess | extract | validate | output

The pipeline is survey-agnostic. It reads the survey name from
--survey, loads the matching YAML from config/surveys/, and
processes whatever fields are defined there. No code changes are
needed to support a new survey — only a new YAML.

#### First survey registered: Maize Community Survey
The Maize Community Survey was calibrated as the first real
instrument to validate the full pipeline end to end. All 57 fields
across 8 pages registered in `config/surveys/maize_community_survey.yaml`.
This serves as the reference example for registering future surveys.

### Scanning Standard Established
One PDF per respondent. All pages scanned in a single CamScanner
session before saving. Staff drop PDFs into data/scans/ and run
one command. PaperTrail handles everything else.

This standard applies to any survey PaperTrail processes.

### Registering a New Survey — The Process
Any new survey with a Qualtrics counterpart can be registered:

```
1. Export Qualtrics template
   Data & Analysis → Export & Import → Export Data → Excel
   Save to: qualtrics_templates/

2. Scan one completed copy of the paper form
   Drop into data/scans/

3. Run preprocessing
   python run_pipeline.py --survey new_survey --stage preprocess

4. Run calibration on each page
   python -m src.scanner.calibration_tool \
     --image data/processed/scan_page01.jpg \
     --survey new_survey

   Answer prompts: questions, values, mark type, field type,
   Qualtrics column IDs. Draw boxes. Tool saves automatically.
   Repeat for each page.

5. Add survey metadata to the YAML
   survey_id: new_survey
   qualtrics:
     template: qualtrics_templates/new_survey_template.xlsx

6. Test
   python run_pipeline.py --survey new_survey
```

Done — that survey processes automatically forever with no further
developer involvement.

### Phase 2 End-to-End Test Results (Maize Community Survey)

```
PDF pages:    8
Respondents:  1
Fields:       57
Clean:        52
Flagged:      5  (4 AMBIGUOUS on Section 2, 1 multi_select mapping bug)
Flag rate:    8.8%
Qualtrics file: 91 columns, correct format
Runtime:      11.97 seconds
```

### Known Issues Remaining
- multi_select output shows "-" in Qualtrics mapper — mapping bug,
  not yet fixed. Queued for next sprint.
- 4 AMBIGUOUS flags on Section 2 fields need investigation.
- x_mark and circled_bubble detection not yet verified against
  known answers on real demographic scans. Lab testing only.

### What Changed From Original Plan
- The calibration tool originally required manual YAML editing after
  each session. Redesigned to write complete field definitions
  interactively. No manual editing ever required.
- The multi-select mapping bug was not caught until the first full
  end-to-end test. Production use should wait until it is fixed.

### Key Technical Lessons
- Multi-page grouping by filename prefix is simpler and more robust
  than detecting page numbers from image content. The naming
  convention (`basename_pageNN.jpg`) is the right contract.
- The calibration tool's auto-save on window close is essential on
  Windows — the OpenCV window does not consistently register
  keyboard events when focus is on the terminal.
- Duplicate prefix detection prevents silent data loss when
  re-calibrating one page of an already-registered survey.

---

## Phase 1 Complete — March 2026

### What Was Built

PaperTrail's core pipeline: scan any paper survey → read marks →
validate → map to Qualtrics columns → produce import-ready Excel.

The pipeline is instrument-agnostic from day one. The survey YAML
defines everything. No field definitions, column mappings, or mark
types are hardcoded in Python.

#### Sprint 1A — Environment & Project Setup
Python 3.14.2 virtual environment on Windows 11. All pip dependencies
installed and verified. Project folder structure created per TRD.
.gitignore configured. run_pipeline.py CLI stub with click. README
scaffolded.

#### Sprint 1B — Preprocessing (preprocess.py)
Quality check via Laplacian blur detection. Grayscale conversion.
Adaptive background noise removal. Deskew via Hough line transform.
CLAHE contrast enhancement. Accepts JPG, PNG, TIFF, PDF. Original
files never modified.

#### Sprint 1C — OMR Engine (omr.py)
Optical mark recognition for circled numbers. Hough circle detection
as primary. Arc contour detection as fallback for partial circles.
Confidence scoring 0.0–1.0 per field. Ambiguity detection flags
when two options score within 0.08 of each other at high confidence.
Initial accuracy: 8/8 on real phone scan.

#### Sprint 1D — Qualtrics Mapper (qualtrics_mapper.py)
Reads any survey's Qualtrics export template. Generates the three-row
header structure required for Qualtrics response import. Auto-populates
all metadata columns with compliant defaults. Leaves computed columns
blank. Validates output before saving. Verified by actual Qualtrics
import — succeeded on first attempt.

#### Sprint 1E — Validation & Logging (validate.py, logger.py)
Field validation against YAML schema: type, scale range, allowed
values, required fields, confidence threshold. flagged_fields.csv
with form_id, field_id, raw_value, confidence, reason. logger.py
appends one row to run_log.csv per run regardless of errors.

#### Sprint 1F — Full Pipeline Integration (run_pipeline.py)
All stages connected in one command. Intermediate JSON between stages
for independent re-running. Human corrections applied from
flagged_fields.csv before export.

### Phase 1 Acceptance Criteria — All Met

```
✅ Full pipeline runs on real scan in one command
✅ 8/8 marks detected correctly
✅ All confidence scores at 1.00 on clean scan
✅ 0 fields flagged on clean scan
✅ Qualtrics file: 91 columns, correct format
✅ Qualtrics import succeeded on first attempt
✅ Every run logged to run_log.csv automatically
✅ Runtime: 1.73 seconds
```

### What Changed From Original Plan
- TRD v1.0 described a general IDP pipeline with PDF reports and
  email distribution. TRD v2.0 narrowed the output target to a
  Qualtrics response import file. This is the right scope — it
  solves the actual problem without overbuilding.
- The calibration tool was not in TRD v1.0. Manual YAML coordinate
  entry proved impractical on real scans. Added and significantly
  extended through Phase 2.

### Key Technical Lessons
- The Qualtrics three-row header structure is strict. Row 1 must
  contain exact ImportIds from the exported template. Getting this
  wrong causes silent import failures with unhelpful Qualtrics errors.
- The processed/ folder must be clean between test runs or old images
  get picked up as extra respondents. Document this in the README.

---

## Project Inception — March 2026

### The Problem
PPMC conducts surveys simultaneously online (Qualtrics) and on paper.
Online responses enter Qualtrics automatically. Paper responses require
staff to manually transcribe every answer and import a correctly
formatted Excel file. One batch of 50 surveys: 3–5 hours of staff
time, frequent import failures, silent data entry errors at 2–5% per
field.

### What PaperTrail Is
A local-first, zero-cost pipeline that accepts scanned paper surveys
and produces Qualtrics-ready Excel files automatically. Works for any
survey that has a Qualtrics counterpart. Staff scan → drop files →
run one command → upload to Qualtrics.

### Core Design Decisions Made at Inception
- **Any survey, not one survey**: YAML registry makes any instrument
  fully automated after one-time calibration. No code changes for
  new surveys.
- **Local and free**: No cloud APIs, no servers, no paid services
  for core operation. Runs on any Windows laptop.
- **One PDF per respondent**: Scanning standard established from day
  one. CamScanner saves all pages in one session.
- **Confidence over silence**: Every extraction produces a score.
  Uncertain fields go to human review — never silently accepted.
- **Qualtrics import file as the output**: Narrower than the original
  TRD v1.0 IDP vision, but exactly right for the actual problem.
