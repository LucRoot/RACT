"""Prompt-file loader for the four v0.5.0 memory-discipline functions.

Lateral Chain branch C (module_06 PRE): each function names its
prompt version as a module-level constant (``INTAKE_PROMPT_VERSION``
etc.); this loader reads
``src/ract/memory/functions/prompts/{function}_{version}.md`` so a
version bump is a one-line constant edit plus a new prompt file.

Second Pass Q4 (module_06): the loader validates that the requested
prompt file exists at import-startup via
:func:`assert_prompt_shipped`. A caller that forgot to add the file
alongside a version bump gets a specific error rather than a silent
fallback to the previous version.
"""

from __future__ import annotations

from pathlib import Path

from ract.core.module_identity import _module_knot, register_module_knot


PROMPTS_DIR: Path = Path(__file__).resolve().parent / "prompts"
"""Location of the shipped prompt files."""


class PromptMissingError(FileNotFoundError):
    """Raised when a prompt file for a given function+version is absent."""


def prompt_path(function: str, version: str) -> Path:
    """Return the on-disk path for ``{function}_{version}.md``."""
    if not function or not version:
        raise ValueError("prompt_path: function and version must be non-empty")
    return PROMPTS_DIR / f"{function}_{version}.md"


def assert_prompt_shipped(function: str, version: str) -> Path:
    """Return the prompt path; raise if the file is missing.

    Called at import time from every function module so a version-
    string constant that has no matching file surfaces before the
    first invocation.
    """
    path = prompt_path(function, version)
    if not path.is_file():
        raise PromptMissingError(
            f"prompt file missing for function={function!r} version={version!r}: "
            f"expected at {path}"
        )
    return path


def load_prompt(function: str, version: str) -> str:
    """Return the contents of the prompt file for ``function``+``version``."""
    path = assert_prompt_shipped(function, version)
    return path.read_text(encoding="utf-8")


class PromptCoverageError(RuntimeError):
    """Raised when a prompt file has no matching function constant, or vice versa.

    Second Pass Q4 (PARTIAL) fix: ``assert_prompt_shipped`` alone
    only checks constant -> file. The reverse ("someone shipped
    ``intake_v2.md`` without bumping the constant") stays silent
    until this checker fires.
    """


def verify_prompt_coverage(expected: dict[str, str]) -> None:
    """Refuse if the files in :data:`PROMPTS_DIR` disagree with ``expected``.

    ``expected`` maps ``function`` -> ``version`` (the shipped
    constants). Every file in ``PROMPTS_DIR`` matching the
    ``{function}_{version}.md`` shape must appear in ``expected``;
    every ``expected`` entry must correspond to an on-disk file.
    Raises :class:`PromptCoverageError` naming the mismatched entry.

    The composition layer (module_07) calls this at startup so a
    silently-added ``intake_v2.md`` triggers a specific failure
    rather than silently falling through to v1.
    """
    if not PROMPTS_DIR.is_dir():
        raise PromptCoverageError(f"prompts directory missing: {PROMPTS_DIR}")
    on_disk: dict[str, str] = {}
    for entry in sorted(PROMPTS_DIR.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        stem = entry.stem
        if "_" not in stem:
            raise PromptCoverageError(
                f"prompt file {entry.name!r} does not match "
                f"'{{function}}_{{version}}.md' shape"
            )
        function, _, version = stem.rpartition("_")
        if not function or not version.startswith("v"):
            raise PromptCoverageError(
                f"prompt file {entry.name!r} has unparseable function/version"
            )
        on_disk[function] = version
    on_disk_set = set(on_disk.items())
    expected_set = set(expected.items())
    extra = on_disk_set - expected_set
    missing = expected_set - on_disk_set
    if extra or missing:
        raise PromptCoverageError(
            f"prompt coverage mismatch: on-disk-not-registered={sorted(extra)!r}, "
            f"registered-not-on-disk={sorted(missing)!r}"
        )


__all__ = [
    "PROMPTS_DIR",
    "PromptCoverageError",
    "PromptMissingError",
    "assert_prompt_shipped",
    "load_prompt",
    "prompt_path",
    "verify_prompt_coverage",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
