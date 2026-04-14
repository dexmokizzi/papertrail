"""
Survey calibration tool for PaperTrail.

Opens a processed survey image in an interactive window.
Records answer regions for every field on the page and
writes a complete survey YAML configuration automatically.

Two calibration modes are available, selectable per field group:

  Bounding box mode  — click and drag to draw a box around
                       each answer option. Saves x, y, w, h.
                       Triggers the bounding box detection path.

  Center-point mode  — single click on the center of each
                       answer option. Saves x, y only (no w/h).
                       Triggers the proximity detection path,
                       which is robust to any mark size.

Mode is selected during setup, before drawing begins. Either
mode can be used for any mark type on any survey layout.
The detection path is always determined by YAML format alone.

Usage:
    python -m src.scanner.calibration_tool
        --image data/processed/your_scan.jpg
        --survey your_survey_name

Controls (bounding box mode):
    Click + drag  ->  Draw a region box
    R             ->  Undo last region
    S or Enter    ->  Save and exit
    Q             ->  Quit without saving
    Z             ->  Zoom in
    X             ->  Zoom out

Controls (center-point mode):
    Click         ->  Mark center of current option
    R             ->  Undo last point
    S or Enter    ->  Save and exit
    Q             ->  Quit without saving
    Z             ->  Zoom in
    X             ->  Zoom out
"""

import os
import re
import cv2
import yaml
import argparse
import numpy as np


# ── Constants ─────────────────────────────────────────────────────────────────

ZOOM_STEP    = 0.2
MIN_ZOOM     = 0.3
MAX_ZOOM     = 3.0
BOX_COLOR    = (0,  180,  80)
POINT_COLOR  = (0,  120, 255)
ACTIVE_COLOR = (0,  120, 255)
DONE_COLOR   = (50, 200,  50)

WINDOW_BBOX  = (
    "PaperTrail Calibration [BOX]  "
    "|  Drag=Draw  R=Undo  S=Save  Z=ZoomIn  X=ZoomOut  Q=Quit"
)
WINDOW_POINT = (
    "PaperTrail Calibration [POINT]  "
    "|  Click=Mark  R=Undo  S=Save  Z=ZoomIn  X=ZoomOut  Q=Quit"
)

MARK_TYPES = [
    "circled_number",
    "filled_bubble",
    "x_mark",
    "circled_bubble",
    "shaded_box",
    "checkmark",
]

FIELD_TYPES = [
    "likert",
    "categorical",
    "multi_select",
    "open_text",
]

# Radius of the dot drawn on the image for center-point marks
POINT_RADIUS = 8


# ── Global state ──────────────────────────────────────────────────────────────

state = {
    "mode":        "bbox",   # 'bbox' or 'point'
    "drawing":     False,    # bbox only: mid-drag flag
    "start":       (0, 0),   # bbox only: drag start
    "end":         (0, 0),   # bbox only: drag end
    "regions":     [],       # accumulated region records
    "field_index": 0,        # next field to calibrate
    "fields":      [],       # full list of (field_id, value) tuples
    "zoom":        1.0,
    "image":       None,
}


# ── Mouse callback ────────────────────────────────────────────────────────────

def _mouse_callback(event, x, y, flags, param):
    """Handle mouse events for both bounding box and center-point modes."""
    ox = int(x / state["zoom"])
    oy = int(y / state["zoom"])

    if state["mode"] == "point":
        _handle_point_click(event, ox, oy)
    else:
        _handle_bbox_drag(event, ox, oy)


def _handle_point_click(event, ox: int, oy: int) -> None:
    """Record a single click as a center-point mark.

    Args:
        event: OpenCV mouse event code.
        ox:    Click x in original image coordinates.
        oy:    Click y in original image coordinates.
    """
    if event == cv2.EVENT_LBUTTONUP:
        _record_point(ox, oy)
        _show()


def _handle_bbox_drag(event, ox: int, oy: int) -> None:
    """Handle click-and-drag to define a bounding box region.

    Args:
        event: OpenCV mouse event code.
        ox:    Mouse x in original image coordinates.
        oy:    Mouse y in original image coordinates.
    """
    if event == cv2.EVENT_LBUTTONDOWN:
        state["drawing"] = True
        state["start"]   = (ox, oy)
        state["end"]     = (ox, oy)

    elif event == cv2.EVENT_MOUSEMOVE and state["drawing"]:
        state["end"] = (ox, oy)
        _show()

    elif event == cv2.EVENT_LBUTTONUP and state["drawing"]:
        state["drawing"] = False
        state["end"]     = (ox, oy)
        x1 = min(state["start"][0], state["end"][0])
        y1 = min(state["start"][1], state["end"][1])
        x2 = max(state["start"][0], state["end"][0])
        y2 = max(state["start"][1], state["end"][1])
        if (x2 - x1) > 10 and (y2 - y1) > 10:
            _record_bbox(x1, y1, x2 - x1, y2 - y1)
        _show()


# ── Region recording ──────────────────────────────────────────────────────────

def _record_point(x: int, y: int) -> None:
    """Save a center-point click and advance to the next field.

    Args:
        x: Click x in original image coordinates.
        y: Click y in original image coordinates.
    """
    idx = state["field_index"]
    if idx >= len(state["fields"]):
        print("  All regions recorded.")
        return

    field = state["fields"][idx]
    state["regions"].append({
        "field_id": field["field_id"],
        "value":    field["value"],
        "x": x,
        "y": y,
        # No w or h — triggers proximity detection path
    })

    print(f"  +  {field['field_id']} = {field['value']}"
          f"   center: ({x}, {y})")

    _advance_field_index()


def _record_bbox(x: int, y: int, w: int, h: int) -> None:
    """Save a bounding box and advance to the next field.

    Args:
        x: Box left edge in original image coordinates.
        y: Box top edge in original image coordinates.
        w: Box width in pixels.
        h: Box height in pixels.
    """
    idx = state["field_index"]
    if idx >= len(state["fields"]):
        print("  All regions recorded.")
        return

    field = state["fields"][idx]
    state["regions"].append({
        "field_id": field["field_id"],
        "value":    field["value"],
        "x": x, "y": y, "w": w, "h": h,
    })

    print(f"  +  {field['field_id']} = {field['value']}"
          f"   x:{x} y:{y} w:{w} h:{h}")

    _advance_field_index()


def _advance_field_index() -> None:
    """Increment field index and print the next prompt."""
    state["field_index"] += 1
    remaining = len(state["fields"]) - state["field_index"]

    if state["field_index"] < len(state["fields"]):
        nxt = state["fields"][state["field_index"]]
        print(f"  -> Next:  {nxt['field_id']} = {nxt['value']}"
              f"  ({remaining} left)")
    else:
        print("\n  All regions recorded — saving automatically...")


# ── Display ───────────────────────────────────────────────────────────────────

def _show() -> None:
    """Redraw the window with all recorded region overlays."""
    img = state["image"].copy()

    for region in state["regions"]:
        if "w" in region and "h" in region:
            _draw_bbox_overlay(img, region)
        else:
            _draw_point_overlay(img, region)

    if state["mode"] == "bbox" and state["drawing"]:
        x1 = min(state["start"][0], state["end"][0])
        y1 = min(state["start"][1], state["end"][1])
        x2 = max(state["start"][0], state["end"][0])
        y2 = max(state["start"][1], state["end"][1])
        cv2.rectangle(img, (x1, y1), (x2, y2), ACTIVE_COLOR, 2)

    _draw_status_bar(img)

    if state["zoom"] != 1.0:
        nw = int(img.shape[1] * state["zoom"])
        nh = int(img.shape[0] * state["zoom"])
        img = cv2.resize(img, (nw, nh),
                         interpolation=cv2.INTER_LINEAR)

    window = (WINDOW_POINT if state["mode"] == "point"
              else WINDOW_BBOX)
    cv2.imshow(window, img)


def _draw_bbox_overlay(img: np.ndarray, region: dict) -> None:
    """Draw a bounding box overlay on the image.

    Args:
        img:    Image to draw on (modified in place).
        region: Region dict with x, y, w, h, field_id, value.
    """
    rx, ry, rw, rh = (region["x"], region["y"],
                      region["w"], region["h"])
    cv2.rectangle(img, (rx, ry), (rx + rw, ry + rh),
                  BOX_COLOR, 2)
    cv2.putText(img,
                f"{region['field_id']}={region['value']}",
                (rx, ry - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, BOX_COLOR, 1)


def _draw_point_overlay(img: np.ndarray, region: dict) -> None:
    """Draw a center-point dot overlay on the image.

    Args:
        img:    Image to draw on (modified in place).
        region: Region dict with x, y, field_id, value.
    """
    cx, cy = region["x"], region["y"]
    cv2.circle(img, (cx, cy), POINT_RADIUS, POINT_COLOR, -1)
    cv2.circle(img, (cx, cy), POINT_RADIUS + 2, DONE_COLOR, 2)
    cv2.putText(img,
                f"{region['field_id']}={region['value']}",
                (cx + POINT_RADIUS + 4, cy + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, POINT_COLOR, 1)


def _draw_status_bar(img: np.ndarray) -> None:
    """Draw the instruction bar at the top of the image.

    Args:
        img: Image to draw on (modified in place).
    """
    idx = state["field_index"]

    if idx < len(state["fields"]):
        f   = state["fields"][idx]
        rem = len(state["fields"]) - idx
        if state["mode"] == "point":
            msg = (f"Click center of:  "
                   f"{f['field_id']} = {f['value']}"
                   f"   ({rem} remaining)")
        else:
            msg = (f"Draw box around:  "
                   f"{f['field_id']} = {f['value']}"
                   f"   ({rem} remaining)")
    else:
        msg = "All done! Saving automatically..."

    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (img.shape[1], 48),
                  (230, 230, 230), -1)
    cv2.addWeighted(overlay, 0.7, img, 0.3, 0, img)
    cv2.putText(img, msg, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 80, 0), 2)


# ── YAML helpers ──────────────────────────────────────────────────────────────

def _load_yaml(yaml_path: str) -> dict:
    """Load existing YAML or return empty dict.

    Args:
        yaml_path: Path to the YAML file.

    Returns:
        Parsed YAML as dict, or empty dict if not found.
    """
    if not os.path.exists(yaml_path):
        return {}
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(yaml_path: str, data: dict) -> None:
    """Save data to YAML file.

    Args:
        yaml_path: Path to write.
        data:      Dict to serialize.
    """
    os.makedirs(os.path.dirname(yaml_path), exist_ok=True)
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f,
                  default_flow_style=False,
                  sort_keys=False,
                  allow_unicode=True)


def _clean_incomplete_fields(existing: dict) -> dict:
    """Remove fields that have no qualtrics_id.

    Leftover from incomplete calibration runs. Safe to remove
    because they cannot be used by the pipeline.

    Args:
        existing: Parsed YAML dict.

    Returns:
        Cleaned dict with incomplete fields removed.
    """
    if "fields" not in existing:
        return existing

    before = len(existing["fields"])
    existing["fields"] = [
        f for f in existing["fields"]
        if f.get("qualtrics_id", "").strip()
    ]
    after = len(existing["fields"])

    if before != after:
        print(f"  Removed {before - after} incomplete "
              f"field(s) from previous calibration.\n")

    return existing


def _check_duplicate_prefix(existing: dict,
                             prefix: str) -> bool:
    """Check if fields with this prefix already exist in YAML.

    Args:
        existing: Parsed YAML dict.
        prefix:   Field ID prefix to check (e.g. S1_Q).

    Returns:
        True if matching fields already exist.
    """
    fields = existing.get("fields", [])
    return any(
        f.get("paper_id", "").startswith(prefix)
        for f in fields
    )


def _ask_duplicate_action(prefix: str) -> str:
    """Ask user what to do when duplicate fields are detected.

    Args:
        prefix: The duplicate field prefix found.

    Returns:
        'replace' or 'skip'.
    """
    print(f"\n  Fields with prefix '{prefix}' already exist.")
    print(f"    1. Replace them (re-calibrate this page)")
    print(f"    2. Skip (keep existing, exit tool)")

    while True:
        choice = input("  Enter 1 or 2: ").strip()
        if choice == "1":
            return "replace"
        elif choice == "2":
            return "skip"
        print("  Please enter 1 or 2.")


# ── Save to YAML ──────────────────────────────────────────────────────────────

def _save(survey_name: str, field_meta: dict) -> None:
    """Write all recorded regions and metadata to the survey YAML.

    Merges new fields into existing YAML. Bounding box regions
    include x, y, w, h. Center-point regions include only x, y.
    The detection path is always determined by the YAML format.

    Args:
        survey_name: Survey ID for the YAML filename.
        field_meta:  Dict mapping field_id -> metadata dict.
    """
    yaml_path = os.path.join("config", "surveys",
                             f"{survey_name}.yaml")
    existing  = _load_yaml(yaml_path)

    if "fields" not in existing:
        existing["fields"] = []

    by_field = _group_regions_by_field(state["regions"])

    for fid, regions in by_field.items():
        meta     = field_meta.get(fid, {})
        complete = _build_field_entry(fid, regions, meta)
        _upsert_field(existing["fields"], complete)

    _save_yaml(yaml_path, existing)
    print(f"\n  Saved  ->  {yaml_path}")
    print(f"  {len(state['regions'])} region(s) written")
    print(f"  {len(by_field)} field(s) added/updated")
    _print_path_summary(by_field)


def _group_regions_by_field(regions: list) -> dict:
    """Group recorded regions by field_id.

    Args:
        regions: List of region dicts from state["regions"].

    Returns:
        Dict mapping field_id -> {value: region_dict}.
    """
    by_field = {}
    for r in regions:
        fid = r["field_id"]
        if fid not in by_field:
            by_field[fid] = {}

        if "w" in r and "h" in r:
            by_field[fid][str(r["value"])] = {
                "x": int(r["x"]),
                "y": int(r["y"]),
                "w": int(r["w"]),
                "h": int(r["h"]),
            }
        else:
            by_field[fid][str(r["value"])] = {
                "x": int(r["x"]),
                "y": int(r["y"]),
            }

    return by_field


def _build_field_entry(fid: str,
                        regions: dict,
                        meta: dict) -> dict:
    """Build a complete field dict for the survey YAML.

    Args:
        fid:     Field paper_id.
        regions: Dict mapping value -> region coord dict.
        meta:    Metadata dict from interactive setup.

    Returns:
        Complete field dict ready to write to YAML.
    """
    return {
        "paper_id":     fid,
        "qualtrics_id": meta.get("qualtrics_id", ""),
        "label":        meta.get("label", ""),
        "type":         meta.get("field_type", "likert"),
        "mark_type":    meta.get("mark_type", "circled_number"),
        "scale":        meta.get("scale", [1, 2, 3, 4]),
        "page":         meta.get("page", 1),
        "required":     True,
        "regions":      regions,
    }


def _upsert_field(fields: list, complete: dict) -> None:
    """Replace an existing field entry or append a new one.

    Args:
        fields:   List of field dicts (modified in place).
        complete: New or updated field dict.
    """
    for i, entry in enumerate(fields):
        if entry.get("paper_id") == complete["paper_id"]:
            fields[i] = complete
            return
    fields.append(complete)


def _print_path_summary(by_field: dict) -> None:
    """Print which detection path each field will use.

    Args:
        by_field: Dict mapping field_id -> regions dict.
    """
    for fid, regions in by_field.items():
        sample = next(iter(regions.values()), {})
        path   = "proximity" if "w" not in sample else "bbox"
        print(f"  {fid:<16}  detection path: {path}")


# ── Interactive setup ─────────────────────────────────────────────────────────

def _ask_calibration_mode() -> str:
    """Ask which calibration mode to use for this field group.

    Center-point mode (single click) triggers the proximity
    detection path, which is robust to any mark size or circle
    drawn by a respondent. Bounding box mode is retained as
    an option for surveys where it works correctly.

    Returns:
        'point' for center-point mode, 'bbox' for bounding box.
    """
    print("\n  Which calibration mode for this field group?")
    print("    1. Center-point  (recommended — single click per")
    print("                      option, robust to any mark size)")
    print("    2. Bounding box  (click and drag — original mode)")

    while True:
        choice = input("  Enter 1 or 2 (default 1): ").strip()
        if choice in ("", "1"):
            print("  Mode: center-point")
            return "point"
        elif choice == "2":
            print("  Mode: bounding box")
            return "bbox"
        print("  Please enter 1 or 2.")


def _ask_mark_type() -> str:
    """Ask which mark type this field group uses.

    Returns:
        Selected mark type string.
    """
    print("\n  What mark type does this section use?")
    for i, mt in enumerate(MARK_TYPES, 1):
        print(f"    {i}. {mt}")

    while True:
        try:
            choice = int(input("  Enter number: ").strip())
            if 1 <= choice <= len(MARK_TYPES):
                selected = MARK_TYPES[choice - 1]
                print(f"  Mark type: {selected}")
                return selected
        except ValueError:
            pass
        print(f"  Please enter 1 to {len(MARK_TYPES)}")


def _ask_field_type() -> str:
    """Ask which field type this section uses.

    Returns:
        Selected field type string.
    """
    print("\n  What field type is this section?")
    for i, ft in enumerate(FIELD_TYPES, 1):
        print(f"    {i}. {ft}")

    while True:
        try:
            choice = int(input("  Enter number: ").strip())
            if 1 <= choice <= len(FIELD_TYPES):
                selected = FIELD_TYPES[choice - 1]
                print(f"  Field type: {selected}")
                return selected
        except ValueError:
            pass
        print(f"  Please enter 1 to {len(FIELD_TYPES)}")


def _ask_page_number(image_path: str) -> int:
    """Ask which page number this image represents.

    Infers a default from the image filename
    (e.g. _page08.jpg -> 8). Page number is stored per-field
    in the YAML so extractor.py routes each field to the
    correct processed image for that respondent.

    Args:
        image_path: Path to the image being calibrated.

    Returns:
        Page number as integer (1-based).
    """
    basename = os.path.basename(image_path)
    match    = re.search(r'_page(\d+)', basename)
    default  = int(match.group(1)) if match else 1

    print(f"\n  Which page number is this image?")
    print(f"  (Must match page number in YAML — extractor.py")
    print(f"  uses this to read the correct image per field.)")

    while True:
        raw = input(
            f"  Page number (default {default}): "
        ).strip()
        if not raw:
            print(f"  Page: {default}")
            return default
        try:
            page = int(raw)
            if page >= 1:
                print(f"  Page: {page}")
                return page
        except ValueError:
            pass
        print("  Please enter a whole number (e.g. 1, 2, 8)")


def _ask_qualtrics_ids(field_ids: list) -> dict:
    """Ask for the Qualtrics column ID for each field.

    Args:
        field_ids: List of paper field ID strings.

    Returns:
        Dict mapping field_id -> qualtrics_id string.
    """
    print("\n  Enter the Qualtrics column ID for each field.")
    print("  Open your Qualtrics template and look at Row 1.")
    print("  Example: Q2.1_1, Q3.1_1, Q8.2 etc.\n")

    mapping = {}
    for fid in field_ids:
        qid = input(f"  {fid} -> Qualtrics ID: ").strip()
        mapping[fid] = qid

    return mapping


def _build_fields(survey_name: str,
                  yaml_path:   str,
                  existing:    dict,
                  image_path:  str) -> tuple:
    """Collect all metadata and build the field list interactively.

    Handles duplicate detection, mode selection, and page number.
    Returns None if the user chose to skip.

    Args:
        survey_name: Survey ID.
        yaml_path:   Path to the YAML file.
        existing:    Current parsed YAML dict.
        image_path:  Path to the image being calibrated.

    Returns:
        Tuple of (fields list, field_meta dict, mode string).
        Returns (None, None, None) if user chose to skip.
    """
    params = _ask_field_group_params()
    scale, mark_type, field_type = (
        params["scale"], params["mark_type"], params["field_type"]
    )
    prefix, start_num = params["prefix"], params["start_num"]

    if _check_duplicate_prefix(existing, prefix):
        action = _ask_duplicate_action(prefix)
        if action == "skip":
            print(f"\n  Keeping existing '{prefix}' fields.")
            return None, None, None
        existing["fields"] = [
            f for f in existing.get("fields", [])
            if not f.get("paper_id", "").startswith(prefix)
        ]
        print(f"  Existing '{prefix}' fields removed.")

    page_number   = _ask_page_number(image_path)
    mode          = _ask_calibration_mode()
    field_ids     = _populate_state_fields(
        prefix, start_num, params["n"], scale
    )
    qualtrics_ids = _ask_qualtrics_ids(field_ids)
    field_meta    = _build_field_meta(
        field_ids, qualtrics_ids,
        field_type, mark_type, scale, page_number
    )
    return state["fields"], field_meta, mode


def _build_field_meta(field_ids: list,
                       qualtrics_ids: dict,
                       field_type: str,
                       mark_type: str,
                       scale: list,
                       page_number: int) -> dict:
    """Build the field_meta dict mapping each field_id to its metadata.

    Args:
        field_ids:     List of paper field ID strings.
        qualtrics_ids: Dict mapping field_id -> qualtrics_id string.
        field_type:    Field type string (likert, categorical, etc.).
        mark_type:     Mark type string (circled_number, etc.).
        scale:         List of answer value strings.
        page_number:   Page number this field group belongs to.

    Returns:
        Dict mapping field_id -> metadata dict.
    """
    coerced_scale = [
        int(v) if v.isdigit() else v
        for v in scale
    ]
    return {
        fid: {
            "qualtrics_id": qualtrics_ids.get(fid, ""),
            "field_type":   field_type,
            "mark_type":    mark_type,
            "scale":        coerced_scale,
            "page":         page_number,
        }
        for fid in field_ids
    }


def _ask_field_group_params() -> dict:
    """Ask all scalar setup questions for a field group.

    Returns:
        Dict with keys: n, scale, mark_type, field_type,
        prefix, start_num.
    """
    n   = int(input("\n  How many questions does this page have? "))
    raw = input(
        "  What are the answer values? "
        "(e.g. 1,2,3,4 or 1,2,3,4,5): "
    ).strip()
    scale      = [s.strip() for s in raw.split(",")]
    mark_type  = _ask_mark_type()
    field_type = _ask_field_type()

    print(f"\n  What prefix should field IDs use?")
    print(f"  Examples: S1_Q (gives S1_Q1, S1_Q2...)")
    prefix = input("  Prefix: ").strip() or "Q"

    try:
        start_num = int(
            input("  Start numbering from? (default 1): ").strip()
            or "1"
        )
    except ValueError:
        start_num = 1

    return {
        "n":          n,
        "scale":      scale,
        "mark_type":  mark_type,
        "field_type": field_type,
        "prefix":     prefix,
        "start_num":  start_num,
    }


def _populate_state_fields(prefix: str,
                            start_num: int,
                            n: int,
                            scale: list) -> list:
    """Populate state['fields'] with all (field_id, value) tuples.

    Args:
        prefix:    Field ID prefix string.
        start_num: Starting question number.
        n:         Number of questions.
        scale:     List of answer value strings.

    Returns:
        List of field_id strings (one per question, not per option).
    """
    field_ids = []
    for i in range(start_num, start_num + n):
        fid = f"{prefix}{i}"
        field_ids.append(fid)
        for v in scale:
            state["fields"].append({
                "field_id": fid,
                "value":    v,
            })
    return field_ids


# ── Main calibration loop ─────────────────────────────────────────────────────

def run_calibration(image_path: str, survey_name: str) -> None:
    """Open the calibration window and record answer regions.

    Args:
        image_path:  Path to the processed survey image.
        survey_name: Survey ID used to locate the YAML file.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    img, existing, yaml_path = _load_calibration_assets(
        image_path, survey_name
    )

    state["fields"] = []
    fields, field_meta, mode = _build_fields(
        survey_name, yaml_path, existing, image_path
    )

    if fields is None:
        print("\n  Nothing to calibrate. Exiting.")
        return
    if not fields:
        print("  No fields defined. Exiting.")
        return

    _save_yaml(yaml_path, existing)
    _init_window_state(img, mode)
    _print_calibration_start(fields, mode)

    window = WINDOW_POINT if mode == "point" else WINDOW_BBOX
    h, w   = img.shape[:2]
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, min(w, 1200), min(h, 900))
    cv2.setMouseCallback(window, _mouse_callback)
    _show()

    _run_event_loop(survey_name, field_meta, window)
    cv2.destroyAllWindows()


def _load_calibration_assets(image_path: str,
                              survey_name: str) -> tuple:
    """Load and validate the image and existing YAML for calibration.

    Args:
        image_path:  Path to the processed survey image.
        survey_name: Survey ID used to locate the YAML file.

    Returns:
        Tuple of (img array, existing YAML dict, yaml_path string).
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not load: {image_path}")

    h, w = img.shape[:2]
    print("\n" + "=" * 60)
    print("  PaperTrail — Survey Calibration Tool")
    print("=" * 60)
    print(f"  Survey : {survey_name}")
    print(f"  Image  : {image_path}")
    print(f"  Size   : {w} x {h} px")

    yaml_path = os.path.join("config", "surveys",
                             f"{survey_name}.yaml")
    existing  = _load_yaml(yaml_path)
    existing  = _clean_incomplete_fields(existing)

    existing_count = len(existing.get("fields", []))
    if existing_count > 0:
        print(f"  Existing fields in YAML: {existing_count}")

    return img, existing, yaml_path


def _init_window_state(img: np.ndarray, mode: str) -> None:
    """Initialise global state for a new calibration session.

    Args:
        img:  Survey image array.
        mode: Calibration mode — 'point' or 'bbox'.
    """
    state["image"]       = img
    state["field_index"] = 0
    state["regions"]     = []
    state["zoom"]        = 1.0
    state["mode"]        = mode


def _print_calibration_start(fields: list, mode: str) -> None:
    """Print the opening instruction for the calibration session.

    Args:
        fields: Full list of (field_id, value) dicts to calibrate.
        mode:   Calibration mode — 'point' or 'bbox'.
    """
    first       = fields[0]
    mode_label  = ("center-point (click)"
                   if mode == "point" else "bounding box (drag)")
    action_verb = "Click the CENTER of" if mode == "point" else "Draw a box around"

    print(f"\n  {len(fields)} region(s) to calibrate")
    print(f"  Mode: {mode_label}")
    print(f"  {action_verb}:  "
          f"{first['field_id']} = {first['value']}\n")


def _run_event_loop(survey_name: str,
                    field_meta:  dict,
                    window:      str) -> None:
    """Run the keyboard/window event loop until done or quit.

    Args:
        survey_name: Survey ID for YAML save path.
        field_meta:  Dict mapping field_id -> metadata dict.
        window:      OpenCV window name to watch.
    """
    while True:
        key = cv2.waitKey(20) & 0xFF

        if (state["field_index"] >= len(state["fields"])
                and state["regions"]):
            _save(survey_name, field_meta)
            break

        if _window_was_closed(window):
            if state["regions"]:
                print("\n  Window closed — saving...")
                _save(survey_name, field_meta)
            else:
                print("\n  Window closed — nothing saved.")
            break

        if key == ord("q"):
            print("\n  Quit — nothing saved.")
            break
        elif key in (ord("s"), 13):
            _handle_save_key(survey_name, field_meta)
            break
        elif key == ord("r"):
            _undo_last_region()
        elif key == ord("z"):
            state["zoom"] = min(MAX_ZOOM,
                                state["zoom"] + ZOOM_STEP)
            print(f"  Zoom: {state['zoom']:.1f}x")
            _show()
        elif key == ord("x"):
            state["zoom"] = max(MIN_ZOOM,
                                state["zoom"] - ZOOM_STEP)
            print(f"  Zoom: {state['zoom']:.1f}x")
            _show()


def _window_was_closed(window: str) -> bool:
    """Check whether the OpenCV window has been closed.

    Args:
        window: OpenCV window name.

    Returns:
        True if the window is no longer visible.
    """
    try:
        visible = cv2.getWindowProperty(
            window, cv2.WND_PROP_VISIBLE)
        return visible < 1
    except cv2.error:
        return True


def _handle_save_key(survey_name: str,
                      field_meta: dict) -> None:
    """Handle S or Enter key press during calibration.

    Args:
        survey_name: Survey ID for YAML save path.
        field_meta:  Dict mapping field_id -> metadata dict.
    """
    if state["regions"]:
        _save(survey_name, field_meta)
    else:
        print("  Nothing to save yet.")


def _undo_last_region() -> None:
    """Remove the most recently recorded region and step back."""
    if state["regions"]:
        removed = state["regions"].pop()
        state["field_index"] = max(0, state["field_index"] - 1)
        print(f"  Undid: "
              f"{removed['field_id']} = {removed['value']}")
        _show()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "PaperTrail calibration — mark answer regions on a "
            "survey image to record coordinates. Supports "
            "center-point mode (proximity detection) and "
            "bounding box mode (original detection)."
        )
    )
    parser.add_argument("--image",  required=True,
                        help="Path to processed survey image")
    parser.add_argument("--survey", required=True,
                        help="Survey name for the YAML config")
    args = parser.parse_args()
    run_calibration(args.image, args.survey)
