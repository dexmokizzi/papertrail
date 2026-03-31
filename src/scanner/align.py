"""
Aligns a preprocessed survey image to a blank reference template.

Uses anchor point detection to correct any remaining positional
offset before mark detection begins.
"""


def align_to_reference(image, reference_path: str):
    """Align a scan to the blank reference template.

    Args:
        image: Preprocessed image as numpy array.
        reference_path: Path to the blank reference scan.

    Returns:
        Aligned image as a numpy array.
    """
    # Sprint 1B
    pass