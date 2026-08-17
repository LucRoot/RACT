"""Display-only authorship marker (module_06 step 6).

The ``__root_author__`` string is the operator's public byline for
RACT. In v0.3 the same marker appeared across ``src/ract/*.py`` and
skill JSON files; v0.3 module_01 scrubbed it. Module_06 reintroduces it
in exactly one location — this module — and reads it only from
``ract --about`` in ``src/ract/cli.py``.

The marker has **no role in any invariant**: it does not gate a
verification path, it does not appear in any Rootknot field, it does
not feed a threat model. The audit gate is a boolean grep:

    grep -R "__root_author__" src/ tests/ | grep -v cli.py | grep -v _about.py

must return zero matches. ``tests/test_root_author_display_only.py``
enforces this.

Reference sources:

- SUBSTRATE spec §7 (author identity refused as invariant).
- REBUILD spec §3 (Rootknot Made Real).
"""

from __future__ import annotations

# Display-only marker. Do not import from an invariant-code path.
__root_author__: str = "Dr. Lucas Root, Ph.D."


def about_lines() -> tuple[str, ...]:
    """Return the ``ract --about`` payload as a tuple of lines.

    The CLI verb reads this and prints each line. Kept as data so the
    CLI's --about branch is a straight print loop.
    """
    return (
        "RACT - Root Agentic Coding Tool",
        f"By {__root_author__}",
        "",
        (
            "RACT is a model-agnostic, local-first agentic coding tool. It "
            "keeps the human in the loop while a small management LM routes "
            "work to the right provider. Every plan and result is Rooted to "
            "the assumption that justifies it."
        ),
        "",
        "License: PolyForm Noncommercial License 1.0.0",
        (
            "  Free for personal use, research, education, and noncommercial "
            "organizations."
        ),
        (f"  Commercial use requires a separate agreement with {__root_author__}"),
    )


# RACT 0.4.0
