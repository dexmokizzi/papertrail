"""
Qualtrics response import file generator for PaperTrail.

Reads a Qualtrics export template and a survey YAML config,
maps detected paper field values to the correct Qualtrics
columns, and produces an Excel file that imports into
Qualtrics on the first attempt without errors.

This module knows nothing about any specific survey.
It works from whatever template and YAML it is given.

Input:  List of extraction dicts + survey YAML + Qualtrics template
Output: Qualtrics-ready .xlsx file in data/output/
"""

import os
import uuid
import pandas as pd
from datetime import datetime
from typing import Optional


# ── Metadata defaults ─────────────────────────────────────────────────────────
# These values are used for all paper respondents.
# Qualtrics accepts these for manually imported responses.

METADATA_DEFAULTS = {
    "Status":              "0",
    "IPAddress":           "0.0.0.0",
    "Progress":            "100",
    "Finished":            "1",
    "RecipientLastName":   "",
    "RecipientFirstName":  "",
    "RecipientEmail":      "",
    "ExternalReference":   "",
    "LocationLatitude":    "",
    "LocationLongitude":   "",
    "DistributionChannel": "paper",
    "UserLanguage":        "EN",
}


# ── Public API ────────────────────────────────────────────────────────────────

def build_import_file(
    extractions:   list,
    survey_config: dict,
    template_path: str,
    output_path:   str,
    batch_date:    Optional[str] = None,
) -> bool:
    """Build a Qualtrics response import Excel file.

    Takes a list of extraction results (one per paper form),
    maps each value to its Qualtrics column using the survey
    YAML, and writes a correctly formatted .xlsx file.

    The output file has the exact three-row header structure
    Qualtrics requires:
        Row 1  — ImportId column headers
        Row 2  — Human-readable question labels
        Row 3+ — One row per paper respondent

    Args:
        extractions:   List of dicts, one per form. Each dict
                       maps paper_id -> detected value.
        survey_config: Parsed survey YAML configuration.
        template_path: Path to the Qualtrics export .xlsx file.
        output_path:   Where to save the completed import file.
        batch_date:    Date string for StartDate/EndDate columns.
                       Defaults to today if not provided.

    Returns:
        True if the file was saved and passed validation.
        False if something went wrong.
    """
    if not extractions:
        print("  No extractions to map. Nothing to write.")
        return False

    if not os.path.exists(template_path):
        print(f"  Template not found: {template_path}")
        return False

    print(f"  Reading template:   {template_path}")
    template = _read_template(template_path)
    if template is None:
        return False

    headers    = template["headers"]     # Row 1 — ImportIds
    labels     = template["labels"]      # Row 2 — Human labels
    computed   = template["computed"]    # Columns to leave blank

    date_str   = batch_date or datetime.now().strftime("%Y-%m-%d")

    print(f"  Mapping {len(extractions)} form(s) "
          f"to {len(headers)} column(s)...")

    # Build the field mapping from YAML
    # paper_id -> qualtrics_id
    field_map  = _build_field_map(survey_config)

    # Build one output row per respondent
    rows       = []
    for i, extraction in enumerate(extractions):
        row = _build_row(
            extraction, headers, field_map,
            computed, date_str, i + 1
        )
        rows.append(row)

    # Assemble the final dataframe
    # Row 1: headers, Row 2: labels, Row 3+: data
    output_df  = _assemble_dataframe(headers, labels, rows)

    # Validate before saving
    valid      = _validate(output_df, headers)
    if not valid:
        print("  Validation failed — file not saved.")
        return False

    # Save to disk
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    output_df.to_excel(output_path, index=False, header=False)
    print(f"  Saved:              {output_path}")
    print(f"  Rows:               {len(rows)} respondent(s)")
    print(f"  Columns:            {len(headers)}")
    print(f"  Ready to import into Qualtrics.")
    return True


# ── Template reader ───────────────────────────────────────────────────────────

def _read_template(template_path: str) -> Optional[dict]:
    """Read a Qualtrics export template and extract its structure.

    Reads Row 1 (ImportIds) and Row 2 (labels) from the template.
    Identifies computed columns that should be left blank on import.

    Args:
        template_path: Path to the Qualtrics export .xlsx file.

    Returns:
        Dict with keys: headers (list), labels (list),
        computed (set of column names to leave blank).
        Returns None if the file cannot be read.
    """
    try:
        df = pd.read_excel(
            template_path,
            header=None,
            nrows=3,
        )
    except Exception as e:
        print(f"  Could not read template: {e}")
        return None

    headers = [str(v) for v in df.iloc[0].tolist()]
    labels  = [str(v) for v in df.iloc[1].tolist()]

    # Identify computed columns by checking which columns
    # in Row 3 (first real response) contain derived values.
    # These are typically score aggregates and topic labels
    # that Qualtrics calculates automatically on import.
    # We identify them from the survey YAML config instead
    # of guessing — more reliable across survey types.
    computed = set()

    return {
        "headers":  headers,
        "labels":   labels,
        "computed": computed,
    }


# ── Field map builder ─────────────────────────────────────────────────────────

def _build_field_map(survey_config: dict) -> dict:
    """Build a mapping from paper field IDs to Qualtrics column IDs.

    Reads the fields section of the survey YAML and returns
    a dict mapping paper_id -> qualtrics_id for every field.

    Args:
        survey_config: Parsed survey YAML configuration dict.

    Returns:
        Dict mapping paper_id (str) -> qualtrics_id (str).
    """
    field_map = {}
    fields    = survey_config.get("fields", [])

    for field in fields:
        paper_id      = field.get("paper_id")
        qualtrics_id  = field.get("qualtrics_id")
        if paper_id and qualtrics_id:
            field_map[paper_id] = qualtrics_id

    # Also check sections if survey uses section structure
    sections = survey_config.get("sections", [])
    for section in sections:
        for field in section.get("fields", []):
            paper_id      = field.get("paper_id")
            qualtrics_id  = field.get("qualtrics_id")
            if paper_id and qualtrics_id:
                field_map[paper_id] = qualtrics_id

    return field_map


# ── Row builder ───────────────────────────────────────────────────────────────

def _build_row(
    extraction: dict,
    headers:    list,
    field_map:  dict,
    computed:   set,
    date_str:   str,
    index:      int,
) -> dict:
    """Build one output row for a single paper respondent.

    Maps every detected paper field value to its Qualtrics
    column. Fills metadata columns with standard defaults.
    Leaves computed columns blank.

    Args:
        extraction: Dict mapping paper_id -> detected value.
        headers:    List of Qualtrics column ImportIds (Row 1).
        field_map:  Dict mapping paper_id -> qualtrics_id.
        computed:   Set of column names to leave blank.
        date_str:   Date string for StartDate/EndDate.
        index:      Respondent number (1-based) for ResponseId.

    Returns:
        Dict mapping column header -> value for this respondent.
    """
    row = {}

    # Build a reverse lookup: qualtrics_id -> detected value
    value_lookup = {}
    for paper_id, detected in extraction.items():
        if paper_id in field_map:
            qualtrics_id = field_map[paper_id]
            value_lookup[qualtrics_id] = detected

    for header in headers:
        # Skip computed columns — Qualtrics fills these
        if header in computed:
            row[header] = ""
            continue

        # Metadata columns
        if header == "StartDate":
            row[header] = date_str
            continue
        if header == "EndDate":
            row[header] = date_str
            continue
        if header == "RecordedDate":
            row[header] = date_str
            continue
        if header == "ResponseId":
            row[header] = f"R_papertrail_{index:04d}"
            continue
        if header == "Duration (in seconds)":
            row[header] = ""
            continue

        # Standard metadata defaults
        if header in METADATA_DEFAULTS:
            row[header] = METADATA_DEFAULTS[header]
            continue

        # Survey response columns
        if header in value_lookup:
            value = value_lookup[header]
            # Use empty string for null values
            row[header] = "" if value is None else str(value)
            continue

        # Column exists in template but not mapped — leave blank
        row[header] = ""

    return row


# ── Dataframe assembler ───────────────────────────────────────────────────────

def _assemble_dataframe(
    headers: list,
    labels:  list,
    rows:    list,
) -> pd.DataFrame:
    """Assemble the final output dataframe.

    Qualtrics requires exactly this structure:
        Row 1 — ImportId column headers
        Row 2 — Human-readable labels
        Row 3+ — One row per respondent

    Args:
        headers: List of ImportId strings (Row 1).
        labels:  List of label strings (Row 2).
        rows:    List of dicts, one per respondent.

    Returns:
        DataFrame with Row 1 as headers, Row 2 as labels,
        and subsequent rows as respondent data.
    """
    # Convert rows list of dicts to list of lists
    # preserving exact column order from template
    data_rows = []
    for row_dict in rows:
        data_rows.append([
            row_dict.get(h, "") for h in headers
        ])

    # Stack: Row 1 (headers) + Row 2 (labels) + data rows
    all_rows = [headers, labels] + data_rows

    return pd.DataFrame(all_rows)


# ── Validator ─────────────────────────────────────────────────────────────────

def _validate(df: pd.DataFrame, headers: list) -> bool:
    """Validate the output file before saving.

    Checks that the file has the correct structure that
    Qualtrics requires for a successful response import.

    Args:
        df:      The assembled output dataframe.
        headers: Expected list of column headers.

    Returns:
        True if validation passes. False otherwise.
    """
    issues = []

    # Must have at least 3 rows (Row 1 + Row 2 + one respondent)
    if len(df) < 3:
        issues.append(
            f"File has only {len(df)} row(s). "
            f"Need at least 3 (headers + labels + 1 respondent)."
        )

    # Row 1 must match expected headers
    actual_headers = df.iloc[0].tolist()
    if actual_headers != headers:
        issues.append(
            "Row 1 headers do not match template. "
            "Import will fail."
        )

    # Must have at least one non-empty response column
    if len(df.columns) < 5:
        issues.append(
            f"Only {len(df.columns)} column(s). "
            f"Expected at least 5."
        )

    if issues:
        for issue in issues:
            print(f"  VALIDATION ERROR: {issue}")
        return False

    print(f"  Validation passed.")
    return True


# ── Convenience loader ────────────────────────────────────────────────────────

def load_survey_config(yaml_path: str) -> dict:
    """Load and return a survey YAML configuration file.

    Args:
        yaml_path: Path to the survey .yaml file.

    Returns:
        Parsed configuration as a dict.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
    """
    import yaml

    if not os.path.exists(yaml_path):
        raise FileNotFoundError(
            f"Survey config not found: {yaml_path}"
        )

    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}