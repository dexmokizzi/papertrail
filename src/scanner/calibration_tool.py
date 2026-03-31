"""
Survey calibration tool for PaperTrail.

Opens a processed survey image in an interactive window.
You click and drag to draw a box around each answer region.
The tool records the coordinates AND all field metadata,
then writes a complete survey YAML automatically.

No manual YAML editing required after calibration.

Features:
- Auto-saves when all regions are recorded
- Auto-saves when window is closed
- Detects duplicate pages and asks before overwriting
- Cleans incomplete fields from previous runs
- Writes complete field definitions including qualtrics_id,
  type, mark_type, scale, and regions

Usage:
    python -m src.scanner.calibration_tool
        --image data/processed/your_scan.jpg
        --survey your_survey_name

Controls:
    Click + drag  ->  Draw a region box
    R             ->  Undo last region
    S or Enter    ->  Save and exit
    Q             ->  Quit without saving
    Z             ->  Zoom in
    X             ->  Zoom out
"""

import os
import cv2
import yaml
import argparse
import numpy as np


# ── Constants ─────────────────────────────────────────────────────────────────

ZOOM_STEP    = 0.2
MIN_ZOOM     = 0.3
MAX_ZOOM     = 3.0
BOX_COLOR    = (0, 180, 80)
ACTIVE_COLOR = (0, 120, 255)
WINDOW_NAME  = "PaperTrail Calibration  |  S=Save  R=Undo  Z=ZoomIn  X=ZoomOut  Q=Quit"

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


# ── Global state ──────────────────────────────────────────────────────────────

state = {
    "drawing":     False,
    "start":       (0, 0),
    "end":         (0, 0),
    "regions":     [],
    "field_index": 0,
    "fields":      [],
    "zoom":        1.0,
    "image":       None,
}


# ── Mouse callback ────────────────────────────────────────────────────────────

def _mouse_callback(event, x, y, flags, param):
    """Handle mouse click-and-drag to define answer regions."""
    ox = int(x / state["zoom"])
    oy = int(y / state["zoom"])

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
            _record(x1, y1, x2 - x1, y2 - y1)

        _show()


# ── Record a region ───────────────────────────────────────────────────────────

def _record(x, y, w, h):
    """Save a completed region and advance to the next field."""
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

    state["field_index"] += 1
    remaining = len(state["fields"]) - state["field_index"]

    if state["field_index"] < len(state["fields"]):
        nxt = state["fields"][state["field_index"]]
        print(f"  -> Draw box around:  "
              f"{nxt['field_id']} = {nxt['value']}"
              f"  ({remaining} left)")
    else:
        print("\n  All regions recorded — saving automatically...")


# ── Display ───────────────────────────────────────────────────────────────────

def _show():
    """Redraw the window with all region overlays."""
    img = state["image"].copy()

    for region in state["regions"]:
        rx, ry, rw, rh = (region["x"], region["y"],
                          region["w"], region["h"])
        cv2.rectangle(img, (rx, ry), (rx + rw, ry + rh),
                      BOX_COLOR, 2)
        cv2.putText(img,
                    f"{region['field_id']}={region['value']}",
                    (rx, ry - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    BOX_COLOR, 1)

    if state["drawing"]:
        x1 = min(state["start"][0], state["end"][0])
        y1 = min(state["start"][1], state["end"][1])
        x2 = max(state["start"][0], state["end"][0])
        y2 = max(state["start"][1], state["end"][1])
        cv2.rectangle(img, (x1, y1), (x2, y2), ACTIVE_COLOR, 2)

    idx = state["field_index"]
    if idx < len(state["fields"]):
        f   = state["fields"][idx]
        rem = len(state["fields"]) - idx
        msg = (f"Draw box around:  {f['field_id']} = {f['value']}"
               f"   ({rem} remaining)")
    else:
        msg = "All done! Saving automatically..."

    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (img.shape[1], 48),
                  (230, 230, 230), -1)
    cv2.addWeighted(overlay, 0.7, img, 0.3, 0, img)
    cv2.putText(img, msg, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 80, 0), 2)

    if state["zoom"] != 1.0:
        nw = int(img.shape[1] * state["zoom"])
        nh = int(img.shape[0] * state["zoom"])
        img = cv2.resize(img, (nw, nh),
                         interpolation=cv2.INTER_LINEAR)

    cv2.imshow(WINDOW_NAME, img)


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

    These are leftover from previous incomplete calibration
    runs that did not use the full tool. Safe to remove
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


def _check_duplicate_prefix(
    existing: dict,
    prefix:   str,
) -> bool:
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
    print(f"\n  Fields with prefix '{prefix}' already exist "
          f"in the YAML.")
    print(f"  What would you like to do?")
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

def _save(survey_name: str, field_meta: dict):
    """Write all recorded regions and metadata to the survey YAML.

    Merges new fields into existing YAML. Handles duplicates
    by replacing existing fields with the same paper_id.

    Args:
        survey_name: Survey ID for the YAML filename.
        field_meta:  Dict mapping field_id -> metadata dict.
    """
    yaml_path = os.path.join("config", "surveys",
                             f"{survey_name}.yaml")

    existing = _load_yaml(yaml_path)

    if "fields" not in existing:
        existing["fields"] = []

    # Group regions by field_id
    by_field = {}
    for r in state["regions"]:
        fid = r["field_id"]
        if fid not in by_field:
            by_field[fid] = {}
        by_field[fid][str(r["value"])] = {
            "x": int(r["x"]),
            "y": int(r["y"]),
            "w": int(r["w"]),
            "h": int(r["h"]),
        }

    for fid, regions in by_field.items():
        meta = field_meta.get(fid, {})

        complete = {
            "paper_id":     fid,
            "qualtrics_id": meta.get("qualtrics_id", ""),
            "label":        meta.get("label", ""),
            "type":         meta.get("field_type", "likert"),
            "mark_type":    meta.get("mark_type",
                                     "circled_number"),
            "scale":        meta.get("scale", [1, 2, 3, 4]),
            "required":     True,
            "regions":      regions,
        }

        # Replace existing entry or append new one
        replaced = False
        for i, entry in enumerate(existing["fields"]):
            if entry.get("paper_id") == fid:
                existing["fields"][i] = complete
                replaced = True
                break

        if not replaced:
            existing["fields"].append(complete)

    _save_yaml(yaml_path, existing)

    print(f"\n  Saved  ->  {yaml_path}")
    print(f"  {len(state['regions'])} region(s) written")
    print(f"  {len(by_field)} field(s) added/updated")


# ── Interactive setup ─────────────────────────────────────────────────────────

def _ask_mark_type() -> str:
    """Ask which mark type this section uses."""
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
    """Ask which field type this section uses."""
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


def _ask_qualtrics_ids(field_ids: list) -> dict:
    """Ask for the Qualtrics column ID for each field."""
    print("\n  Enter the Qualtrics column ID for each field.")
    print("  Open your Qualtrics template and look at Row 1.")
    print("  Example: Q2.1_1, Q3.1_1, Q8.2 etc.\n")

    mapping = {}
    for fid in field_ids:
        qid = input(f"  {fid} -> Qualtrics ID: ").strip()
        mapping[fid] = qid

    return mapping


def _build_fields(
    survey_name: str,
    yaml_path:   str,
    existing:    dict,
) -> tuple:
    """Build field list and collect all metadata interactively.

    Handles duplicate detection and asks user what to do.
    Returns None if user chose to skip.

    Args:
        survey_name: Survey ID.
        yaml_path:   Path to the YAML file.
        existing:    Current parsed YAML dict.

    Returns:
        Tuple of (fields list, field_meta dict).
        Returns (None, None) if user chose to skip.
    """
    # Ask how many questions
    n = int(input("\n  How many questions does this page have? "))

    # Ask answer values
    raw = input(
        "  What are the answer values? "
        "(e.g. 1,2,3,4 or 1,2,3,4,5): "
    ).strip()
    scale = [s.strip() for s in raw.split(",")]

    # Ask mark type
    mark_type = _ask_mark_type()

    # Ask field type
    field_type = _ask_field_type()

    # Ask prefix
    print(f"\n  What prefix should field IDs use?")
    print(f"  Examples: S1_Q (gives S1_Q1, S1_Q2...)")
    print(f"            S2_Q (gives S2_Q1, S2_Q2...)")
    prefix = input("  Prefix: ").strip() or "Q"

    # Ask starting number
    try:
        start_num = int(input(
            "  Start numbering from? (default 1): "
        ).strip() or "1")
    except ValueError:
        start_num = 1

    # Check for duplicates
    if _check_duplicate_prefix(existing, prefix):
        action = _ask_duplicate_action(prefix)
        if action == "skip":
            print(f"\n  Keeping existing '{prefix}' fields.")
            return None, None
        elif action == "replace":
            # Remove existing fields with this prefix
            existing["fields"] = [
                f for f in existing.get("fields", [])
                if not f.get("paper_id", "").startswith(prefix)
            ]
            print(f"  Existing '{prefix}' fields removed.")
            print(f"  Proceeding with fresh calibration.\n")

    # Build field list
    field_ids = []
    for i in range(start_num, start_num + n):
        fid = f"{prefix}{i}"
        field_ids.append(fid)
        for v in scale:
            state["fields"].append({
                "field_id": fid,
                "value":    v
            })

    # Ask Qualtrics column IDs
    qualtrics_ids = _ask_qualtrics_ids(field_ids)

    # Build metadata per field
    field_meta = {}
    for fid in field_ids:
        field_meta[fid] = {
            "qualtrics_id": qualtrics_ids.get(fid, ""),
            "field_type":   field_type,
            "mark_type":    mark_type,
            "scale":        [
                int(v) if v.isdigit() else v
                for v in scale
            ],
        }

    return state["fields"], field_meta


# ── Main ──────────────────────────────────────────────────────────────────────

def run_calibration(image_path: str, survey_name: str):
    """Open the calibration window and record answer regions."""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    print("\n" + "=" * 60)
    print("  PaperTrail — Survey Calibration Tool")
    print("=" * 60)
    print(f"  Survey : {survey_name}")
    print(f"  Image  : {image_path}")

    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not load: {image_path}")

    h, w = img.shape[:2]
    print(f"  Size   : {w} x {h} px")

    # Load and clean existing YAML
    yaml_path = os.path.join("config", "surveys",
                             f"{survey_name}.yaml")
    existing  = _load_yaml(yaml_path)
    existing  = _clean_incomplete_fields(existing)

    # Show existing field count
    existing_count = len(existing.get("fields", []))
    if existing_count > 0:
        print(f"  Existing fields in YAML: {existing_count}")

    # Reset state fields
    state["fields"] = []

    # Interactive setup
    fields, field_meta = _build_fields(
        survey_name, yaml_path, existing
    )

    if fields is None:
        print("\n  Nothing to calibrate. Exiting.")
        return

    if not fields:
        print("  No fields defined. Exiting.")
        return

    # Save cleaned YAML before starting
    _save_yaml(yaml_path, existing)

    state["image"]       = img
    state["field_index"] = 0
    state["regions"]     = []
    state["zoom"]        = 1.0

    print(f"\n  {len(fields)} region(s) to calibrate")
    print(f"  Starting with: "
          f"{fields[0]['field_id']} = {fields[0]['value']}")
    print(f"  Draw a box around that answer option.\n")

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, min(w, 1200), min(h, 900))
    cv2.setMouseCallback(WINDOW_NAME, _mouse_callback)
    _show()

    while True:
        key = cv2.waitKey(20) & 0xFF

        # Auto-save when all regions are recorded
        if (state["field_index"] >= len(state["fields"])
                and state["regions"]):
            _save(survey_name, field_meta)
            cv2.destroyAllWindows()
            break

        # Window closed — auto-save
        try:
            visible = cv2.getWindowProperty(
                WINDOW_NAME, cv2.WND_PROP_VISIBLE)
            if visible < 1:
                if state["regions"]:
                    print("\n  Window closed — saving...")
                    _save(survey_name, field_meta)
                else:
                    print("\n  Window closed — nothing saved.")
                break
        except cv2.error:
            break

        if key == ord("q"):
            print("\n  Quit — nothing saved.")
            break

        elif key == ord("s") or key == 13:
            if state["regions"]:
                _save(survey_name, field_meta)
            else:
                print("  Nothing to save yet.")
            break

        elif key == ord("r"):
            if state["regions"]:
                removed = state["regions"].pop()
                state["field_index"] = max(
                    0, state["field_index"] - 1)
                print(f"  Undid: "
                      f"{removed['field_id']} = "
                      f"{removed['value']}")
                _show()

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

    cv2.destroyAllWindows()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="PaperTrail calibration — click regions "
                    "on a survey image to record coordinates."
    )
    parser.add_argument("--image",  required=True,
                        help="Path to processed survey image")
    parser.add_argument("--survey", required=True,
                        help="Survey name for the YAML config")
    args = parser.parse_args()
    run_calibration(args.image, args.survey)