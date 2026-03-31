# PaperTrail — Project Roadmap

Public Policy & Management Center (PPMC)
Graduate Research Assistant — Internal Systems Project
Last updated: March 2026

---

## What PaperTrail Is

PaperTrail scans completed paper surveys and produces a
Qualtrics-ready Excel import file automatically. It eliminates
manual data entry for paper respondents — making paper
participation as operationally efficient as digital participation.

Staff scan a paper survey. PaperTrail reads every response.
Staff upload one file to Qualtrics. Done.

---

## Current Status

Sprint 1C complete. OMR detection working on real phone scans.
Currently building Sprint 1D — Qualtrics output.

---

## Completed

### Sprint 1A — Environment Setup ✅
- Python 3.14.2 virtual environment configured on Windows 11
- All pip dependencies installed and verified
- Tesseract 5.5.0 installed at Windows OS level
- Poppler installed at Windows OS level for PDF support
- OpenCV 4.13.0 confirmed working
- CLI entry point (run_pipeline.py) working with click
- Project folder structure created
- .gitignore configured

### Sprint 1B — Preprocessing ✅
- preprocess.py handles any input format:
    PDF (CamScanner, Adobe Scan, flatbed scanner)
    JPG, PNG, TIFF
    Phone camera photos
    Multi-page PDFs (split into per-page images)
- Converts PDF pages to images at 300 DPI
- Removes gray background and scanner noise
- Corrects rotational skew up to ±15 degrees
- Enhances contrast using CLAHE
- Adaptive thresholding for uneven lighting
- Batch processing — handles entire folder in one run
- Tested on real CamScanner phone scans

### Sprint 1C — Calibration Tool + OMR ✅

#### Calibration Tool (calibration_tool.py)
- Opens any processed survey image in an interactive window
- Staff click and drag to draw boxes around answer regions
- Zoom in/out for precision (Z/X keys)
- Undo last region (R key)
- Save coordinates to YAML automatically (S key)
- Works for any survey layout:
    Table grid, inline bubbles, vertical list,
    checkboxes, scattered options — any format
- Tested and saving YAML correctly

#### Mark Detection (omr.py)
- Detects circled numbers using Hough circle detection
  with arc contour fallback for partial circles
- Detects filled bubbles using dark pixel density
- Detects X marks using diagonal Hough line detection
- Detects circled bubbles (smaller variant of circled number)
- Confidence scoring 0.0–1.0 per field
- Ambiguity detection for double marks
- Asymmetric ROI padding:
    15% horizontal (avoids adjacent column bleed)
    30% vertical (captures circles above/below box)
- Results on real phone scan: 8/8 correct, all confidence 1.00

---

## In Progress

### Sprint 1D — Qualtrics Mapper (current)
Build qualtrics_mapper.py:
- Read the Qualtrics export template (.xlsx)
- Read the survey YAML for field-to-column mapping
- Map detected values to exact Qualtrics column IDs
- Generate the three-row Qualtrics header structure:
    Row 1: Column ImportIds (QID_1, QID_2, etc.)
    Row 2: Human-readable question labels
    Row 3+: One row per paper respondent
- Auto-populate metadata columns:
    IPAddress       → 0.0.0.0
    ResponseId      → R_papertrail_001
    StartDate       → scan batch date
    EndDate         → scan batch date
    Status          → 0
    Finished        → 1
    DistributionChannel → paper
    UserLanguage    → EN
- Leave computed Qualtrics columns blank
- Validate output against Qualtrics template before saving
- Save output as: survey_id_YYYY-MM-DD_batch.xlsx

Definition of done: Output file imports into Qualtrics
on the first attempt without errors.

---

## Upcoming

### Sprint 1E — Validation + Logging
Build validate.py:
- Validate extracted values against YAML rules
- Flag fields below confidence threshold (default 0.75)
- Flag ambiguous marks, missing required fields,
  out-of-range values
- Produce flagged_fields.csv:
    form_id, field_id, raw_value, confidence, reason
- Never block whole form for one flagged field
- Never overwrite raw extracted values

Build logger.py:
- Append one row to run_log.csv after every pipeline run
- Log: timestamp, survey_id, forms_processed,
  fields_extracted, fields_flagged, flag_rate_pct,
  qualtrics_validation_passed, pipeline_runtime_sec,
  operator

### Sprint 1F — Full Pipeline Wiring
Wire all modules into run_pipeline.py:
- Single command runs everything end to end
- --input flag for scan folder
- --survey flag for survey name
- --stage flag to run one stage only
- --dry-run flag to simulate without writing files
- Baseline measurement before go-live:
  Time one staff member processing 20 forms manually

---

## Phase 2 — Additional Mark Types + Full Instrument Coverage

### Sprint 2A — Remaining Mark Types
- Test and tune X mark detection on real X mark surveys
- Test and tune filled bubble detection on real bubble surveys
- Test and tune circled bubble detection on real surveys
- Multi-select field handling (select all that apply)

### Sprint 2B — Second Survey Instrument
- Register a second PPMC survey instrument end to end
- Confirm registration process works without code changes
- Verify Qualtrics import succeeds for second instrument

### Sprint 2C — Streamlit Review UI
Build app.py:
- File uploader for scan batches
- Display extracted fields in a table
- Flagged fields highlighted in amber
- Scan image visible in side panel
- Accepted fields read-only
- Corrections typed directly in UI
- One-click Qualtrics export download
- No command line needed
- Staff confirm usable after one-page guide

### Sprint 2D — Form Registry
Build form_registry.py:
- Auto-identify which YAML applies to an incoming scan
- Staff do not need to specify survey name manually

---

## Deferred — Needs Testing Before Production

These items were flagged during Sprint 1C and must be
addressed before PaperTrail is used on real research data:

- Raw phone photos with poor lighting or heavy shadows
- Faint pencil marks
- Heavy ink bleed
- Sloppy or off-centre hand-drawn circles
- Very large circles extending far outside calibration box
- Partially erased marks
- All mark types tested on real forms (not just circled numbers)
- Multi-select fields on real demographic sections
- Multi-page survey booklets
- Different image resolutions
- Wrinkled or folded paper

Action: Collect diverse scan samples before go-live.
Test each case. Tune OMR thresholds as needed.

---

## Deferred — Future Ideas

Everything here is out of scope for Phase 1 and Phase 2.
Nothing gets built until explicitly moved into a sprint.

- Cloud OCR for handwritten comment transcription
  (Google Vision API or Azure — free tier available)
- Automated blank reference scan generation
  (instead of manual scanning of blank forms)
- Confidence threshold configuration per survey in YAML
  (currently global default of 0.75)
- Batch progress dashboard with estimated time remaining
- Export to CSV in addition to Excel
- Support for surveys with skip logic
- Support for rating scales beyond numeric
  (e.g. emoji scales, slider scales)
- Auto-detection of answer grid without calibration
  (would require cloud APIs or ML model)
- Integration with other survey platforms beyond Qualtrics
- Mobile app for scanning (instead of using camera + transfer)
- Historical trend reports from run_log.csv

---

## Known Limitations

These are not bugs — they are intentional design boundaries:

- Every new survey type requires one-time calibration
  (5-10 minutes of clicking regions per instrument)
- Handwritten open-text comments are saved as image crops
  and must be transcribed manually if needed
- Very poor quality scans will flag fields for human review
  rather than guess — this is correct behaviour
- PaperTrail requires a matching Qualtrics survey to exist
  before it can process paper responses for that instrument

---

## Completed Milestones

| Milestone                          | Status  | Date       |
|------------------------------------|---------|------------|
| Environment setup                  | Done    | March 2026 |
| Preprocessing pipeline             | Done    | March 2026 |
| Calibration tool                   | Done    | March 2026 |
| OMR — circled number detection     | Done    | March 2026 |
| 8/8 accuracy on real phone scan    | Done    | March 2026 |
| Qualtrics mapper                   | Pending | —          |
| Validation + flagging              | Pending | —          |
| Full pipeline end-to-end           | Pending | —          |
| First successful Qualtrics import  | Pending | —          |
| Second survey instrument           | Pending | —          |
| Streamlit review UI                | Pending | —          |
| Staff sign-off on usability        | Pending | —          |