from __future__ import annotations

import json
import csv
import io
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from qualframe.config import load_project_manifest, resolve_repo_path
from qualframe.io.files import sha256_for_file
from qualframe.io.transcript_io import transcript_to_text
from qualframe.models import (
    CodebookSpec,
    CreatedStudy,
    MethodPolicyUpdate,
    MethodSpec,
    SourceImportRecord,
    StudyChangeAction,
    StudyCreationRequest,
)


_MAX_IMPORT_BYTES = 25 * 1024 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify_study_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:64].rstrip("-")
    if len(slug) < 3:
        slug = f"study-{uuid.uuid4().hex[:8]}"
    return slug


class StudyWorkspace:
    """Create local study folders and manifests without mutating source fixtures."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.studies_root = self.repo_root / "studies"

    def create(self, request: StudyCreationRequest) -> CreatedStudy:
        study_id = request.study_id or slugify_study_id(request.title)
        final_root = (self.studies_root / study_id).resolve()
        if not final_root.is_relative_to(self.studies_root.resolve()):
            raise ValueError("Study ID escaped the local studies folder.")
        if final_root.exists():
            raise FileExistsError(
                f"A study with ID '{study_id}' already exists. Choose another ID."
            )

        self.studies_root.mkdir(parents=True, exist_ok=True)
        temp_root = Path(
            tempfile.mkdtemp(prefix=".qualframe-new-", dir=self.studies_root)
        )
        try:
            imported = self._write_study(
                temp_root=temp_root,
                final_root=final_root,
                study_id=study_id,
                request=request,
            )
            load_project_manifest(temp_root / "project.yaml")
            temp_root.replace(final_root)
        except Exception:
            if temp_root.exists() and temp_root.is_relative_to(self.studies_root):
                shutil.rmtree(temp_root)
            raise

        manifest_path = final_root / "project.yaml"
        load_project_manifest(manifest_path)
        return CreatedStudy(
            study_id=study_id,
            title=request.title,
            project_manifest_path=str(manifest_path.relative_to(self.repo_root)),
            data_classification=request.data_classification,
            template=request.template,
            imported_source_count=len(imported),
        )

    def managed_study_root(self, project_manifest_path: Path) -> Path:
        project_path = project_manifest_path.resolve()
        studies_root = self.studies_root.resolve()
        if project_path.name != "project.yaml" or not project_path.is_relative_to(
            studies_root
        ):
            raise ValueError(
                "Imports and policy editing are available only for studies created "
                "inside the local studies folder."
            )
        study_root = project_path.parent
        if study_root.parent != studies_root:
            raise ValueError("Managed study must be a direct child of the studies folder.")
        return study_root

    def import_transcript(
        self,
        *,
        project_manifest_path: Path,
        filename: str,
        content: bytes,
        group_label: str,
        actor: str,
        rationale: str,
    ) -> SourceImportRecord:
        actor, rationale = self._validate_action_fields(actor, rationale)
        study_root = self.managed_study_root(project_manifest_path)
        project = load_project_manifest(project_manifest_path)
        safe_name = self._safe_filename(filename, {".txt", ".docx"})
        if any(
            record.source_kind == "transcript"
            and record.original_filename.casefold() == safe_name.casefold()
            for record in self._source_records(project)
        ):
            raise FileExistsError(
                f"A transcript named '{safe_name}' is already registered in this study."
            )
        group = group_label.strip() or "Ungrouped"
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,79}", group):
            raise ValueError(
                "Group label may contain letters, numbers, spaces, hyphens, and underscores."
            )
        self._validate_import_size(content)
        transcript_root = resolve_repo_path(
            self.repo_root, project.paths["raw_transcripts"]
        ).resolve()
        if not transcript_root.is_relative_to(study_root):
            raise ValueError("Transcript destination escaped the managed study.")
        destination = (transcript_root / group / safe_name).resolve()
        if not destination.is_relative_to(transcript_root):
            raise ValueError("Transcript destination escaped the transcript folder.")
        if destination.exists():
            raise FileExistsError(
                f"Transcript '{safe_name}' already exists in group '{group}'."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_name(f".upload-{uuid.uuid4().hex}{destination.suffix}")
        try:
            temp_path.write_bytes(content)
            if destination.suffix.lower() == ".txt":
                content.decode("utf-8")
            else:
                transcript_to_text(temp_path)
            temp_path.replace(destination)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        record = self._uploaded_record(
            project=project,
            source_kind="transcript",
            filename=safe_name,
            destination=destination,
            actor=actor,
            rationale=rationale,
        )
        self._append_source_record(project, record)
        return record

    def import_codebook(
        self,
        *,
        project_manifest_path: Path,
        filename: str,
        content: bytes,
        actor: str,
        rationale: str,
    ) -> SourceImportRecord:
        actor, rationale = self._validate_action_fields(actor, rationale)
        study_root = self.managed_study_root(project_manifest_path)
        project = load_project_manifest(project_manifest_path)
        safe_name = self._safe_filename(filename, {".yaml", ".yml"})
        self._validate_import_size(content)
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Codebook YAML must use UTF-8 encoding.") from exc
        data = yaml.safe_load(decoded)
        if not isinstance(data, dict):
            raise ValueError("Codebook YAML must contain a top-level mapping.")
        codebook = CodebookSpec.model_validate(data)
        config_dir = study_root / "config"
        version_path = self._next_version_path(config_dir, "codebook", ".yaml")
        version_path.write_text(
            yaml.safe_dump(codebook.model_dump(exclude_none=True), sort_keys=False),
            encoding="utf-8",
        )
        record = self._uploaded_record(
            project=project,
            source_kind="codebook",
            filename=safe_name,
            destination=version_path,
            actor=actor,
            rationale=rationale,
        )
        previous = project.codebook
        relative = version_path.relative_to(self.repo_root).as_posix()
        self._update_project_reference(
            project_manifest_path, "codebook", relative
        )
        self._append_source_record(project, record)
        self._append_change(
            study_root,
            project_id=project.project_id,
            change_kind="codebook_import",
            previous_ref=previous,
            new_ref=relative,
            actor=actor,
            rationale=rationale,
        )
        return record

    def import_metadata(
        self,
        *,
        project_manifest_path: Path,
        filename: str,
        content: bytes,
        actor: str,
        rationale: str,
    ) -> SourceImportRecord:
        actor, rationale = self._validate_action_fields(actor, rationale)
        study_root = self.managed_study_root(project_manifest_path)
        project = load_project_manifest(project_manifest_path)
        safe_name = self._safe_filename(filename, {".csv"})
        self._validate_import_size(content)
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Metadata CSV must use UTF-8 encoding.") from exc
        reader = csv.DictReader(io.StringIO(decoded))
        fieldnames = reader.fieldnames or []
        if "source_filename" not in fieldnames:
            raise ValueError("Metadata CSV requires a 'source_filename' column.")
        rows = list(reader)
        if not rows:
            raise ValueError("Metadata CSV must contain at least one data row.")
        values = [row.get("source_filename", "").strip() for row in rows]
        if any(not value for value in values):
            raise ValueError("Metadata source_filename values cannot be blank.")
        if len(values) != len(set(values)):
            raise ValueError("Metadata source_filename values must be unique.")
        known = {
            record.original_filename
            for record in self._source_records(project)
            if record.source_kind == "transcript"
        }
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(
                "Metadata references transcripts not imported into this study: "
                + ", ".join(unknown)
            )
        reference_dir = study_root / "data/reference"
        version_path = self._next_version_path(reference_dir, "metadata", ".csv")
        version_path.write_text(decoded, encoding="utf-8")
        record = self._uploaded_record(
            project=project,
            source_kind="metadata",
            filename=safe_name,
            destination=version_path,
            actor=actor,
            rationale=rationale,
        )
        previous = project.metadata_file
        relative = version_path.relative_to(self.repo_root).as_posix()
        self._update_project_reference(
            project_manifest_path, "metadata_file", relative
        )
        self._append_source_record(project, record)
        self._append_change(
            study_root,
            project_id=project.project_id,
            change_kind="metadata_import",
            previous_ref=previous,
            new_ref=relative,
            actor=actor,
            rationale=rationale,
        )
        return record

    def update_method_policy(
        self,
        *,
        project_manifest_path: Path,
        update: MethodPolicyUpdate,
        actor: str,
        rationale: str,
    ) -> Path:
        actor, rationale = self._validate_action_fields(actor, rationale)
        study_root = self.managed_study_root(project_manifest_path)
        project = load_project_manifest(project_manifest_path)
        if not project.method:
            raise ValueError("Study does not have a method configuration to revise.")
        method_path = resolve_repo_path(self.repo_root, project.method)
        method = MethodSpec.model_validate(
            yaml.safe_load(method_path.read_text(encoding="utf-8"))
        )
        version_path = self._next_version_path(study_root / "config", "method", ".yaml")
        version_number = int(re.search(r"_v(\d+)\.yaml$", version_path.name).group(1))
        data = method.model_dump(exclude_none=True)
        data["id"] = f"{project.project_id}_method_v{version_number}"
        data["version"] = f"1.0.{version_number - 1}"
        data["segmentation"]["strategy"] = update.segmentation_strategy
        data["context"]["before"] = update.context_before
        data["context"]["after"] = update.context_after
        data["coding"]["cardinality"] = update.coding_cardinality
        data["coding"]["allow_overlapping_spans"] = update.allow_overlapping_spans
        if update.coding_cardinality == "single_label":
            data["coding"]["max_codes_per_unit"] = 1
        else:
            data["coding"].pop("max_codes_per_unit", None)
        data["partitioning"]["strategy"] = update.partition_strategy
        revised = MethodSpec.model_validate(data)
        version_path.write_text(
            yaml.safe_dump(revised.model_dump(exclude_none=True), sort_keys=False),
            encoding="utf-8",
        )
        previous = project.method
        relative = version_path.relative_to(self.repo_root).as_posix()
        self._update_project_reference(project_manifest_path, "method", relative)
        self._append_change(
            study_root,
            project_id=project.project_id,
            change_kind="method_update",
            previous_ref=previous,
            new_ref=relative,
            actor=actor,
            rationale=rationale,
        )
        return version_path

    def source_records(self, project_manifest_path: Path) -> list[SourceImportRecord]:
        self.managed_study_root(project_manifest_path)
        return self._source_records(load_project_manifest(project_manifest_path))

    def _write_study(
        self,
        *,
        temp_root: Path,
        final_root: Path,
        study_id: str,
        request: StudyCreationRequest,
    ) -> list[SourceImportRecord]:
        for relative in (
            "data/raw/transcripts",
            "data/raw/workbooks",
            "data/reference",
            "data/working",
            "artifacts",
            "review_queue",
            "exports",
            "logs",
            "config",
        ):
            (temp_root / relative).mkdir(parents=True, exist_ok=True)

        project_relative = final_root.relative_to(self.repo_root).as_posix()
        imported: list[SourceImportRecord] = []
        codebook_path: str | None = None
        base_method_name = (
            "directed_content_analysis_v1.yaml"
            if request.template == "generic_directed"
            else "cfir_directed_content_analysis_v1.yaml"
        )
        base_method_path = self.repo_root / "config/methods" / base_method_name
        method_data = yaml.safe_load(base_method_path.read_text(encoding="utf-8"))
        method_data["id"] = f"{study_id}_method_v1"
        method_data["name"] = f"{request.title} analysis method"
        local_method = temp_root / "config/method_v1.yaml"
        local_method.write_text(
            yaml.safe_dump(method_data, sort_keys=False), encoding="utf-8"
        )
        method_path = f"{project_relative}/config/method_v1.yaml"
        if request.template == "generic_directed":
            source_codebook = (
                self.repo_root / "config/codebooks/example_directed_codebook_v1.yaml"
            )
            destination = temp_root / "config/codebook_v1.yaml"
            shutil.copy2(source_codebook, destination)
            codebook_path = f"{project_relative}/config/codebook_v1.yaml"
            imported.append(
                self._record_import(
                    source=source_codebook,
                    destination=destination,
                    final_destination=f"{project_relative}/config/codebook_v1.yaml",
                    source_kind="codebook",
                )
            )

        if request.include_synthetic_fixtures:
            fixtures_root = self.repo_root / (
                "demo/fixtures/directed_transcripts"
                if request.template == "generic_directed"
                else "demo/fixtures/transcripts"
            )
            for source in sorted(fixtures_root.rglob("*")):
                if not source.is_file():
                    continue
                relative = source.relative_to(fixtures_root)
                destination = temp_root / "data/raw/transcripts" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                imported.append(
                    self._record_import(
                        source=source,
                        destination=destination,
                        final_destination=(
                            f"{project_relative}/data/raw/transcripts/"
                            f"{relative.as_posix()}"
                        ),
                        source_kind="transcript",
                    )
                )
            if request.template == "cfir":
                source_codebook = self.repo_root / "demo/fixtures/reference/codebook.txt"
                destination = temp_root / "data/reference/codebook.txt"
                shutil.copy2(source_codebook, destination)
                imported.append(
                    self._record_import(
                        source=source_codebook,
                        destination=destination,
                        final_destination=f"{project_relative}/data/reference/codebook.txt",
                        source_kind="codebook",
                    )
                )

        manifest = self._manifest(
            study_id=study_id,
            title=request.title,
            classification=request.data_classification,
            template=request.template,
            project_relative=project_relative,
            codebook_path=codebook_path,
            method_path=method_path,
        )
        (temp_root / "project.yaml").write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )
        manifest_path = temp_root / "source_import_manifest.jsonl"
        manifest_path.write_text(
            "".join(record.model_dump_json() + "\n" for record in imported),
            encoding="utf-8",
        )
        return imported

    def _record_import(
        self,
        *,
        source: Path,
        destination: Path,
        final_destination: str,
        source_kind: str,
    ) -> SourceImportRecord:
        return SourceImportRecord(
            source_id=f"source-{uuid.uuid4().hex}",
            source_kind=source_kind,
            original_filename=source.name,
            destination_path=final_destination,
            sha256=sha256_for_file(destination),
            imported_at_utc=_utc_now(),
            provenance="checked_in_synthetic_fixture",
        )

    def _safe_filename(self, filename: str, allowed_suffixes: set[str]) -> str:
        normalized = filename.replace("\\", "/")
        safe_name = Path(normalized).name.strip()
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("Uploaded file must have a valid filename.")
        if len(safe_name) > 180:
            raise ValueError("Uploaded filename is too long.")
        if Path(safe_name).suffix.lower() not in allowed_suffixes:
            allowed = ", ".join(sorted(allowed_suffixes))
            raise ValueError(f"Unsupported file type. Allowed: {allowed}.")
        return safe_name

    def _validate_import_size(self, content: bytes) -> None:
        if not content:
            raise ValueError("Uploaded file is empty.")
        if len(content) > _MAX_IMPORT_BYTES:
            raise ValueError("Uploaded file exceeds the 25 MB local import limit.")

    def _next_version_path(
        self,
        directory: Path,
        stem: str,
        suffix: str,
    ) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        version = 1
        while (directory / f"{stem}_v{version}{suffix}").exists():
            version += 1
        return directory / f"{stem}_v{version}{suffix}"

    def _source_records(self, project: object) -> list[SourceImportRecord]:
        source_manifest = getattr(project, "source_manifest", None)
        if not source_manifest:
            return []
        path = resolve_repo_path(self.repo_root, source_manifest)
        if not path.exists():
            return []
        return [
            SourceImportRecord.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _append_source_record(
        self,
        project: object,
        record: SourceImportRecord,
    ) -> None:
        source_manifest = getattr(project, "source_manifest", None)
        if not source_manifest:
            raise ValueError("Managed study does not define a source import manifest.")
        path = resolve_repo_path(self.repo_root, source_manifest)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    def _uploaded_record(
        self,
        *,
        project: object,
        source_kind: str,
        filename: str,
        destination: Path,
        actor: str,
        rationale: str,
    ) -> SourceImportRecord:
        return SourceImportRecord(
            source_id=f"source-{uuid.uuid4().hex}",
            source_kind=source_kind,
            original_filename=filename,
            destination_path=destination.relative_to(self.repo_root).as_posix(),
            sha256=sha256_for_file(destination),
            imported_at_utc=_utc_now(),
            provenance="researcher_import",
            imported_by=actor,
            rationale=rationale,
        )

    def _validate_action_fields(self, actor: str, rationale: str) -> tuple[str, str]:
        actor = actor.strip()
        rationale = rationale.strip()
        if not actor or not rationale:
            raise ValueError("Imports and configuration changes require researcher name and rationale.")
        return actor, rationale

    def _update_project_reference(
        self,
        project_manifest_path: Path,
        field: str,
        value: str,
    ) -> None:
        data = yaml.safe_load(project_manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Project manifest must contain a top-level mapping.")
        data[field] = value
        load_project_manifest_data = dict(data)
        from qualframe.models import ProjectManifest

        ProjectManifest.model_validate(load_project_manifest_data)
        temp_path = project_manifest_path.with_name(
            f".project-{uuid.uuid4().hex}.yaml"
        )
        try:
            temp_path.write_text(
                yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
            )
            temp_path.replace(project_manifest_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _append_change(
        self,
        study_root: Path,
        *,
        project_id: str,
        change_kind: str,
        previous_ref: str | None,
        new_ref: str,
        actor: str,
        rationale: str,
    ) -> StudyChangeAction:
        action = StudyChangeAction(
            action_id=f"study-change-{uuid.uuid4().hex}",
            project_id=project_id,
            change_kind=change_kind,
            previous_ref=previous_ref,
            new_ref=new_ref,
            actor=actor,
            rationale=rationale,
            timestamp_utc=_utc_now(),
        )
        path = study_root / "logs/study_changes.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(action.model_dump_json() + "\n")
        return action

    def _manifest(
        self,
        *,
        study_id: str,
        title: str,
        classification: str,
        template: str,
        project_relative: str,
        codebook_path: str | None,
        method_path: str,
    ) -> dict[str, object]:
        paths = {
            "raw_transcripts": f"{project_relative}/data/raw/transcripts",
            "raw_workbooks": f"{project_relative}/data/raw/workbooks",
            "reference": f"{project_relative}/data/reference",
            "working": f"{project_relative}/data/working",
            "artifacts": f"{project_relative}/artifacts",
            "review_queue": f"{project_relative}/review_queue",
            "exports": f"{project_relative}/exports",
            "logs": f"{project_relative}/logs",
        }
        common: dict[str, object] = {
            "project_id": study_id,
            "title": title,
            "created_at_utc": _utc_now(),
            "data_classification": classification,
            "source_manifest": f"{project_relative}/source_import_manifest.jsonl",
            "mode": "transcript_first",
            "paths": paths,
            "governance": {
                "enforce_review_gates": False,
                "require_release_for_export": False,
            },
            "structured_output": {
                "enforce": False,
                "spec": "config/schemas/cfir_stage_outputs_v1.yaml",
            },
        }
        if template == "generic_directed":
            common.update(
                {
                    "framework": "config/frameworks/example_directed_v1.yaml",
                    "pipeline": "config/pipelines/directed_content_analysis_contracts_v1.yaml",
                    "method": method_path,
                    "codebook": codebook_path,
                    "review_policy": "config/review_policies/calibration_then_risk_v1.yaml",
                    "analysis_plan": "config/analysis_plans/example_group_comparison_v1.yaml",
                    "cost_policy": "config/cost_policies/example_local_email_20_usd_v1.yaml",
                    "pricing_snapshot": "config/pricing/mock_pricing_v1.yaml",
                    "provider": {
                        "name": "mock",
                        "model": "synthetic-contract-fixture",
                        "temperature": 0.0,
                        "max_tokens": 4000,
                    },
                }
            )
        else:
            common.update(
                {
                    "framework": "config/frameworks/cfir_v1.yaml",
                    "pipeline": "config/pipelines/transcript_cfir.yaml",
                    "method": method_path,
                    "provider": {
                        "name": "cached_demo",
                        "model": "qualframe-synthetic-cache-v1",
                        "temperature": 0.0,
                        "max_tokens": 32000,
                    },
                }
            )
        return common
