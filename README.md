# PaperTrail

**From paper surveys to Qualtrics — automatically. For any survey.**

PaperTrail is a local-first, zero-cost Intelligent Document Processing pipeline built for the Public Policy and Management Center (PPMC). It accepts scanned paper surveys, reads every respondent's answers using computer vision, validates the results, and produces a correctly formatted Excel file that uploads directly into Qualtrics on the first attempt.

No cloud. No paid APIs. No server required. It runs entirely on a standard Windows laptop.

---

## The Problem It Solves

PPMC runs surveys simultaneously online and on paper. Online responses flow into Qualtrics automatically. Paper responses, however, required staff to manually transcribe every answer into a spreadsheet — a process that took 3 to 5 hours per batch, introduced silent data entry errors at an estimated 2 to 5 percent per field, and produced inconsistent results depending on who did the transcription.

PaperTrail eliminates that manual step entirely.

---

## How It Works

The pipeline runs in four stages, each writing to its own folder so nothing is ever lost or overwritten.

```
Stage 1   Staff scans completed paper forms with CamScanner
          One PDF per respondent, all pages in one session

Stage 2   Drop PDFs into data/scans/your_survey_name/
          Run one command:
          python run_pipeline.py --survey your_survey_name

Stage 3   PaperTrail reads every answer using computer vision
          Uncertain fields are flagged for human review
          Staff correct only the uncertain ones, not the whole form

Stage 4   Upload data/output/your_survey_name_import.xlsx to Qualtrics
          Paper responses appear alongside online responses immediately
```

That is the complete workflow. Staff never touch Python, never open a CSV by hand, and never manually transcribe a single answer.

---

## Why This Is Different From a Simple Script

Most automation attempts for paper surveys either break on unusual handwriting, work only for one specific form, or require an internet connection and a paid service. PaperTrail was designed to avoid all of those limitations.

**It is survey-agnostic.** Any paper survey that has a Qualtrics counterpart can be registered. Each instrument is described in a single YAML configuration file. After a one-time calibration session, that survey processes automatically forever with no code changes required.

**It never silently accepts uncertain data.** Every extracted field receives a confidence score from 0.0 to 1.0. Fields the system is uncertain about are flagged for human review. Nothing gets written to the output file with a wrong value and no warning.

**It runs entirely locally.** No cloud account, API key, or internet connection is needed for the core pipeline. The system runs on any Windows laptop that has Python and OpenCV installed.

**It preserves the original data.** Raw extracted values are never overwritten. Human corrections go into a separate column. Every correction is traceable back to the original scan.

---

## What It Can Detect

PaperTrail supports four mark types that appear across PPMC survey instruments:

| Mark type | What respondents do |
|---|---|
| circled_number | Circle a printed number (e.g. circle the 3) |
| filled_bubble | Fill in or darken a printed bubble |
| x_mark | Draw an X through a printed square or circle |
| circled_bubble | Draw a circle around a small printed empty bubble |

Multiple mark types can exist within the same survey. All detection algorithms try multiple approaches and take the strongest signal. The system handles large circles, small circles, pencil marks, pen marks, and partial circles without requiring any manual tuning per respondent.

---

## The Detection Approach

The core detection engine uses a proximity-based algorithm built on OpenCV. For each answer option, the system extracts a fixed-radius window around the option's calibrated center point and scores it independently. The option with the highest score in its own window wins.

This means circle size does not matter. A respondent who draws a very large circle around option 4 and a respondent who draws a very small circle around option 4 both produce the same correct result, because the center of any circle drawn around an option is always closest to that option's center point.

The window radius is calculated dynamically from the actual spacing between declared option centers. A form with options 200 pixels apart gets a 70-pixel window. A form with options 80 pixels apart gets a 28-pixel window. This scaling happens automatically with no hardcoded values, which is what makes the approach work across any survey layout and any image resolution.

---

## Confidence Scoring and Human Review

Every extracted field produces a score between 0.0 and 1.0. The system routes fields based on that score.

| Score range | Status | What happens |
|---|---|---|
| 0.90 to 1.00 | High confidence | Accepted automatically |
| 0.75 to 0.89 | Moderate | Accepted, logged for audit |
| 0.50 to 0.74 | Low confidence | Written to flagged_fields.csv for review |
| 0.00 to 0.49 | Unreadable | Excluded until a correction is entered |

On a clean scan from a typical respondent, most forms produce a flag rate under 15 percent. Staff open flagged_fields.csv, look at the original scan, and type the correct value. The pipeline then re-runs the output stage and produces the final file with corrections applied.

---

## Installation

**Requirements:** Windows 11, Python 3.10 or higher, Tesseract OCR 5.x

Clone the repository and set up a virtual environment:

```bash
git clone https://github.com/your-org/papertrail.git
cd papertrail
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Tesseract OCR must be installed at the OS level separately from pip. Download the installer from https://github.com/UB-Mannheim/tesseract/wiki, run it, and add `C:\Program Files\Tesseract-OCR` to your Windows PATH.

Verify everything is working:

```bash
python -c "import cv2, pytesseract, pandas, yaml; print('Ready.')"
```

---

## Running a Batch

Drop scans into the survey subfolder and run the pipeline:

```bash
python run_pipeline.py --survey your_survey_name
```

If any fields are flagged, open `data/flagged/flagged_fields.csv`, enter corrections in the `corrected_value` column, and re-run just the output stage:

```bash
python run_pipeline.py --survey your_survey_name --stage output
```

Then import `data/output/your_survey_name_import.xlsx` into Qualtrics via Data and Analysis → Export and Import → Import Data.

Multiple batch runs append into the same output file. You can process forms across multiple days and produce one import file for the entire batch.

---

## Registering a New Survey

Any new survey PPMC runs on paper can be registered. The process takes about 30 to 45 minutes and never needs to be repeated for that instrument.

**Step 1.** Export the Qualtrics template from the target survey. In Qualtrics: Data and Analysis → Export and Import → Export Data → Excel format. Save to `qualtrics_templates/your_survey_name_template.xlsx`.

**Step 2.** Scan a blank copy of the form. This is the reference image — the blank form has printed answer positions that are correct for every respondent. Save to `templates/survey_forms/your_survey_name_blank.jpg`.

**Step 3.** Run preprocessing on a completed scan to produce calibration images:

```bash
python run_pipeline.py --survey your_survey_name --stage preprocess
```

**Step 4.** Run the calibration tool on each page. The tool asks you questions interactively — no manual YAML editing required:

```bash
python -m src.scanner.calibration_tool ^
    --image data/processed/your_scan_page01.jpg ^
    --survey your_survey_name
```

When prompted, choose center-point mode and click the center of each printed answer option. The tool saves automatically when you finish. Repeat for each page.

**Step 5.** Add two lines to the generated YAML file in `config/surveys/`:

```yaml
survey_id: your_survey_name
qualtrics:
  template: qualtrics_templates/your_survey_name_template.xlsx
```

**Step 6.** Run the pipeline on a test scan and compare the output against the paper form to verify. Once it matches, the survey is registered permanently.

---

## Folder Structure

```
papertrail/
├── config/surveys/          one YAML file per registered survey
├── qualtrics_templates/     Qualtrics export files, one per survey
├── data/                    all survey data, excluded from git
│   ├── scans/               drop raw PDFs here, organized by survey subfolder
│   ├── processed/           preprocessed page images
│   ├── extracted/           JSON extraction results
│   ├── flagged/             flagged_fields.csv for human review
│   ├── validated/           reviewed and corrected data
│   └── output/              Qualtrics-ready xlsx files
├── templates/survey_forms/  blank reference scans for calibration
├── src/scanner/             preprocess.py, omr.py, extractor.py,
│                            calibration_tool.py, ocr.py, align.py
├── src/                     validate.py, qualtrics_mapper.py, logger.py
├── logs/run_log.csv         auto-appended after every pipeline run
├── CHANGELOG.md             one entry per sprint close
├── ROADMAP.md               all deferred feature ideas
└── run_pipeline.py          single CLI entry point
```

---

## Pipeline Commands

```bash
python run_pipeline.py --survey name                   full pipeline
python run_pipeline.py --survey name --stage output    output only, after corrections
python run_pipeline.py --survey name --dry-run         simulate without writing files
python run_pipeline.py --survey name --stage preprocess
python run_pipeline.py --survey name --stage extract
python run_pipeline.py --survey name --stage validate
python run_pipeline.py --help
```

---

## Development Status

PaperTrail is in active development by a solo graduate research assistant at PPMC. The core pipeline is working end-to-end and has been verified against real multi-page scans.

What is working right now: the full pipeline runs from PDF to Qualtrics import file in under 20 seconds. Multi-page PDF support handles any number of pages. All four mark types are detected across mixed surveys. The corrections workflow preserves staff work across multiple re-runs. Batch accumulation appends multiple scan sessions into one output file. Processed scans are automatically archived after each successful run to prevent duplicate respondents.

What is in progress: blank reference form calibration is the next step before broader staff deployment. The system achieves its most consistent results when calibrated on a blank form rather than a completed respondent scan. Phase 3, a Streamlit browser interface, will allow non-technical staff to review flagged fields and enter corrections without touching any files directly.

Measured results so far: on a respondent with standard mark style, the flag rate is around 12 percent. On a respondent who draws unusually large circles, the proximity-based detection approach brought the flag rate from 64.9 percent down to 19.3 percent after full recalibration.

---

## Technical Stack

All dependencies are free and open source. Nothing requires a paid account or an internet connection.

```
opencv-python     image preprocessing and all mark detection
pytesseract       printed text extraction via Tesseract OCR
pdf2image         splits multi-page PDFs into per-page images
Pillow            image handling and format conversion
pandas            all tabular data and Excel output
openpyxl          xlsx read and write operations
pydantic v2       runtime field validation against YAML schema
PyYAML            all configuration file parsing
click             CLI interface for run_pipeline.py
numpy             pixel array operations used by OpenCV
streamlit         Phase 3 browser review UI (planned)
```

---

## Important Notes

The `data/` folder is never committed to git. Real survey data stays on the local machine. The `.gitignore` excludes it from day one.

Corrections entered in `flagged_fields.csv` are preserved across any number of re-validation runs. Raw extracted values are never overwritten — corrections always live in a separate `corrected_value` column.

If Qualtrics edits a survey structure after registration, re-export the template and update the YAML before the next batch run.

---

## Project Documentation

The full Technical Requirements Document governs all scope decisions. New feature requests go to `ROADMAP.md` only and do not enter active development without explicit re-scoping. The CHANGELOG records what was built, what changed, and what was learned at the close of every sprint.

---

*PaperTrail — Public Policy and Management Center, PPMC*
*Graduate Research Assistant — Internal Systems Project, 2026*
