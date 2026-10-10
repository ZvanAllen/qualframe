"""Immutable, artifact-bound QA inventories with legacy review-path preservation."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path

from qualframe.io.files import sha256_for_file, sha256_for_text
from qualframe.models import StageArtifact
from qualframe.qa.rules import ReviewQueueItem


def _serialized(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)


def _identity(value: dict) -> str:
    return sha256_for_text(_serialized(value))


def _within(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("QA inventory paths must be nonblank strings.")
    path = (root.resolve() / relative.replace("\\", "/")).resolve()
    if not path.is_relative_to(root.resolve()) or path.suffix != ".json":
        raise ValueError("QA inventory path is outside its declared root or is not JSON.")
    return path


def _write_immutable(path: Path, value: dict) -> str:
    text = _serialized(value)
    digest = sha256_for_text(text)
    if path.exists():
        if sha256_for_file(path) != digest:
            raise ValueError("Stored QA inventory or review item changed.")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(text)
    return digest


def _verified_inventory(artifact_root: Path, review_root: Path, manifest: dict) -> dict | None:
    relative = manifest.get("qa_inventory_path")
    expected_hash = manifest.get("qa_inventory_sha256")
    if relative is None and expected_hash is None:
        return None
    if (
        not isinstance(relative, str)
        or not relative
        or not isinstance(expected_hash, str)
        or not expected_hash
    ):
        raise ValueError("A declared QA inventory requires both its path and hash.")
    path = _within(artifact_root, relative)
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise ValueError("Run QA inventory hash differs from the manifest.")
    inventory = json.loads(content)
    if (
        not isinstance(inventory, dict)
        or not isinstance(inventory.get("items"), list)
        or not isinstance(inventory.get("artifact_hashes"), dict)
        or inventory.get("kind") != "qualframe_qa_inventory_v1"
        or inventory.get("run_id") != manifest.get("run_id")
        or len(inventory.get("items", [])) != manifest.get("qa_failure_count")
    ):
        raise ValueError("Run QA inventory identity or count differs from the manifest.")
    expected = {
        _within(artifact_root, relative).relative_to(artifact_root.resolve()).as_posix()
        for relative in manifest.get("artifact_paths", [])
    }
    if set(inventory.get("artifact_hashes", {})) != expected:
        raise ValueError("Run QA inventory scope differs from the manifest artifacts.")
    for relative, digest in inventory["artifact_hashes"].items():
        if sha256_for_file(_within(artifact_root, relative)) != digest:
            raise ValueError("QA inventory artifact changed.")
    seen_ids, seen_paths = set(), set()
    for item in inventory["items"]:
        required = {
            "item_id",
            "artifact_path",
            "artifact_sha256",
            "review_item_path",
            "review_item_sha256",
        }
        if (
            not isinstance(item, dict)
            or not required <= item.keys()
            or any(not isinstance(item[key], str) or not item[key] for key in required)
        ):
            raise ValueError("QA inventory item is incomplete.")
        if (
            item["artifact_path"] not in inventory["artifact_hashes"]
            or item["artifact_sha256"] != inventory["artifact_hashes"][item["artifact_path"]]
        ):
            raise ValueError("QA review item is not bound to an artifact in the inventory scope.")
        path = _within(review_root, item["review_item_path"])
        item_content = path.read_bytes()
        if (
            item["item_id"] in seen_ids
            or path in seen_paths
            or hashlib.sha256(item_content).hexdigest() != item["review_item_sha256"]
        ):
            raise ValueError("QA inventory review item is duplicated or changed.")
        payload = json.loads(item_content)
        keys = {field.name for field in dataclasses.fields(ReviewQueueItem)}
        if (
            not isinstance(payload, dict)
            or not keys <= payload.keys()
            or payload.get("run_id") != manifest["run_id"]
        ):
            raise ValueError("QA review item payload is malformed or belongs to another run.")
        if "qa_item_id" in payload and any(
            payload.get(key) != value
            for key, value in {
                "qa_item_id": item["item_id"],
                "artifact_path": item["artifact_path"],
                "artifact_sha256": item["artifact_sha256"],
            }.items()
        ):
            raise ValueError("Generated QA item attribution differs from its inventory.")
        seen_ids.add(item["item_id"])
        seen_paths.add(path)
    return inventory


def review_item_paths(artifact_root: Path, review_root: Path, manifest: dict) -> list[Path]:
    """Read current QA items; manifests without inventories retain legacy behavior.

    Legacy files absent from a new inventory remain unchanged on disk, along with
    their append-only adjudications. They are historical, not current QA findings.
    """
    inventory = _verified_inventory(artifact_root, review_root, manifest)
    if inventory is None:
        return sorted(review_root.glob("*.json"))
    paths = [_within(review_root, item["review_item_path"]) for item in inventory["items"]]
    # Disagreement records have their own identities and remain independently reviewable.
    for path in sorted(review_root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue  # Unassociated legacy files cannot replace a declared inventory.
        if isinstance(payload, dict) and payload.get("kind") == "disagreement":
            paths.append(path)
    return paths


def write_run_qa_inventory(
    *,
    run_id: str,
    artifact_root: Path,
    review_root: Path,
    artifact_paths: list[str],
    evaluate: Callable[[StageArtifact], list[ReviewQueueItem]],
) -> dict:
    """Rebuild QA once per unique manifest artifact, without rewriting artifacts.

    Reuse already bound review paths and legacy schema/method items with explicit
    source provenance so their adjudication IDs remain stable. Anonymous legacy
    row failures remain history; their decisions are never assigned to a guessed source.
    """
    artifact_root, review_root = artifact_root.resolve(), review_root.resolve()
    previous_path = artifact_root / "run_manifest.json"
    previous = (
        _verified_inventory(
            artifact_root,
            review_root,
            json.loads(previous_path.read_text(encoding="utf-8")),
        )
        if previous_path.exists()
        else None
    )
    bound = {item["item_id"]: item for item in previous["items"]} if previous else {}
    artifacts, desired = {}, []
    paths = dict.fromkeys(_within(artifact_root, value) for value in artifact_paths)
    structured_failures = 0
    for path in paths:
        relative = path.relative_to(artifact_root).as_posix()
        content = path.read_bytes()
        artifact = StageArtifact.model_validate_json(content)
        if artifact.run_id != run_id:
            raise ValueError("QA artifact belongs to another run.")
        digest = hashlib.sha256(content).hexdigest()
        artifacts[relative] = digest
        structured_failures += int(artifact.structured_output_valid is False)
        failures = sorted((dataclasses.asdict(item) for item in evaluate(artifact)), key=_identity)
        occurrences: Counter[str] = Counter()
        for failure in failures:
            signature = _identity(failure)
            occurrence = occurrences[signature]
            occurrences[signature] += 1
            identity = "qa-" + _identity(
                dict(
                    artifact_path=relative,
                    artifact_sha256=digest,
                    failure=failure,
                    occurrence=occurrence,
                )
            )
            desired.append(
                dict(
                    item_id=identity,
                    artifact_path=relative,
                    artifact_sha256=digest,
                    input_path=artifact.input_path,
                    failure=failure,
                    failure_signature=signature,
                )
            )
        if sha256_for_file(path) != digest:
            raise ValueError("Artifact changed while rebuilding QA.")

    legacy: dict[str, list[Path]] = defaultdict(list)
    keys = {field.name for field in dataclasses.fields(ReviewQueueItem)}
    for path in sorted(review_root.glob("*.json")):
        path = _within(review_root, path.relative_to(review_root).as_posix())
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict) and set(payload) == keys and payload.get("run_id") == run_id:
            legacy[_identity(payload)].append(path)
    multiplicity = Counter(item["failure_signature"] for item in desired)
    items, used_paths = [], set()
    for item in desired:
        old = bound.get(item["item_id"])
        candidates = legacy.get(item["failure_signature"], [])
        if old:
            path = _within(review_root, old["review_item_path"])
            digest = old["review_item_sha256"]
        elif (
            len(candidates) == 1
            and multiplicity[item["failure_signature"]] == 1
            and item["failure"]["rule_id"] in {"structured_output_schema", "directed_method_policy"}
            and item["failure"]["row_data"] == {"input_path": item["input_path"]}
        ):
            path = candidates[0]
            content = path.read_bytes()
            if _identity(json.loads(content)) != item["failure_signature"]:
                raise ValueError("Legacy QA item changed while binding its source.")
            digest = hashlib.sha256(content).hexdigest()
        else:
            path = review_root / "generated" / f"{item['item_id']}.json"
            digest = _write_immutable(
                path,
                dict(
                    **item["failure"],
                    qa_item_id=item["item_id"],
                    artifact_path=item["artifact_path"],
                    artifact_sha256=item["artifact_sha256"],
                ),
            )
        if path in used_paths:
            raise ValueError("A review decision path cannot represent two QA findings.")
        used_paths.add(path)
        items.append(
            dict(
                item_id=item["item_id"],
                artifact_path=item["artifact_path"],
                artifact_sha256=item["artifact_sha256"],
                review_item_path=path.relative_to(review_root).as_posix(),
                review_item_sha256=digest,
            )
        )
    inventory = dict(
        kind="qualframe_qa_inventory_v1",
        run_id=run_id,
        artifact_hashes=artifacts,
        items=items,
        unassociated_legacy_paths=[
            path.relative_to(review_root).as_posix()
            for values in legacy.values()
            for path in values
            if path not in used_paths
        ],
    )
    path = artifact_root / "qa" / f"inventory-{_identity(inventory)}.json"
    digest = _write_immutable(path, inventory)
    return dict(
        artifact_paths=list(artifacts),
        qa_failure_count=len(items),
        structured_output_failure_count=structured_failures,
        qa_inventory_path=path.relative_to(artifact_root).as_posix(),
        qa_inventory_sha256=digest,
    )
