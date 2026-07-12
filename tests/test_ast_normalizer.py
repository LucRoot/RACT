# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.ast_normalizer import canonical_hash, canonical_similarity, canonicalize


def test_identical_sources_score_one() -> None:
    src = "def helper(x):\n    y = x + 1\n    return y\n"
    assert canonical_similarity(src, src) == 1.0


def test_renamed_locals_score_high() -> None:
    a = "def calc(value):\n    result = value * 2\n    return result\n"
    b = "def calc(input):\n    doubled = input * 2\n    return doubled\n"
    assert canonical_similarity(a, b) >= 0.9


def test_renamed_function_and_class_score_high() -> None:
    a = (
        "class Counter:\n"
        "    def increment(self, amount):\n"
        "        self.total = self.total + amount\n"
        "        return self.total\n"
    )
    b = (
        "class Tally:\n"
        "    def bump(self, delta):\n"
        "        self.total = self.total + delta\n"
        "        return self.total\n"
    )
    assert canonical_similarity(a, b) >= 0.85


def test_docstring_only_change_stays_high() -> None:
    a = 'def f(x):\n    """First docstring."""\n    return x + 1\n'
    b = 'def f(x):\n    """Completely different docstring."""\n    return x + 1\n'
    assert canonical_similarity(a, b) >= 0.95


def test_canonical_hash_stable_under_rename() -> None:
    a = "def alpha(beta):\n    gamma = beta + 1\n    return gamma\n"
    b = "def one(two):\n    three = two + 1\n    return three\n"
    assert canonical_hash(a) == canonical_hash(b)


def test_different_logic_scores_lower() -> None:
    a = "def f(x):\n    return x + 1\n"
    b = "def f(x):\n    return x * 100\n"
    assert canonical_similarity(a, b) < 0.9


def test_canonicalize_drops_annotations() -> None:
    src = "def f(x: int) -> str:\n    return str(x)\n"
    out = canonicalize(src)
    assert "int" not in out
    assert "str" not in out
    assert "return" in out


def test_invalid_source_returns_input() -> None:
    src = "this is not python !!!"
    assert canonicalize(src) == src
