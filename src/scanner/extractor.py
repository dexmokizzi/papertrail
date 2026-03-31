"""
Multi-page survey extractor for PaperTrail.

Groups processed page images by source PDF (respondent),
detects marks on each page, and combines all pages into
one extraction result per respondent.

One PDF = one respondent = one row in Qualtrics.

Input:  Folder of processed page images + survey YAML
Output: List of per-respondent extraction dicts
"""

import os
import re
import cv2
import json
from collections import defaultdict

from src.scanner.omr import detect_mark, detect_multi_select


# ── Public API ────────────────────────────────────────────────────────────────

def extract_batch(
    processed_dir: str,
    survey_config: dict,
    output_dir:    str,
) -> list:
    """Extract marks from all processed images in a folder.

    Groups page images by source PDF, then processes each
    page against the fields assigned to that page number
    in the survey YAML. Combines all pages into one
    extraction result per respondent.

    Args:
        processed_dir: Folder containing preprocessed images.
        survey_config: Parsed survey YAML dict.
        output_dir:    Folder to write extraction JSON files.

    Returns:
        List of extraction dicts, one per respondent.
        Each dict has keys: form_id, fields, pages_found.
    """
    images   = _find_images(processed_dir)
    grouped  = _group_by_respondent(images)
    fields   = survey_config.get("fields", [])
    page_map = _build_page_map(fields)

    print(f"\n  Found {len(grouped)} respondent(s), "
          f"{sum(len(p) for p in grouped.values())} page(s) total")

    extractions = []

    for form_id, pages in sorted(grouped.items()):
        print(f"\n  Respondent: {form_id}")
        print(f"  Pages found: {sorted(pages.keys())}")

        result = _extract_respondent(
            form_id  = form_id,
            pages    = pages,
            page_map = page_map,
        )

        extractions.append(result)

        # Print per-field summary
        for field_id, detection in result["fields"].items():
            value = detection.get("value", "-")
            conf  = detection.get("confidence", 0.0)
            flag  = (f"  [{detection.get('flag', '')}]"
                     if detection.get("flag") else "")
            print(f"    {field_id:<16} → "
                  f"{str(value):<8} "
                  f"(confidence: {conf:.2f}){flag}")

    # Save to disk
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "extractions.json")
    _save_extractions(extractions, out_path)
    print(f"\n  Saved extractions → {out_path}")

    return extractions


# ── Grouping ──────────────────────────────────────────────────────────────────

def _find_images(processed_dir: str) -> list:
    """Find all processed image files in a folder.

    Args:
        processed_dir: Path to search for images.

    Returns:
        List of full file paths for supported image types.
    """
    supported = (".jpg", ".jpeg", ".png", ".tiff", ".tif")
    files = []

    for filename in os.listdir(processed_dir):
        if os.path.splitext(filename)[1].lower() in supported:
            files.append(
                os.path.join(processed_dir, filename)
            )

    return sorted(files)


def _group_by_respondent(image_paths: list) -> dict:
    """Group page images by their source PDF respondent.

    Expects filenames in the format produced by preprocess.py:
        SomeName_page01.jpg
        SomeName_page02.jpg

    Single-page files without a page number are treated as
    one-page respondents.

    Args:
        image_paths: List of full image file paths.

    Returns:
        Dict mapping form_id -> {page_num -> image_path}.
    """
    grouped = defaultdict(dict)

    for path in image_paths:
        filename = os.path.basename(path)
        base     = os.path.splitext(filename)[0]

        # Match pattern: anything_pageNN
        match = re.match(r"^(.+)_page(\d+)$", base)

        if match:
            form_id  = match.group(1)
            page_num = int(match.group(2))
        else:
            # Single page file — treat as page 1
            form_id  = base
            page_num = 1

        grouped[form_id][page_num] = path

    return dict(grouped)


def _build_page_map(fields: list) -> dict:
    """Build a mapping from page number to field definitions.

    Args:
        fields: List of field dicts from the survey YAML.

    Returns:
        Dict mapping page_num (int) -> list of field dicts.
    """
    page_map = defaultdict(list)

    for field in fields:
        page = field.get("page", 1)
        page_map[page].append(field)

    return dict(page_map)


# ── Extraction ────────────────────────────────────────────────────────────────

def _extract_respondent(
    form_id:  str,
    pages:    dict,
    page_map: dict,
) -> dict:
    """Extract all fields from one respondent's pages.

    Iterates through available pages, loads each image,
    and runs mark detection on all fields assigned to
    that page number. Combines results into one dict.

    Fields from missing pages are recorded as null with
    a MISSING_PAGE flag so they appear in flagged_fields.csv
    for human review.

    Args:
        form_id:  Unique identifier for this respondent.
        pages:    Dict mapping page_num -> image_path.
        page_map: Dict mapping page_num -> field list.

    Returns:
        Extraction dict with form_id, fields, pages_found.
    """
    all_fields   = {}
    pages_found  = sorted(pages.keys())
    pages_needed = sorted(page_map.keys())

    # Process each page that has fields defined
    for page_num in pages_needed:
        fields_on_page = page_map[page_num]

        if page_num not in pages:
            # Page missing — flag all fields on this page
            print(f"    WARNING: Page {page_num} missing "
                  f"for respondent {form_id}")
            for field in fields_on_page:
                all_fields[field["paper_id"]] = {
                    "value":      None,
                    "confidence": 0.0,
                    "mark_type":  field.get("mark_type", ""),
                    "flag":       "MISSING_PAGE",
                    "note":       f"Page {page_num} not found",
                }
            continue

        # Load the page image
        image_path = pages[page_num]
        image      = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)

        if image is None:
            print(f"    WARNING: Could not load {image_path}")
            for field in fields_on_page:
                all_fields[field["paper_id"]] = {
                    "value":      None,
                    "confidence": 0.0,
                    "mark_type":  field.get("mark_type", ""),
                    "flag":       "IMAGE_ERROR",
                    "note":       f"Could not load page {page_num}",
                }
            continue

        # Detect marks on this page
        for field in fields_on_page:
            field_id  = field["paper_id"]
            field_type = field.get("type", "likert")

            if field_type == "multi_select":
                result = detect_multi_select(image, field)
            else:
                result = detect_mark(image, field)

            all_fields[field_id] = result

    return {
        "form_id":     form_id,
        "fields":      all_fields,
        "pages_found": pages_found,
    }


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_extractions(extractions: list, path: str) -> None:
    """Save extraction results to JSON for pipeline stages.

    Converts all values to JSON-serialisable types.

    Args:
        extractions: List of extraction result dicts.
        path:        Output file path.
    """
    serializable = []

    for item in extractions:
        fields = {}
        for field_id, detection in item["fields"].items():
            fields[field_id] = {
                "value":      detection.get("value"),
                "confidence": float(
                    detection.get("confidence", 0.0)
                ),
                "flag":       detection.get("flag", ""),
                "note":       detection.get("note", ""),
            }
        serializable.append({
            "form_id":     item["form_id"],
            "fields":      fields,
            "pages_found": item.get("pages_found", []),
        })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2)