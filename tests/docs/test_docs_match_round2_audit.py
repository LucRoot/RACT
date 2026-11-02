"""Round-2 audit (seam 4): the doc claims corrected there stay corrected.

Each test pins one corrected sentence against the tree so the wrong claim
cannot silently return: a registry that does not exist, a flag this
release refuses, key locations, env allowlist counts, the README
exit-code list, a dead verb alias, and CHANGELOG mojibake.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MOJIBAKE_DASH = "\u00e2\u20ac\u201d"  # an em-dash run through a double decode


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_harness_does_not_name_a_signature_registry() -> None:
    harness = _read("docs/HARNESS.md")
    assert "SignatureRegistry" not in harness
    assert ".ract/signatures" not in harness


def test_readme_exit_codes_include_the_budget_code() -> None:
    assert "4 a budget was used up" in _read("README.md")


def test_events_doc_says_json_schema_is_refused() -> None:
    events = _read("docs/EVENTS_SESSION.md")
    assert "`structured_output`" in events
    assert "--json-schema" in events
    assert "not supported" in events
    assert "exit code 2" in events


def test_threat_model_counts_match_the_code() -> None:
    from ract.security import sandbox_env

    threat = _read("docs/THREAT_MODEL.md")
    allowlist = len(sandbox_env.DEFAULT_ALLOWLIST)
    never = len(sandbox_env.NEVER_PASSTHROUGH)
    assert f"({allowlist} POSIX + Windows + locale names)" in threat
    assert f"({never} credential-shaped names" in threat
    assert "(44 POSIX" not in threat
    assert "(17 credential-shaped" not in threat


def test_threat_model_places_the_operator_key_outside_the_workspace() -> None:
    threat = _read("docs/THREAT_MODEL.md")
    assert "<config>/operator/operator.key.json" in threat
    assert "ADR-0048 D2" in threat


def test_verb_descriptions_has_no_loop_alias() -> None:
    from ract.cli import CLI_VERBS
    from ract.cli_help import VERB_DESCRIPTIONS

    assert "loop" not in CLI_VERBS
    assert "loop" not in VERB_DESCRIPTIONS


def test_changelog_has_no_em_dash_mojibake() -> None:
    assert MOJIBAKE_DASH not in _read("CHANGELOG.md")
