"""
Optical character recognition for printed text fields.

Reads printed respondent IDs, form numbers, and section labels.
Saves handwritten open-text regions as image crops.
"""


def extract_text(image, field_config: dict) -> dict:
    """Extract printed text from a form field region.

    Args:
        image: Aligned image as numpy array.
        field_config: Field definition from the survey YAML.

    Returns:
        Dict with keys: value (str or None), confidence (float).
    """
    # Sprint 1C
    pass