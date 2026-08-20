"""Sandbox environment allowlist loader (SUBSTRATE §4.3).

External review (REVIEW_4_UNKNOWN §D1) surfaced a data-exfil risk in the
current shim: sandboxed steps that go through the (non-bwrap) code path
inherit the parent process' environment wholesale, which leaks enterprise
tokens, deployment credentials, and any name-not-on-the-blacklist secret
directly into untrusted execution. The bwrap backend already implements
the correct pattern via ``--clearenv`` + manifest ``env.passthrough``;
this module lifts the same allowlist model up one layer so every sandbox
entry (bwrap, Seatbelt, and the Windows unenforced stub) enforces it.

Contract:

- The sandbox reads an ordered allowlist:
  1. ``manifest.env.passthrough`` names (per-run, operator-declared).
  2. ``.ract/sandbox_env.allowlist`` names (per-project persistent).
  3. Built-in ``DEFAULT_ALLOWLIST`` for standard POSIX/Windows env vars
     that legitimate tooling needs (PATH, HOME, USER, etc.).
- Sandbox env is computed as
  ``{k: os.environ[k] for k in allowlist if k in os.environ}``.
- Every environment variable in the process env that is NOT on the
  allowlist is counted (never named/logged) and surfaced as a single
  ``sandbox.env_scrubbed`` WARN entry.

Design intent: reviewer D1's "strict Allowlist Initialization Engine"
without breaking existing sandbox backends. Callers pass the loader's
result (a ``dict[str, str]``) into subprocess spawn as ``env=``.

Not touched by this module: the actual ``os.environ`` of the harness
process. The allowlist only shapes what the CHILD (sandbox / subprocess)
sees. If the operator wants to scrub the harness itself, that is an
operational concern outside the substrate.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default allowlist -- names legitimate tooling needs.
# ---------------------------------------------------------------------------
#
# The default set is deliberately CONSERVATIVE. Every name here is either
# (a) required by POSIX shells and standard tooling, or (b) required by
# Windows to boot a subprocess (USERPROFILE / TEMP / SYSTEMROOT). Names
# that carry secrets by convention (``*_TOKEN``, ``*_KEY``, ``*_SECRET``,
# ``AWS_*``, ``GITHUB_TOKEN``, ``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``,
# ``ANTHROPIC_AUTH_TOKEN``, ``GH_TOKEN``) are DELIBERATELY absent. An
# operational step that legitimately needs one of those declares it under
# ``manifest.env.passthrough`` (per-run allowlist) or under
# ``.ract/sandbox_env.allowlist`` (per-project persistent).
DEFAULT_ALLOWLIST: tuple[str, ...] = (
    # POSIX shell + user identity
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "PWD",
    "OLDPWD",
    # Windows equivalents (harmless on POSIX -- os.environ.get returns None)
    "USERPROFILE",
    "USERNAME",
    "USERDOMAIN",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "PATHEXT",
    "WINDIR",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMDATA",
    "PUBLIC",
    "ALLUSERSPROFILE",
    # Temp
    "TEMP",
    "TMP",
    "TMPDIR",
    # Locale
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LC_MESSAGES",
    "LC_NUMERIC",
    "LC_TIME",
    "LC_COLLATE",
    "LC_MONETARY",
    # Time
    "TZ",
    # Terminal
    "TERM",
    "TERMINFO",
    "COLORTERM",
    # Python (interpreter + stdlib; NOT PYTHONPATH which routes imports)
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    # SSL trust store paths (never the cert content itself)
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)


# Names that must NEVER slip onto any allowlist -- even if an operator
# declared them in ``manifest.env.passthrough`` or the project allowlist
# file, the substrate refuses to pass them through. Defense in depth
# against a compromised manifest / allowlist file.
NEVER_PASSTHROUGH: frozenset[str] = frozenset(
    {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_SECURITY_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        # Session cookies / auth surface most CI systems inject
        "NPM_TOKEN",
        "PYPI_TOKEN",
        "TWINE_PASSWORD",
        "DOCKER_PASSWORD",
        "SLACK_TOKEN",
    }
)


# SP Q3(a) amendment (OpenRouter DEFECT verdict): the frozenset of
# exact upper-case names above misses lower-case variants and glob
# shapes. This prefix set catches every credential-shape family so
# an operator declaring ``aws_access_key_id`` or ``AWS_*`` still
# gets refused. Match is case-insensitive against the upper form.
NEVER_PASSTHROUGH_PREFIXES: frozenset[str] = frozenset(
    {
        "AWS_",
        "OPENAI_",
        "ANTHROPIC_",
        "GOOGLE_",
        "OPENROUTER_",
        "DEEPSEEK_",
        "NPM_",
        "PYPI_",
        "TWINE_",
        "DOCKER_",
        "SLACK_",
        "AZURE_",
        "GCP_",
        "STRIPE_",
    }
)


def _is_never_passthrough(name: str, extra_denied: frozenset[str] = frozenset()) -> bool:
    """Return True when ``name`` is a hard-denied env var.

    Match is case-insensitive; both the exact-name and prefix-family
    checks fire against the upper-case form. Glob wildcards (``*``,
    ``?``) in the manifest allowlist are ALSO refused -- they are
    typically an attacker's attempt to grep-widen a passthrough
    surface.
    """
    upper = name.upper()
    # Glob shapes are refused unconditionally -- the allowlist is
    # supposed to be a set of literal names, not patterns.
    if any(ch in name for ch in "*?["):
        return True
    if upper in NEVER_PASSTHROUGH:
        return True
    for prefix in NEVER_PASSTHROUGH_PREFIXES:
        if upper.startswith(prefix):
            return True
    for name_extra in extra_denied:
        if upper == name_extra.upper():
            return True
    return False


def _redact_name_for_log(name: str) -> str:
    """SP Q3(b) amendment -- redact credential-shaped names in WARN log.

    Even the NAME of a credential-shaped var is sensitive (an
    attacker reading logs learns which secrets the operator has
    configured). Redact past the underscore-family prefix.
    """
    upper = name.upper()
    for prefix in NEVER_PASSTHROUGH_PREFIXES:
        if upper.startswith(prefix):
            return f"{prefix}<REDACTED>"
    if upper in NEVER_PASSTHROUGH:
        # Keep first three chars + <REDACTED> so the audit still
        # attributes the refusal to a family.
        return f"{name[:3].upper()}<REDACTED>"
    return name


ALLOWLIST_FILE_NAME = "sandbox_env.allowlist"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AllowlistFileMalformed(ValueError):
    """Raised when ``.ract/sandbox_env.allowlist`` has an unparseable line.

    The file format is JSONL (one JSON string per line) with ``#``-prefix
    comments and blank lines allowed. A line that is not a comment / not
    blank / not a JSON string trips this error; the substrate refuses to
    silently ignore a malformed allowlist entry because a partial parse
    could leak the very env vars the operator meant to scrub.
    """


# ---------------------------------------------------------------------------
# Result value
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxEnvResult:
    """The scrubbed environment for one sandbox entry, plus audit info.

    - ``env`` is the dict caller passes to ``subprocess.Popen(env=...)``.
    - ``scrubbed_count`` names how many env vars from the process env
      were dropped (count-only, never values, per D1 privacy scope).
    - ``never_passthrough_denied`` names how many entries appeared on
      an allowlist but were denied by ``NEVER_PASSTHROUGH``. Non-zero
      means an operator (or an attacker) tried to route a hard-denied
      name through; the caller SHOULD escalate on non-zero.
    - ``allowlist_source`` is one of ``"manifest"``, ``"file"``,
      ``"default"`` -- whichever source contributed the largest set of
      names; ties resolve to the more explicit source.
    """

    env: dict[str, str]
    scrubbed_count: int = 0
    never_passthrough_denied: int = 0
    allowlist_source: str = "default"


# ---------------------------------------------------------------------------
# File loader
# ---------------------------------------------------------------------------


def load_allowlist_file(path: Path) -> tuple[str, ...]:
    """Read ``.ract/sandbox_env.allowlist`` from ``path``.

    File format (JSONL, permissive):

    - Lines beginning with ``#`` (after leading whitespace) are comments.
    - Blank lines are ignored.
    - Every other line MUST parse as a JSON string.

    Returns the tuple of allowlist entries, in file order, with
    duplicates preserved (the caller de-duplicates against the union of
    sources).

    A missing file returns ``()`` without raising -- the file is
    optional; the default allowlist + manifest ``env.passthrough`` are
    still consulted.
    """
    if not path.exists():
        return ()
    entries: list[str] = []
    # SP Q3(d) amendment: use utf-8-sig so UTF-8 BOM at file start is
    # silently stripped (Windows editors love to insert one). Trailing-
    # comma foot-gun handled per-line below with a lenient recovery.
    text = path.read_text(encoding="utf-8-sig")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        # Per-line BOM strip -- defensive (multi-line concatenation
        # tools can leave a stray BOM mid-file).
        stripped = raw.lstrip("﻿").strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            # Lenient recovery for a single trailing comma on the line;
            # everything else still refuses.
            if stripped.endswith(","):
                try:
                    parsed = json.loads(stripped[:-1])
                except json.JSONDecodeError:
                    raise AllowlistFileMalformed(
                        f"{path} line {lineno}: not a JSON string: {exc}"
                    ) from exc
            else:
                raise AllowlistFileMalformed(
                    f"{path} line {lineno}: not a JSON string: {exc}"
                ) from exc
        if not isinstance(parsed, str):
            raise AllowlistFileMalformed(
                f"{path} line {lineno}: allowlist entries must be JSON "
                f"strings; got {type(parsed).__name__}"
            )
        entries.append(parsed)
    return tuple(entries)


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_sandbox_env(
    *,
    process_env: dict[str, str] | None = None,
    manifest_passthrough: Sequence[str] = (),
    allowlist_file: Path | None = None,
    include_default: bool = True,
    extra_denied: Iterable[str] = (),
) -> SandboxEnvResult:
    """Compute the scrubbed sandbox environment.

    ``process_env`` defaults to ``os.environ`` -- pass an explicit dict
    from tests to isolate. ``manifest_passthrough`` is
    ``CapabilityManifest.env.passthrough``; the caller extracts it and
    passes here so this module does not import the pydantic manifest
    (keeps the sandbox_env module low-dependency, testable without
    importing pydantic in a hot-path context).

    ``allowlist_file`` defaults to ``<project>/.ract/sandbox_env.allowlist``
    when the caller resolves it; ``None`` skips the file source.
    ``include_default`` gates the DEFAULT_ALLOWLIST contribution --
    tests that need a bare allowlist can pass ``False``.

    ``extra_denied`` extends ``NEVER_PASSTHROUGH`` for a specific run
    (e.g. an operator who wants ``MY_CUSTOM_TOKEN`` blocked).

    Returns ``SandboxEnvResult``. The result's ``env`` is safe to hand
    to ``subprocess.Popen(env=...)``. WARN entries are emitted via the
    module logger; capture with a caplog fixture or ``LogCapture`` in
    tests.
    """
    env_source = os.environ if process_env is None else process_env

    # Build the union allowlist in source order. A name that appears in
    # multiple sources still lands in the union once.
    union: dict[str, str] = {}  # name -> source
    for name in manifest_passthrough:
        union.setdefault(name, "manifest")
    if allowlist_file is not None:
        try:
            file_entries = load_allowlist_file(allowlist_file)
        except AllowlistFileMalformed:
            # Re-raise -- a malformed allowlist is a hard error. The
            # substrate refuses to silently degrade to the default set
            # because that would silently pass through env vars the
            # operator meant to scrub.
            raise
        for name in file_entries:
            union.setdefault(name, "file")
    if include_default:
        for name in DEFAULT_ALLOWLIST:
            union.setdefault(name, "default")

    # Apply NEVER_PASSTHROUGH denies. SP Q3(a) amendment: use
    # case-insensitive prefix + exact match so a manifest entry like
    # ``aws_access_key_id`` or ``AWS_*`` still refuses. SP Q3(b)
    # amendment: log a REDACTED form of the name so audits see the
    # refusal family without leaking the specific env var name.
    extra_denied_set = frozenset(extra_denied)
    denied_hits = 0
    scrubbed_env: dict[str, str] = {}
    denied_names: set[str] = set()
    for name, source in union.items():
        if _is_never_passthrough(name, extra_denied_set):
            denied_hits += 1
            denied_names.add(name)
            _LOG.warning(
                "sandbox_env: denied allowlist entry %r (source=%s); "
                "in NEVER_PASSTHROUGH — the substrate refuses to pass "
                "credential-shaped names into the sandbox",
                _redact_name_for_log(name),
                source,
            )
            continue
        if name in env_source:
            scrubbed_env[name] = env_source[name]

    # Count names in process env that were NOT allowlisted.
    scrubbed_count = 0
    for name in env_source:
        if name not in union or name in denied_names:
            scrubbed_count += 1

    if scrubbed_count > 0:
        _LOG.warning(
            "sandbox_env: scrubbed %d environment variable(s) from the "
            "sandbox env (count-only; values never logged). Allowlist "
            "sources: manifest.env.passthrough=%d, file=%d, default=%d.",
            scrubbed_count,
            sum(1 for s in union.values() if s == "manifest"),
            sum(1 for s in union.values() if s == "file"),
            sum(1 for s in union.values() if s == "default"),
        )

    # Determine primary source for the audit field.
    counts = {"manifest": 0, "file": 0, "default": 0}
    for source in union.values():
        counts[source] = counts.get(source, 0) + 1
    if counts["manifest"] >= counts["file"] and counts["manifest"] >= counts["default"]:
        primary = "manifest"
    elif counts["file"] >= counts["default"]:
        primary = "file"
    else:
        primary = "default"
    if not union:
        primary = "default"

    return SandboxEnvResult(
        env=scrubbed_env,
        scrubbed_count=scrubbed_count,
        never_passthrough_denied=denied_hits,
        allowlist_source=primary,
    )


def default_allowlist_path(project_dir: Path) -> Path:
    """Return the canonical location of the project's allowlist file."""
    return Path(project_dir) / ".ract" / ALLOWLIST_FILE_NAME


__all__ = [
    "ALLOWLIST_FILE_NAME",
    "AllowlistFileMalformed",
    "DEFAULT_ALLOWLIST",
    "NEVER_PASSTHROUGH",
    "SandboxEnvResult",
    "build_sandbox_env",
    "default_allowlist_path",
    "load_allowlist_file",
]


# RACT 0.5.1
