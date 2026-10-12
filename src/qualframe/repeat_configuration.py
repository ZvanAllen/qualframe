"""Match completed runs by saved coding settings, never by display labels or current files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from qualframe.configuration_lock import SPENDING_KINDS
from qualframe.models import ProviderConfig


def locked_run_configuration(run_root: Path) -> dict:
    """Return the coding identity and readable settings recorded when this run started.

    Project identity/path and spending asset hashes are excluded: the project file combines
    study identity and spending settings with coding settings, whose own assets are locked.
    Asset paths are locators, so identical configurations can match across study folders.
    Missing historical records are not evidence that configurations match.
    """
    try:
        lock = json.loads((run_root / "analysis_configuration_lock.json").read_text(encoding="utf-8"))
        settings = json.loads((run_root / "run_settings.json").read_text(encoding="utf-8"))
        provider = settings["provider"]
        assets = lock["assets"]
        if not isinstance(provider, dict) or not provider.get("name") or not isinstance(assets, list):
            raise ValueError("Missing provider settings or locked assets.")
        required_provider_fields = set(ProviderConfig.model_fields) - {"api_key_env"}
        if required_provider_fields - provider.keys():
            raise ValueError("Missing saved provider settings: " + ", ".join(sorted(required_provider_fields - provider.keys())))
        coding_assets = []
        for asset in assets:
            if asset["kind"] in (*SPENDING_KINDS, "project"):
                continue
            if not all(asset.get(key) for key in ("kind", "id", "sha256")):
                raise ValueError("A locked coding asset has no identity or hash.")
            coding_assets.append({key: asset[key] for key in ("kind", "id", "sha256")})
        kinds = {asset["kind"] for asset in coding_assets}
        required = {"provider", "framework", "pipeline", "prompt_set", "prompt", "codebook"}
        if settings.get("method_id"):
            required.add("method")
        if required - kinds:
            raise ValueError("Missing locked coding assets: " + ", ".join(sorted(required - kinds)))
        # The original provider hash includes api_key_env, which is commonly study-specific.
        # Require that locked asset, but compare every saved inference field instead of its raw hash.
        coding_assets = [asset for asset in coding_assets if asset["kind"] != "provider"]
        provider = {key: value for key, value in provider.items() if key != "api_key_env"}
        configuration = dict(provider=provider, assets=sorted(coding_assets, key=lambda a: (a["kind"], a["id"], a["sha256"])))
        canonical = json.dumps(configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return dict(eligible=False, reason=f"Saved configuration is incomplete or unreadable ({type(exc).__name__}).")
    return dict(eligible=True, fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(), **configuration)


def automatic_stability_groups(runs: list[tuple[str, Path]]) -> tuple[list[dict], list[dict]]:
    """Group selected local and cross-study run IDs; return skipped-record explanations too."""
    groups: dict[str, dict] = {}
    skipped = []
    for run_id, root in runs:
        configuration = locked_run_configuration(root)
        if not configuration["eligible"]:
            skipped.append(dict(run_id=run_id, reason=configuration["reason"]))
            continue
        key = configuration["fingerprint"]
        group = groups.setdefault(key, dict(fingerprint=key, members=[], provider=configuration["provider"], assets=configuration["assets"]))
        if run_id not in group["members"]:
            group["members"].append(run_id)
    return [group for group in groups.values() if len(group["members"]) > 1], skipped
