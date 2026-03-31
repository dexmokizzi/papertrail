"""
Orchestrates OMR and OCR extraction across all fields in a survey.

Reads the survey YAML to determine which detection method to use
for each field, then returns a complete extraction result dict.
"""


def extract_form(image_path: str, survey_config: dict) -> dict:
    """Extract all field values from a single survey form image.

    Args:
        image_path: Path to the aligned scan image.
        survey_config: Parsed survey YAML configuration.

    Returns:
        Dict mapping field IDs to extracted value and confidence.
    """
    # Sprint 1C
    pass