# PaperTrail — Changelog

Public Policy & Management Center (PPMC)
Graduate Research Assistant — Internal Systems Project

All notable changes to PaperTrail are documented here.
Most recent sprint at the top.

---

## Sprint 1D — March 2026

### What was built

#### qualtrics_mapper.py
Maps detected paper field values to a Qualtrics-ready
Excel import file. Works with any survey — never hardcodes
column structure or survey-specific logic.

Key behaviours:
- Reads any Qualtrics export template to get exact
  column headers and labels from Row 1 and Row 2
- Maps paper fields to Qualtrics columns via survey YAML
- Generates the exact three-row Qualtrics header structure:
    Row 1  — ImportId column headers
    Row 2  — Human-readable question labels
    Row 3+ — One row per paper respondent
- Auto-populates all metadata columns:
    StartDate, EndDate, RecordedDate → batch scan date
    IPAddress                        → 0.0.0.0
    ResponseId                       → R_papertrail_NNNN
    Status                           → 0
    Progress                         → 100
    Finished                         → 1
    DistributionChannel              → paper
    UserLanguage                     → EN
- Leaves computed Qualtrics columns blank —
  Qualtrics calculates these automatically on import
- Validates output structure before saving —
  catches format errors before they reach Qualtrics
- Works for any survey instrument

#### config/surveys/test_survey.yaml — updated
Merged calibrated pixel coordinates from Sprint 1C
with Qualtrics column ID mappings for Sprint 1D.
YAML now contains both regions and qualtrics_id
for all 8 fields — ready for end-to-end testing.

### Test results
Output file verified programmatically:
- Shape: 3 rows × 91 columns — matches template exactly
- Row 1: exact Qualtrics ImportIds copied from template
- Row 2: exact human-readable labels copied from template
- Row 3: paper respondent with correct values:
    Q3.1_1 → 3    Q3.1_2 → 4    Q3.1_3 → 4
    Q3.1_4 → 4    Q3.1_5 → 3    Q3.1_6 → 4
    Q3.1_7 → 2    Q3.1_8 → 4
- All metadata columns correctly populated
- DistributionChannel = paper allows teams to filter
  paper responses from online responses in Qualtrics
- Qualtrics import test pending staff availability

### Key lessons
- The Qualtrics export template is the single source of
  truth for column structure. Copying it directly into
  the output file guarantees first-attempt import success.
- DistributionChannel = paper is important — it lets
  research teams separate paper and online respondents
  in their Qualtrics analysis without extra work.
- Computed columns must be left blank — attempting to
  fill them causes import failures in some Qualtrics
  survey configurations.

---

## Sprint 1C — March 2026

### What was built

#### calibration_tool.py
Interactive survey calibration tool. Opens any processed
survey image in a window. Staff click and drag to draw
boxes around each answer region. Coordinates are saved
to the survey YAML configuration file automatically.

Controls:
- Click + drag  →  Draw a region box
- R             →  Undo last region
- S             →  Save and exit
- Q             →  Quit without saving
- Z             →  Zoom in
- X             →  Zoom out

Works for any survey layout — table grid, inline bubbles,
vertical checkbox list, scattered options. The calibration
process is survey-agnostic. Only the coordinates change
per instrument, never the code.

One-time setup per survey instrument. After calibration
that survey processes automatically forever.

#### omr.py — initial version
Optical mark recognition module. Detects which answer
option a respondent selected on a paper survey form.

Supported mark types:
- circled_number  →  Hough circle + arc contour fallback
- filled_bubble   →  Dark pixel density measurement
- x_mark          →  Diagonal Hough line detection
- circled_bubble  →  Smaller variant of circled_number
- shaded_box      →  Dark pixel density (same as bubble)
- checkmark       →  Diagonal line detection, wider angles

Every detected field returns a value and a confidence
score between 0.0 and 1.0. Fields below the threshold
are flagged for human review rather than accepted silently.

Any unrecognised mark type returns zero confidence and
routes to human review — the system never silently
accepts an unknown mark type.

Key design decisions:
- Asymmetric ROI padding:
    15% horizontal — prevents column bleed
    30% vertical   — captures circles above/below box
- Arc contour fallback: catches partial circles that
  Hough circle detection misses
- Ambiguity detection: flags fields where two options
  score within 0.08 of each other and both above 0.85

### Test results
Real phone scan (CamScanner PDF), 8-question survey:
- 8/8 fields detected correctly
- All confidence scores at 1.00
- Zero flags

### What changed from plan
- calibration_tool.py added as new file — not in original
  project structure. Necessary because coordinate
  registration is required before mark detection can work
  on any survey layout.

- omr.py went through four iterations before working:
    Iteration 1: Hough circles too sensitive —
                 detected printed numbers as circles
    Iteration 2: Min radius too large —
                 missed real hand-drawn circles entirely
    Iteration 3: Flat 30% padding on all sides —
                 column bleed caused 4/8 AMBIGUOUS flags
    Iteration 4: Asymmetric padding (15% x, 30% y) —
                 8/8 correct, zero flags

- calibration_tool.py had a cv2.imwrite bug in the save
  function that required two iterations to fix

### Key lessons
- Hand-drawn circles extend beyond calibrated boxes.
  ROI padding is not optional — it is essential.
- Horizontal and vertical padding must be tuned separately.
  Flat padding causes column bleed into adjacent options.
- Hough circle detection picks up printed numerals and
  cell borders as false positives. Minimum circle radius
  must be set relative to region size, not as fixed pixels.
- The best debugging approach for OMR problems is to save
  the actual ROI images and inspect what the algorithm sees.
- Arc contour detection is essential as a Hough fallback —
  many real hand-drawn circles are partially cut off by
  calibration box boundaries.

---

## Sprint 1B — March 2026

### What was built

#### preprocess.py
Full image preprocessing pipeline. Accepts any scan
format and produces a clean, high-contrast image ready
for mark detection.

Functions built:
- load_image()         Handles JPG, PNG, TIFF, PDF
- _load_pdf()          Converts PDF pages at 300 DPI
- _load_image()        Loads standard image formats
- _check_quality()     Flags blurry or undersized images
- _to_grayscale()      Converts BGR to single channel
- _clean_background()  Adaptive threshold removes gray wash
- _deskew()            Corrects rotation up to ±15 degrees
- _enhance_contrast()  CLAHE local contrast improvement
- preprocess()         Full pipeline, single file
- preprocess_batch()   Processes entire input folder

Handles all input types:
- CamScanner PDFs
- Adobe Scan PDFs
- Raw phone camera photos
- Flatbed scanner images (300 DPI minimum)
- Any combination of the above in one batch

### What changed from plan
- remove_background_noise() required two iterations:
    Version 1: CLAHE normalization — left gray background
               visible in lower half of processed images
    Version 2: Adaptive Gaussian thresholding — cleaned
               background to white correctly
- Poppler required separate Windows OS installation.
  pdf2image depends on Poppler which is not a pip package.
  Added to setup documentation.

### Key lessons
- Adaptive thresholding handles uneven backgrounds far
  better than CLAHE normalization for real-world scans.
- pdf2image requires Poppler at OS level on Windows.
  This is not obvious from the pip install documentation.
- CamScanner's gray background wash requires adaptive
  thresholding — simple contrast adjustment is not enough.

---

## Sprint 1A — March 2026

### What was built

#### Development environment
- Python 3.14.2 virtual environment configured on Windows 11
- All pip dependencies installed and verified:
    opencv-python 4.13.0
    pytesseract 0.3.x
    imutils, pdf2image, Pillow
    pandas, openpyxl
    pydantic, PyYAML
    click, numpy, streamlit
- Tesseract OCR 5.5.0 installed at Windows OS level
- Poppler installed at Windows OS level
- Both added to Windows PATH

#### Project structure
Full directory layout created:
- config/surveys/
- data/scans/, processed/, extracted/
- data/flagged/, validated/, output/
- qualtrics_templates/
- templates/survey_forms/
- src/scanner/, src/registry/
- tests/sample_scans/
- logs/

All stub Python files created with module docstrings
and function signatures ready for implementation:
- src/scanner/preprocess.py
- src/scanner/align.py
- src/scanner/omr.py
- src/scanner/ocr.py
- src/scanner/extractor.py
- src/registry/form_registry.py
- src/validate.py
- src/qualtrics_mapper.py
- src/logger.py

#### run_pipeline.py
CLI entry point with click. Accepts:
- --input     Scan folder path
- --survey    Survey name matching a YAML config
- --stage     Run one specific stage only
- --dry-run   Simulate without writing any files

Verified working:
  python run_pipeline.py --survey test --dry-run
  Output: PaperTrail starting... Sprint 1A complete.

#### .gitignore
Configured from day one:
- /data/ excluded — survey data never committed
- .venv/ excluded
- .env excluded
- __pycache__ excluded

### What changed from plan
- Nothing. Sprint 1A went exactly as planned.

### Key lessons
- Tesseract requires a separate Windows installer and
  PATH configuration — not just pip install pytesseract.
- Poppler also requires a separate Windows installation
  for pdf2image PDF conversion to work.
- Configuring .gitignore before the first commit is
  critical. Adding it later risks accidentally committing
  sensitive survey data to version control.

---

## Project Background

### Why PaperTrail Exists

PPMC runs surveys through two channels simultaneously.
Online respondents submit directly to Qualtrics —
automatic, zero staff effort. Paper respondents require
staff to manually transcribe every response into a
spreadsheet, match it to the exact Qualtrics format,
and import it manually. For a batch of 50 surveys this
takes 3-5 hours. Import failures are common because
Qualtrics is strict about column format — one wrong
header causes the entire import to fail.

PaperTrail eliminates the manual transcription step.

### Why Paper Surveys Matter

The community members who fill paper surveys are often
the most important voices in PPMC research — older
residents, households without reliable internet, people
who distrust digital forms. Making their participation
operationally difficult is a quiet form of exclusion.
PaperTrail is the infrastructure that removes that barrier
so that paper and digital participation are operationally
equivalent for PPMC staff.

### Core Design Principles

1. Free and local — no paid APIs, no cloud, no server
2. Any survey — register once, automate forever
3. Humans stay in the loop — flag uncertainty, never guess
4. No technical debt — config in YAML, logic in Python
5. Survives the developer leaving — documented as built

### Version History

| Version | Date       | Description                          |
|---------|------------|--------------------------------------|
| 0.1     | March 2026 | Project initiated                    |
| 0.2     | March 2026 | Preprocessing pipeline complete      |
| 0.3     | March 2026 | Calibration tool complete            |
| 0.4     | March 2026 | OMR detection — 8/8 on real scan     |
| 0.5     | March 2026 | Qualtrics mapper complete            |
|         |            | Output file verified — ready to      |
|         |            | import into Qualtrics                |