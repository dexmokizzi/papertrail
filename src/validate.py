"""
Validation engine for PaperTrail.

Checks every extracted field value against the rules
declared in the survey YAML before it goes anywhere
near the Qualtrics output file.

Produces flagged_fields.csv listing every field that
needs human review. Fields that pass validation proceed
automatically. A partially flagged form never blocks
the clean fields — only uncertain fields wait.

Input:  Extraction dict + survey YAML config
Output: Clean fields dict + flagged_fields.csv
"""

import os
import csv
from datetime import datetime
from typing import Optional


# ── Constants ─────────────────────────────────────────────────────────────────

# Default confidence threshold below which a field is flagged.
# Can be overridden per survey in the YAML config.
DEFAULT_CONFIDENCE_THRESHOLD = 0.75

# Flagged fields CSV column headers
FLAGGED_HEADERS = [
    "form_id",
    "field_id",
    "raw_value",
    "confidence",
    "reason",
    "timestamp",
]


# ── Public API ────────────────────────────────────────────────────────────────

def validate_extraction(
    form_id:       str,
    extraction:    dict,
    survey_config: dict,
    flagged_path:  str = "data/flagged/flagged_fields.csv",
) -> dict:
    """Validate all extracted field values for a single form.

    Checks every field against its declared type, scale range,
    allowed values, required status, and confidence score.
    Writes any failing fields to flagged_fields.csv.

    Clean fields are returned immediately. Flagged fields are
    excluded from the result and must be corrected manually
    before the output stage runs.

    Args:
        form_id:       Unique identifier for this form.
        extraction:    Dict mapping paper_id -> detection result.
                       Each value should be a dict with keys:
                       value, confidence, flag (optional).
        survey_config: Parsed survey YAML configuration.
        flagged_path:  Where to write flagged_fields.csv.

    Returns:
        Dict with keys:
            clean   (dict)  — validated field values ready
                              for Qualtrics mapping
            flagged (list)  — list of flagged field dicts
            summary (dict)  — counts for logging
    """
    fields     = _get_all_fields(survey_config)
    threshold  = survey_config.get(
        "confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD
    )

    clean   = {}
    flagged = []

    for field in fields:
        paper_id = field.get("paper_id")
        if not paper_id:
            continue

        detection = extraction.get(paper_id, {})

        # Handle both raw value dicts and plain values
        if isinstance(detection, dict):
            value      = detection.get("value")
            confidence = detection.get("confidence", 0.0)
            omr_flag   = detection.get("flag", "")
        else:
            value      = detection
            confidence = 1.0 if detection is not None else 0.0
            omr_flag   = ""

        # Run all validation checks
        flag_reason = _check_field(
            value, confidence, omr_flag,
            field, threshold
        )

        if flag_reason:
            flagged.append({
                "form_id":    form_id,
                "field_id":   paper_id,
                "raw_value":  str(value) if value is not None else "",
                "confidence": round(confidence, 3),
                "reason":     flag_reason,
                "timestamp":  datetime.now().isoformat(),
            })
        else:
            clean[paper_id] = value

    # Write flagged fields to CSV
    if flagged:
        _write_flagged(flagged, flagged_path)

    return {
        "clean":   clean,
        "flagged": flagged,
        "summary": {
            "total":         len(fields),
            "clean":         len(clean),
            "flagged":       len(flagged),
            "flag_rate_pct": round(
                len(flagged) / len(fields) * 100, 1
            ) if fields else 0.0,
        },
    }


def validate_batch(
    extractions:   list,
    survey_config: dict,
    flagged_path:  str = "data/flagged/flagged_fields.csv",
) -> dict:
    """Validate all forms in a batch.

    Runs validate_extraction on each form and aggregates
    the results. Clean forms proceed to Qualtrics mapping.
    Flagged fields across all forms are written to one CSV.

    Any corrections already entered in flagged_fields.csv
    are preserved — re-running validate never wipes work
    that staff have already done.

    Args:
        extractions:   List of dicts, each with keys:
                       form_id and fields (extraction dict).
        survey_config: Parsed survey YAML configuration.
        flagged_path:  Where to write flagged_fields.csv.

    Returns:
        Dict with keys:
            clean_extractions (list)  — validated extractions
            all_flagged       (list)  — all flagged fields
            summary           (dict)  — batch-level counts
    """
    clean_extractions = []
    all_flagged       = []
    total_fields      = 0
    total_flagged     = 0

    # Load any corrections staff have already entered.
    # These are preserved when the file is regenerated —
    # re-running validate never loses correction work.
    existing_corrections = _load_existing_corrections(
        flagged_path
    )

    # Regenerate the flagged file with fresh flag rows
    # but with existing corrections written back in.
    _reset_flagged(flagged_path, existing_corrections)

    for item in extractions:
        form_id    = item.get("form_id", f"form_{len(clean_extractions)+1:04d}")
        extraction = item.get("fields", {})

        result = validate_extraction(
            form_id       = form_id,
            extraction    = extraction,
            survey_config = survey_config,
            flagged_path  = flagged_path,
        )

        clean_extractions.append({
            "form_id": form_id,
            "fields":  result["clean"],
        })

        all_flagged   += result["flagged"]
        total_fields  += result["summary"]["total"]
        total_flagged += result["summary"]["flagged"]

    # Write corrections back into the regenerated file
    if existing_corrections:
        _restore_corrections(flagged_path, existing_corrections)

    return {
        "clean_extractions": clean_extractions,
        "all_flagged":       all_flagged,
        "summary": {
            "forms_processed":   len(extractions),
            "total_fields":      total_fields,
            "total_flagged":     total_flagged,
            "flag_rate_pct":     round(
                total_flagged / total_fields * 100, 1
            ) if total_fields > 0 else 0.0,
        },
    }


def load_corrections(flagged_path: str) -> dict:
    """Load human corrections from flagged_fields.csv.

    Staff review flagged_fields.csv and enter corrections
    in a corrected_value column. This function reads those
    corrections and returns them as a lookup dict.

    Args:
        flagged_path: Path to the flagged_fields.csv file.

    Returns:
        Dict mapping (form_id, field_id) -> corrected_value.
        Empty dict if file does not exist or has no corrections.
    """
    corrections = {}

    if not os.path.exists(flagged_path):
        return corrections

    with open(flagged_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            corrected = row.get("corrected_value", "").strip()
            if corrected:
                key = (row["form_id"], row["field_id"])
                corrections[key] = corrected

    return corrections


# ── Validation checks ─────────────────────────────────────────────────────────

def _check_field(
    value:      any,
    confidence: float,
    omr_flag:   str,
    field:      dict,
    threshold:  float,
) -> Optional[str]:
    """Run all validation checks on a single field value.

    Checks are run in priority order. The first failing
    check returns its reason string. A field that passes
    all checks returns None.

    Args:
        value:      The detected value (may be None).
        confidence: Detection confidence score 0.0-1.0.
        omr_flag:   Flag from OMR engine (AMBIGUOUS, etc.)
        field:      Field definition from survey YAML.
        threshold:  Minimum confidence to auto-accept.

    Returns:
        Reason string if field should be flagged.
        None if field passes all checks.
    """
    paper_id = field.get("paper_id", "unknown")
    required = field.get("required", False)

    # Check 1 — OMR engine flagged this field
    if omr_flag == "AMBIGUOUS":
        return "AMBIGUOUS — two options scored similarly"

    if omr_flag == "NO_DETECTION":
        return "NO_DETECTION — mark detection failed"

    # Check 2 — Required field is missing
    if value is None and required:
        return "MISSING — required field has no detected value"

    # Check 3 — Low confidence
    if confidence < threshold:
        return (
            f"LOW_CONFIDENCE — score {confidence:.2f} "
            f"is below threshold {threshold:.2f}"
        )

    # Check 4 — Skip remaining checks if no value
    if value is None:
        return None

    # Check 5 — Value type validation
    field_type = field.get("type", "likert")

    if field_type in ["likert", "categorical"]:
        # Value must be convertible to a number
        try:
            float(str(value))
        except ValueError:
            return (
                f"INVALID_TYPE — expected numeric value, "
                f"got '{value}'"
            )

    # Check 6 — Scale range validation for Likert fields
    if field_type == "likert":
        scale = field.get("scale", [1, 2, 3, 4])
        str_value = str(value)
        str_scale = [str(s) for s in scale]
        if str_value not in str_scale:
            return (
                f"OUT_OF_RANGE — value '{value}' not in "
                f"scale {scale}"
            )

    # Check 7 — Allowed values validation for categorical
    if field_type == "categorical":
        allowed = field.get("allowed_values", [])
        if allowed:
            str_value   = str(value)
            str_allowed = [str(a) for a in allowed]
            if str_value not in str_allowed:
                return (
                    f"INVALID_VALUE — '{value}' not in "
                    f"allowed values {allowed}"
                )

    # All checks passed
    return None


# ── File helpers ──────────────────────────────────────────────────────────────

def _load_existing_corrections(path: str) -> dict:
    """Load any corrections already entered in the CSV.

    Called before regenerating the flagged file so that
    staff corrections are never lost on re-run.

    Args:
        path: Path to flagged_fields.csv.

    Returns:
        Dict mapping (form_id, field_id) -> corrected_value.
        Empty dict if file does not exist or has no corrections.
    """
    corrections = {}

    if not os.path.exists(path):
        return corrections

    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                corrected = row.get(
                    "corrected_value", ""
                ).strip()
                if corrected:
                    key = (row["form_id"], row["field_id"])
                    corrections[key] = corrected
    except Exception:
        pass

    return corrections


def _reset_flagged(path: str, existing: dict) -> None:
    """Delete the flagged file so it can be regenerated.

    Existing corrections are passed in separately and will
    be written back after the new flag rows are appended.
    This is safe — corrections are never lost.

    Args:
        path:     Path to flagged_fields.csv.
        existing: Corrections already entered by staff.
                  Informational only — used for log message.
    """
    if os.path.exists(path):
        os.remove(path)

    if existing:
        n = len(existing)
        print(
            f"  Preserving {n} existing correction(s) "
            f"through re-validation."
        )


def _restore_corrections(path: str, corrections: dict) -> None:
    """Write existing corrections back into the regenerated CSV.

    After validate_batch regenerates the flag rows, this
    function reads the fresh file and writes the corrections
    back into the corrected_value column for any matching
    (form_id, field_id) pairs.

    Fields that were previously flagged but are no longer
    flagged after re-validation simply do not appear in
    the file — their corrections are no longer needed.

    Args:
        path:        Path to flagged_fields.csv.
        corrections: Dict mapping (form_id, field_id)
                     -> corrected_value string.
    """
    if not os.path.exists(path):
        return

    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            key = (row["form_id"], row["field_id"])
            if key in corrections:
                row["corrected_value"] = corrections[key]
            rows.append(row)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_flagged(flagged: list, path: str) -> None:
    """Append flagged fields to the CSV review file.

    Creates the file and writes headers if it does not exist.
    Appends rows if the file already exists — preserving
    flags from earlier forms in the same batch.

    Args:
        flagged: List of flagged field dicts.
        path:    Path to the flagged_fields.csv file.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    write_headers = _needs_headers(path)

    with open(path, "a", newline="", encoding="utf-8") as f:
        all_headers = FLAGGED_HEADERS + ["corrected_value"]
        writer = csv.DictWriter(f, fieldnames=all_headers)

        if write_headers:
            writer.writeheader()

        for row in flagged:
            writer.writerow({
                **row,
                "corrected_value": "",
            })


def _needs_headers(path: str) -> bool:
    """Check if the CSV file needs headers written.

    Args:
        path: Path to check.

    Returns:
        True if file does not exist or is empty.
    """
    if not os.path.exists(path):
        return True
    return os.path.getsize(path) == 0


# ── YAML field extractor ──────────────────────────────────────────────────────

def _get_all_fields(survey_config: dict) -> list:
    """Extract all field definitions from a survey config.

    Handles both flat field lists and section-based structures.

    Args:
        survey_config: Parsed survey YAML configuration.

    Returns:
        Flat list of all field definition dicts.
    """
    fields = []

    # Flat field list
    fields += survey_config.get("fields", [])

    # Section-based structure
    for section in survey_config.get("sections", []):
        fields += section.get("fields", [])

    return fields
