"""Workspace, offline demo, JSON coding output, and compatible-endpoint setup."""
from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from qualframe.app_workspace import ensure_workspace, list_study_manifests, researcher_name, write_settings
from qualframe.dashboard import DashboardApp, make_handler
from qualframe.demo_study import create_demo_study
from qualframe.evidence_review import load_evidence_review_records
from qualframe.io.response_parser import coding_response_schema, parse_coding_json, parse_model_output
from qualframe.models import ProviderConfig
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.provider_setup import ProviderSetup
from qualframe.providers import build_provider
from qualframe.providers.recorded_provider import RecordedProvider, recording_key


def test_workspace_gets_templates_once_and_never_overwrites(tmp_path: Path) -> None:
    first = ensure_workspace(tmp_path / "ws")
    assert first.copied > 0
    prompt = first.root / "prompts/directed/v3/directed_coding.md"
    prompt.write_text("researcher edit", encoding="utf-8")
    second = ensure_workspace(tmp_path / "ws")
    assert second.copied == 0
    assert prompt.read_text(encoding="utf-8") == "researcher edit"
    assert (first.root / "studies").is_dir()


def test_settings_remember_the_researcher(tmp_path: Path) -> None:
    assert researcher_name(tmp_path) == ""
    write_settings(tmp_path, researcher_name="Unnamed researcher")
    assert researcher_name(tmp_path) == ""  # the placeholder is never a name
    write_settings(tmp_path, researcher_name="Ada")
    assert researcher_name(tmp_path) == "Ada"


def test_placeholder_reviewer_is_not_saved_as_the_name(tmp_path: Path) -> None:
    root = ensure_workspace(tmp_path / "ws").root
    _, project_path, _ = create_demo_study(root, with_comparison=False)
    app = DashboardApp(ProjectRunner(project_path))
    form = app.fill_identity({"reviewer": ["Unnamed researcher"]}, "Saved results")
    assert form["actor"] == ["Unnamed researcher"] and researcher_name(root) == ""
    app.fill_identity({"actor": ["Grace"]}, "x")
    assert researcher_name(root) == "Grace"


def test_json_coding_output_becomes_review_rows() -> None:
    text = '```json\n{"codings": [{"meaning_unit": "mu-1", "quote": "A & B | C", "code_id": "x", "rationale": "fits"}]}\n```'
    rows = parse_coding_json(text)["Directed Coding"]
    assert rows[0]["Evidence Start"] == "auto" and rows[0]["Code ID"] == "x"
    assert rows[0]["Exact Evidence"] == "A &amp; B | C"  # review unescapes back to the exact quote
    assert parse_coding_json("| a |\n|---|\n| 1 |") is None
    assert parse_model_output('{"codings": []}') == {"Directed Coding": []}
    schema = coding_response_schema(["b", "a"])
    assert schema["properties"]["codings"]["items"]["properties"]["code_id"]["enum"] == ["a", "b"]


def test_compatible_endpoint_configuration_and_validation() -> None:
    config = ProviderConfig(name="openai_compatible", model="gpt-oss:20b", base_url="http://localhost:11434/v1")
    provider = build_provider(config)
    assert provider.name == "openai_compatible" and provider.base_url == "http://localhost:11434/v1"
    with pytest.raises(ValueError):
        ProviderConfig(name="openai_compatible", model="m")
    with pytest.raises(ValueError):
        ProviderConfig(name="openai", model="m", base_url="http://localhost:1")
    base = dict(provider="openai_compatible", model="gpt-oss:20b", max_tokens=1000, absolute_limit_usd=1,
                input_rate=0, output_rate=0, pricing_date="2026-01-01", governance_confirmed=True)
    assert ProviderSetup.model_validate({**base, "base_url": "http://localhost:11434/v1"}).input_rate == 0
    with pytest.raises(ValueError, match="https"):
        ProviderSetup.model_validate({**base, "base_url": "http://example.org/v1"})
    with pytest.raises(ValueError, match="prices"):
        ProviderSetup.model_validate({**base, "provider": "openai", "pricing_source": "https://openai.com/api/pricing"})


def test_offline_demo_study_codes_from_recordings(tmp_path: Path) -> None:
    root = ensure_workspace(tmp_path / "ws").root
    created, project_path, run_id = create_demo_study(root)
    assert created.imported_source_count == 8  # six transcripts, a codebook and metadata
    runner = ProjectRunner(project_path)
    assert runner.codebook is not None and len(runner.codebook.codes) == 15
    records = load_evidence_review_records(runner.repo_root / "studies" / created.study_id / "artifacts" / run_id / "evidence_review/index.json")
    assert len(records) == 92  # Claude Sonnet 5.5, recorded October 2026
    assert all(record.anchoring_method == "unique_exact_quote" for record in records)
    assert all(not record.validation_issues for record in records)
    assert list_study_manifests(root) == [project_path]


def test_recorded_provider_only_answers_for_its_transcripts_and_instructions() -> None:
    provider = RecordedProvider("demo-illustrative-a")
    instructions = (Path(__file__).resolve().parents[1] / "prompts/directed/v3/directed_coding.md").read_text(encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        provider.complete(system_prompt="", user_prompt=f"{instructions}\n\n---\n\nTranscript:\n\nSomething else\n\n---\n\nCodebook")
    with pytest.raises(ValueError, match="different ones"):
        provider.complete(system_prompt="", user_prompt="Edited instructions\n\n---\n\nTranscript:\n\nSomething else")
    assert recording_key("no transcript here") is None


def _serve(app: DashboardApp):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def test_app_starts_without_a_study_and_opens_the_demo(tmp_path: Path) -> None:
    root = ensure_workspace(tmp_path / "ws").root
    app = DashboardApp(None, workspace_root=root)
    server, thread, base = _serve(app)
    try:
        home = urlopen(base + "/", timeout=10).read().decode("utf-8")
        assert "Open the demo study" in home and "No studies yet" in home
        css = urlopen(base + "/static/workspace.css", timeout=10).read().decode("utf-8")
        assert "@font-face" in css
        with pytest.raises(Exception):
            urlopen(base + "/static/../dashboard.py", timeout=10)
        page = urlopen(Request(base + "/demo", data=b"", method="POST"), timeout=60).read().decode("utf-8")
        assert "Demo study ready" in page and "Continue reviewing" in page
        name = urlencode({"researcher_name": "Grace", "back": "/review"}).encode()
        review = urlopen(Request(base + "/settings/name", data=name, method="POST"), timeout=10).read().decode("utf-8")
        assert "Recording decisions as Grace" in review
        results = urlopen(base + "/compare", timeout=10).read().decode("utf-8")
        assert "Codes in common" in results
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_methods_record_summarises_run_and_review(tmp_path: Path) -> None:
    from qualframe.methods_record import build_methods_record, methods_markdown, methods_paragraph

    root = ensure_workspace(tmp_path / "ws").root
    created, project_path, run_id = create_demo_study(root, with_comparison=False)
    app = DashboardApp(ProjectRunner(project_path))
    records = load_evidence_review_records(app.artifacts_dir / run_id / "evidence_review/index.json")
    for record, decision in zip(records[:3], ["accept", "reject", "accept"]):
        app.handle_action("/evidence-action", {"run_id": [run_id], "item": [record.record_id],
                                               "decision": [decision], "reviewer": ["Ada"]})
    record = build_methods_record(app, run_id)
    assert record["qualframe_version"] and record["model"]["label"] == "Claude Sonnet 5.5"
    assert record["review"]["decisions"]["accept"] == 2 and record["review"]["decisions"]["reject"] == 1
    assert record["review"]["reviewers"] == ["Ada"] and len(record["transcripts"]) == 6
    assert record["prompt"]["path"].endswith("directed/v3/directed_coding.md")
    paragraph = methods_paragraph(record)
    assert "accepting 2" in paragraph and "rejecting 1" in paragraph and "15-code codebook" in paragraph
    assert "## Human review" in methods_markdown(record)


def test_runner_stops_when_a_local_model_reads_only_part_of_the_prompt(tmp_path: Path) -> None:
    from qualframe.providers.base import LLMResponse, LLMUsage

    class Truncating:
        name = "openai_compatible"

        def complete(self, **_):
            return LLMResponse(text='{"codings": []}', status="completed",
                               usage=LLMUsage(input_tokens=4096, output_tokens=20))

    root = ensure_workspace(tmp_path / "ws").root
    _, project_path, _ = create_demo_study(root, with_comparison=False)
    runner = ProjectRunner(project_path)
    with pytest.raises(RuntimeError, match="context length"):
        runner._complete(provider=Truncating(), cost_controller=None, stage_id="coding",
                         input_label="P01", user_prompt="word " * 20000)
    # A full read passes.
    Truncating.complete = lambda self, **_: LLMResponse(text='{"codings": []}', status="completed",
                                                         usage=LLMUsage(input_tokens=26000, output_tokens=20))
    assert runner._complete(provider=Truncating(), cost_controller=None, stage_id="coding",
                            input_label="P01", user_prompt="word " * 20000).text


def test_cost_estimate_allows_for_reasoning_tokens(tmp_path: Path) -> None:
    from qualframe.coding_ui import cost_for, estimate_study

    root = ensure_workspace(tmp_path / "ws").root
    _, project_path, _ = create_demo_study(root, with_comparison=False)
    estimate = estimate_study(DashboardApp(ProjectRunner(project_path)))
    # Claude Sonnet 5.5 used 29,243 input and 15,815 output tokens on the demo (October 2026).
    assert estimate["input_tokens"] >= 29_000 * 0.9 and estimate["output_tokens"] >= 15_815
    assert 0.2 <= cost_for(estimate, 2.0, 10.0) <= 0.35


def test_compatible_endpoint_streams_and_reads_usage() -> None:
    """A slow local server is read as a stream; reasoning deltas are ignored and usage is kept."""
    import time
    from http.server import BaseHTTPRequestHandler

    pytest.importorskip("openai")
    seen: dict = {}

    class FakeOllama(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            base = {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "gpt-oss:20b"}
            events = [
                {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "reasoning": "Thinking..."}, "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {"content": '{"codings": '}, "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {"content": "[]}"}, "finish_reason": "stop"}]},
                {**base, "choices": [], "usage": {"prompt_tokens": 5000, "completion_tokens": 900, "total_tokens": 5900}},
            ]
            for event in events:
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = build_provider(ProviderConfig(name="openai_compatible", model="gpt-oss:20b",
                                                 base_url=f"http://127.0.0.1:{server.server_port}/v1"))
        response = provider.complete(system_prompt="s", user_prompt="u")
    finally:
        server.shutdown()
        server.server_close()
    assert seen["body"]["stream"] is True and seen["body"]["stream_options"] == {"include_usage": True}
    assert response.text == '{"codings": []}' and response.status == "completed"
    assert response.usage.input_tokens == 5000 and response.usage.output_tokens == 900


def _accept_all(app: DashboardApp, run_id: str) -> None:
    from qualframe.evidence_review import latest_evidence_action_by_record

    records = load_evidence_review_records(app.artifacts_dir / run_id / "evidence_review/index.json")
    decided = latest_evidence_action_by_record(app.review_dir / run_id)
    for record in records:
        if record.record_id not in decided:
            app.handle_action("/evidence-action", {"run_id": [run_id], "item": [record.record_id],
                                                   "decision": ["accept"], "reviewer": ["Ada"]})


def test_reviewers_can_add_and_remove_codes_the_model_missed(tmp_path: Path) -> None:
    from qualframe.evidence_review import export_evidence_review_package, load_run_records
    from qualframe.io.transcript_io import transcript_to_text
    from qualframe.methods_record import build_methods_record, methods_paragraph
    from qualframe.reviewed_analysis import reviewed_snapshot_payload
    from qualframe.review_ui import render_review

    root = ensure_workspace(tmp_path / "ws").root
    _, project_path, run_id = create_demo_study(root, with_comparison=False)
    app = DashboardApp(ProjectRunner(project_path))
    index = app.artifacts_dir / run_id / "evidence_review/index.json"
    first = load_evidence_review_records(index)[0]
    text = transcript_to_text(app.repo_root / first.source_path)
    sentence = "Ask the people who'll use it, before signing up."
    start = text.index(sentence)
    form = {"run_id": [run_id], "item": [first.record_id], "source_path": [first.source_path], "reviewer": ["Ada"],
            "added_start": [str(start)], "added_end": [str(start + len(sentence))],
            "added_code_id": ["org_leadership"], "rationale": ["Advice about involving users in the decision."]}
    app.handle_action("/evidence-add", form)
    app.handle_action("/evidence-add", {**form, "added_code_id": ["people_trust"], "rationale": [""]})
    with pytest.raises(ValueError, match="codebook"):
        app.handle_action("/evidence-add", {**form, "added_code_id": ["not-a-code"]})
    with pytest.raises(ValueError, match="Select the passage"):
        app.handle_action("/evidence-add", {**form, "added_start": ["5"], "added_end": ["5"]})
    records = load_run_records(index, app.review_dir / run_id)
    added = [r for r in records if r.anchoring_method == "researcher_selection"]
    assert len(records) == 94 and len(added) == 2
    assert added[0].evidence_span.exact_text == sentence and added[0].assignment.origin == "human"
    # Removing an addition is a recorded decision, like rejecting a proposal.
    app.handle_action("/evidence-action", {"run_id": [run_id], "item": [added[1].record_id],
                                           "decision": ["reject"], "reviewer": ["Ada"], "seconds_on_item": ["4.2"]})
    page = render_review(app, run_id=run_id, item_id=added[0].record_id)
    assert "Added by Ada during review" in page and "Remove this code" in page and "Add a code the model missed" in page
    assert "0 of 92 decided, 2 added" in page

    _accept_all(app, run_id)
    payload = reviewed_snapshot_payload(app.repo_root, app.artifacts_dir / run_id, app.review_dir / run_id)
    kept = [item for item in payload["evidence"] if item["record_id"] == added[0].record_id]
    assert len(payload["evidence"]) == 93 and kept and kept[0]["code_id"] == "org_leadership"
    assert added[1].record_id in {item["record_id"] for item in payload["rejected"]}
    record = build_methods_record(app, run_id)
    assert record["review"]["added_by_researchers"] == 1 and record["review"]["decisions"]["accept"] == 92
    assert "coded 1 passage that the model had not proposed" in methods_paragraph(record)
    exported = json.loads(export_evidence_review_package(project_manifest_path=project_path, run_id=run_id)[0].read_text(encoding="utf-8"))
    origins = [row["Origin"] for row in exported["evidence"]]
    assert origins.count("Added by researcher") == 2 and origins.count("Model proposal") == 92


def test_quotations_that_differ_only_in_typography_are_suggested(tmp_path: Path, monkeypatch) -> None:
    """gpt-oss-20b wrote non-breaking hyphens (lunch‑and‑learn) where the transcript has plain ones."""
    import qualframe.demo_study as demo
    from qualframe.evidence_review import blocking_review_issues
    from qualframe.io.transcript_io import transcript_to_text

    monkeypatch.setattr(demo, "PRIMARY_RECORDING", "gpt-oss-20b-ollama-2026-10")
    root = ensure_workspace(tmp_path / "ws").root
    _, project_path, run_id = demo.create_demo_study(root, with_comparison=False)
    app = DashboardApp(ProjectRunner(project_path))
    records = load_evidence_review_records(app.artifacts_dir / run_id / "evidence_review/index.json")
    suggested = [r for r in records if r.anchoring_method == "normalized_quote_candidate"]
    assert len(records) == 89 and len(suggested) == 5
    for record in suggested:
        source = transcript_to_text(app.repo_root / record.source_path)
        assert "‑" in record.proposed_exact_text and "‑" not in record.evidence_span.exact_text
        assert blocking_review_issues(record, source) == []
    app.handle_action("/evidence-action", {"run_id": [run_id], "item": [suggested[0].record_id],
                                           "decision": ["accept"], "reviewer": ["Ada"], "seconds_on_item": ["12.5"]})
    from qualframe.evidence_review import load_review_timing
    assert list(load_review_timing(app.review_dir / run_id).values()) == [12.5]


def test_text_kept_with_each_code_can_be_the_whole_answer_and_question(tmp_path: Path) -> None:
    from qualframe.demo_study import PRIMARY_RECORDING, run_recording
    from qualframe.io.transcript_io import transcript_to_text

    root = ensure_workspace(tmp_path / "ws").root
    _, project_path, _ = create_demo_study(root, with_comparison=False)
    app = DashboardApp(ProjectRunner(project_path))
    app.handle_method_update({"segmentation_strategy": ["model_proposed"], "coding_cardinality": ["multi_label"],
                              "partition_strategy": ["full_codebook"], "context_preset": ["question"],
                              "context_before": ["1"], "context_after": ["1"], "context_unit": ["sentences"],
                              "allow_overlapping_spans": ["yes"], "actor": ["Ada"]})
    method = ProjectRunner(project_path).method
    assert (method.context.unit, method.context.before, method.context.after) == ("turns", 1, 0)
    run_id = run_recording(project_path, PRIMARY_RECORDING, "with-question")
    record = load_evidence_review_records(root / "studies" / project_path.parent.name / "artifacts" / run_id / "evidence_review/index.json")[4]
    text = transcript_to_text(root / record.source_path)
    span = record.evidence_span
    kept = text[span.context_start_offset:span.context_end_offset]
    assert kept.startswith("Interviewer:") and "\n\nParticipant:" in kept and span.exact_text in kept


def test_coding_instructions_are_edited_as_new_versions(tmp_path: Path) -> None:
    from qualframe.coding_instructions import current_instructions, instruction_versions, save_instructions, use_instructions
    from qualframe.configuration_lock import create_configuration_lock

    root = ensure_workspace(tmp_path / "ws").root
    _, project_path, _ = create_demo_study(root, with_comparison=False)
    app = DashboardApp(ProjectRunner(project_path))
    _, original_file, text, label = current_instructions(app.repo_root, project_path)
    assert label == "QualFrame standard instructions"
    with pytest.raises(ValueError, match="Output section"):
        save_instructions(app.study_workspace, project_path, text=text.split("## Output")[0], label="No output",
                          actor="Ada", rationale="test")
    edited = text.replace("usually one to three sentences", "usually one sentence")
    ref = save_instructions(app.study_workspace, project_path, text=edited, label="Shorter meaning units",
                            actor="Ada", rationale="Pilot shorter quotations")
    stage, path, now, label = current_instructions(app.repo_root, project_path)
    assert label == "Shorter meaning units" and "usually one sentence" in now and path != original_file
    assert original_file.read_text(encoding="utf-8") == text  # the released prompt is untouched
    versions = instruction_versions(app.repo_root, project_path)
    assert [v.label for v in versions] == ["QualFrame standard instructions", "Shorter meaning units"] and versions[1].current
    lock = create_configuration_lock(project_path)
    assert any(asset.path.endswith("coding_instructions_v1.md") for asset in lock.assets if asset.kind == "prompt")
    # Recorded demo responses refuse to stand in for edited instructions.
    from qualframe.demo_study import PRIMARY_RECORDING, run_recording
    with pytest.raises(Exception, match="different ones"):
        run_recording(project_path, PRIMARY_RECORDING, "edited-run")
    use_instructions(app.study_workspace, project_path, framework_ref=versions[0].framework_ref, actor="Ada", rationale="Back")
    assert current_instructions(app.repo_root, project_path)[3] == "QualFrame standard instructions"
    assert ref in {v.framework_ref for v in instruction_versions(app.repo_root, project_path)}


def test_instructions_panel_saves_and_lists_versions(tmp_path: Path) -> None:
    from qualframe.coding_ui import render_coding

    root = ensure_workspace(tmp_path / "ws").root
    _, project_path, _ = create_demo_study(root, with_comparison=False)
    app = DashboardApp(ProjectRunner(project_path))
    page = render_coding(app)
    assert "Coding instructions" in page and "QualFrame standard instructions" in page
    from qualframe.coding_instructions import current_instructions
    text = current_instructions(app.repo_root, project_path)[2]
    message = app.handle_instructions("/instructions/save", {"instructions": [text + "\nPrefer whole sentences.\n"],
                                                               "label": ["Whole sentences"], "actor": ["Ada"]})
    assert "new version" in message
    page = render_coding(app)
    assert "Whole sentences" in page and "Use this version" in page and "claude-sonnet-5-5" in page


def test_a_sample_run_codes_only_the_chosen_transcripts_and_compares_on_them(tmp_path: Path) -> None:
    from qualframe.coding_ui import render_coding
    from qualframe.comparison_ui import render_comparison
    from qualframe.demo_study import PRIMARY_RECORDING, _use_recording

    root = ensure_workspace(tmp_path / "ws").root
    _, project_path, full_run = create_demo_study(root, with_comparison=False)
    app = DashboardApp(ProjectRunner(project_path))
    page = render_coding(app)
    assert "A sample to check the output and cost first" in page and "P04 nurse practitioner" in page
    files = [p.relative_to(app.repo_root).as_posix() for p in app.runner._transcript_files()]
    runner = ProjectRunner(project_path)
    runner.transcript_sample = set(files[:2])
    _use_recording(project_path, PRIMARY_RECORDING)
    plan = runner.build_run_plan()
    assert plan.transcript_sample == sorted(files[:2]) and len(plan.planned_stage_runs) == 2
    runner.save_run_plan(plan, "sample-run")
    ProjectRunner(project_path).execute_run_plan(plan, "sample-run")
    from qualframe.evidence_review import write_evidence_review_index
    index = write_evidence_review_index(project_manifest_path=project_path, run_id="sample-run")
    records = load_evidence_review_records(index)
    assert records and {r.source_path.replace("\\", "/") for r in records} <= set(files[:2])
    app = DashboardApp(ProjectRunner(project_path))
    compared = render_comparison(app, "sample-run", full_run)
    assert "Compared on the 2 transcripts both runs coded; 4 coded by only one run are left out." in compared
    assert "sample of 2" in compared and "Codes in common" in compared


def test_start_coding_with_a_sample_from_the_page(tmp_path: Path) -> None:
    import time
    from urllib.parse import parse_qs, urlparse

    root = ensure_workspace(tmp_path / "ws").root
    _, project_path, _ = create_demo_study(root, with_comparison=False)
    app = DashboardApp(ProjectRunner(project_path))
    first = app.runner._transcript_files()[0].relative_to(app.repo_root).as_posix()
    with pytest.raises(ValueError, match="at least one"):
        app.handle_app_action("/coding/start", {"scope": ["sample"], "actor": ["Ada"]})
    location = app.handle_app_action("/coding/start", {"scope": ["sample"], "sample": [first], "actor": ["Ada"]})
    run_id = parse_qs(urlparse(location).query)["run_id"][0]
    for _ in range(100):
        job = app._job_snapshot(run_id)
        if job is None or job.status != "running":
            break
        time.sleep(0.1)
    plan = json.loads((app.artifacts_dir / run_id / "run_plan.json").read_text(encoding="utf-8"))
    assert plan["transcript_sample"] == [first] and len(plan["planned_stage_runs"]) == 1
    manifest = json.loads((app.artifacts_dir / run_id / "run_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["artifact_paths"]) == 1
