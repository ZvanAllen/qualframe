from __future__ import annotations

from qualframe.io.response_parser import parse_markdown_tables
from qualframe.models import ProviderConfig
from qualframe.providers import build_provider
from qualframe.providers.cached_demo_provider import CachedDemoProvider
from qualframe.qa.rules import run_qa_on_artifact


def test_build_provider_selects_network_free_cached_demo() -> None:
    provider = build_provider(ProviderConfig(name="cached_demo"))
    assert isinstance(provider, CachedDemoProvider)
    assert provider.name == "cached_demo"


def test_cached_demo_deliberately_triggers_only_valence_conflict() -> None:
    provider = CachedDemoProvider()
    response = provider.complete(
        system_prompt="return markdown",
        user_prompt="Eight Excel workbooks, each representing one jurisdictional demo network",
    )
    parsed = parse_markdown_tables(response.text)

    failures = run_qa_on_artifact(
        run_id="demo-test",
        stage_id="cross_network_synthesis",
        prompt_sha256="demo-prompt-sha",
        parsed_output=parsed,
        allowed_network_labels=["Synthetic Network Alpha", "Synthetic Network Beta"],
        required_columns=["CFIR Domain", "CFIR Construct", "Quote", "Explanation"],
    )

    assert [failure.rule_id for failure in failures] == ["one_network_one_valence"]
    assert response.provider == "cached_demo"
    assert response.model == "qualframe-synthetic-cache-v1"
