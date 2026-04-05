"""
PaperTrail — main pipeline entry point.

Runs the complete pipeline from scanned survey images
to a Qualtrics-ready Excel import file in one command.

Usage:
    python run_pipeline.py --survey maize_community_survey
    python run_pipeline.py --survey maize_community_survey --dry-run
    python run_pipeline.py --survey maize_community_survey --stage output

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

from src.scanner.preprocess   import preprocess_batch
from src.validate             import validate_batch, load_corrections
from src.qualtrics_mapper     import build_import_file
from src.logger               import log_run


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option(
    "--input", "input_dir",
    default="data/scans/",
    show_default=True,
    help="Folder containing scanned survey PDFs or images.",
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
    """PaperTrail — scan paper surveys and produce
    Qualtrics import files automatically."""

    start_time = time.time()

    _print_header(survey, input_dir, stage, dry_run)

    # ── Load survey config ────────────────────────────────────────────────────
    yaml_path = os.path.join(
        "config", "surveys", f"{survey}.yaml"
    )
    if not os.path.exists(yaml_path):
        click.echo(
            f"\n  ERROR: Survey config not found: {yaml_path}"
        )
        click.echo(
            f"  Run the calibration tool first to register "
            f"this survey."
        )
        return

    with open(yaml_path, "r", encoding="utf-8") as f:
        survey_config = yaml.safe_load(f)

    template_path = (
        survey_config
        .get("qualtrics", {})
        .get("template", "")
    )

    # Track these across stages for logging
    processed_files = []
    extractions     = []
    validation      = {}
    success         = False

    # ── Stage 1: Preprocess ───────────────────────────────────────────────────
    if stage in ["all", "preprocess"]:
        click.echo("\n" + "─" * 60)
        click.echo("  STAGE 1 — Preprocessing scans")
        click.echo("─" * 60)

        if dry_run:
            click.echo(
                f"  [DRY RUN] Would preprocess all files "
                f"in {input_dir}"
            )
        else:
            processed = preprocess_batch(
                input_dir  = input_dir,
                output_dir = "data/processed/",
            )
            processed_files = processed
            click.echo(
                f"  Preprocessed {len(processed)} page(s)"
            )

    # ── Stage 2: Extract ──────────────────────────────────────────────────────
    if stage in ["all", "extract"]:
        click.echo("\n" + "─" * 60)
        click.echo("  STAGE 2 — Detecting marks")
        click.echo("─" * 60)

        image_files = [
            f for f in os.listdir("data/processed/")
            if f.lower().endswith(
                (".jpg", ".jpeg", ".png", ".tiff")
            )
        ]

        if not image_files:
            click.echo("  No processed images found.")
            click.echo(
                "  Run with --stage preprocess first."
            )
            return

        if dry_run:
            click.echo(
                f"  [DRY RUN] Would extract marks from "
                f"{len(image_files)} image(s)"
            )
        else:
            from src.scanner.extractor import extract_batch

            extractions = extract_batch(
                processed_dir = "data/processed/",
                survey_config = survey_config,
                output_dir    = "data/extracted/",
            )

            click.echo(
                f"\n  Extracted {len(extractions)} "
                f"respondent(s)"
            )

    # ── Stage 3: Validate ─────────────────────────────────────────────────────
    if stage in ["all", "validate"]:
        click.echo("\n" + "─" * 60)
        click.echo("  STAGE 3 — Validating extracted values")
        click.echo("─" * 60)

        # Load from disk if coming from a previous stage run
        if not extractions:
            extractions = _load_extractions()

        if not extractions:
            click.echo("  No extractions found.")
            click.echo(
                "  Run with --stage extract first."
            )
            return

        if dry_run:
            click.echo(
                f"  [DRY RUN] Would validate "
                f"{len(extractions)} respondent(s)"
            )
        else:
            os.makedirs("data/flagged", exist_ok=True)

            validation = validate_batch(
                extractions   = extractions,
                survey_config = survey_config,
                flagged_path  = "data/flagged/flagged_fields.csv",
            )

            s = validation["summary"]
            click.echo(
                f"  Respondents:    {s['forms_processed']}"
            )
            click.echo(
                f"  Total fields:   {s['total_fields']}"
            )
            click.echo(
                f"  Clean:          "
                f"{s['total_fields'] - s['total_flagged']}"
            )
            click.echo(
                f"  Flagged:        {s['total_flagged']}"
            )
            click.echo(
                f"  Flag rate:      {s['flag_rate_pct']}%"
            )

            if s["total_flagged"] > 0:
                click.echo(
                    f"\n  Review flagged fields in: "
                    f"data/flagged/flagged_fields.csv"
                )
                click.echo(
                    f"  Enter corrections in the "
                    f"corrected_value column, then re-run "
                    f"with --stage output"
                )
            else:
                click.echo(
                    "\n  All fields passed validation ✓"
                )

            # Save the full raw extractions — not just clean fields.
            # Flagged fields must be present in validated.json so
            # that human corrections from flagged_fields.csv can be
            # applied to them in the output stage. If only clean
            # fields are saved here, corrections have nowhere to land.
            _save_validated(extractions)

    # ── Stage 4: Output ───────────────────────────────────────────────────────
    if stage in ["all", "output"]:
        click.echo("\n" + "─" * 60)
        click.echo(
            "  STAGE 4 — Building Qualtrics import file"
        )
        click.echo("─" * 60)

        validated = _load_validated()

        if not validated:
            click.echo("  No validated data found.")
            click.echo(
                "  Run with --stage validate first."
            )
            return

        # Apply any human corrections from flagged_fields.csv.
        # Corrections are written into corrected_value on each
        # field dict. The mapper reads corrected_value first,
        # falling back to value if no correction was entered.
        corrections = load_corrections(
            "data/flagged/flagged_fields.csv"
        )
        if corrections:
            click.echo(
                f"  Applying {len(corrections)} "
                f"correction(s) from flagged_fields.csv"
            )
            validated = _apply_corrections(
                validated, corrections
            )

        if not template_path:
            click.echo(
                "  ERROR: No Qualtrics template path "
                "in survey YAML."
            )
            click.echo(
                "  Add qualtrics.template to your "
                "survey YAML."
            )
            return

        if not os.path.exists(template_path):
            click.echo(
                f"  ERROR: Template not found: "
                f"{template_path}"
            )
            return

        from datetime import datetime
        date_str    = datetime.now().strftime("%Y-%m-%d")
        output_name = f"{survey}_{date_str}_import.xlsx"
        output_path = os.path.join(
            "data", "output", output_name
        )
        os.makedirs("data/output", exist_ok=True)

        if dry_run:
            click.echo(
                f"  [DRY RUN] Would build: {output_path}"
            )
            success = True
        else:
            # Pass field dicts directly — corrected_value is
            # already embedded in each field dict by
            # _apply_corrections above. The mapper reads
            # corrected_value first, then falls back to value.
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
        total_fields  = 0
        total_flagged = 0
        if validation and "summary" in validation:
            total_fields  = validation["summary"].get(
                "total_fields", 0
            )
            total_flagged = validation["summary"].get(
                "total_flagged", 0
            )

        log_run(
            survey_id                   = survey,
            forms_processed             = len(extractions),
            fields_extracted            = total_fields,
            fields_flagged              = total_flagged,
            qualtrics_validation_passed = success,
            pipeline_runtime_sec        = runtime,
            operator                    = operator,
        )

    # ── Final summary ─────────────────────────────────────────────────────────
    click.echo("\n" + "═" * 60)
    click.echo("  COMPLETE")
    click.echo("═" * 60)
    click.echo(f"  Runtime:  {runtime} seconds")

    if not dry_run and stage == "all":
        if success:
            click.echo(f"  Output:   {output_path}")
            click.echo(
                f"\n  Next step: import into Qualtrics"
            )
            click.echo(
                f"  Data & Analysis → "
                f"Export & Import → Import Data"
            )
        elif (validation
              and validation.get("summary", {})
                            .get("total_flagged", 0) > 0):
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
            f"\n  This was a dry run — no files written"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_header(
    survey:    str,
    input_dir: str,
    stage:     str,
    dry_run:   bool,
) -> None:
    """Print the pipeline startup banner.

    Args:
        survey:    Survey name being processed.
        input_dir: Input folder path.
        stage:     Pipeline stage being run.
        dry_run:   Whether this is a dry run.
    """
    click.echo("\n" + "═" * 60)
    click.echo("  PaperTrail")
    click.echo(
        "  From paper surveys to Qualtrics — automatically"
    )
    click.echo("═" * 60)
    click.echo(f"  Survey:   {survey}")
    click.echo(f"  Input:    {input_dir}")
    click.echo(f"  Stage:    {stage}")
    if dry_run:
        click.echo(
            f"  Mode:     DRY RUN — no files will be written"
        )


def _load_extractions() -> list:
    """Load raw extractions from data/extracted/.

    Returns:
        List of extraction dicts, or empty list if not found.
    """
    path = os.path.join(
        "data", "extracted", "extractions.json"
    )
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_validated(validated: list) -> None:
    """Save extractions to data/validated/ for the output stage.

    Saves the full extraction including flagged fields so that
    human corrections from flagged_fields.csv can be applied
    to them in the output stage. If only clean fields were saved,
    corrected values would have nowhere to land.

    Args:
        validated: List of extraction dicts (all fields).
    """
    os.makedirs("data/validated", exist_ok=True)
    path = os.path.join(
        "data", "validated", "validated.json"
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(validated, f, indent=2)


def _load_validated() -> list:
    """Load validated extractions from data/validated/.

    Returns:
        List of validated dicts, or empty list if not found.
    """
    path = os.path.join(
        "data", "validated", "validated.json"
    )
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _apply_corrections(
    validated:   list,
    corrections: dict,
) -> list:
    """Apply human corrections from flagged_fields.csv.

    Corrections are keyed by (form_id, field_id) tuples.
    Raw extracted values are never overwritten — corrections
    are written to a corrected_value key inside each field dict.
    The qualtrics_mapper reads corrected_value first, falling
    back to value when no correction exists.

    Args:
        validated:   List of extraction dicts (all fields).
        corrections: Dict mapping (form_id, field_id)
                     -> corrected_value string.

    Returns:
        Updated list with corrections embedded in field dicts.
    """
    for item in validated:
        form_id = item.get("form_id", "")
        fields  = item.get("fields", {})

        for key, corrected in corrections.items():
            if isinstance(key, tuple):
                fid_form, fid_field = key
                if fid_form != form_id:
                    continue
                if fid_field not in fields:
                    # Field was flagged but not in validated —
                    # create a placeholder so correction lands
                    fields[fid_field] = {}
                fields[fid_field]["corrected_value"] = corrected
            else:
                if key in fields:
                    fields[key]["corrected_value"] = corrected

    return validated


if __name__ == "__main__":
    main()