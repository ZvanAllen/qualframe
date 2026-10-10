from __future__ import annotations

import argparse
import html
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from qualframe import __version__
from qualframe.io.export import export_run
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.qa.inventory import review_item_paths


PROJECT_YAML = REPO_ROOT / "demo" / "project" / "project_demo.yaml"


def _link(path: Path, report_dir: Path) -> str:
    return Path(os.path.relpath(path, report_dir)).as_posix()


def _write_report(
    *,
    run_id: str,
    plan_path: Path,
    manifest_path: Path,
    review_items: list[Path],
    export_paths: list[Path],
) -> Path:
    report_dir = REPO_ROOT / "demo" / "presentation"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "index.html"

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_root = manifest_path.parent
    artifacts = []
    for rel_path in manifest["artifact_paths"]:
        path = artifact_root / rel_path
        artifacts.append((path, json.loads(path.read_text(encoding="utf-8"))))

    stage_counts = Counter(item["stage_id"] for _, item in artifacts)
    prompt_rows = sorted(
        {
            (item.get("stage_id", ""), item.get("prompt_ref", ""), item.get("prompt_sha256", ""))
            for _, item in artifacts
        }
    )
    review_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in review_items]

    source_rows = "".join(
        f"<tr><td>{html.escape(item['path'])}</td><td>{html.escape(item['kind'])}</td>"
        f"<td><code>{html.escape((item.get('sha256') or '')[:16])}&hellip;</code></td></tr>"
        for item in plan["discovered_inputs"]
    )
    stage_rows = "".join(
        f"<tr><td>{html.escape(stage_id)}</td><td>{count}</td></tr>"
        for stage_id, count in stage_counts.items()
    )
    prompt_table_rows = "".join(
        f"<tr><td>{html.escape(stage)}</td><td>{html.escape(ref)}</td>"
        f"<td><code>{html.escape(sha[:16])}&hellip;</code></td></tr>"
        for stage, ref, sha in prompt_rows
    )
    review_rows = "".join(
        f"<tr><td>{html.escape(payload['rule_id'])}</td>"
        f"<td>{html.escape(payload['stage_id'])}</td>"
        f"<td>{html.escape(payload['reason'])}</td>"
        f"<td><a href='{html.escape(_link(path, report_dir))}'>Open JSON</a></td></tr>"
        for path, payload in zip(review_items, review_payloads, strict=True)
    )
    export_rows = "".join(
        f"<li><a href='{html.escape(_link(path, report_dir))}'>{html.escape(path.name)}</a></li>"
        for path in export_paths
    )
    artifact_rows = "".join(
        f"<li><a href='{html.escape(_link(path, report_dir))}'>{html.escape(path.relative_to(artifact_root).as_posix())}</a></li>"
        for path, _ in artifacts
    )

    report_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QualFrame synthetic interview demo</title>
  <style>
    :root {{ color-scheme: light; --ink:#18212b; --muted:#5f6b76; --navy:#14324a; --blue:#1f6f8b; --paper:#f7f8f5; --line:#d8ded8; --warn:#fff3cd; }}
    body {{ margin:0; background:var(--paper); color:var(--ink); font:16px/1.5 system-ui,Segoe UI,sans-serif; }}
    main {{ max-width:1080px; margin:0 auto; padding:36px 24px 72px; }}
    h1,h2 {{ color:var(--navy); line-height:1.15; }}
    h1 {{ font-size:2.35rem; margin-bottom:.25rem; }}
    h2 {{ margin-top:2.2rem; border-bottom:2px solid var(--line); padding-bottom:.35rem; }}
    .eyebrow {{ color:var(--blue); font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
    .banner {{ background:var(--warn); border-left:6px solid #d39e00; padding:14px 18px; margin:24px 0; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; }}
    .card {{ background:white; border:1px solid var(--line); border-radius:10px; padding:16px; }}
    .value {{ font-size:1.45rem; font-weight:750; color:var(--navy); overflow-wrap:anywhere; }}
    .label {{ color:var(--muted); font-size:.88rem; }}
    table {{ width:100%; border-collapse:collapse; background:white; }}
    th,td {{ border:1px solid var(--line); padding:9px 11px; text-align:left; vertical-align:top; }}
    th {{ background:#eaf0ef; }}
    code {{ font-size:.88em; }}
    a {{ color:#075e82; }}
    .foot {{ color:var(--muted); margin-top:3rem; font-size:.9rem; }}
  </style>
</head>
<body><main>
  <div class="eyebrow">QualFrame v{html.escape(__version__)}</div>
  <h1>Synthetic interview demonstration</h1>
  <p>Run-specific, read-only evidence page for the developer-operated QualFrame workflow engine.</p>
  <div class="banner"><strong>Synthetic fixture only.</strong> Nothing on this page is a research finding. This page is not a general-purpose QualFrame user interface and it does not provide adjudication or release controls.</div>

  <div class="cards">
    <div class="card"><div class="label">Run ID</div><div class="value">{html.escape(run_id)}</div></div>
    <div class="card"><div class="label">Pipeline</div><div class="value">{html.escape(plan['pipeline_id'])}</div></div>
    <div class="card"><div class="label">Provider</div><div class="value">cached_demo</div></div>
    <div class="card"><div class="label">Artifacts / exports</div><div class="value">{len(artifacts)} / {len(export_paths)}</div></div>
    <div class="card"><div class="label">QA items routed</div><div class="value">{manifest['qa_failure_count']}</div></div>
  </div>

  <h2>1. Configuration and execution</h2>
  <p>The checked-in project manifest selects a synthetic CFIR framework, the active five-stage transcript pipeline, and a network-free cached provider. The runner executed the same artifact, parser, QA, and export paths used by configured model providers.</p>
  <table><thead><tr><th>Stage</th><th>Artifacts</th></tr></thead><tbody>{stage_rows}</tbody></table>
  <p><a href="{html.escape(_link(plan_path, report_dir))}">Open run plan</a> &middot; <a href="{html.escape(_link(PROJECT_YAML, report_dir))}">Open project configuration</a></p>

  <h2>2. Source provenance</h2>
  <table><thead><tr><th>Synthetic input</th><th>Kind</th><th>SHA-256 prefix</th></tr></thead><tbody>{source_rows}</tbody></table>

  <h2>3. Versioned methods and prompt identity</h2>
  <table><thead><tr><th>Stage</th><th>Prompt reference</th><th>Prompt SHA-256 prefix</th></tr></thead><tbody>{prompt_table_rows}</tbody></table>

  <h2>4. Automated QA and review routing</h2>
  <p>The final cached row deliberately lists <em>Synthetic Network Alpha</em> as both facilitator and barrier. The deterministic QA engine detected that conflict and wrote the review item below.</p>
  <table><thead><tr><th>Rule</th><th>Stage</th><th>Reason</th><th>Evidence</th></tr></thead><tbody>{review_rows}</tbody></table>

  <h2>5. Traceable artifacts and Excel exports</h2>
  <p><a href="{html.escape(_link(manifest_path, report_dir))}">Open run manifest</a></p>
  <details><summary>Artifact JSON files ({len(artifacts)})</summary><ul>{artifact_rows}</ul></details>
  <details open><summary>Excel exports ({len(export_paths)})</summary><ul>{export_rows}</ul></details>

  <p class="foot">Generated locally at {datetime.now(timezone.utc).isoformat()} without network access. Cached outputs are explicitly synthetic fallbacks, not model-generated findings.</p>
</main></body></html>""",
        encoding="utf-8",
    )
    (report_dir / "latest_run.txt").write_text(run_id + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline QualFrame interview demonstration.")
    parser.add_argument("--run-id", help="Optional unique run ID. A timestamped demo ID is used by default.")
    args = parser.parse_args()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("demo_%Y%m%dT%H%M%SZ")

    print("[1/6] Loading the synthetic demo configuration")
    runner = ProjectRunner(PROJECT_YAML)
    if runner.project.provider.name != "cached_demo":
        raise RuntimeError("Demo safety check failed: provider must be cached_demo.")

    artifact_root = REPO_ROOT / runner.project.paths["artifacts"] / run_id
    if artifact_root.exists():
        raise RuntimeError(f"Run ID already exists; choose a new one: {run_id}")

    print("[2/6] Discovering and hashing synthetic inputs")
    plan = runner.build_run_plan()
    if not plan.discovered_inputs or any(
        not item.path.replace("\\", "/").startswith("demo/fixtures/")
        for item in plan.discovered_inputs
    ):
        raise RuntimeError("Demo safety check failed: every input must be under demo/fixtures/.")
    plan_path = runner.save_run_plan(plan, run_id)
    print(f"      run_id={run_id}; inputs={len(plan.discovered_inputs)}; plan_items={len(plan.planned_stage_runs)}")

    print("[3/6] Executing the five-stage pipeline from checked-in cached responses")
    manifest_path = runner.execute_run_plan(
        plan,
        run_id,
        progress_callback=lambda stage_id: print(f"      -> {stage_id}"),
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review_dir = REPO_ROOT / runner.project.paths["review_queue"] / run_id
    review_items = review_item_paths(artifact_root, review_dir, manifest)
    if manifest["qa_failure_count"] != 1 or len(review_items) != 1:
        raise RuntimeError(
            "Demo reliability check failed: expected exactly one deliberately seeded QA item."
        )
    review_payload = json.loads(review_items[0].read_text(encoding="utf-8"))
    if review_payload["rule_id"] != "one_network_one_valence":
        raise RuntimeError("Demo reliability check failed: unexpected QA rule was triggered.")
    print("[4/6] Verified one deliberate QA conflict and its review-queue JSON")

    exports_dir = REPO_ROOT / runner.project.paths["exports"]
    export_paths = export_run(run_id, artifact_root, exports_dir)
    if len(export_paths) != len(manifest["artifact_paths"]):
        raise RuntimeError("Demo reliability check failed: every artifact should produce an Excel export.")
    print(f"[5/6] Exported {len(export_paths)} traceable Excel workbooks")

    report_path = _write_report(
        run_id=run_id,
        plan_path=plan_path,
        manifest_path=manifest_path,
        review_items=review_items,
        export_paths=export_paths,
    )
    print(f"[6/6] Ready to present: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
