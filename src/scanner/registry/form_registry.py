"""
Identifies which survey YAML configuration applies to a given scan.

Used when the survey type is not specified manually, to automatically
match an incoming scan to its registered instrument.
"""


def identify_survey(image_path: str, config_dir: str = "config/surveys/") -> str:
    """Identify which registered survey a scan belongs to.

    Args:
        image_path: Path to the scan image.
        config_dir: Folder containing survey YAML files.

    Returns:
        survey_id string matching a YAML filename in config_dir.
    """
    # Sprint 2D
    pass