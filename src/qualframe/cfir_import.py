"""Versioned CFIR reference workbook import without generic conversion."""
from pathlib import Path
from uuid import uuid4
import shutil
from qualframe.codebook_excel import read_excel
from qualframe.cfir_review import reference_codes
from qualframe.config import load_project_manifest, load_pipeline_spec, resolve_repo_path


def import_reference(workspace, project_path: Path, filename: str, content: bytes, actor: str, rationale: str):
    actor, rationale = workspace._validate_action_fields(actor, rationale)
    root = workspace.managed_study_root(project_path)
    project = load_project_manifest(project_path)
    pipeline = load_pipeline_spec(resolve_repo_path(workspace.repo_root, project.pipeline))
    if not any(s.domain_iterations for s in pipeline.stages):
        raise ValueError('Reference workbook import is only available for the CFIR workflow.')
    name = workspace._safe_filename(filename, {'.xlsx'})
    sheets = read_excel(content)
    if len(sheets) != 1 or any(len(row) > 2 and any(row[2:]) for row in sheets[0].rows):
        raise ValueError('Use the two-column CFIR reference workbook with domain headings and definitions.')
    folder = root / 'data/reference' / ('cfir-' + uuid4().hex)
    folder.mkdir(parents=True)
    target = folder / 'codebook.xlsx'
    target.write_bytes(content)
    codes = reference_codes(target)
    if not codes or len({c['id'] for c in codes}) != len(codes):
        raise ValueError('CFIR hierarchy is missing or contains ambiguous duplicate entries.')
    previous = project.paths['reference']
    relative = folder.relative_to(workspace.repo_root).as_posix()
    shutil.copy2(project_path, root / 'config' / ('project-before-cfir-' + uuid4().hex + '.yaml'))
    record = workspace._uploaded_record(project=project, source_kind='codebook', filename=name,
        destination=target, actor=actor, rationale=rationale)
    workspace._update_project_reference(project_path, 'paths', {**project.paths, 'reference': relative})
    workspace._append_source_record(project, record)
    workspace._append_change(root, project_id=project.project_id, change_kind='codebook_import',
        previous_ref=previous, new_ref=relative, actor=actor, rationale=rationale)
    return record


def reference_codebook_spec(codes: list[dict], *, codebook_id: str, name: str, version: str = "1") -> dict:
    """The CFIR reference catalogue as a QualFrame codebook, keeping each construct's ID.

    Lets the same CFIR workbook be used with QualFrame's general coding instructions, and keeps
    the code IDs identical so runs of both kinds can be compared directly.
    """
    import re

    def domain_title(code: dict) -> str:
        domain = re.sub(r"\s+domain$", "", code["domain"], flags=re.IGNORECASE).title()
        section = code.get("section", "")
        return f"{domain} ({section.title()})" if section else domain

    entries = []
    for code in codes:
        parent = None
        if code["parent_label"]:
            matches = [c["id"] for c in codes if c["raw_label"] == code["parent_label"] and not c["parent_label"]
                       and c["domain"] == code["domain"] and c.get("section", "") == code.get("section", "")]
            if len(matches) != 1:
                raise ValueError(f"The parent of {code['label']} could not be identified in the CFIR workbook.")
            parent = matches[0]
        entries.append({"id": code["id"], "label": f"{domain_title(code)}: {code['label']}",
                        "parent_id": parent, "definition": code["definition"]})
    return {"id": codebook_id, "version": version, "name": name, "codes": entries}
