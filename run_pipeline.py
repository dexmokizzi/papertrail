"""
PaperTrail — main pipeline entry point.

Runs the complete pipeline from scanned survey images
to a Qualtrics-ready Excel import file in one command.

Usage:
    python run_pipeline.py --input data/scans/ --survey your_survey_name
    python run_pipeline.py --input data/scans/ --survey your_survey_name --dry-run
    python run_pipeline.py --input data/scans/ --survey your_survey_name --stage output

Stages:
    all        Run the full pipeline (default)
    preprocess Run image preprocessing only
    extract    Run mark detection only
    validate   Run validation only
    output     Run Qualtrics mapping and export only
"""

import os
import time
import json
import click
import yaml
import cv2

from src.scanner.preprocess     import preprocess_batch
from src.scanner.omr            import detect_mark
from src.scanner.validate               import validate_batch, load_corrections
from src.scanner.qualtrics_mapper       import build_import_file, load_survey_config
from src.scanner.logger                 import log_run, get_summary


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option(
    "--input", "input_dir",
    default="data/scans/",
    show_default=True,
    help="Folder containing scanned survey images.",
)
@click.option(
    "--survey",
    required=True,
    help="Survey name matching a YAML file in config/surveys/.",
)
@click.option(
    "--stage",
    default="all",
    type=click.Choice(
        ["all", "preprocess", "extract", "validate", "output"],
        case_sensitive=False,
    ),
    show_default=True,
    help="Run a specific pipeline stage only.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Simulate the run without writing any output files.",
)
@click.option(
    "--operator",
    default="developer",
    show_default=True,
    help="Name of the person running the pipeline.",
)
def main(input_dir, survey, stage, dry_run, operator):
    """PaperTrail — scan paper surveys and generate
    Qualtrics import files automatically."""

    start_time = time.time()

    _print_header(survey, input_dir, stage, dry_run)

    # Load survey configuration
    yaml_path = os.path.join("config", "surveys", f"{survey}.yaml")
    if not os.path.exists(yaml_path):
        click.echo(f"\n  ERROR: Survey config not found: {yaml_path}")
        click.echo(f"  Run the calibration tool first to register this survey.")
        return

    with open(yaml_path, "r", encoding="utf-8") as f:
        survey_config = yaml.safe_load(f)

    template_path = survey_config.get("qualtrics", {}).get(
        "template", ""
    )

    # ── Stage: Preprocess ─────────────────────────────────────────────────────
    if stage in ["all", "preprocess"]:
        click.echo("\n" + "─" * 60)
        click.echo("  STAGE 1 — Preprocessing scans")
        click.echo("─" * 60)

        if dry_run:
            click.echo("  [DRY RUN] Would preprocess all files in "
                       f"{input_dir}")
        else:
            processed = preprocess_batch(
                input_dir  = input_dir,
                output_dir = "data/processed/",
            )
            click.echo(f"  Preprocessed {len(processed)} file(s)")

    # ── Stage: Extract ────────────────────────────────────────────────────────
    if stage in ["all", "extract"]:
        click.echo("\n" + "─" * 60)
        click.echo("  STAGE 2 — Detecting marks")
        click.echo("─" * 60)

        processed_files = [
            f for f in os.listdir("data/processed/")
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".tiff"))
        ]

        if not processed_files:
            click.echo("  No processed images found.")
            click.echo("  Run with --stage preprocess first.")
            return

        extractions = []

        for filename in processed_files:
            image_path = os.path.join("data/processed/", filename)
            form_id    = os.path.splitext(filename)[0]

            click.echo(f"\n  Scanning: {filename}")

            image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if image is None:
                click.echo(f"  WARNING: Could not load {filename} — skipping")
                continue

            fields     = _get_all_fields(survey_config)
            form_fields = {}

            for field in fields:
                result = detect_mark(image, field)
                form_fields[field["paper_id"]] = result
                value = result.get("value", "-")
                conf  = result.get("confidence", 0.0)
                flag  = f"  [{result.get('flag','')}]" \
                    if result.get("flag") else ""
                click.echo(
                    f"    {field['paper_id']:<8} → "
                    f"{str(value):<6} "
                    f"(confidence: {conf:.2f}){flag}"
                )

            extractions.append({
                "form_id": form_id,
                "fields":  form_fields,
            })

        # Save extractions for next stage
        if not dry_run:
            _save_extractions(extractions)
            click.echo(
                f"\n  Extracted {len(extractions)} form(s)"
            )

    # ── Stage: Validate ───────────────────────────────────────────────────────
    if stage in ["all", "validate"]:
        click.echo("\n" + "─" * 60)
        click.echo("  STAGE 3 — Validating extracted values")
        click.echo("─" * 60)

        extractions = _load_extractions()

        if not extractions:
            click.echo("  No extractions found.")
            click.echo("  Run with --stage extract first.")
            return

        if dry_run:
            click.echo(
                f"  [DRY RUN] Would validate "
                f"{len(extractions)} form(s)"
            )
        else:
            validation = validate_batch(
                extractions   = extractions,
                survey_config = survey_config,
                flagged_path  = "data/flagged/flagged_fields.csv",
            )

            s = validation["summary"]
            click.echo(f"  Forms:          {s['forms_processed']}")
            click.echo(f"  Total fields:   {s['total_fields']}")
            click.echo(f"  Clean:          {s['total_fields'] - s['total_flagged']}")
            click.echo(f"  Flagged:        {s['total_flagged']}")
            click.echo(f"  Flag rate:      {s['flag_rate_pct']}%")

            if s["total_flagged"] > 0:
                click.echo(
                    f"\n  Review flagged fields in: "
                    f"data/flagged/flagged_fields.csv"
                )
                click.echo(
                    f"  Enter corrections in the "
                    f"corrected_value column then re-run "
                    f"with --stage output"
                )
            else:
                click.echo(
                    "\n  All fields passed validation"
                )

            # Save validated extractions
            _save_validated(validation["clean_extractions"])

    # ── Stage: Output ─────────────────────────────────────────────────────────
    if stage in ["all", "output"]:
        click.echo("\n" + "─" * 60)
        click.echo("  STAGE 4 — Building Qualtrics import file")
        click.echo("─" * 60)

        validated = _load_validated()

        if not validated:
            click.echo("  No validated data found.")
            click.echo("  Run with --stage validate first.")
            return

        # Apply any human corrections
        corrections  = load_corrections(
            "data/flagged/flagged_fields.csv"
        )
        if corrections:
            click.echo(
                f"  Applying {len(corrections)} correction(s) "
                f"from flagged_fields.csv"
            )
            validated = _apply_corrections(validated, corrections)

        if not template_path:
            click.echo(
                "  ERROR: No Qualtrics template path in YAML."
            )
            click.echo(
                "  Add qualtrics.template to your survey YAML."
            )
            return

        if not os.path.exists(template_path):
            click.echo(
                f"  ERROR: Template not found: {template_path}"
            )
            return

        # Build output filename
        from datetime import datetime
        date_str    = datetime.now().strftime("%Y-%m-%d")
        output_name = f"{survey}_{date_str}_import.xlsx"
        output_path = os.path.join("data", "output", output_name)

        if dry_run:
            click.echo(
                f"  [DRY RUN] Would build: {output_path}"
            )
            success = True
        else:
            # Extract just the field values for the mapper
            clean_extractions = [
                item["fields"] for item in validated
            ]

            success = build_import_file(
                extractions   = clean_extractions,
                survey_config = survey_config,
                template_path = template_path,
                output_path   = output_path,
                batch_date    = date_str,
            )

    # ── Log the run ───────────────────────────────────────────────────────────
    runtime = round(time.time() - start_time, 2)

    if not dry_run and stage == "all":
        try:
            val_summary = validation["summary"]
        except NameError:
            val_summary = {
                "total_fields":  0,
                "total_flagged": 0,
            }

        log_run(
            survey_id                    = survey,
            forms_processed              = len(
                processed_files
                if 'processed_files' in dir() else []
            ),
            fields_extracted             = val_summary.get(
                "total_fields", 0
            ),
            fields_flagged               = val_summary.get(
                "total_flagged", 0
            ),
            qualtrics_validation_passed  = success
                if 'success' in dir() else False,
            pipeline_runtime_sec         = runtime,
            operator                     = operator,
        )

    # ── Final summary ─────────────────────────────────────────────────────────
    click.echo("\n" + "═" * 60)
    click.echo("  COMPLETE")
    click.echo("═" * 60)
    click.echo(f"  Runtime:  {runtime} seconds")

    if not dry_run and stage == "all":
        if 'success' in dir() and success:
            click.echo(f"  Output:   {output_path}")
            click.echo(
                f"\n  Next step: import the file into Qualtrics"
            )
            click.echo(
                f"  Data & Analysis → "
                f"Export & Import → Import Data"
            )
        elif 'val_summary' in dir() and \
                val_summary.get("total_flagged", 0) > 0:
            click.echo(
                f"\n  Action required: review flagged fields"
            )
            click.echo(
                f"  data/flagged/flagged_fields.csv"
            )
            click.echo(
                f"  Then re-run: python run_pipeline.py "
                f"--survey {survey} --stage output"
            )

    if dry_run:
        click.echo(
            f"\n  This was a dry run — no files were written"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_header(survey, input_dir, stage, dry_run):
    """Print the pipeline startup banner."""
    click.echo("\n" + "═" * 60)
    click.echo("  PaperTrail")
    click.echo("  From paper surveys to Qualtrics — automatically")
    click.echo("═" * 60)
    click.echo(f"  Survey:   {survey}")
    click.echo(f"  Input:    {input_dir}")
    click.echo(f"  Stage:    {stage}")
    if dry_run:
        click.echo(f"  Mode:     DRY RUN — no files will be written")


def _get_all_fields(survey_config: dict) -> list:
    """Get all field definitions from the survey config."""
    fields = list(survey_config.get("fields", []))
    for section in survey_config.get("sections", []):
        fields += section.get("fields", [])
    return fields


def _save_extractions(extractions: list) -> None:
    """Save raw extractions to data/extracted/ as JSON."""
    os.makedirs("data/extracted", exist_ok=True)
    path = os.path.join("data", "extracted", "extractions.json")

    # Convert extraction dicts to serializable format
    serializable = []
    for item in extractions:
        fields = {}
        for k, v in item["fields"].items():
            if isinstance(v, dict):
                fields[k] = {
                    "value":      v.get("value"),
                    "confidence": v.get("confidence", 0.0),
                    "flag":       v.get("flag", ""),
                }
            else:
                fields[k] = {"value": v, "confidence": 1.0}
        serializable.append({
            "form_id": item["form_id"],
            "fields":  fields,
        })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2)


def _load_extractions() -> list:
    """Load raw extractions from data/extracted/."""
    path = os.path.join("data", "extracted", "extractions.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_validated(validated: list) -> None:
    """Save validated extractions to data/validated/ as JSON."""
    os.makedirs("data/validated", exist_ok=True)
    path = os.path.join("data", "validated", "validated.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(validated, f, indent=2)


def _load_validated() -> list:
    """Load validated extractions from data/validated/."""
    path = os.path.join("data", "validated", "validated.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _apply_corrections(
    validated:   list,
    corrections: dict,
) -> list:
    """Apply human corrections from flagged_fields.csv.

    Args:
        validated:   List of validated extraction dicts.
        corrections: Dict mapping (form_id, field_id)
                     -> corrected_value.

    Returns:
        Updated list with corrections applied.
    """
    for item in validated:
        form_id = item["form_id"]
        for field_id, corrected in corrections.items():
            if isinstance(field_id, tuple):
                fid_form, fid_field = field_id
                if fid_form == form_id:
                    item["fields"][fid_field] = corrected
            else:
                item["fields"][field_id] = corrected

    return validated


if __name__ == "__main__":
    main()