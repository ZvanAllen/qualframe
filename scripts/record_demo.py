"""Record coding responses over the bundled demo dataset so the demo can replay them offline.

Real recording (sends the six fictional demo transcripts to the provider; costs cents). A preset
from config/model_presets.yaml supplies the model, settings and prices; API keys come from the
environment or the .env file next to this repository's README:

    python scripts/record_demo.py --name claude-sonnet-5-5-2026-10 --label "Claude Sonnet 5.5" \
        --preset anthropic-sonnet-5-5 --yes

    python scripts/record_demo.py --name gpt-oss-20b-ollama-2026-10 --label "gpt-oss-20b (Ollama)" \
        --preset local-ollama --yes

Any preset value can be overridden (--model, --base-url, --temperature, ...). Spending is capped
by --limit-usd (default $1), using the same cost controls as the app.

Illustrative recording (no model; replays hand-written codings, clearly labelled as such):

    python scripts/record_demo.py --name demo-illustrative-a --label "Illustrative coder A" \
        --illustrative demo/datasets/ai-scribe/illustrative/recording_a.json

Responses are stored under demo/recordings/<name>/ keyed by transcript hash, together with
the exact provider settings and prompt hash. Only the fictional demo transcripts are sent.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=False)

from qualframe.app_workspace import ensure_workspace  # noqa: E402
from qualframe.io.files import sha256_for_file  # noqa: E402
from qualframe.pipeline import project_runner as runner_module  # noqa: E402
from qualframe.pipeline.project_runner import ProjectRunner  # noqa: E402
from qualframe.provider_setup import ProviderSetup, save_provider_setup  # noqa: E402
from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage, estimate_tokens  # noqa: E402
from qualframe.providers.recorded_provider import recording_key, transcript_from_prompt  # noqa: E402
from qualframe.study_setup import StudyWorkspace  # noqa: E402

DATASET = REPO_ROOT / "demo/datasets/ai-scribe"


class IllustrativeProvider(LLMProvider):
    """Answers with hand-written codings for the demo participant named in the transcript."""

    name = "illustrative"

    def __init__(self, codings: dict[str, list[dict]]) -> None:
        self.codings = codings

    def complete(self, *, system_prompt, user_prompt, attachments=None, response_schema=None):
        transcript = transcript_from_prompt(user_prompt) or ""
        match = re.search(r"Participant (P\d\d),", transcript)
        rows = self.codings.get(match.group(1), []) if match else []
        text = json.dumps({"codings": rows}, ensure_ascii=False, indent=1)
        return LLMResponse(text=text, model="illustrative", provider=self.name,
                           usage=LLMUsage(input_tokens=estimate_tokens(user_prompt), output_tokens=estimate_tokens(text)))


class CapturingProvider(LLMProvider):
    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.captured: list[tuple[str, LLMResponse]] = []

    def complete(self, *, system_prompt, user_prompt, attachments=None, response_schema=None):
        kwargs = {"response_schema": response_schema} if response_schema is not None else {}
        response = self.inner.complete(system_prompt=system_prompt, user_prompt=user_prompt, **kwargs)
        self.captured.append((user_prompt, response))
        return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="Folder name, e.g. sonnet-5-5-2026-10")
    parser.add_argument("--label", required=True, help="Name shown in the app")
    parser.add_argument("--illustrative", type=Path, help="Hand-written codings JSON (no model call)")
    parser.add_argument("--preset", help="Model preset id from config/model_presets.yaml")
    parser.add_argument("--provider", choices=["openai", "anthropic", "openai_compatible"])
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--input-rate", type=float, help="USD per million input tokens")
    parser.add_argument("--output-rate", type=float, help="USD per million output tokens")
    parser.add_argument("--limit-usd", type=float, default=1.0, help="Spending ceiling for this recording")
    parser.add_argument("--yes", action="store_true", help="Confirm sending the demo transcripts to the provider")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.name):
        parser.error("Use letters, numbers, hyphens and underscores for --name.")
    target = REPO_ROOT / "demo/recordings" / args.name
    if target.exists():
        parser.error(f"{target} already exists; choose a new name.")
    preset: dict = {}
    checked_on = None
    if args.preset:
        catalogue = yaml.safe_load((REPO_ROOT / "config/model_presets.yaml").read_text(encoding="utf-8"))
        presets = {item["id"]: item for item in catalogue["presets"]}
        if args.preset not in presets:
            parser.error(f"Unknown preset. Choose one of: {', '.join(presets)}")
        preset = presets[args.preset]
        checked_on = catalogue.get("checked_on")
        args.provider = args.provider or preset["provider"]
        args.model = args.model or preset.get("model")
        args.base_url = args.base_url or preset.get("base_url") or None
    if not args.illustrative and not (args.provider and args.model):
        parser.error("Give --illustrative, or --preset, or --provider and --model.")
    if args.provider and not args.yes:
        parser.error("Add --yes to confirm sending the six fictional demo transcripts to the provider.")

    workspace = Path(tempfile.mkdtemp(prefix="qualframe-record-"))
    try:
        ensure_workspace(workspace)
        created = StudyWorkspace(workspace).create_from_dataset(dataset_root=DATASET, title="Recording study")
        project_path = workspace / created.project_manifest_path
        settings: dict = {"name": "mock", "model": "illustrative"}
        if args.provider:
            def pick(name, default=None):
                value = getattr(args, name)
                return value if value is not None else preset.get(name, default)

            reasoning = pick("reasoning_effort")
            setup = ProviderSetup(
                provider=args.provider,
                model=args.model,
                max_tokens=pick("max_tokens", 16000),
                temperature=None if reasoning else pick("temperature"),
                api_mode="responses" if (reasoning or preset.get("api_mode") == "responses") else "chat_completions",
                reasoning_effort=reasoning,
                absolute_limit_usd=args.limit_usd,
                input_rate=pick("input_rate", 0),
                output_rate=pick("output_rate", 0),
                pricing_date=checked_on or datetime.now(timezone.utc).date().isoformat(),
                pricing_source=preset.get("pricing_source", ""),
                governance_confirmed=True,
                base_url=args.base_url,
            )
            save_provider_setup(StudyWorkspace(workspace), project_path, setup, actor="record_demo.py",
                                rationale="Record demo responses over fictional transcripts",
                                use_environment_key=True)
            settings = {key: value for key, value in yaml.safe_load(project_path.read_text(encoding="utf-8"))["provider"].items()
                        if value is not None and key != "api_key_env"}
            settings["prices_usd_per_million"] = {"input": setup.input_rate, "output": setup.output_rate,
                                                  "checked_on": str(setup.pricing_date)}

        original_build = runner_module.build_provider
        capture: CapturingProvider | None = None

        def build(config):
            nonlocal capture
            inner = (IllustrativeProvider(json.loads(args.illustrative.read_text(encoding="utf-8")))
                     if args.illustrative else original_build(config))
            capture = CapturingProvider(inner)
            return capture

        runner_module.build_provider = build
        try:
            runner = ProjectRunner(project_path)
            plan = runner.build_run_plan()
            runner.save_run_plan(plan, "recording")
            runner.execute_run_plan(plan, "recording")
        finally:
            runner_module.build_provider = original_build

        (target / "responses").mkdir(parents=True)
        usage = {"input_tokens": 0, "output_tokens": 0}
        for prompt, response in capture.captured if capture else []:
            key = recording_key(prompt)
            (target / "responses" / f"{key}.txt").write_text(response.text, encoding="utf-8")
            if response.usage:
                usage["input_tokens"] += response.usage.input_tokens + response.usage.cached_input_tokens
                usage["output_tokens"] += response.usage.output_tokens + response.usage.reasoning_tokens
        prompt_file = workspace / "prompts/directed/v3/directed_coding.md"
        info = {
            "id": args.name,
            "label": args.label,
            "kind": "illustrative" if args.illustrative else "model",
            "description": (
                "Hand-written example codings for demonstrating the software. Not output from a model."
                if args.illustrative else f"Responses recorded from {args.label} over the fictional demo transcripts."
            ),
            "provider_settings": settings,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dataset": DATASET.name,
            "prompt_sha256": sha256_for_file(prompt_file),
            "requests": len(capture.captured) if capture else 0,
            "reported_usage": usage,
            "response_status": sorted({response.status or "unknown" for _, response in (capture.captured if capture else [])}),
        }
        rates = settings.get("prices_usd_per_million")
        if rates:
            info["estimated_cost_usd"] = round(
                (usage["input_tokens"] * rates["input"] + usage["output_tokens"] * rates["output"]) / 1_000_000, 4)
        (target / "recording.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        print(f"Saved {info['requests']} responses to {target.relative_to(REPO_ROOT)}")
        print(f"Tokens: {usage['input_tokens']} in, {usage['output_tokens']} out; status: {', '.join(info['response_status'])}"
              + (f"; about ${info['estimated_cost_usd']:.3f}" if "estimated_cost_usd" in info else ""))
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
