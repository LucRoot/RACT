#!/usr/bin/env python3
"""Verify every tree-sitter grammar loads at the pinned version.

Depth Chain leaf: "tree-sitter grammars for Python, TypeScript, Rust,
and Go are all available as PyPI wheels on Windows ARM64. If a grammar
wheel is missing, the initial build fails at import time." This script
imports each of the four language modules (which each raise
:class:`~ract.memory.languages.GrammarVersionMismatchError` at import
if the installed version drifts from the pin) and prints a summary.

Exits 0 when every grammar loads at the pin; 1 on any mismatch.
"""

from __future__ import annotations

import sys
from importlib import import_module

from ract.memory.languages import GrammarVersionMismatchError, _installed_version


LANGUAGE_MODULES: dict[str, str] = {
    "python": "ract.memory.languages.python",
    "typescript": "ract.memory.languages.typescript",
    "rust": "ract.memory.languages.rust",
    "go": "ract.memory.languages.go",
}


def main() -> int:
    ok = True
    for language, module_name in LANGUAGE_MODULES.items():
        try:
            module = import_module(module_name)
        except GrammarVersionMismatchError as exc:
            print(f"FAIL {language}: {exc}")
            ok = False
            continue
        except Exception as exc:
            print(f"FAIL {language}: {type(exc).__name__}: {exc}")
            ok = False
            continue
        expected = getattr(module, "SUPPORTED_GRAMMAR_VERSION", "unknown")
        observed = _installed_version(f"tree-sitter-{language}")
        print(f"OK   {language}: expected {expected} observed {observed}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
