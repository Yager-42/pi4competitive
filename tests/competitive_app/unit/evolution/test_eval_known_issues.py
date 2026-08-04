from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from competitive_app.application.evolution.adapters.pi_llm import PiLlmAdapter
from competitive_app.application.evolution.eval.analyzers import checks
from competitive_app.application.evolution.eval.analyzers.contract_compiler import ContractCompiler
from competitive_app.application.evolution.eval.analyzers.response_contract_checker import ResponseContractChecker
from competitive_app.application.evolution.eval.registry import EvalRegistry, RegistryEvalBridge
from competitive_app.application.evolution.injector import _read_body
from competitive_app.application.evolution.parser import install_local, parse_skill_file
from competitive_app.domain.evolution.eval_types import ContractRule
from competitive_app.domain.evolution.evolution_types import EvalContext


def _record(path: Path) -> SimpleNamespace:
    return SimpleNamespace(path=str(path))


def _skill(path: Path, *, enabled: str = "true", body: str = "body") -> None:
    path.write_text(
        f"---\nname: example\ndescription: Example\nenabled: {enabled}\n---\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_complete_json_uses_json_decoder_for_delimiters() -> None:
    class Models:
        async def completeSimple(self, _model, _request):
            return 'prefix {"rationale":"use } and ] here", "ok": true} suffix'

    result = await PiLlmAdapter(Models(), {}).complete_json("prompt")
    assert result == {"rationale": "use } and ] here", "ok": True}


def test_citation_requires_actual_reference() -> None:
    assert not checks.check_must_cite("Please cite sources in your answer.")
    assert checks.check_must_cite("source: https://example.com/reference")
    assert checks.check_must_cite("https://example.com/reference")


def test_malformed_frontmatter_is_not_parseable() -> None:
    assert not checks.check_json_parseable("---\nname: example\nbody")
    assert not checks.check_json_parseable("---\nname: [broken\n---\nbody")
    assert checks.check_json_parseable("---\nname: example\n---\nbody")


def test_density_counts_whole_directive_tokens_and_phrases() -> None:
    assert checks.semantic_density("MUSTARD") == 0.0
    assert checks.semantic_density("MUST NOT") == pytest.approx(1 / 2)


def test_strict_paragraph_limit_is_exclusive() -> None:
    rules = ContractCompiler().compile("less than 2 paragraph")
    paragraph_rule = next(rule for rule in rules if rule.rule_id == "paragraph_limit")
    assert paragraph_rule.params == {"max": 2, "strict": True}
    content = "---\nname: example\ndescription: Example\n---\n\nfirst\n\nsecond"
    assert not ResponseContractChecker()._run_rule("paragraph_limit", content, paragraph_rule.params)


def test_unknown_contract_rule_fails_closed() -> None:
    class Compiler:
        def compile(self, _content: str) -> list[ContractRule]:
            return [ContractRule("typo_rule", "programmatic", True)]

    result = ResponseContractChecker(Compiler()).check("body")
    assert result.hard_failures == ("typo_rule",)
    assert result.recommendation == "reject"
    assert result.evidence[0].candidate_pass is False


@pytest.mark.asyncio
async def test_registry_rejects_unreadable_baseline(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.md"
    candidate.write_text("body", encoding="utf-8")
    missing = _record(tmp_path / "missing.md")
    result = await RegistryEvalBridge(EvalRegistry(ResponseContractChecker())).evaluate(
        EvalContext(missing, _record(candidate))
    )
    assert result.score == 0.0
    assert result.hard_failures == ("eval_exception",)


def test_injector_only_closes_frontmatter_on_its_own_line(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        '---\nname: example\ndescription: "inline --- marker"\n---\n\nBODY\n',
        encoding="utf-8",
    )
    assert _read_body(str(path)) == "BODY\n"


def test_parser_coerces_quoted_boolean(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    _skill(path, enabled='"false"')
    assert parse_skill_file(path).enabled is False


def test_install_local_validates_before_replacing_existing_install(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("not frontmatter", encoding="utf-8")
    destination = tmp_path / "dest" / "example"
    destination.mkdir(parents=True)
    (destination / "KEEP").write_text("untouched", encoding="utf-8")

    with pytest.raises(ValueError):
        install_local(source, "example", destination.parent)
    assert (destination / "KEEP").read_text(encoding="utf-8") == "untouched"


def test_install_local_copies_valid_skill(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _skill(source / "SKILL.md")
    skill_id = install_local(source, "example", tmp_path / "dest")
    assert skill_id.startswith("example__imp_")
    assert (tmp_path / "dest" / "example" / "SKILL.md").is_file()
