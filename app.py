"""
PaperTrail — Phase 3 Streamlit review interface.

Lets non-technical staff run the pipeline, review flagged
fields with the scan visible alongside, enter corrections,
and download the final Qualtrics import file — all without
touching a terminal or editing a CSV directly.

This UI is a thin wrapper around the existing CLI pipeline.
It shells out to run_pipeline.py for every stage so the
underlying logic never has to be duplicated or re-implemented.

Run with:
    streamlit run app.py
"""

import os
import sys
import glob
import subprocess
from datetime import datetime

import cv2
import yaml
import numpy as np
import pandas as pd
import streamlit as st
from pdf2image import convert_from_path


# ── Paths ─────────────────────────────────────────────────────────────────────

SURVEYS_DIR    = "config/surveys"
SCANS_DIR      = "data/scans"
PROCESSED_DIR  = "data/processed"
FLAGGED_PATH   = "data/flagged/flagged_fields.csv"
OUTPUT_DIR     = "data/output"
REVIEW_CACHE   = "data/review_cache"


# ── Survey helpers ────────────────────────────────────────────────────────────

def list_surveys() -> list:
    """List all registered surveys from config/surveys/*.yaml.

    Returns:
        Sorted list of survey_id strings.
    """
    if not os.path.isdir(SURVEYS_DIR):
        return []
    files = glob.glob(os.path.join(SURVEYS_DIR, "*.yaml"))
    return sorted(os.path.splitext(os.path.basename(f))[0]
                  for f in files)


def load_survey_config(survey: str) -> dict:
    """Load a survey's YAML config.

    Args:
        survey: Survey name matching the YAML filename.

    Returns:
        Parsed YAML dict, or empty dict if not found.
    """
    path = os.path.join(SURVEYS_DIR, f"{survey}.yaml")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_field_lookup(survey_config: dict) -> dict:
    """Build a quick lookup from field_id to its YAML definition.

    Args:
        survey_config: Parsed survey YAML dict.

    Returns:
        Dict mapping paper_id -> field definition dict.
    """
    return {
        f.get("paper_id"): f
        for f in survey_config.get("fields", [])
        if f.get("paper_id")
    }


# ── Pipeline execution ────────────────────────────────────────────────────────

def run_pipeline_stage(survey: str, stage: str = "all") -> tuple:
    """Run a pipeline stage via subprocess and capture output.

    Shells out to the existing run_pipeline.py CLI so the UI
    never duplicates pipeline logic — it only triggers it.

    Args:
        survey: Survey name to process.
        stage:  Pipeline stage to run (default 'all').

    Returns:
        Tuple of (success: bool, output: str).
    """
    cmd = [
        sys.executable, "run_pipeline.py",
        "--survey", survey,
        "--stage", stage,
        "--operator", "streamlit_ui",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=600
    )
    output  = result.stdout + "\n" + result.stderr
    success = result.returncode == 0
    return success, output


def save_uploaded_files(survey: str, uploaded_files: list) -> int:
    """Save uploaded PDFs into the survey's scan folder.

    Args:
        survey:         Survey name.
        uploaded_files:  List of Streamlit UploadedFile objects.

    Returns:
        Number of files saved.
    """
    target_dir = os.path.join(SCANS_DIR, survey)
    os.makedirs(target_dir, exist_ok=True)

    count = 0
    for uploaded in uploaded_files:
        dest = os.path.join(target_dir, uploaded.name)
        with open(dest, "wb") as f:
            f.write(uploaded.getbuffer())
        count += 1
    return count


# ── Flagged fields handling ───────────────────────────────────────────────────

def load_flagged_fields() -> pd.DataFrame:
    """Load flagged_fields.csv with tolerant column naming.

    Different pipeline versions may name columns slightly
    differently. This normalises to a consistent set so the
    UI works regardless of which version produced the file.

    Returns:
        DataFrame with columns: form_id, field_id, raw_value,
        confidence, reason, corrected_value. Empty if no file.
    """
    if not os.path.exists(FLAGGED_PATH):
        return pd.DataFrame(columns=[
            "form_id", "field_id", "raw_value",
            "confidence", "reason", "corrected_value",
        ])

    df = pd.read_csv(FLAGGED_PATH, dtype=str).fillna("")

    rename_map = {
        "respondent_id":     "form_id",
        "value":             "raw_value",
        "raw_extracted_value": "raw_value",
        "flag_reason":       "reason",
        "flag":              "reason",
        "note":              "reason",
    }
    df = df.rename(columns={
        k: v for k, v in rename_map.items() if k in df.columns
    })

    for col in ["form_id", "field_id", "raw_value",
                "confidence", "reason", "corrected_value"]:
        if col not in df.columns:
            df[col] = ""

    return df


def save_flagged_fields(df: pd.DataFrame) -> None:
    """Write the flagged fields DataFrame back to disk.

    Args:
        df: DataFrame with corrections filled in.
    """
    os.makedirs(os.path.dirname(FLAGGED_PATH), exist_ok=True)
    df.to_csv(FLAGGED_PATH, index=False)


# ── Image retrieval for review ────────────────────────────────────────────────

def get_page_image(survey: str, form_id: str,
                    page_num: int) -> "np.ndarray | None":
    """Retrieve a page image for review, regenerating if needed.

    Checks data/processed/ first since that's fastest. If the
    file was already cleared by auto-clean on a later pipeline
    run, falls back to re-rendering just that page from the
    archived original PDF — cached afterward so it's only
    done once per page.

    Args:
        survey:   Survey name (used to find the archive folder).
        form_id:  Respondent identifier matching the scan filename.
        page_num: Page number to retrieve.

    Returns:
        Grayscale image array, or None if it cannot be found.
    """
    direct_path = os.path.join(
        PROCESSED_DIR, f"{form_id}_page{page_num:02d}.jpg"
    )
    if os.path.exists(direct_path):
        return cv2.imread(direct_path, cv2.IMREAD_GRAYSCALE)

    cache_path = os.path.join(
        REVIEW_CACHE, f"{form_id}_page{page_num:02d}.jpg"
    )
    if os.path.exists(cache_path):
        return cv2.imread(cache_path, cv2.IMREAD_GRAYSCALE)

    archive_pdf = os.path.join(
        SCANS_DIR, survey, "archive", f"{form_id}.pdf"
    )
    if not os.path.exists(archive_pdf):
        return None

    try:
        pages = convert_from_path(
            archive_pdf, dpi=300,
            first_page=page_num, last_page=page_num,
        )
    except Exception:
        return None

    if not pages:
        return None

    os.makedirs(REVIEW_CACHE, exist_ok=True)
    img = cv2.cvtColor(np.array(pages[0]), cv2.COLOR_RGB2GRAY)
    cv2.imwrite(cache_path, img)
    return img


def crop_field_region(image: np.ndarray, field: dict,
                       margin: int = 60) -> "np.ndarray | None":
    """Crop the area around a field's calibrated regions.

    Builds a bounding box around all declared option positions
    for this field plus a margin, so staff can see the full
    answer row — not just one isolated option.

    Args:
        image:  Full page image.
        field:  Field definition dict with a 'regions' key.
        margin: Extra pixels added on every side.

    Returns:
        Cropped image array, or None if regions are invalid.
    """
    regions = field.get("regions", {})
    xs, ys  = [], []

    for region in regions.values():
        if not isinstance(region, dict):
            continue
        x = region.get("x")
        y = region.get("y")
        w = region.get("w", 0)
        h = region.get("h", 0)
        if x is None or y is None:
            continue
        xs.extend([x, x + w])
        ys.extend([y, y + h])

    if not xs or not ys:
        return None

    img_h, img_w = image.shape[:2]
    x1 = max(0,      int(min(xs)) - margin)
    y1 = max(0,      int(min(ys)) - margin)
    x2 = min(img_w,  int(max(xs)) + margin)
    y2 = min(img_h,  int(max(ys)) + margin)

    if x2 <= x1 or y2 <= y1:
        return None

    return image[y1:y2, x1:x2]


# ── Streamlit UI ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PaperTrail Review",
    page_icon=None,
    layout="wide",
)

st.title("PaperTrail")
st.caption("From paper surveys to Qualtrics, review and correct flagged fields")

surveys = list_surveys()
if not surveys:
    st.error(
        "No surveys registered yet. Add a survey YAML to "
        "config/surveys/ first."
    )
    st.stop()

survey = st.sidebar.selectbox("Survey", surveys)
survey_config = load_survey_config(survey)
field_lookup  = get_field_lookup(survey_config)

tab_upload, tab_review, tab_download = st.tabs(
    ["Upload & Run", "Review Flagged Fields", "Download Output"]
)


# ── Tab 1 — Upload & Run ──────────────────────────────────────────────────────

with tab_upload:
    st.subheader("Upload completed survey scans")
    st.write(
        "Drop one PDF per respondent below. Each PDF should "
        "contain all pages for that respondent in one file."
    )

    uploaded_files = st.file_uploader(
        "Choose PDF files",
        type=["pdf"],
        accept_multiple_files=True,
    )

    if uploaded_files and st.button("Save uploaded files"):
        count = save_uploaded_files(survey, uploaded_files)
        st.success(f"Saved {count} file(s) to data/scans/{survey}/")

    st.divider()
    st.subheader("Run the pipeline")

    if st.button("Run full pipeline", type="primary"):
        with st.spinner("Processing scans — this takes a few seconds..."):
            success, output = run_pipeline_stage(survey, "all")

        if success:
            st.success("Pipeline completed successfully.")
        else:
            st.error("Pipeline encountered an error.")

        with st.expander("View detailed log"):
            st.code(output, language=None)

    st.divider()
    flagged_df = load_flagged_fields()
    if not flagged_df.empty:
        n_flagged = len(flagged_df[flagged_df["corrected_value"] == ""])
        n_forms   = flagged_df["form_id"].nunique()
        st.metric("Respondents with flagged fields", n_forms)
        st.metric("Fields awaiting review", n_flagged)
    else:
        st.info("No flagged fields — all clear, or no batch run yet.")


# ── Tab 2 — Review Flagged Fields ─────────────────────────────────────────────

with tab_review:
    st.subheader("Review fields the system was uncertain about")

    flagged_df = load_flagged_fields()
    pending    = flagged_df[flagged_df["corrected_value"] == ""]

    if pending.empty:
        st.success("Nothing to review right now.")
    else:
        st.write(
            f"{len(pending)} field(s) need a quick look. "
            f"Look at the scan, type the correct value, then submit."
        )

        corrections = {}

        for form_id in pending["form_id"].unique():
            form_rows = pending[pending["form_id"] == form_id]
            st.markdown(f"### Respondent: `{form_id}`")

            for idx, row in form_rows.iterrows():
                field_id = row["field_id"]
                field    = field_lookup.get(field_id, {})
                page_num = field.get("page", 1)

                col_img, col_input = st.columns([2, 1])

                with col_img:
                    image = get_page_image(survey, form_id, page_num)
                    crop  = (
                        crop_field_region(image, field)
                        if image is not None else None
                    )
                    if crop is not None:
                        st.image(
                            crop, channels="GRAY",
                            caption=f"{field_id} — page {page_num}",
                        )
                    else:
                        st.warning("Scan image not available for preview.")

                with col_input:
                    st.write(f"**Field:** {field_id}")
                    st.write(f"**System reason:** {row['reason']}")
                    st.write(f"**Raw value:** {row['raw_value'] or '—'}")

                    key = f"correction_{form_id}_{field_id}_{idx}"
                    value = st.text_input(
                        "Correct value", key=key,
                    )
                    corrections[idx] = value

                st.divider()

        if st.button("Submit corrections", type="primary"):
            updated = 0
            for idx, value in corrections.items():
                if value.strip():
                    flagged_df.at[idx, "corrected_value"] = value.strip()
                    updated += 1

            save_flagged_fields(flagged_df)

            with st.spinner("Applying corrections and rebuilding output..."):
                success, output = run_pipeline_stage(survey, "output")

            if success:
                st.success(
                    f"Saved {updated} correction(s) and rebuilt the "
                    f"output file."
                )
            else:
                st.error("Something went wrong rebuilding the output.")

            with st.expander("View detailed log"):
                st.code(output, language=None)

            st.rerun()


# ── Tab 3 — Download Output ───────────────────────────────────────────────────

with tab_download:
    st.subheader("Download the Qualtrics import file")

    output_name = f"{survey}_import.xlsx"
    output_path = os.path.join(OUTPUT_DIR, output_name)

    if os.path.exists(output_path):
        mtime = datetime.fromtimestamp(
            os.path.getmtime(output_path)
        ).strftime("%Y-%m-%d %H:%M")
        st.write(f"Last updated: {mtime}")

        with open(output_path, "rb") as f:
            st.download_button(
                "Download Qualtrics import file",
                data=f.read(),
                file_name=output_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        st.divider()
        st.write(
            "**Next step:** In Qualtrics, go to "
            "**Data & Analysis → Export & Import → Import Data** "
            "and upload this file."
        )
    else:
        st.info(
            f"No output file yet for '{survey}'. Run the pipeline "
            f"in the Upload & Run tab first."
        )