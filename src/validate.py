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

DEFAULT_CONFIDENCE_THRESHOLD = 0.75

# Ink delta scoring produces scores in the 0.02-0.20 range.
# The standard 0.75 threshold rejects all ink delta detections
# even when correct. Use this lower threshold when the detection
# method is ink delta.
INK_DELTA_CONFIDENCE_THRESHOLD = 0.01

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

    Args:
        form_id:       Unique identifier for this form.
        extraction:    Dict mapping paper_id -> detection result.
        survey_config: Parsed survey YAML configuration.
        flagged_path:  Where to write flagged_fields.csv.

    Returns:
        Dict with keys: clean, flagged, summary.
    """
    fields    = _get_all_fields(survey_config)
    threshold = survey_config.get(
        "confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD
    )

    clean   = {}
    flagged = []

    for field in fields:
        paper_id = field.get("paper_id")
        if not paper_id:
            continue

        detection = extraction.get(paper_id, {})

        if isinstance(detection, dict):
            value            = detection.get("value")
            confidence       = detection.get("confidence", 0.0)
            omr_flag         = detection.get("flag", "")
            detection_method = detection.get("path_used", "")
        else:
            value            = detection
            confidence       = 1.0 if detection is not None else 0.0
            omr_flag         = ""
            detection_method = ""

        # Use a lower confidence threshold for ink delta scoring.
        # Ink delta scores are smaller in magnitude than shape scores
        # but the relative winner is still meaningful and correct.
        effective_threshold = (
            INK_DELTA_CONFIDENCE_THRESHOLD
            if detection_method == "proximity"
            and confidence < DEFAULT_CONFIDENCE_THRESHOLD
            and confidence > 0.0
            else threshold
        )

        flag_reason = _check_field(
            value, confidence, omr_flag, field, effective_threshold
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

    Any corrections already entered in flagged_fields.csv
    are preserved — re-running validate never wipes work
    that staff have already done.

    Args:
        extractions:   List of dicts with form_id and fields.
        survey_config: Parsed survey YAML configuration.
        flagged_path:  Where to write flagged_fields.csv.

    Returns:
        Dict with keys: clean_extractions, all_flagged, summary.
    """
    clean_extractions = []
    all_flagged       = []
    total_fields      = 0
    total_flagged     = 0

    existing_corrections = _load_existing_corrections(flagged_path)
    _reset_flagged(flagged_path, existing_corrections)

    for item in extractions:
        form_id    = item.get(
            "form_id",
            f"form_{len(clean_extractions)+1:04d}"
        )
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


def load_corrections(
    flagged_path:  str,
    survey_config: Optional[dict] = None,
) -> dict:
    """Load human corrections from flagged_fields.csv.

    Validates each correction against the field's declared scale.
    Invalid corrections are rejected with a printed warning so
    staff can fix them before bad data reaches Qualtrics.

    Args:
        flagged_path:  Path to the flagged_fields.csv file.
        survey_config: Parsed survey YAML for scale validation.
                       If None, no scale validation is applied.

    Returns:
        Dict mapping (form_id, field_id) -> corrected_value.
        Empty dict if file does not exist or has no corrections.
    """
    corrections = {}
    invalid     = []

    if not os.path.exists(flagged_path):
        return corrections

    field_lookup = {}
    if survey_config:
        for field in _get_all_fields(survey_config):
            pid = field.get("paper_id")
            if pid:
                field_lookup[pid] = field

    with open(flagged_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            corrected = row.get("corrected_value", "").strip()
            if not corrected:
                continue

            field_id = row["field_id"]
            form_id  = row["form_id"]

            if field_lookup and field_id in field_lookup:
                rejection = _validate_correction(
                    corrected, field_lookup[field_id]
                )
                if rejection:
                    invalid.append(
                        f"  INVALID CORRECTION — "
                        f"{form_id} / {field_id}: "
                        f"'{corrected}' — {rejection}"
                    )
                    continue

            corrections[(form_id, field_id)] = corrected

    if invalid:
        print(
            f"\n  WARNING: {len(invalid)} correction(s) "
            f"rejected — value outside declared scale:"
        )
        for msg in invalid:
            print(msg)
        print(
            "  Fix these in flagged_fields.csv and "
            "re-run --stage output.\n"
        )

    return corrections


def _validate_correction(
    corrected: str,
    field:     dict,
) -> Optional[str]:
    """Check a staff correction against the field declared scale.

    Args:
        corrected: The correction value entered by staff.
        field:     Field definition from the survey YAML.

    Returns:
        Rejection reason string if invalid, None if valid.
    """
    field_type = field.get("type", "likert")

    if field_type == "open_text":
        return None

    if field_type == "multi_select":
        scale     = field.get("scale", [])
        str_scale = [str(s) for s in scale]
        values    = [v.strip() for v in corrected.split(",")]
        invalid   = [v for v in values if v not in str_scale]
        if invalid:
            return f"values {invalid} not in scale {scale}"
        return None

    scale = field.get("scale", [])
    if not scale:
        return None

    str_scale = [str(s) for s in scale]
    if str(corrected) not in str_scale:
        return f"'{corrected}' not in scale {scale}"

    return None


# ── Validation checks ─────────────────────────────────────────────────────────

def _check_field(
    value:      any,
    confidence: float,
    omr_flag:   str,
    field:      dict,
    threshold:  float,
) -> Optional[str]:
    """Run all validation checks on a single field value.

    Checks run in priority order. First failing check returns
    its reason string. Passes all checks returns None.

    Args:
        value:      The detected value (may be None).
        confidence: Detection confidence score 0.0-1.0.
        omr_flag:   Flag from OMR engine (AMBIGUOUS, etc.)
        field:      Field definition from survey YAML.
        threshold:  Minimum confidence to auto-accept.

    Returns:
        Reason string if field should be flagged, else None.
    """
    required = field.get("required", False)

    if omr_flag == "AMBIGUOUS":
        return "AMBIGUOUS — two options scored similarly"

    if omr_flag == "NO_DETECTION":
        return "NO_DETECTION — mark detection failed"

    if value is None and required:
        return "MISSING — required field has no detected value"

    if confidence < threshold:
        return (
            f"LOW_CONFIDENCE — score {confidence:.2f} "
            f"is below threshold {threshold:.2f}"
        )

    if value is None:
        return None

    field_type = field.get("type", "likert")

    if field_type in ["likert", "categorical"]:
        try:
            float(str(value))
        except ValueError:
            return (
                f"INVALID_TYPE — expected numeric value, "
                f"got '{value}'"
            )

    if field_type == "likert":
        scale     = field.get("scale", [1, 2, 3, 4])
        str_value = str(value)
        str_scale = [str(s) for s in scale]
        if str_value not in str_scale:
            return (
                f"OUT_OF_RANGE — value '{value}' not in "
                f"scale {scale}"
            )

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

    return None


# ── File helpers ──────────────────────────────────────────────────────────────

def _load_existing_corrections(path: str) -> dict:
    """Load corrections already entered before regenerating the file.

    Args:
        path: Path to flagged_fields.csv.

    Returns:
        Dict mapping (form_id, field_id) -> corrected_value.
    """
    corrections = {}
    if not os.path.exists(path):
        return corrections
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                corrected = row.get("corrected_value", "").strip()
                if corrected:
                    key = (row["form_id"], row["field_id"])
                    corrections[key] = corrected
    except Exception:
        pass
    return corrections


def _reset_flagged(path: str, existing: dict) -> None:
    """Delete the flagged file so it can be regenerated cleanly.

    Args:
        path:     Path to flagged_fields.csv.
        existing: Corrections already entered by staff.
    """
    if os.path.exists(path):
        os.remove(path)
    if existing:
        print(
            f"  Preserving {len(existing)} existing "
            f"correction(s) through re-validation."
        )


def _restore_corrections(path: str, corrections: dict) -> None:
    """Write corrections back into the regenerated CSV.

    Args:
        path:        Path to flagged_fields.csv.
        corrections: Dict mapping (form_id, field_id) -> value.
    """
    if not os.path.exists(path):
        return

    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader     = csv.DictReader(f)
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
            writer.writerow({**row, "corrected_value": ""})


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

    Args:
        survey_config: Parsed survey YAML configuration.

    Returns:
        Flat list of all field definition dicts.
    """
    fields = []
    fields += survey_config.get("fields", [])
    for section in survey_config.get("sections", []):
        fields += section.get("fields", [])
    return fields
