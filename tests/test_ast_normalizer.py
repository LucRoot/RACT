"""Tests for AST-based structural normalization."""

from __future__ import annotations


from ract.ast_normalizer import (
    normalize_python,
    structural_similarity,
    structural_similarity_normalized,
)


def test_normalize_makes_renamed_functions_identical():
    a = '''
def add(x, y):
    """docstring"""
    return x + y
'''
    b = """
def sum(a, b):
    # inline comment
    return a + b
"""
    assert normalize_python(a) == normalize_python(b)
    assert structural_similarity(a, b) == 1.0


def test_structural_similarity_distinguishes_different_operators():
    a = "def f(a, b): return a + b"
    b = "def f(a, b): return a * b"
    assert structural_similarity(a, b) < 1.0


def test_structural_similarity_distinguishes_different_structure():
    a = "def f(a, b): return a + b"
    b = "def f(a, b):\n    c = a + b\n    return c"
    assert structural_similarity(a, b) < 1.0


def test_invalid_source_returns_zero_similarity():
    assert structural_similarity("def f(", "def g(): pass") == 0.0


def test_annotations_are_stripped():
    a = "def f(x: int) -> int:\n    return x"
    b = "def f(x):\n    return x"
    assert normalize_python(a) == normalize_python(b)


def test_three_rename_clone_of_real_module_is_identical():
    """Regression: a clone that renames three identifiers must be caught.

    This is the case Claude identified: renaming `assumption`, `confidence`,
    and `provenance` in rooted.py produced a compression ratio of 0.897 and
    passed the novelty gate. Structural normalization sees it as identical.
    """
    source = """
class Rooted:
    def __init__(self, assumption, confidence, provenance):
        self.assumption = assumption
        self.confidence = confidence
        self.provenance = provenance

    def is_sound(self):
        return self.assumption is not None and self.confidence >= 0.7
"""
    clone = (
        source.replace("assumption", "hypothesis")
        .replace("confidence", "certainty")
        .replace("provenance", "source")
    )
    assert structural_similarity(source, clone) == 1.0


def test_class_and_function_names_are_normalized():
    a = "class Foo:\n    def bar(self): return 1"
    b = "class Baz:\n    def qux(self): return 1"
    assert structural_similarity(a, b) == 1.0


def test_imports_are_normalized_consistently():
    a = "from typing import List\n\ndef f(x: List[int]): return x"
    b = "from typing import Sequence\n\ndef f(x: Sequence[int]): return x"
    # Imports are normalized but the type names inside annotations are
    # stripped, so only the function structure matters.
    assert structural_similarity(a, b) == 1.0


def test_structural_similarity_normalized_skips_renormalization():
    """The normalized variant accepts pre-normalized sources directly."""
    source = "def add(x, y): return x + y"
    clone = "def sum(a, b): return a + b"
    norm_a = normalize_python(source)
    norm_b = normalize_python(clone)
    assert structural_similarity_normalized(norm_a, norm_b) == 1.0


def test_structural_similarity_normalized_returns_zero_for_dissimilar_sizes():
    """A large size ratio short-circuits to zero without expensive matching."""
    small = normalize_python("def f(): pass")
    large = normalize_python("\n".join([f"def f{i}(): pass" for i in range(100)]))
    assert structural_similarity_normalized(small, large) == 0.0


# RACT 0.1.1 - Trust and Tooling
