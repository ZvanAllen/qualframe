"""Study-scoped Excel previews and explicit version activation."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import yaml

from qualframe.codebook_excel import FIELDS, convert_excel, read_excel
from qualframe.config import load_pipeline_spec, load_project_manifest, resolve_repo_path
from qualframe.io.files import sha256_for_file
from qualframe.study_setup import StudyWorkspace


class ExcelImportWorkflow:
    def __init__(self, workspace: StudyWorkspace, project_path: Path) -> None:
        self.workspace = workspace
        self.project_path = project_path
        self.root = workspace.managed_study_root(project_path) / "data/working/codebook_previews"

    def stage(self, filename: str, content: bytes, actor: str, rationale: str) -> str:
        project = load_project_manifest(self.project_path)
        pipeline = load_pipeline_spec(resolve_repo_path(self.workspace.repo_root, project.pipeline))
        if any(stage.domain_iterations for stage in pipeline.stages):
            raise ValueError(
                "Excel column mapping is available for the generic Directed content analysis "
                "template. Legacy CFIR uses its separately configured reference workbook."
            )
        self.workspace._safe_filename(filename, {".xlsx"})
        self.workspace._validate_action_fields(actor, rationale)
        read_excel(content)
        token = uuid.uuid4().hex
        folder = self.root / token
        folder.mkdir(parents=True)
        (folder / "source.xlsx").write_bytes(content)
        (folder / "import.json").write_text(
            json.dumps(
                {
                    "filename": filename,
                    "actor": actor.strip(),
                    "rationale": rationale.strip(),
                    "sha256": sha256_for_file(folder / "source.xlsx"),
                }
            ),
            encoding="utf-8",
        )
        return token

    def load(self, token: str) -> tuple[bytes, dict]:
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            raise ValueError("Invalid workbook preview identifier.")
        folder = (self.root / token).resolve()
        if not folder.is_relative_to(self.root.resolve()):
            raise ValueError("Preview escaped the study.")
        try:
            metadata = json.loads((folder / "import.json").read_text(encoding="utf-8"))
            if sha256_for_file(folder / "source.xlsx") != metadata["sha256"]:
                raise ValueError("The preview source changed. Upload the workbook again.")
            return (folder / "source.xlsx").read_bytes(), metadata
        except FileNotFoundError as exc:
            raise ValueError(
                "Workbook preview was not found in this study. Upload it again."
            ) from exc

    def convert(self, token: str, options: dict[str, str]):
        content, metadata = self.load(token)
        sheets = read_excel(content)
        selected = next((s for s in sheets if s.name == options.get("sheet")), None)
        if selected is None:
            raise ValueError("Choose a worksheet from this workbook.")
        codebook = convert_excel(
            selected,
            int(options.get("header_row", "1")),
            {key: options.get(key, "") for key in FIELDS},
            name=options.get("name", ""),
            codebook_id=options.get("codebook_id", ""),
            version=options.get("version", ""),
        )
        return codebook, content, metadata

    def commit(self, token: str, options: dict[str, str]):
        codebook, content, metadata = self.convert(token, options)
        receipt = self.root / token / "receipt.json"
        # Exclusive receipt reservation prevents double-clicks from importing twice.
        try:
            reservation = receipt.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise ValueError(
                "This workbook preview has already been imported or is being imported."
            ) from exc
        with reservation:
            record = self.workspace.import_codebook(
                project_manifest_path=self.project_path,
                filename="converted-codebook.yaml",
                content=yaml.safe_dump(codebook.model_dump(), sort_keys=False).encode("utf-8"),
                actor=metadata["actor"],
                rationale=metadata["rationale"],
                original_upload=(metadata["filename"], content),
                conversion={
                    "schema_version": 1,
                    "sheet": options["sheet"],
                    "header_row": int(options["header_row"]),
                    "mapping": {k: options.get(k, "") for k in FIELDS},
                },
            )
            reservation.write(record.model_dump_json())
        return record
