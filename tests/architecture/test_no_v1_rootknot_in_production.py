"""Grep-gate: production ``src/ract/`` may not call the v1 ``make_rootknot``.

v0.5.1 wiring module_02 (Lens D D2) migrated the sole production
emit-site (``executor/steps.py::_record_provenance``) from the v1
factory :func:`ract.core.rootknot.make_rootknot` to the v4 factory
:func:`ract.core.rootknot.make_rootknot_v4`. A regression that
reintroduced a v1 call anywhere under ``src/ract/`` would strip the
``workspace_digest`` + ``prompt_digest`` + ``run_id`` bindings from
the signed canonical bytes and re-open the Lens D D2 audit finding.

This gate scans every ``.py`` file under ``src/ract/`` for a
``make_rootknot(`` invocation (WITHOUT the ``_v2``/``_v3``/``_v4``
suffix) and fails unless the containing file appears in the small
exempt allowlist below.

Reference:
- ``_BUILD/audit_2026-08-21/lens_D_rootknot_signatures.md`` D2.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_02.md``.
"""

from __future__ import annotations

import re
from pathlib import Path


# Files that legitimately mention ``make_rootknot(`` for reasons other
# than a v1 emit call (definition site, backward-compat verify path,
# docstring reference). Every entry names the reason.
_ALLOWLIST: dict[str, str] = {
    # Factory definitions live here; the ``def make_rootknot(`` line
    # is the v1 factory itself and must remain for v0.3 fixture reads.
    "core/rootknot.py": "factory definition site (v1 + v2 + v3 + v4)",
}


_V1_CALL_PATTERN = re.compile(r"\bmake_rootknot\s*\(")
_V2_V3_V4_PATTERN = re.compile(r"\bmake_rootknot_v[234]\s*\(")


def _iter_py_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        # Skip __pycache__ noise.
        if "__pycache__" in rel:
            continue
        yield rel, path


def test_no_v1_make_rootknot_call_in_src() -> None:
    """No production file may invoke the v1 ``make_rootknot(`` factory."""
    src_root = Path(__file__).resolve().parents[2] / "src" / "ract"
    assert src_root.is_dir(), src_root

    offenders: list[tuple[str, int, str]] = []
    for rel, path in _iter_py_files(src_root):
        if rel in _ALLOWLIST:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            # Strip any make_rootknot_vN references from the search
            # window before checking the v1-shaped pattern.
            scrubbed = _V2_V3_V4_PATTERN.sub("<v234>", line)
            if _V1_CALL_PATTERN.search(scrubbed):
                offenders.append((rel, lineno, line.strip()))

    assert not offenders, (
        "Production ``make_rootknot(`` call detected (Lens D D2 regression). "
        "Migrate to make_rootknot_v4 or add an explicit allowlist entry with "
        "justification.\n"
        + "\n".join(f"  {rel}:{ln}: {src}" for rel, ln, src in offenders)
    )


def test_allowlist_entries_actually_exist() -> None:
    """Allowlist paths must correspond to files under src/ract/."""
    src_root = Path(__file__).resolve().parents[2] / "src" / "ract"
    for rel in _ALLOWLIST:
        assert (src_root / rel).is_file(), (
            f"allowlist entry {rel!r} does not exist under {src_root}"
        )
