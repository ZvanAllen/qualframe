"""QualBench from the command line: import a reference coding, or compare coding runs.

Examples (run from the QualFrame application folder):

  uv run python scripts/qualbench.py compare --study "%USERPROFILE%/QualFrame/studies/my-study/project.yaml" \
      --run 20261011T164719Z --run 20261011T165635Z --reference phase-1a

  uv run python scripts/qualbench.py import-reference --study .../project.yaml --id phase-1a \
      --label "Phase 1a transcript coding" --statement "GPT-5.2 Pro output, reviewed by the team" \
      --by "Zack" --map "studies/my-study/data/raw/transcripts/ON/1A.docx=C:/outputs/1A_coding.xlsx"

No model is called and nothing in the study is changed, except that import-reference saves the
reference (with copies of its workbooks) under the study's references folder and compare writes a
report under the study's exports/qualbench folder.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qualframe.config import load_project_manifest, resolve_repo_path  # noqa: E402
from qualframe.qualbench import (  # noqa: E402
    build_qualbench,
    reference_coding_set,
    run_coding_set,
    write_qualbench,
)
from qualframe.reference_coding import (  # noqa: E402
    build_reference_coding,
    load_reference_coding,
    reference_folder,
    save_reference_coding,
)


def _study(path: str) -> tuple[Path, Path]:
    project = Path(path).expanduser().resolve()
    if not project.exists():
        raise SystemExit(f"Study file not found: {project}")
    return project, project.parents[2]


def import_reference(args) -> None:
    project, repo_root = _study(args.study)
    files = {}
    for entry in args.map:
        transcript, _, workbook = entry.partition("=")
        if not workbook:
            raise SystemExit("Give each --map as transcript=workbook.")
        files[transcript.strip()] = Path(workbook.strip()).expanduser()
    payload = build_reference_coding(repo_root=repo_root, project_path=project, reference_id=args.id,
                                     label=args.label, statement=args.statement, files=files,
                                     created_by=args.by, independent_human_coding=args.independent_human_coding)
    counts = payload["counts"]
    print(f"{len(payload['sources'])} transcripts: {counts['included']} located passages, "
          f"{counts['quotations_not_found']} quotations not found, {counts['unmatched_constructs']} "
          f"construct labels not matched, {counts['absences']} 'no relevant quote' rows.")
    for note in payload["notices"]:
        print("  " + note)
    if args.dry_run:
        return
    print("Saved", save_reference_coding(project, payload, files))


def compare(args) -> None:
    project, repo_root = _study(args.study)
    manifest = load_project_manifest(project)
    artifacts = resolve_repo_path(repo_root, manifest.paths["artifacts"])
    sets = []
    for entry in args.run:
        # "RUN" is a run of this study; "STUDY-ID:RUN" is a run of another study in the same workspace.
        study_id, _, run_id = entry.rpartition(":")
        run_root = artifacts / run_id
        if study_id:
            other = repo_root / "studies" / study_id / "project.yaml"
            run_root = resolve_repo_path(repo_root, load_project_manifest(other).paths["artifacts"]) / run_id
        sets.append(run_coding_set(repo_root, run_root))
    reference = None
    if args.reference:
        path = reference_folder(project, args.reference) / "reference.json"
        reference = reference_coding_set(load_reference_coding(path, repo_root))
    groups = [group.split(",") for group in args.stability or []]
    report = build_qualbench(sets, reference=reference, stability_groups=groups)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out).expanduser() if args.out else project.parent / "exports" / "qualbench" / stamp
    write_qualbench(report, out)
    print("Wrote", out)
    for row in report["presence"]:
        if row["scope_kind"] == "all" and row["level"] == "code":
            extra = f", F1 {row['f1']:.2f}" if row["f1"] is not None else ""
            kappa = "n/a" if row["cohen_kappa"] is None else f"{row['cohen_kappa']:.2f}"
            print(f"  {row['left']} vs {row['right']}: agreement {row['percent_agreement']:.2f}, "
                  f"kappa {kappa}, AC1 {row['gwet_ac1']:.2f}{extra}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("import-reference", help="Import an earlier coding as a reference.")
    one.add_argument("--study", required=True, help="The study's project.yaml")
    one.add_argument("--id", required=True, help="Short ID, such as phase-1a")
    one.add_argument("--label", required=True)
    one.add_argument("--statement", required=True, help="What the reference is: how it was coded and reviewed")
    one.add_argument("--by", required=True, help="Your name, recorded with the reference")
    one.add_argument("--map", action="append", required=True, help="transcript=workbook (repeat)")
    one.add_argument("--independent-human-coding", action="store_true",
                     help="Declare independent human coding; defaults to false. Describe the provenance in --statement.")
    one.add_argument("--dry-run", action="store_true")
    one.set_defaults(func=import_reference)
    two = sub.add_parser("compare", help="Compare runs with each other and with a reference.")
    two.add_argument("--study", required=True)
    two.add_argument("--run", action="append", default=[],
                     help="Run ID (repeat); STUDY-ID:RUN-ID for a run of another study with the same transcripts")
    two.add_argument("--reference", help="Reference ID")
    two.add_argument("--stability", action="append", help="Comma-separated run IDs that repeat one configuration")
    two.add_argument("--out", help="Folder for the report (default: the study's exports/qualbench)")
    two.set_defaults(func=compare)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
