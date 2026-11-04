"""B-168: every string the setup flow prints or asks is scored for reading level and checked for jargon.

The strings are read from the wizard's source (ast), so the test does not hand-copy them: every io.say and
io.ask argument, and every module-level text constant the wizard prints. An f-string keeps its literal
parts and puts "x" where a value goes. The score is Flesch-Kincaid grade, computed here (no dependency).
Report: docs/ux/readability_report.md (written on every run). The target is about grade 6; a string above
FAIL_ABOVE is a failure to be carded, not hidden.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WIZARD = ROOT / "src" / "ract" / "setup" / "wizard.py"
JARGON = ROOT / "docs" / "ux" / "jargon.txt"
REPORT = ROOT / "docs" / "ux" / "readability_report.md"
FAIL_ABOVE = 8.0
WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


def _text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            else:
                parts.append("x")
        return "".join(parts)
    return None


def collect_strings() -> list[str]:
    tree = ast.parse(WIZARD.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "io":
                if node.func.attr in {"say", "ask"} and node.args:
                    text = _text(node.args[0])
                    if text:
                        found.append(text)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id.isupper():
                text = _text(node.value)
                if text:
                    found.append(text)
    return [
        line.strip() for text in found for line in text.splitlines() if line.strip()
    ]


def syllables(word: str) -> int:
    word = word.lower().rstrip("e") or word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    return max(1, len(groups))


def grade(text: str) -> float:
    words = WORD.findall(text)
    if not words:
        return 0.0
    sentences = max(1, len(re.findall(r"[.!?](\s|$)", text)) or 1)
    syl = sum(syllables(w) for w in words)
    return 0.39 * (len(words) / sentences) + 11.8 * (syl / len(words)) - 15.59


def jargon_terms() -> dict[str, str]:
    terms = {}
    for line in JARGON.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith(("#", "exempt")) and "|" in line:
            term, plain = line.split("|", 1)
            terms[term.strip().lower()] = plain.strip()
    return terms


def exemptions() -> list[str]:
    """Strings that are labels or config comments, not sentences: listed in jargon.txt as "exempt | text | reason"."""
    out = []
    for line in JARGON.read_text(encoding="utf-8").splitlines():
        if line.startswith("exempt") and line.count("|") >= 2:
            out.append(line.split("|")[1].strip())
    return out


def is_graded(text: str) -> bool:
    """A label (fewer than four words) and a config comment are not graded; the rest are."""
    if len(WORD.findall(text)) < 4 or " # " in text:
        return False
    return not any(text.startswith(ex) for ex in exemptions())


STRINGS = collect_strings()


def test_the_wizard_has_strings_to_score() -> None:
    assert len(STRINGS) >= 30


def test_every_string_is_scored_and_the_report_is_written() -> None:
    rows = [(grade(text), text) for text in STRINGS]
    lines = [
        "# Readability report (B-168)",
        "",
        "Grade is Flesch-Kincaid, target about 6; above "
        f"{FAIL_ABOVE} is a failure to card.",
        "",
        "| grade | string |",
        "| --- | --- |",
    ]
    for value, text in rows:
        lines.append(f"| {value:.1f} | {text.replace('|', '/')} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert len(rows) == len(STRINGS)


@pytest.mark.parametrize("text", [s for s in STRINGS if is_graded(s)])
def test_no_string_is_above_the_failure_grade(text: str) -> None:
    assert grade(text) <= FAIL_ABOVE, f"grade {grade(text):.1f}: {text}"


@pytest.mark.parametrize("text", STRINGS)
def test_no_jargon_word_is_used_in_a_first_run_string(text: str) -> None:
    lowered = text.lower()
    for term, plain in jargon_terms().items():
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            pytest.fail(f"jargon '{term}' (say: {plain}): {text}")
