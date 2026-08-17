"""Gate ``docs/USE_CASES.jsonl`` against the CLI verb surface.

The catalog is the release-surface record of accepted goals and refused
non-goals. Adding a CLI verb without a matching accepted entry fails
this gate. Removing a rejected entry requires an ADR.

The verb source of truth is ``ract.cli.CLI_VERBS``. The default
``ract --help`` output enumerates flags only; subcommands are dispatched
by ``argv[0]`` match. Parsing ``--help`` was the original spec, but the
help output does not enumerate the subcommand set, so the constant is
used instead. See ``docs/USE_CASES.jsonl`` header rationale.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from ract import cli as ract_cli
from ract.cli import CLI_VERBS


REPO_ROOT = Path(__file__).resolve().parent.parent
USE_CASES_PATH = REPO_ROOT / "docs" / "USE_CASES.jsonl"
REQUIRED_FIELDS = ("title", "description", "status", "rationale")
VALID_STATUS = {"accepted", "rejected"}


def _load_entries() -> list[dict]:
    """Return the parsed USE_CASES.jsonl entries."""
    text = USE_CASES_PATH.read_text(encoding="utf-8")
    entries: list[dict] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            entries.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            pytest.fail(f"USE_CASES.jsonl line {line_no} is not valid JSON: {exc}")
    return entries


def test_use_cases_jsonl_parses() -> None:
    """Every line is JSON with the four required fields."""
    entries = _load_entries()
    assert entries, "USE_CASES.jsonl is empty"
    for i, entry in enumerate(entries):
        for field in REQUIRED_FIELDS:
            assert field in entry, f"entry {i} missing field {field!r}: {entry}"
        assert entry["status"] in VALID_STATUS, (
            f"entry {i} has invalid status {entry['status']!r}"
        )


def test_every_cli_verb_is_accepted() -> None:
    """Every CLI verb has an accepted entry; every accepted entry is a verb."""
    entries = _load_entries()
    accepted_titles = {
        entry["title"].lower() for entry in entries if entry["status"] == "accepted"
    }
    verb_set = {verb.lower() for verb in CLI_VERBS}

    missing = verb_set - accepted_titles
    assert not missing, (
        f"CLI verbs without accepted USE_CASES.jsonl entry: {sorted(missing)}"
    )

    extra = accepted_titles - verb_set
    assert not extra, (
        f"accepted USE_CASES.jsonl entries without a matching CLI verb: "
        f"{sorted(extra)}"
    )


def test_no_rejected_entry_leaks_as_verb() -> None:
    """No rejected entry title collides with a CLI verb."""
    entries = _load_entries()
    verb_set = {verb.lower() for verb in CLI_VERBS}
    for entry in entries:
        if entry["status"] != "rejected":
            continue
        assert entry["title"].lower() not in verb_set, (
            f"rejected entry {entry['title']!r} collides with a shipped CLI verb"
        )


def _dispatch_verbs_from_main() -> set[str]:
    """Walk ``ract.cli.main`` for every ``argv[0] == "..."`` compare.

    Returns the lowercased set of literal strings compared against
    ``argv[0]`` (or against ``argv[1:]`` after the ``run`` alias
    stripping). If someone adds a subcommand branch without also
    adding it to ``CLI_VERBS``, this catches the drift.
    """
    source = inspect.getsource(ract_cli.main)
    tree = ast.parse(source)
    verbs: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # Look for ``... argv[0] == "literal" ...``
        left = node.left
        if not (
            isinstance(left, ast.Subscript)
            and isinstance(left.value, ast.Name)
            and left.value.id == "argv"
        ):
            continue
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, ast.Eq):
                continue
            if isinstance(comparator, ast.Constant) and isinstance(
                comparator.value, str
            ):
                verbs.add(comparator.value.lower())
    return verbs


def test_cli_verbs_matches_dispatch_table() -> None:
    """CLI_VERBS is the exhaustive union of dispatch-table literals plus 'run'.

    ``run`` is stripped from argv before dispatch (it is an alias for
    the default intent path) and does not appear as a comparison
    literal; every other verb must appear on both sides.
    """
    dispatch_verbs = _dispatch_verbs_from_main()
    declared = {verb.lower() for verb in CLI_VERBS}
    # ``run`` is aliased away before the dispatch chain, so it is
    # declared without appearing as a compare literal.
    missing_from_declared = dispatch_verbs - declared
    assert not missing_from_declared, (
        f"dispatch branches without a CLI_VERBS entry: "
        f"{sorted(missing_from_declared)}"
    )
    missing_from_dispatch = declared - dispatch_verbs - {"run"}
    assert not missing_from_dispatch, (
        f"CLI_VERBS entries without a dispatch branch: "
        f"{sorted(missing_from_dispatch)}"
    )


def test_rejected_entries_have_rationale() -> None:
    """Every rejected entry carries a non-empty rationale."""
    entries = _load_entries()
    rejected = [entry for entry in entries if entry["status"] == "rejected"]
    assert rejected, "USE_CASES.jsonl has no rejected entries"
    for entry in rejected:
        rationale = entry.get("rationale", "")
        assert isinstance(rationale, str) and rationale.strip(), (
            f"rejected entry {entry['title']!r} has empty rationale"
        )
