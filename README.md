# PaperTrail

From paper surveys to Qualtrics — automatically.

PaperTrail scans completed paper survey forms and produces a 
Qualtrics-ready import file. No manual data entry. No import failures.

## Setup

1. Clone the repo
2. Create and activate a virtual environment:
   python -m venv .venv
   .venv\Scripts\activate
3. Install dependencies:
   pip install -r requirements.txt
4. Install Tesseract OCR at the OS level:
   https://github.com/UB-Mannheim/tesseract/wiki

## Usage

python run_pipeline.py --input data/scans/ --survey your_survey_name

## Registering a New Survey

See Section 4 of the TRD for full instructions.

## Project Structure

See Section 9 of the TRD.