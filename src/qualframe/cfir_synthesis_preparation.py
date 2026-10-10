"""Prepare explicit CFIR cross-domain requests without dispatching a provider.

This is a planning and post-parse validation aid, separate from legacy execution.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from qualframe.config import load_stage_output_spec
from qualframe.io.files import sha256_for_file, sha256_for_text
from qualframe.io.response_parser import parse_markdown_tables
from qualframe.models import StageArtifact, StageOutputSpec
from qualframe.qa.rules import run_qa_on_artifact
from qualframe.reviewed_analysis import snapshot_identity
from qualframe.structured_output import validate_stage_output

CORE_DOMAINS = ("Innovation", "Outer Setting", "Inner Setting", "Individuals", "Implementation Process")
NETWORK_COLUMNS = ("CFIR Domain", "CFIR Construct", "Combined Evidence Quotes", "Synthesized Explanation", "Source File(s)")
NETWORKS = ("AB AMN", "BC AMN", "HE AMN", "NB AMN", "NL AMN", "NS AMN", "ON AMN", "PEI AMN")
PLAN_KIND = "qualframe_cfir_cross_domain_preparation_v1"


def build_cross_domain_plan(
    repo_root: Path,
    network_artifacts: dict[str, Path],
    codebook: dict,
    *,
    input_provenance: str,
    domains: tuple[str, ...] = CORE_DOMAINS,
) -> dict:
    """Bind selected saved network outputs and prepare one request per domain.

    No provider, cost approval, human-review action or pipeline run is created.
    Partial network cohorts are explicit. All supplied artifacts must originate
    from one run and preserve their domain-specific tables.
    """
    if not input_provenance.strip():
        raise ValueError("Describe the actual review/origin status of selected inputs.")
    if not network_artifacts or set(network_artifacts) - set(NETWORKS):
        raise ValueError("Supply distinct known AMN network labels.")
    if not domains or len(set(domains)) != len(domains) or set(domains) - set(CORE_DOMAINS):
        raise ValueError("Select distinct core CFIR domains; the Outcomes Addendum is outside this plan.")
    if not isinstance(codebook.get("codes"), list) or not codebook["codes"]:
        raise ValueError("A frozen codebook catalog is required.")
    prompt_path = repo_root / "prompts/cfir/v2/05_cross_domain_synthesis.md"
    schema_path = repo_root / "config/schemas/cfir_stage_outputs_v2.yaml"
    template = prompt_path.read_text(encoding="utf-8")
    if template.count("{CFIR_DOMAIN}") != 1 or template.count("{NETWORK_LABELS}") != 1:
        raise ValueError("The versioned prompt must have exactly its two declared placeholders.")
    spec = load_stage_output_spec(schema_path)
    parsed_by_network, bindings = {}, {}
    runs = set()
    for network, path in sorted(network_artifacts.items()):
        path = path.resolve()
        artifact = StageArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        if artifact.stage_id != "participant_to_network_synthesis" or not artifact.parsed_output:
            raise ValueError("Select parsed participant-to-network synthesis artifacts.")
        if artifact.input_path.split("(", 1)[0].strip() != network:
            raise ValueError("Network identity differs from the artifact input label.")
        if artifact.structured_output_valid is False:
            raise ValueError("An artifact with failed structural validation cannot supply this plan.")
        problems = validate_stage_output(artifact.stage_id, artifact.parsed_output, spec)
        if problems:
            raise ValueError("Network input does not match the declared five-domain contract: " + "; ".join(problems))
        runs.add(artifact.run_id)
        parsed_by_network[network] = copy.deepcopy(artifact.parsed_output)
        bindings[network] = dict(
            path=str(path), sha256=sha256_for_file(path), run_id=artifact.run_id,
            stage_id=artifact.stage_id, prompt_sha256=artifact.prompt_sha256,
            model=artifact.model, provider=artifact.provider,
            validation_performed_here="post-parse input structure only; no new semantic or human review",
        )
    if len(runs) != 1:
        raise ValueError("Do not silently combine network outputs from different runs.")
    requests = []
    for domain in domains:
        packets = []
        for network, parsed in parsed_by_network.items():
            rows = [row for sheet in parsed.values() for row in sheet if row["CFIR Domain"] == domain]
            if not rows:
                raise ValueError("Each selected network must explicitly represent the requested domain.")
            packets.append({"network": network, "rows": rows})
        contract = spec.stages["cross_network_synthesis"].model_dump(mode="json")
        contract["allowed_values"]["CFIR Domain"] = [domain]
        contract["required_values"]["CFIR Domain"] = [domain]
        text = template.replace("{CFIR_DOMAIN}", domain).replace(
            "{NETWORK_LABELS}", "\n".join("- " + name for name in sorted(network_artifacts))
        )
        user_prompt = text + "\n\nFrozen network inputs (JSON):\n" + json.dumps(packets, ensure_ascii=False, indent=2)
        user_prompt += "\n\nFrozen codebook (JSON):\n" + json.dumps(codebook, ensure_ascii=False, indent=2)
        requests.append(dict(
            domain=domain, input_packet_sha256=snapshot_identity(packets),
            user_prompt=user_prompt, user_prompt_sha256=sha256_for_text(user_prompt),
            structural_contract=contract, structural_contract_sha256=snapshot_identity(contract),
            allowed_network_labels=sorted(network_artifacts),
        ))
    return dict(
        kind=PLAN_KIND, status="prepared_only_not_executed",
        provider_calls=0, provider_configuration=None, spending_authorized=False,
        input_provenance=input_provenance.strip(), input_bindings=bindings,
        codebook_sha256=snapshot_identity(codebook),
        prompt={"path":str(prompt_path), "sha256":sha256_for_file(prompt_path)},
        schema={"path":str(schema_path), "sha256":sha256_for_file(schema_path)},
        domains=list(domains), networks=sorted(network_artifacts), requests=requests,
        limitations=[
            "This preparation is separate from the legacy one-domain runner and is not an executed synthesis.",
            "No semantic correctness, complete construct coverage or quote fidelity is established by the structural contract.",
            "External execution requires a separate approved provider configuration, source transfers and absolute budget.",
            "Review status comes from the explicit input-provenance statement; preparation does not create human decisions.",
        ],
    )


def validate_prepared_response(request: dict, response_text: str) -> list[str]:
    """Return structural/membership issues, not a semantic-quality judgment."""
    if request.get("structural_contract_sha256") != snapshot_identity(request["structural_contract"]):
        raise ValueError("Prepared response contract changed.")
    contract = request["structural_contract"]
    if contract.get("allowed_values", {}).get("CFIR Domain") != [request["domain"]]:
        raise ValueError("Prepared domain and contract disagree.")
    parsed = parse_markdown_tables(response_text)
    spec = StageOutputSpec(id="cfir_cross_domain_prepared_v1", stages={"cross_network_synthesis":contract})
    issues = validate_stage_output("cross_network_synthesis", parsed, spec)
    qa = run_qa_on_artifact(
        run_id="prepared-validation", stage_id="cross_network_synthesis",
        prompt_sha256=request.get("user_prompt_sha256", ""), parsed_output=parsed,
        allowed_network_labels=request["allowed_network_labels"],
        required_columns=contract["required_columns"], enabled_rules=contract["qa_rules"],
    )
    return issues + [item.reason for item in qa]


def write_cross_domain_plan(plan: dict, output_root: Path, *, dry_run: bool = False) -> Path:
    """Immutable content-addressed bundle; dry run does not touch the filesystem."""
    if plan.get("kind") != PLAN_KIND or plan.get("provider_calls") != 0:
        raise ValueError("Only unexecuted preparation plans can be written here.")
    folder = output_root / ("cross-domain-" + snapshot_identity(plan))
    content = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    if dry_run:
        return folder
    target = folder / "plan.json"
    if target.exists():
        if target.read_text(encoding="utf-8") != content:
            raise ValueError("An existing plan differs; preserve it and create a new version.")
        for request in plan["requests"]:
            slug = re.sub(r"[^a-z0-9]+", "-", request["domain"].lower()).strip("-")
            preview = folder / (slug + ".txt")
            if not preview.is_file() or preview.read_text(encoding="utf-8") != request["user_prompt"]:
                raise ValueError("An existing request preview differs from its frozen plan.")
        return folder
    if folder.exists() and any(folder.iterdir()):
        raise ValueError("An incomplete existing bundle requires a new output location.")
    folder.mkdir(parents=True, exist_ok=True)
    for request in plan["requests"]:
        slug = re.sub(r"[^a-z0-9]+", "-", request["domain"].lower()).strip("-")
        (folder / (slug + ".txt")).write_text(request["user_prompt"], encoding="utf-8")
    target.write_text(content, encoding="utf-8")
    return folder
