# PaperTrail: CHANGELOG

All notable changes to this project are documented here.
One entry per sprint close. Each entry records what was built,
what changed from the original plan, and one key technical lesson.

---
## OMR Robustness Sprint, April 2026

### What Was Built

This sprint addressed the core reliability problem identified during
multi-respondent testing: the bounding box detection approach produced
a 64.9% flag rate on a respondent who drew larger-than-average circles.
The root cause was that tight calibration boxes allowed large circles
to bleed into adjacent columns, causing both options to score high and
triggering false AMBIGUOUS flags. The solution is a new proximity-based
detection path that is robust to any mark size.

#### omr.py — dual detection path architecture

Two detection paths now exist side by side, selected automatically
from the YAML region format:

Bounding box path: regions contain x, y, w, h keys. Extracts a
padded ROI around each declared box and scores it. Original behavior,
unchanged. All existing calibrated surveys continue working without
modification.

Proximity path: regions contain only x, y keys (center points, no
width or height). For each option, extracts a fixed-radius window
around the declared center point and scores it independently. Circle
size has no effect on detection — a large or small circle drawn
around an option always scores highest in that option's own window.

The path is determined entirely by YAML format. Mark type never
determines the path. Both paths reuse the same scoring functions.

#### omr.py — dynamic radius calculation

The proximity window radius is computed dynamically from the minimum
distance between declared center points using _compute_option_radius().
At 35% of minimum spacing, the radius automatically scales to any
image resolution, form density, or option spacing without hardcoded
values. A 200px spacing produces a 70px window. A 100px spacing
produces a 35px window. Single-option fields fall back to 40px.

#### calibration_tool.py — center-point mode

A new single-click calibration mode was added alongside the existing
click-and-drag bounding box mode. When center-point mode is selected,
staff click once on the center of each answer option. The tool saves
only x and y — no width or height — which triggers the proximity
detection path in omr.py. Center-point calibration is faster, more
forgiving of placement precision, and produces detection that is
robust to any respondent mark size. Either mode can be used for any
mark type on any survey layout.

### Multi-Respondent Testing Results

Two respondents tested against the same registered instrument:

Respondent 1 (original calibration scan):
  Flag rate with bounding box calibration: 12.3%
  Calibration source: respondent's own scan

Respondent 2 (large circles, different mark style):
  Flag rate before proximity detection: 64.9%
  Flag rate after center-point recalibration: 19.3%
  Improvement: 26 additional fields correctly detected

### Critical Finding: Calibrate on Blank Forms

During multi-respondent testing a critical calibration principle was
identified: center-point calibration must be performed on a blank
reference form, not on a completed respondent's scan. When calibrated
on a respondent's scan, the center points reflect that specific scan's
pixel positions. Slight differences in phone position, perspective, and
scale between scan sessions cause the center points to be slightly off
for other respondents, increasing flag rates.

The correct workflow is to scan one blank copy of the survey form and
calibrate on that. The printed numbers and bubbles on a blank form are
at fixed positions that are correct for every respondent. This is
consistent with the TRD design — templates/survey_forms/ was always
intended to hold blank reference scans.

Blank form calibration for the registered instrument is pending and
will be completed when a blank copy is available. All center-point
calibration performed in this sprint used a completed respondent scan
as a temporary measure.

### Known Issues Remaining

The circled_bubble detection path has a specific limitation for tightly
packed options (spacing under 60px). The small printed bubble next to
each option is itself a circle and scores similarly to the respondent's
larger circle at the minimum 20px window radius. No radius value
cleanly separates selected from unselected options in this layout.
The correct fix is a size-based scorer that distinguishes the
respondent's larger outer circle from the small printed bubble.
This is deferred to a future sprint pending more real scan data.

The blank form calibration issue affects all page 8 demographic fields
in the currently registered instrument. These fields flag consistently
until blank form recalibration is completed.

### What Changed From Original Plan

The original plan assumed bounding box calibration would be sufficient
for production use. Multi-respondent testing proved this wrong for
respondents with non-standard mark sizes. The proximity detection
architecture was not in the original TRD and emerged entirely from
real data testing. This confirms the TRD principle that each phase
closes on real data — lab testing would not have surfaced this problem.

### Key Technical Lesson

Calibration on a respondent's completed scan is a silent reliability
risk. The system appears to work correctly during single-respondent
testing but degrades when other respondents have different mark sizes
or when their scans have slightly different pixel positions. The lesson:
calibrate on a blank reference form, test on multiple completed scans
with known answers, and treat flag rate consistency across respondents
as the acceptance criterion — not just accuracy on one scan.

## Bug Fixes & Corrections Workflow, April 2026

### What Was Fixed

This sprint closed six bugs identified during the first real
end-to-end verification run on a live multi-page scan. All fixes
are survey-agnostic — they apply to any instrument registered
in PaperTrail, not just the one used for validation.

#### omr.py — multi_select silent data loss (critical)
`detect_multi_select` returned `{"values": [...]}` (plural key)
but `extractor.py` read `detection.get("value")` (singular key).
Multi-select detections were correct internally but silently
dropped before reaching the output file. Fixed by making
`detect_multi_select` return `"value"` consistently with all
other detection functions. A list value (e.g. `["5", "6"]`)
is formatted as a comma-separated string by the mapper
(`"5,6"`) which is the correct Qualtrics import format.

#### omr.py — false AMBIGUOUS flags on circled_bubble fields
The global `AMBIGUITY_MIN_SCORE = 0.85` was too loose for
circled bubble fields where options are physically separated on
the page. A large hand-drawn circle extending into an adjacent
region would cause the second option to score ~0.92, triggering
a false ambiguity flag even when the correct answer was clear.
Fixed by adding `CIRCLED_BUBBLE_AMBIGUITY_MIN = 0.96` and
passing it as a parameter to `_pick_best`. The tighter threshold
reflects the physical reality: genuine double-circling on
separated bubbles is rare; high second-option scores almost
always mean circle bleed, not genuine ambiguity.

#### calibration_tool.py — page number never saved (critical)
The calibration tool asked for mark type, field type, prefix,
and Qualtrics IDs — but never asked which page number the image
represented. All calibrated fields were saved with `page: None`.
`extractor.py` defaulted missing page numbers to page 1, so
all fields on pages 2–8 were run against the page 1 image.
Detection appeared to work (no errors) but produced wrong
values silently. Fixed by adding `_ask_page_number(image_path)`
which infers the default from the filename
(`_page08.jpg → 8`) so operators just press Enter in most cases.
Page number is now always written to every field in the YAML.

#### run_pipeline.py — flagged fields excluded from validated.json
`_save_validated` was called with `validation["clean_extractions"]`
which only contained fields that passed validation. Flagged fields
were excluded entirely. When corrections were applied in the output
stage, those fields did not exist in `validated.json` to receive
them — corrections were silently ignored. Fixed by saving the full
raw extractions (all fields including flagged) to `validated.json`.
The mapper reads `corrected_value` first, falling back to `value`
when no correction exists.

#### validate.py — _clear_flagged wiped staff corrections on re-run
`_clear_flagged` deleted `flagged_fields.csv` at the start of
every validation run. If staff entered corrections and then
re-ran `--stage validate` for any reason, all their work was
silently lost. Fixed by replacing `_clear_flagged` with a
load/reset/restore pattern:
1. `_load_existing_corrections` reads corrections before the
   file is touched
2. `_reset_flagged` deletes the file (corrections safely in memory)
3. Fresh flag rows are written during validation
4. `_restore_corrections` writes corrections back into the
   regenerated file for any matching (form_id, field_id) pair
Corrections now survive any number of re-validation runs.

#### qualtrics_mapper.py — corrected_value never read
`_build_row` always read `detected.get("value")` and never
checked for `corrected_value`. Human corrections were present
in the validated data but the mapper ignored them, producing
blank cells in the output file for every corrected field.
Fixed with one line: `corrected_value` is now read first,
falling back to `value` when no correction exists.

### End-to-End Verification Results

Full pipeline verified against a real 8-page multi-section
survey scan (57 fields, 4 mark types, multi-select demographics).

```
Fields auto-detected correctly:  50/57  (88%)
Fields flagged for human review:   7/57  (12%)
All 7 corrections applied:        yes
Final Qualtrics file:             57/57 fields correct
Multi-select field:               yes (comma-separated format)
Runtime:                          ~12 seconds
```

All 7 flagged fields had clear answers on the paper. Root cause:
hand-drawn circles on tightly spaced grids produce high scores
on adjacent columns. These are correct flags — the system is
uncertain, not wrong. Staff review time for 7 fields is a
fraction of manual transcription for the full form.

### Known Issues Remaining
- Flag rate on circled-number surveys with tight column spacing
  will typically be 10-15% on phone scans. Calibration quality
  and scan quality are the primary levers. Threshold tuning
  deferred until more real scan data is available.
- Corrections entry currently requires editing flagged_fields.csv
  directly. Non-technical staff workflow blocked on Phase 3
  Streamlit UI. Foundation is verified correct — UI can now
  be built on top of it reliably.
- Multi-respondent batch testing not yet completed. Single-
  respondent pipeline verified. Batch of 10+ recommended before
  broader staff deployment.

### What Changed From Original Plan
- Phase 2 CHANGELOG noted multi_select as a known bug queued
  for next sprint. Fixed this sprint along with five other
  silent failure bugs discovered during real-scan verification.
- The corrections workflow required more foundational work than
  anticipated. The bugs were not visible in unit testing —
  they only surfaced during full end-to-end verification on
  a real scan with known answers. This validates the TRD
  requirement that each phase closes on real data, not
  synthetic test data.

### Key Technical Lesson
Silent failures dominated this sprint. Every bug followed the
same pattern: the pipeline ran without errors, produced output,
and reported success — but the output was wrong. Key examples:
the wrong key name (`values` vs `value`) dropped multi-select
data silently; missing page numbers caused fields to be
detected against the wrong image with no error; corrections
sat in memory but never reached the output file. The lesson:
for data pipelines, a clean run is not the same as a correct
run. End-to-end verification against known answers on real
inputs is the only reliable acceptance test.

---

## Phase 2 Complete, April 2026

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

#### First survey registered
The first real multi-page instrument was calibrated to validate
the full pipeline end to end. All fields across 8 pages registered
in the survey YAML. This serves as the reference example for
registering future surveys.

### Scanning Standard Established
One PDF per respondent. All pages scanned in a single CamScanner
session before saving. Staff drop PDFs into data/scans/ and run
one command. PaperTrail handles everything else.

This standard applies to any survey PaperTrail processes.

### Registering a New Survey — The Process
Any new survey with a Qualtrics counterpart can be registered:

```
1. Export Qualtrics template
   Data & Analysis -> Export & Import -> Export Data -> Excel
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

### Phase 2 End-to-End Test Results

```
PDF pages:    8
Respondents:  1
Fields:       57
Clean:        52
Flagged:      5  (4 AMBIGUOUS on circled-number grid, 1 multi_select bug)
Flag rate:    8.8%
Qualtrics file: 91 columns, correct format
Runtime:      11.97 seconds
```

### Known Issues Remaining
- multi_select output shows "-" in Qualtrics mapper — mapping bug,
  not yet fixed. Queued for next sprint.
- AMBIGUOUS flags on tightly spaced circled-number grids need
  investigation.
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

## Phase 1 Complete, March 2026

### What Was Built

PaperTrail's core pipeline: scan any paper survey -> read marks ->
validate -> map to Qualtrics columns -> produce import-ready Excel.

The pipeline is instrument-agnostic from day one. The survey YAML
defines everything. No field definitions, column mappings, or mark
types are hardcoded in Python.

#### Sprint 1A: Environment & Project Setup
Python 3.14.2 virtual environment on Windows 11. All pip dependencies
installed and verified. Project folder structure created per TRD.
.gitignore configured. run_pipeline.py CLI stub with click. README
scaffolded.

#### Sprint 1B: Preprocessing (preprocess.py)
Quality check via Laplacian blur detection. Grayscale conversion.
Adaptive background noise removal. Deskew via Hough line transform.
CLAHE contrast enhancement. Accepts JPG, PNG, TIFF, PDF. Original
files never modified.

#### Sprint 1C: OMR Engine (omr.py)
Optical mark recognition for circled numbers. Hough circle detection
as primary. Arc contour detection as fallback for partial circles.
Confidence scoring 0.0-1.0 per field. Ambiguity detection flags
when two options score within 0.08 of each other at high confidence.
Initial accuracy: 8/8 on real phone scan.

#### Sprint 1D: Qualtrics Mapper (qualtrics_mapper.py)
Reads any survey's Qualtrics export template. Generates the three-row
header structure required for Qualtrics response import. Auto-populates
all metadata columns with compliant defaults. Leaves computed columns
blank. Validates output before saving. Verified by actual Qualtrics
import — succeeded on first attempt.

#### Sprint 1E: Validation & Logging (validate.py, logger.py)
Field validation against YAML schema: type, scale range, allowed
values, required fields, confidence threshold. flagged_fields.csv
with form_id, field_id, raw_value, confidence, reason. logger.py
appends one row to run_log.csv per run regardless of errors.

#### Sprint 1F: Full Pipeline Integration (run_pipeline.py)
All stages connected in one command. Intermediate JSON between stages
for independent re-running. Human corrections applied from
flagged_fields.csv before export.

### Phase 1 Acceptance Criteria, All Met

```
Full pipeline runs on real scan in one command     yes
8/8 marks detected correctly                       yes
All confidence scores at 1.00 on clean scan        yes
0 fields flagged on clean scan                     yes
Qualtrics file: 91 columns, correct format         yes
Qualtrics import succeeded on first attempt        yes
Every run logged to run_log.csv automatically      yes
Runtime: 1.73 seconds                              yes
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

## Project Inception, March 2026

### The Problem
PPMC conducts surveys simultaneously online (Qualtrics) and on paper.
Online responses enter Qualtrics automatically. Paper responses require
staff to manually transcribe every answer and import a correctly
formatted Excel file. One batch of 50 surveys: 3-5 hours of staff
time, frequent import failures, silent data entry errors at 2-5% per
field.

### What PaperTrail Is
A local-first, zero-cost pipeline that accepts scanned paper surveys
and produces Qualtrics-ready Excel files automatically. Works for any
survey that has a Qualtrics counterpart. Staff scan -> drop files ->
run one command -> upload to Qualtrics.

### Core Design Decisions Made at Inception
- Any survey, not one survey: YAML registry makes any instrument
  fully automated after one-time calibration. No code changes for
  new surveys.
- Local and free: No cloud APIs, no servers, no paid services
  for core operation. Runs on any Windows laptop.
- One PDF per respondent: Scanning standard established from day
  one. CamScanner saves all pages in one session.
- Confidence over silence: Every extraction produces a score.
  Uncertain fields go to human review — never silently accepted.
- Qualtrics import file as the output: Narrower than the original
  TRD v1.0 IDP vision, but exactly right for the actual problem.
