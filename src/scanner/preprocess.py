"""
Preprocesses raw survey scan images for mark detection.

Accepts any image or PDF file — phone photo, flatbed scan,
CamScanner PDF, Adobe Scan — and returns a clean, straight,
high-contrast image ready for alignment and OMR detection.

Input:  Any image file (JPG, PNG, TIFF) or PDF
Output: Clean grayscale image saved to data/processed/
"""

import os
import cv2
import numpy as np
from pdf2image import convert_from_path


# ── Constants ─────────────────────────────────────────────────────────────────

# Minimum image dimension in pixels — below this we request a re-scan
MIN_DIMENSION_PX = 800

# Maximum skew angle we attempt to correct — beyond this, flag for re-scan
MAX_SKEW_DEGREES = 15

# Target DPI when converting PDF pages to images
PDF_DPI = 300


# ── Public entry point ────────────────────────────────────────────────────────

def preprocess(file_path: str, output_path: str) -> np.ndarray:
    """Run the full preprocessing pipeline on a single scan file.

    Loads the file, checks quality, removes background noise,
    corrects skew, and enhances contrast. Saves the result to
    output_path and returns the processed image array.

    Args:
        file_path:   Path to the raw input file (image or PDF).
        output_path: Where to save the preprocessed output image.

    Returns:
        Preprocessed image as a grayscale numpy array.

    Raises:
        FileNotFoundError: If the input file does not exist.
        ValueError: If the file format is not supported or
                    image quality is below minimum threshold.
    """
    print(f"  Loading      {os.path.basename(file_path)}")
    image = _load(file_path)

    print(f"  Checking     image quality")
    _check_quality(image, file_path)

    print(f"  Converting   to grayscale")
    gray = _to_grayscale(image)

    print(f"  Cleaning     background noise")
    gray = _clean_background(gray)

    print(f"  Deskewing    correcting rotation")
    gray = _deskew(gray)

    print(f"  Enhancing    contrast")
    gray = _enhance_contrast(gray)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, gray)
    print(f"  Saved        {output_path}")

    return gray


# ── Step 1: Load ──────────────────────────────────────────────────────────────

def _load(file_path: str) -> np.ndarray:
    """Load any supported file format into a numpy array.

    Handles JPG, PNG, TIFF, and PDF. PDFs are converted at
    300 DPI. Multi-page PDFs use the first page only — callers
    that need all pages should split the PDF first.

    Args:
        file_path: Path to the input file.

    Returns:
        Image as a BGR numpy array (OpenCV format).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return _load_pdf(file_path)

    if ext in [".jpg", ".jpeg", ".png", ".tiff", ".tif"]:
        return _load_image(file_path)

    raise ValueError(
        f"Unsupported file format '{ext}'. "
        f"Supported: JPG, PNG, TIFF, PDF"
    )


def _load_pdf(file_path: str) -> np.ndarray:
    """Convert the first page of a PDF to a numpy image array.

    Args:
        file_path: Path to the PDF file.

    Returns:
        First page as a BGR numpy array at PDF_DPI resolution.
    """
    pages = convert_from_path(file_path, dpi=300)
    if not pages:
        raise ValueError(f"Could not extract any pages from: {file_path}")

    # Convert PIL RGB image to OpenCV BGR array
    image = np.array(pages[0])
    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


def _load_image(file_path: str) -> np.ndarray:
    """Load a standard image file into a numpy array.

    Args:
        file_path: Path to the image file.

    Returns:
        Image as a BGR numpy array.
    """
    image = cv2.imread(file_path)
    if image is None:
        raise ValueError(f"Could not read image file: {file_path}")
    return image


# ── Step 2: Quality check ─────────────────────────────────────────────────────

def _check_quality(image: np.ndarray, file_path: str) -> None:
    """Check that an image meets minimum quality requirements.

    Flags images that are too small, too blurry, or too dark
    to produce reliable mark detection results.

    Args:
        image:     Image as a numpy array.
        file_path: Original file path — used in error messages.

    Raises:
        ValueError: If the image fails any quality check.
    """
    h, w = image.shape[:2]

    # Minimum size check
    if h < MIN_DIMENSION_PX or w < MIN_DIMENSION_PX:
        raise ValueError(
            f"Image too small ({w}x{h}px). "
            f"Minimum is {MIN_DIMENSION_PX}px on each side. "
            f"Please re-scan at higher resolution: {file_path}"
        )

    # Blur check using Laplacian variance
    # A variance below 50 indicates significant blur
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) \
        if len(image.shape) == 3 else image
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()

    if blur_score < 30:
        raise ValueError(
            f"Image appears too blurry (blur score: {blur_score:.1f}). "
            f"Please re-scan with better focus: {file_path}"
        )


# ── Step 3: Grayscale ─────────────────────────────────────────────────────────

def _to_grayscale(image: np.ndarray) -> np.ndarray:
    """Convert a BGR image to grayscale.

    If the image is already grayscale, returns it unchanged.

    Args:
        image: Image as a numpy array.

    Returns:
        Grayscale image as a single-channel numpy array.
    """
    if len(image.shape) == 2:
        return image  # Already grayscale
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


# ── Step 4: Clean background ──────────────────────────────────────────────────

def _clean_background(gray: np.ndarray) -> np.ndarray:
    """Remove background noise and normalize to clean white.

    Uses adaptive thresholding to handle uneven lighting,
    gray backgrounds from scanner apps, and shadow gradients
    from phone photos. Produces a clean black-on-white image.

    Args:
        gray: Grayscale image as a numpy array.

    Returns:
        Binary black-on-white image as a numpy array.
    """
    # Adaptive Gaussian threshold handles:
    # - Uneven lighting across the page
    # - Gray wash from CamScanner / phone cameras
    # - Shadow gradients from phone photos
    binary = cv2.adaptiveThreshold(
        gray,
        maxValue=255,
        adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        thresholdType=cv2.THRESH_BINARY,
        blockSize=31,   # Size of local neighbourhood — larger = more tolerant
        C=10            # Constant subtracted from mean — higher = lighter threshold
    )

    # Mild morphological closing to fill small gaps in marks
    # This helps with faint pencil marks and partial circles
    kernel = np.ones((2, 2), np.uint8)
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    return cleaned


# ── Step 5: Deskew ────────────────────────────────────────────────────────────

def _deskew(gray: np.ndarray) -> np.ndarray:
    """Correct rotational skew in a scanned document.

    Detects the dominant text/line angle using minimum area
    rectangle fitting on foreground pixels, then rotates to
    correct it. Skew beyond MAX_SKEW_DEGREES is not corrected
    — those scans should be re-captured.

    Args:
        gray: Grayscale image as a numpy array.

    Returns:
        Deskewed image as a numpy array.
    """
    # Find foreground pixels (dark marks on white background)
    inverted = cv2.bitwise_not(gray)
    coords = np.column_stack(np.where(inverted > 0))

    if len(coords) < 100:
        # Not enough foreground content to estimate angle
        return gray

    # Fit minimum area rectangle to all foreground pixels
    angle = cv2.minAreaRect(coords)[-1]

    # Convert angle to standard rotation convention
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    # Skip correction if skew is negligible
    if abs(angle) < 0.5:
        return gray

    # Skip correction if skew is beyond our safe range
    if abs(angle) > MAX_SKEW_DEGREES:
        print(
            f"  Warning      Skew angle {angle:.1f}° exceeds "
            f"{MAX_SKEW_DEGREES}° limit. Skipping correction. "
            f"Consider re-scanning."
        )
        return gray

    # Rotate to correct the skew
    (h, w) = gray.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    corrected = cv2.warpAffine(
        gray, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255  # Fill new border areas with white
    )

    return corrected


# ── Step 6: Enhance contrast ──────────────────────────────────────────────────

def _enhance_contrast(gray: np.ndarray) -> np.ndarray:
    """Sharpen contrast to make marks more distinct for OMR.

    Applies CLAHE (Contrast Limited Adaptive Histogram
    Equalization) for local contrast improvement. This helps
    with faint pencil marks, light ink, and partial circles
    that might otherwise be missed by the detection algorithm.

    Args:
        gray: Grayscale image as a numpy array.

    Returns:
        Contrast-enhanced grayscale image.
    """
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


# ── Batch helper ──────────────────────────────────────────────────────────────

def preprocess_batch(input_dir: str, output_dir: str) -> list:
    """Preprocess all supported scan files in a folder.

    Processes every JPG, PNG, TIFF, and PDF file found in
    input_dir. Multi-page PDFs are split into individual
    page images. Results are saved to output_dir.

    Args:
        input_dir:  Folder containing raw scan files.
        output_dir: Folder where processed images are saved.

    Returns:
        List of output file paths for successfully processed files.
    """
    supported = (".jpg", ".jpeg", ".png", ".tiff", ".tif", ".pdf")
    files = [
        f for f in os.listdir(input_dir)
        if os.path.splitext(f)[1].lower() in supported
    ]

    if not files:
        print(f"No supported scan files found in {input_dir}")
        return []

    print(f"Found {len(files)} file(s) to process\n")
    processed = []
    failed    = []

    for filename in files:
        input_path = os.path.join(input_dir, filename)
        base_name  = os.path.splitext(filename)[0]
        ext        = os.path.splitext(filename)[1].lower()

        print(f"[{files.index(filename)+1}/{len(files)}] {filename}")

        try:
            if ext == ".pdf":
                # Handle multi-page PDFs — save each page separately
                pages = convert_from_path(input_path, dpi=PDF_DPI)
                print(f"  Pages:       {len(pages)} page(s) found")

                for page_num, page in enumerate(pages, start=1):
                    # Convert PIL to OpenCV
                    image = np.array(page)
                    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

                    # Build output path with page number
                    output_name = f"{base_name}_page{page_num:02d}.jpg"
                    output_path = os.path.join(output_dir, output_name)

                    print(f"  Processing   page {page_num}/{len(pages)}")

                    # Run preprocessing on this page
                    _check_quality(image, input_path)
                    gray    = _to_grayscale(image)
                    gray    = _clean_background(gray)
                    gray    = _deskew(gray)
                    gray    = _enhance_contrast(gray)

                    os.makedirs(output_dir, exist_ok=True)
                    cv2.imwrite(output_path, gray)
                    print(f"  Saved        {output_path}")
                    processed.append(output_path)

            else:
                # Single image file
                output_name = f"{base_name}.jpg"
                output_path = os.path.join(output_dir, output_name)
                preprocess(input_path, output_path)
                processed.append(output_path)

        except (ValueError, FileNotFoundError) as e:
            print(f"  FAILED: {e}")
            failed.append(filename)

        print()

    print(f"Complete: {len(processed)} page(s) processed, "
          f"{len(failed)} failed")
    if failed:
        print(f"Failed files: {', '.join(failed)}")

    return processed