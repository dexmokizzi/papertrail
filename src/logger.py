"""
Run logger for PaperTrail.

Appends one row to run_log.csv after every pipeline run.
No manual logging required. After 30 days this file
contains everything needed for an impact report.

Input:  Run metrics from the pipeline
Output: One new row appended to logs/run_log.csv
"""

import os
import csv
from datetime import datetime


# ── Log file config ───────────────────────────────────────────────────────────

LOG_PATH = "logs/run_log.csv"

LOG_HEADERS = [
    "run_timestamp",
    "survey_id",
    "forms_processed",
    "fields_extracted",
    "fields_flagged",
    "flag_rate_pct",
    "qualtrics_validation_passed",
    "pipeline_runtime_sec",
    "operator",
    "notes",
]


# ── Public API ────────────────────────────────────────────────────────────────

def log_run(
    survey_id:                  str,
    forms_processed:            int,
    fields_extracted:           int,
    fields_flagged:             int,
    qualtrics_validation_passed: bool,
    pipeline_runtime_sec:       float,
    operator:                   str = "developer",
    notes:                      str = "",
    log_path:                   str = LOG_PATH,
) -> None:
    """Append one row to run_log.csv after a pipeline run.

    Creates the log file and writes headers if it does not
    exist. Always appends — never overwrites existing records.
    Every run is permanently recorded regardless of errors.

    Args:
        survey_id:                   Survey instrument processed.
        forms_processed:             Number of forms in the batch.
        fields_extracted:            Total fields OMR/OCR attempted.
        fields_flagged:              Fields sent for human review.
        qualtrics_validation_passed: Whether output passed format check.
        pipeline_runtime_sec:        Total end-to-end runtime.
        operator:                    Who ran the pipeline.
        notes:                       Optional free-text notes.
        log_path:                    Path to run_log.csv.
    """
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    flag_rate = (
        round(fields_flagged / fields_extracted * 100, 2)
        if fields_extracted > 0 else 0.0
    )

    row = {
        "run_timestamp":              datetime.now().isoformat(),
        "survey_id":                  survey_id,
        "forms_processed":            forms_processed,
        "fields_extracted":           fields_extracted,
        "fields_flagged":             fields_flagged,
        "flag_rate_pct":              flag_rate,
        "qualtrics_validation_passed": str(qualtrics_validation_passed),
        "pipeline_runtime_sec":       round(pipeline_runtime_sec, 2),
        "operator":                   operator,
        "notes":                      notes,
    }

    write_headers = _needs_headers(log_path)

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_HEADERS)
        if write_headers:
            writer.writeheader()
        writer.writerow(row)

    print(f"  Logged  →  {log_path}")


def get_summary(log_path: str = LOG_PATH) -> dict:
    """Read run_log.csv and return summary statistics.

    Used for impact reporting. Returns totals and averages
    across all recorded runs.

    Args:
        log_path: Path to run_log.csv.

    Returns:
        Dict with summary statistics. Empty dict if no log.
    """
    if not os.path.exists(log_path):
        return {}

    rows = []
    with open(log_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows   = list(reader)

    if not rows:
        return {}

    total_forms    = sum(int(r["forms_processed"]) for r in rows)
    total_fields   = sum(int(r["fields_extracted"]) for r in rows)
    total_flagged  = sum(int(r["fields_flagged"]) for r in rows)
    total_runs     = len(rows)
    avg_runtime    = sum(
        float(r["pipeline_runtime_sec"]) for r in rows
    ) / total_runs
    passed_imports = sum(
        1 for r in rows
        if r["qualtrics_validation_passed"].lower() == "true"
    )

    return {
        "total_runs":            total_runs,
        "total_forms_processed": total_forms,
        "total_fields_extracted":total_fields,
        "total_fields_flagged":  total_flagged,
        "overall_flag_rate_pct": round(
            total_flagged / total_fields * 100, 2
        ) if total_fields > 0 else 0.0,
        "avg_runtime_sec":       round(avg_runtime, 2),
        "successful_imports":    passed_imports,
        "import_success_rate":   round(
            passed_imports / total_runs * 100, 1
        ),
    }


# ── Helper ────────────────────────────────────────────────────────────────────

def _needs_headers(path: str) -> bool:
    """Check if the log file needs headers written.

    Args:
        path: Path to check.

    Returns:
        True if file does not exist or is empty.
    """
    if not os.path.exists(path):
        return True
    return os.path.getsize(path) == 0