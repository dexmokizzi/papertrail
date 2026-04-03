# PaperTrail

**From paper surveys to Qualtrics — automatically. For any survey.**

PaperTrail is a local-first, zero-cost pipeline that accepts scanned
paper surveys and produces Qualtrics-ready Excel import files. Staff
scan completed forms, drop them in a folder, and run one command. The
output file uploads directly into an existing Qualtrics survey on the
first attempt.

No cloud. No paid APIs. No server. Runs on any Windows laptop.

---

## What It Does

PPMC runs surveys simultaneously online and on paper. Online responses
go into Qualtrics automatically. Paper responses used to require staff
to manually transcribe every answer into a spreadsheet — 3–5 hours per
batch, frequent import failures, and silent data entry errors.

PaperTrail eliminates that manual step:

```
Staff scans completed paper surveys (phone or flatbed)
        ↓
Drop PDFs into data/scans/
        ↓
python run_pipeline.py --survey your_survey_name
        ↓
Upload data/output/your_survey_2026-04-01_batch.xlsx to Qualtrics
        ↓
Done — paper responses appear alongside online responses
```

PaperTrail works for **any survey** that has a Qualtrics counterpart.
Each instrument is registered once. After that, every future batch
processes automatically with no developer involvement.

---

## Requirements

- Windows 11
- Python 3.10+ (tested on 3.14.2)
- Tesseract OCR 5.x (installed separately — see Installation)
- CamScanner or Microsoft Lens for phone scanning
- Flatbed scanner at 300 DPI minimum (alternative)

---

## Installation

### Step 1 — Clone the repository

```
git clone https://github.com/your-org/papertrail.git
cd papertrail
```

### Step 2 — Create a virtual environment

```
python -m venv .venv
.venv\Scripts\activate
```

### Step 3 — Install Python dependencies

```
pip install -r requirements.txt
```

Or install manually:

```
pip install opencv-python pytesseract imutils pdf2image Pillow ^
    pandas openpyxl pydantic PyYAML click numpy streamlit
```

### Step 4 — Install Tesseract OCR

Tesseract is not a Python package. It must be installed at the Windows
OS level separately.

1. Download the installer from:
   https://github.com/UB-Mannheim/tesseract/wiki
2. Run the installer (accept defaults)
3. Add Tesseract to your Windows PATH:
   - Open System Properties → Advanced → Environment Variables
   - Under System variables, find `Path` → Edit → New
   - Add: `C:\Program Files\Tesseract-OCR`
4. Verify: open a new terminal and run `tesseract --version`

### Step 5 — Verify everything works

```
python -c "import cv2, pytesseract, pandas, yaml; print('Ready.')"
```

If this prints `Ready.` without errors, installation is complete.

---

## Running a Batch

This is the most common operation — processing a folder of scans for a
survey that is already registered.

### Step 1 — Scan the completed paper forms

Use CamScanner. Scan all pages of one respondent's booklet in a single
session before saving. This produces one PDF per respondent.

Phone photos also work. Microsoft Lens is recommended — it
automatically corrects perspective distortion before saving.

### Step 2 — Drop scans into the input folder

```
data/scans/
    respondent_001.pdf
    respondent_002.pdf
    respondent_003.pdf
    ...
```

### Step 3 — Run the pipeline

```
.venv\Scripts\activate
python run_pipeline.py --survey your_survey_name
```

Replace `your_survey_name` with the `survey_id` from the survey's YAML
file in `config/surveys/`.

### Step 4 — Check for flagged fields

If any fields were uncertain, PaperTrail writes them to:

```
data/flagged/flagged_fields.csv
```

Open this file alongside the original scan. For each flagged row, type
the correct value into the `corrected_value` column and save.

Then re-run just the output stage:

```
python run_pipeline.py --survey your_survey_name --stage output
```

### Step 5 — Import into Qualtrics

1. Log into Qualtrics and open the target survey
2. Click **Data & Analysis** in the top navigation
3. Click **Export & Import** → **Import Data**
4. Select the file from `data/output/`
5. Click **Import**

Paper responses appear in Qualtrics immediately alongside online
responses.

---

## Other Commands

```bash
# Run a specific stage only
python run_pipeline.py --survey your_survey_name --stage preprocess
python run_pipeline.py --survey your_survey_name --stage extract
python run_pipeline.py --survey your_survey_name --stage validate
python run_pipeline.py --survey your_survey_name --stage output

# Test a new config without writing any files
python run_pipeline.py --survey your_survey_name --dry-run

# See all options
python run_pipeline.py --help
```

---

## Registering a New Survey

Any new survey that PPMC runs on paper can be registered. Registration
is a one-time process. After it is done, every future batch of that
survey runs with the single command above. No code changes required.

### What you need before starting

- The paper survey form (one completed copy for testing, one blank copy
  for the reference scan)
- The Qualtrics survey open in a browser

### Step 1 — Export the Qualtrics template

In Qualtrics: **Data & Analysis → Export & Import → Export Data**

Choose Excel format. Under **Download**, select **Export values, not
labels**. Download the file and save it to:

```
qualtrics_templates/your_survey_name_template.xlsx
```

### Step 2 — Scan a blank copy of the form

Scan one clean, blank (unanswered) copy of the paper form. Save to:

```
templates/survey_forms/your_survey_name_blank.jpg
```

This is the reference image PaperTrail uses to locate answer grids on
each filled scan.

### Step 3 — Preprocess a completed scan

Drop one completed scan into `data/scans/` and run preprocessing:

```
python run_pipeline.py --survey your_survey_name --stage preprocess
```

This produces aligned page images in `data/processed/` that the
calibration tool needs.

### Step 4 — Run the calibration tool

The calibration tool walks you through marking every answer region on
the form interactively. It asks questions and you answer them — no
manual YAML editing required.

```
python -m src.scanner.calibration_tool ^
    --image data/processed/your_scan_page01.jpg ^
    --survey your_survey_name
```

For each field:
1. Draw a box around the answer region by clicking and dragging
2. Answer the prompts (mark type, field type, Qualtrics column ID, etc.)
3. Repeat for every field on the page

The tool saves automatically when you finish. For multi-page surveys,
repeat for each page image.

### Step 5 — Add survey metadata to the YAML

Open `config/surveys/your_survey_name.yaml` and add two lines if they
are not already there:

```yaml
survey_id: your_survey_name
qualtrics:
  template: qualtrics_templates/your_survey_name_template.xlsx
```

### Step 6 — Test with real forms

```
python run_pipeline.py --survey your_survey_name
```

Compare the output file against the paper forms to verify the extracted
values are correct. If grid positions need adjustment, re-run the
calibration tool on the affected page.

Once the output imports into Qualtrics correctly, the survey is
registered permanently. All future batches run automatically.

---

## Folder Structure

```
papertrail/
├── README.md
├── requirements.txt
├── CHANGELOG.md                  ← one entry per sprint close
├── ROADMAP.md                    ← all deferred ideas live here
├── .gitignore                    ← excludes data/, .venv, .env
│
├── config/
│   └── surveys/                  ← one YAML file per registered survey
│       └── your_survey_name.yaml
│
├── qualtrics_templates/          ← Qualtrics export files (one per survey)
│   └── your_survey_name_template.xlsx
│
├── data/                         ← ALL SURVEY DATA — in .gitignore
│   ├── scans/        [INPUT]     ← drop raw scans or PDFs here
│   ├── processed/    [STEP 1]    ← preprocessed, aligned images
│   ├── extracted/    [STEP 2]    ← JSON extraction results
│   │   └── crops/               ← handwritten field image crops
│   ├── flagged/      [STEP 3]    ← flagged_fields.csv for review
│   ├── validated/    [STEP 3]    ← reviewed, corrected data
│   └── output/       [STEP 4]   ← Qualtrics-ready .xlsx files
│
├── templates/
│   └── survey_forms/             ← blank reference scans for alignment
│       └── your_survey_name_blank.jpg
│
├── src/
│   ├── scanner/
│   │   ├── preprocess.py         ← deskew, denoise, contrast, PDF split
│   │   ├── align.py              ← match filled scan to blank reference
│   │   ├── omr.py                ← all mark detection algorithms
│   │   ├── ocr.py                ← Tesseract wrappers, crop saving
│   │   ├── extractor.py          ← combines OMR+OCR into field dict
│   │   └── calibration_tool.py  ← interactive registration tool
│   ├── registry/
│   │   └── form_registry.py      ← identifies which YAML to use
│   ├── validate.py               ← validates fields against YAML rules
│   ├── qualtrics_mapper.py       ← maps fields to Qualtrics format
│   └── logger.py                 ← appends to run_log.csv
│
├── tests/
│   ├── test_omr.py
│   ├── test_validate.py
│   ├── test_qualtrics_mapper.py
│   └── sample_scans/             ← anonymized test images (safe to commit)
│
├── logs/
│   └── run_log.csv               ← auto-appended after every run
│
└── run_pipeline.py               ← single CLI entry point
```

---

## How Confidence Scoring Works

Every extracted field receives a confidence score from 0.0 to 1.0.
Low-confidence fields go to human review instead of Qualtrics.

| Score      | Status             | What happens                        |
|------------|--------------------|-------------------------------------|
| 0.90–1.00  | High confidence    | Accepted automatically              |
| 0.75–0.89  | Moderate           | Accepted, logged for audit          |
| 0.50–0.74  | Low confidence     | Written to flagged_fields.csv       |
| 0.00–0.49  | Unreadable         | Excluded until correction entered   |

On a clean flatbed scan, most forms have zero flagged fields. Staff
only ever correct the uncertain ones — not the whole form.

---

## Supported Mark Types

PaperTrail detects four mark types used across PPMC survey instruments:

| Mark type        | What respondents do                                |
|------------------|----------------------------------------------------|
| `circled_number` | Circle a printed number (e.g. circle the 3)        |
| `filled_bubble`  | Fill in or darken a printed bubble                 |
| `x_mark`         | Draw an X through a printed square or circle       |
| `circled_bubble` | Draw a circle around a small printed empty bubble  |

Mark type is declared per-field in the survey YAML. Multiple mark types
can coexist within the same survey. All detection algorithms try
multiple approaches automatically and take the strongest signal.

---

## Important Notes

**The data/ folder is never committed to git.** Real survey data stays
on your local machine. The `.gitignore` excludes it from day one.

**Never edit `data/` files between stages.** If you need to re-run
from a specific stage, use `--stage` to start from there.

**Clean data/processed/ between unrelated test runs.** Old preprocessed
images in that folder will be grouped with new scans as if they belong
to the same batch.

**If Qualtrics edits a survey, re-export the template.** Any change to
the Qualtrics survey structure (adding/removing questions, changing
response codes) requires a new template export and a YAML update before
the next batch.

---

## Troubleshooting

**Tesseract not found**
Make sure Tesseract is installed and its folder is in your Windows PATH.
Open a new terminal after changing PATH settings.

**Import fails in Qualtrics**
Check that the `qualtrics_id` values in the YAML exactly match the
column headers in Row 1 of the exported Qualtrics template. One
mismatch causes the entire import to fail.

**Fields flagged as AMBIGUOUS**
Two answer options scored similarly. Open the original scan, check the
field by eye, and enter the correct value in `corrected_value` in
`flagged_fields.csv`.

**data/processed/ is empty after preprocessing**
Check that your scan files are in `data/scans/` and are JPG, PNG, TIFF,
or PDF format. Check the terminal output for quality check failures.

**Wrong values extracted**
The answer grid coordinates may need recalibration. Re-run the
calibration tool on the affected page and draw tighter boxes around
the answer regions.

---

## Project Documentation

- **CHANGELOG.md** — what was built, what changed, what was learned
- **ROADMAP.md** — all deferred feature ideas (only place they live)
- **TRD** — full Technical Requirements Document (see project files)

---

## Architecture

PaperTrail is a five-stage linear pipeline. Each stage writes to a new
folder. No stage modifies its inputs. Any stage can be re-run
independently without losing prior work.

```
Stage 1 — Preprocess    data/scans/      → data/processed/
Stage 2 — Extract       data/processed/  → data/extracted/
Stage 3 — Validate      data/extracted/  → data/flagged/ + data/validated/
Stage 4 — Map & Export  data/validated/  → data/output/
```

Each survey instrument is described in a YAML configuration file in
`config/surveys/`. The pipeline reads the survey name from `--survey`,
loads the matching YAML, and processes whatever fields are defined there.
Adding a new survey requires no code changes — only a new YAML file
and a calibration session.

---

*PaperTrail — Public Policy & Management Center, PPMC*
*Graduate Research Assistant — Internal Systems Project*
