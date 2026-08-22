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
import sys
from dataclasses import dataclass, field
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
    # v0.5.2 hardening module_02 (DA-A F-3 close):
    # ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` USED to live here so
    # legit tools could find the trust store. The DA-A audit
    # flagged them as trust-store hijack surfaces (an attacker
    # who sets either pointing at an attacker-controlled bundle
    # gets every TLS handshake inside the sandbox to succeed
    # against a rogue CA). They are now on ``NEVER_PASSTHROUGH``
    # instead; operators who need enterprise CA bundles inside
    # the sandbox declare a specific path via a manifest
    # ``sandbox.trust_store`` field (v0.6 backlog item) rather
    # than opening the whole ``SSL_CERT_FILE`` interpretation
    # to whatever the parent env carries.
)


# Names that must NEVER slip onto any allowlist -- even if an operator
# declared them in ``manifest.env.passthrough`` or the project allowlist
# file, the substrate refuses to pass them through. Defense in depth
# against a compromised manifest / allowlist file.
NEVER_PASSTHROUGH: frozenset[str] = frozenset(
    {
        # ---- Credential-shaped exact names (v0.5.1 baseline) ----
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
        # ---- v0.5.2 module_02 (DA-A F-3, Ox Alpha) additions ----
        # LIBRARY-INJECTION defense: every entry below is a
        # code-execution / trust-boundary primitive when set on a
        # process that later shells out. Grouped by family so an
        # auditor can trace back to the CVE / vector class.
        #
        # -- Dynamic-linker family (POSIX / glibc):
        # `LD_PRELOAD` = inject a shared object into every child;
        # `LD_LIBRARY_PATH` = poison library resolution order;
        # `LD_AUDIT` = load rtld-audit hooks; `GLIBC_TUNABLES` =
        # CVE-2023-4911 Looney Tunables privilege escalation.
        # Prefix `LD_` catches the rest (LD_BIND_NOW / LD_DEBUG /
        # LD_ORIGIN_PATH / LD_PROFILE / LD_SHOW_AUXV / etc).
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "GLIBC_TUNABLES",
        "LOCPATH",
        "NLSPATH",
        # -- Dynamic-linker family (macOS):
        # `DYLD_INSERT_LIBRARIES` = macOS LD_PRELOAD equivalent
        # (SIP-hardened for /usr/bin/* but attacker-writable for
        # any custom binary in the sandbox); `DYLD_LIBRARY_PATH`
        # + `DYLD_FRAMEWORK_PATH` = library-path poisoning;
        # `DYLD_FALLBACK_*` = fallback overrides; `DYLD_ROOT_PATH`
        # = chroot-like re-root of the loader; `DYLD_FORCE_FLAT_NAMESPACE`
        # = merge symbols so an earlier lib wins over the real one.
        # Prefix `DYLD_` catches the rest.
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "DYLD_FRAMEWORK_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_FALLBACK_FRAMEWORK_PATH",
        "DYLD_ROOT_PATH",
        "DYLD_PRINT_TO_FILE",
        "DYLD_FORCE_FLAT_NAMESPACE",
        # -- macOS malloc-family (heap tampering / logs to file):
        # `MallocStackLogging` / `MallocLogFile` = redirect libc
        # malloc bookkeeping to an attacker-writable file; other
        # `MALLOC_*` under prefix.
        "MallocStackLogging",
        "MallocLogFile",
        "MallocScribble",
        "MallocPreScribble",
        "MallocGuardEdges",
        # -- Python interpreter injection:
        # `PYTHONPATH` = prepend to sys.path so `import foo` loads
        # attacker's foo; `PYTHONHOME` = re-root the whole stdlib;
        # `PYTHONSTARTUP` = script that runs before every REPL /
        # interactive shell; `PYTHONBREAKPOINT` = alt breakpoint()
        # entrypoint; `PYTHONINSPECT` = drop to REPL on exit;
        # `PYTHONUSERBASE` = re-root the user site-packages dir.
        # NOTE: `PYTHONIOENCODING` + `PYTHONUTF8` stay on
        # DEFAULT_ALLOWLIST -- they are I/O tuning, not code
        # injection. Enumerated (not `PYTHON` prefix) so those
        # two continue to pass through.
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONBREAKPOINT",
        "PYTHONINSPECT",
        "PYTHONUSERBASE",
        "PYTHONDONTWRITEBYTECODE",
        # -- Node.js interpreter injection:
        # `NODE_OPTIONS` accepts `--require /path/to/evil.js` and
        # arbitrary V8 flags; `NODE_PATH` = poison module search;
        # `NODE_EXTRA_CA_CERTS` = trust-store hijack. NODE_ENV
        # (dev/prod/test) is a legitimate build-system knob and
        # is left off the deny list (it never appears in default
        # allowlist either -- operator declares in manifest if
        # the sandbox step needs it).
        "NODE_OPTIONS",
        "NODE_PATH",
        "NODE_EXTRA_CA_CERTS",
        # -- Ruby / Perl / Java interpreter injection:
        "RUBYOPT",
        "RUBYLIB",
        "RUBYPATH",
        "PERL5OPT",
        "PERL5LIB",
        "PERLIO",
        "PERL5DB",
        # Java -- `_JAVA_OPTIONS` is auto-prepended to every JVM
        # startup (undocumented but honored); `JAVA_TOOL_OPTIONS`
        # is the documented equivalent; `JDK_JAVA_OPTIONS` for
        # tools like javac; `CLASSPATH` poisons class resolution.
        "JAVA_TOOL_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "_JAVA_OPTIONS",
        "CLASSPATH",
        "JAVA_OPTS",
        # -- Shell auto-run hooks:
        # `BASH_ENV` runs a script on every non-interactive bash
        # invocation; `ENV` same for POSIX sh. `PROMPT_COMMAND`
        # runs before every prompt (interactive). `CDPATH` +
        # `IFS` are lesser-known but classic injection primitives
        # for scripts that `cd $var` or field-split unquoted.
        "BASH_ENV",
        "ENV",
        "ZDOTDIR",  # zsh startup-file directory (co-build Fork 5 gotcha)
        "PROMPT_COMMAND",
        "CDPATH",
        "IFS",
        # -- Git tool subversion:
        # `GIT_SSH_COMMAND` = arbitrary command executed as ssh
        # (used by every `git fetch/push` over ssh -- so a
        # sandbox step that runs git clone with this poisoned
        # runs the attacker's payload); `GIT_ASKPASS` /
        # `SSH_ASKPASS` = arbitrary command for password prompts;
        # `GIT_EXEC_PATH` = re-root git's helper binaries;
        # `GIT_CONFIG_GLOBAL` / `GIT_CONFIG_SYSTEM` = point git
        # at an attacker's config (config keys include
        # `core.sshCommand`, `core.gitProxy`, etc). `GIT_TRACE_*`
        # writes to attacker-controlled files. `GIT_SSL_CAINFO` =
        # trust-store hijack for git HTTPS.
        "GIT_SSH_COMMAND",
        "GIT_EXEC_PATH",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_TRACE",
        "GIT_TRACE_PACKET",
        "GIT_TRACE_SETUP",
        "GIT_SSL_CAINFO",
        "GIT_HTTP_LOW_SPEED_LIMIT",
        "GIT_HTTP_LOW_SPEED_TIME",
        "GIT_PROXY_COMMAND",
        # -- Editor invocation vectors:
        # `EDITOR` / `VISUAL` / `PAGER` are exec'd by many CLIs
        # (git commit, `less`, etc.) -- setting them to arbitrary
        # commands is direct RCE inside the sandbox.
        "EDITOR",
        "VISUAL",
        "PAGER",
        "SYSTEMD_EDITOR",
        "SYSTEMD_PAGER",
        # -- Trust-store hijack:
        # These USED to live on DEFAULT_ALLOWLIST (v0.5.1) so
        # tools inside the sandbox found the system trust store.
        # DA-A F-3 flagged the risk: an attacker with a poisoned
        # process env can point either at an attacker-controlled
        # bundle and every TLS handshake inside the sandbox now
        # succeeds against a rogue CA. Moved to deny; enterprise
        # CA bundle support is a v0.6 controlled-injection field.
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        # -- Egress redirection (upper + lower case variants;
        # curl / requests / node all honor lower-case forms):
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        # -- Windows PowerShell hijack:
        # `PSMODULEPATH` poisons `Import-Module` resolution --
        # any script that Imports-Module by name loads the
        # attacker's version. `_NT_SYMBOL_PATH` = point windbg
        # / dbghelp at attacker payloads (network paths supported).
        "PSMODULEPATH",
        "_NT_SYMBOL_PATH",
        "_NT_SYMCACHE_PATH",
        "_NT_ALT_SYMBOL_PATH",
        # -- Build-tool cache / config poisoning:
        # `CARGO_HOME` / `GOPATH` / `GOMODCACHE` re-root package
        # caches (attacker inserts a poisoned dep). `PIP_CONFIG_FILE`
        # / `PIP_INDEX_URL` = redirect pip to attacker's index.
        # `RUSTFLAGS` / `MAKEFLAGS` / `GOFLAGS` = arbitrary build
        # flag injection.
        "CARGO_HOME",
        "GOPATH",
        "GOMODCACHE",
        "GOROOT",
        "PIP_CONFIG_FILE",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_TRUSTED_HOST",
        "RUSTFLAGS",
        "MAKEFLAGS",
        "GOFLAGS",
        # -- Persistence config-root:
        # `XDG_CONFIG_HOME` = attacker-controlled config root for
        # every XDG-conformant tool (git if set, ssh via helpers,
        # etc). `XDG_DATA_HOME` = same for data caches.
        # `HOME` intentionally NOT deny-listed (git / ssh / most
        # POSIX tools break without it); it is a residual risk
        # documented in `docs/SUBSTRATE.md` §sandbox.env_scrubbed
        # and mitigated by bwrap `--ro-bind` on Linux and Seatbelt
        # on macOS. On the Windows unenforced stub, HOME is
        # already noted as a residual risk of the stub itself.
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    }
)


# SP Q3(a) amendment (OpenRouter DEFECT verdict): the frozenset of
# exact upper-case names above misses lower-case variants and glob
# shapes. This prefix set catches every credential-shape family so
# an operator declaring ``aws_access_key_id`` or ``AWS_*`` still
# gets refused. Match is case-insensitive against the upper form.
#
# v0.5.2 module_02 (DA-A F-3 + Ox Alpha co-build Fork 1 verdict C):
# add PREFIX families whose ENTIRE family is dangerous. Enumerated
# names in `NEVER_PASSTHROUGH` above cover the KNOWN-bad specifics;
# these prefixes cover the "next CVE hasn't been named yet" case
# for families where every name is unsafe by construction. Prefix
# is intentionally NOT used for PYTHON / NODE / GIT because those
# families mix safe (PYTHONIOENCODING / NODE_ENV / GIT_AUTHOR_NAME)
# with dangerous names -- enumeration is the right tool there.
NEVER_PASSTHROUGH_PREFIXES: frozenset[str] = frozenset(
    {
        # Credential-shape families (v0.5.1 baseline)
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
        # v0.5.2 module_02 additions -- pure-danger families:
        # `LD_*` -- glibc dynamic-linker knobs, ALL are hijack /
        # tuning / debug primitives (LD_BIND_NOW, LD_DEBUG,
        # LD_ORIGIN_PATH, LD_PROFILE, LD_SHOW_AUXV, ...).
        "LD_",
        # `DYLD_*` -- macOS dyld equivalent. All names are loader
        # hijacks or tunables.
        "DYLD_",
        # `_JAVA_*` -- undocumented JVM auto-options (`_JAVA_OPTIONS`
        # is the canonical instance).
        "_JAVA_",
        # `MALLOC_` -- glibc + macOS malloc-debugging redirections
        # (MALLOC_CHECK_, MALLOC_TRACE, MALLOC_PERTURB_,
        # MallocScribble, etc).
        "MALLOC_",
        # `NPM_CONFIG_` (upper-case; lowercase caught by casefold
        # deny compare) -- every entry is a registry / cafile /
        # ignore-scripts poisoning surface. Deny the whole family;
        # legitimate build steps configure npm via package.json /
        # .npmrc under the worktree, not via env.
        "NPM_CONFIG_",
        # `PIP_` -- pip config env vars (PIP_INDEX_URL /
        # PIP_TRUSTED_HOST / PIP_CONFIG_FILE / PIP_CERT). Every
        # one is either registry redirect or trust-store poison.
        "PIP_",
    }
)


def _platform_case_key(name: str) -> str:
    """v0.5.2 module_02 (DA-A M-4 + Ox Alpha co-build Fork 3 verdict A).

    Return the normalized key for the ``union`` dict + the intersection
    against process_env. On Windows the OS env block is
    case-INsensitive; two entries ``LD_PRELOAD`` and ``ld_preload``
    are the SAME variable to CreateProcess. Casefolding on Windows
    prevents the union counter from double-firing AND ensures the
    intersect step does not carry two distinct spellings of the
    same name into the sandbox env dict (undefined which value
    Windows loader picks when the block has duplicates).

    On POSIX env names are case-SENSITIVE per POSIX; casefolding
    would silently merge ``mode`` and ``MODE`` -- rare but real,
    so keep raw on POSIX.

    Uses ``.upper()`` NOT ``.casefold()`` on Windows to match the
    NT invariant upcasing semantics (e.g., 'ß'.casefold() == 'ss'
    would over-merge; Windows upcases 'ß' to 'ß'). Ox Alpha Fork 3
    gotcha explicitly called this out.
    """
    if sys.platform == "win32":
        return name.upper()
    return name


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


# v0.5.1 wiring module_04 SP Q6 amendment (OpenRouter DEFECT verdict):
# a heuristic detector for credential-shaped names that the operator
# declared in ``manifest.env.passthrough`` but that the deny surface
# does NOT catch. Without this signal, a NEW credential family
# (e.g. ``ANTHROPIC_ORG_TOKEN``, ``CLAUDE_API_KEY``, ``MYCO_SECRET_V3``)
# would slip through until the deny set was patched, and the
# ``never_passthrough_denied`` counter would stay at zero -- giving
# the operator a false sense of safety. The heuristic matches any
# name whose upper form ends in one of the credential-family suffixes.
# A match is passed through (backward-compat: heuristic hits are not
# a hard denial) but is COUNTED and WARN-logged (redacted) so an
# operator auditing the ``sandbox.env_scrubbed`` event sees the
# signal and can add the name to
# ``.ract/never_passthrough_extra.allowlist`` (or upstream to
# ``NEVER_PASSTHROUGH``).
_CREDENTIAL_SHAPE_SUFFIXES: tuple[str, ...] = (
    "_TOKEN",
    "_KEY",
    "_SECRET",
    "_PASSWORD",
    "_PASSWD",
    "_CREDENTIALS",
    "_CREDENTIAL",
    "_API",
    "_AUTH",
    "_ACCESS_KEY_ID",
    "_ACCESS_KEY",
    "_ACCESS_TOKEN",
    "_PRIVATE_KEY",
    "_BEARER",
    "_SESSION_TOKEN",
)


def _is_credential_shaped_but_not_denied(
    name: str, extra_denied: frozenset[str] = frozenset()
) -> bool:
    """Return True when ``name`` looks like a credential but is NOT denied.

    Used as a WARN heuristic; does NOT change the pass/deny decision.
    A name that is already covered by ``NEVER_PASSTHROUGH`` /
    ``NEVER_PASSTHROUGH_PREFIXES`` / ``extra_denied`` returns False
    (the deny surface has it).
    """
    if _is_never_passthrough(name, extra_denied):
        return False
    upper = name.upper()
    return any(upper.endswith(suffix) for suffix in _CREDENTIAL_SHAPE_SUFFIXES)


# v0.5.2 module_02 -- family classifier for the refused-name counter.
# Maps each denied entry to a family bucket for the
# ``sandbox.env_scrubbed`` trace event so an auditor can grep one
# JSONL trace and see "loader-hijack tried 3x in this session"
# without leaking any name. Order matters -- most-specific first.
_REFUSED_FAMILY_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # (family_name, exact_upper_names, upper_prefix_matches)
    (
        "loader",
        (
            "GLIBC_TUNABLES",
            "LOCPATH",
            "NLSPATH",
        ),
        # macOS malloc names use CamelCase (upper == "MALLOC..." with
        # no underscore); catch via bare `MALLOC` prefix in addition
        # to the underscored `MALLOC_` family.
        ("LD_", "DYLD_", "MALLOC_", "MALLOC"),
    ),
    (
        "interpreter",
        (
            "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONBREAKPOINT",
            "PYTHONINSPECT", "PYTHONUSERBASE", "PYTHONDONTWRITEBYTECODE",
            "NODE_OPTIONS", "NODE_PATH",
            "RUBYOPT", "RUBYLIB", "RUBYPATH",
            "PERL5OPT", "PERL5LIB", "PERLIO", "PERL5DB",
            "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "JAVA_OPTS",
            "BASH_ENV", "ENV", "ZDOTDIR", "PROMPT_COMMAND", "CDPATH", "IFS",
        ),
        ("_JAVA_",),
    ),
    (
        "trust_store",
        (
            "SSL_CERT_FILE", "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
            "NODE_EXTRA_CA_CERTS", "GIT_SSL_CAINFO",
        ),
        (),
    ),
    (
        "egress",
        (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        ),
        (),
    ),
    (
        "git_tool",
        (
            "GIT_SSH_COMMAND", "GIT_EXEC_PATH", "GIT_ASKPASS", "SSH_ASKPASS",
            "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
            "GIT_TRACE", "GIT_TRACE_PACKET", "GIT_TRACE_SETUP",
            "GIT_HTTP_LOW_SPEED_LIMIT", "GIT_HTTP_LOW_SPEED_TIME",
            "GIT_PROXY_COMMAND",
        ),
        (),
    ),
    (
        "editor",
        ("EDITOR", "VISUAL", "PAGER", "SYSTEMD_EDITOR", "SYSTEMD_PAGER"),
        (),
    ),
    (
        "windows_module",
        ("PSMODULEPATH",),
        ("_NT_",),
    ),
    (
        "build_cache",
        (
            "CARGO_HOME", "GOPATH", "GOMODCACHE", "GOROOT",
            "RUSTFLAGS", "MAKEFLAGS", "GOFLAGS",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME",
        ),
        ("NPM_CONFIG_", "PIP_"),
    ),
    (
        "credential",
        # Leaf-name credentials whose prefix does NOT match one of the
        # credential-family prefixes below (GITHUB / GH / no shared root).
        (
            "GITHUB_TOKEN",
            "GH_TOKEN",
        ),
        (
            "AWS_", "OPENAI_", "ANTHROPIC_", "GOOGLE_", "OPENROUTER_",
            "DEEPSEEK_", "NPM_", "PYPI_", "TWINE_", "DOCKER_", "SLACK_",
            "AZURE_", "GCP_", "STRIPE_",
        ),
    ),
)


def _classify_refused_family(name: str) -> str:
    """Return the family bucket for a refused env-var name.

    Used to populate ``SandboxEnvResult.refused_family_counts`` and
    the ``sandbox.env_scrubbed`` trace event's ``refused_family_counts``
    details dict. The family names are stable audit strings -- an
    external SIEM correlating RACT trace events keys on these.

    Falls through to ``"other"`` for a name that hits the deny surface
    via ``extra_denied`` or ``_is_never_passthrough`` glob-shape check
    (the operator-declared ``AWS_*`` case).
    """
    if any(ch in name for ch in "*?["):
        return "glob_shape"
    upper = name.upper()
    for family, exacts, prefixes in _REFUSED_FAMILY_RULES:
        if upper in exacts:
            return family
        for prefix in prefixes:
            if upper.startswith(prefix):
                return family
    return "other"


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
    - ``credential_shaped_unblocked_count`` (SP Q6 amendment) names
      allowlist entries whose SHAPE looks like a credential (suffix
      match on ``_TOKEN`` / ``_KEY`` / ``_SECRET`` / etc.) but that
      the deny surface did NOT catch. These names ARE passed through
      -- the heuristic is a WARN signal, not a hard denial -- but a
      non-zero count means the deny surface has a gap the operator
      should close (extend ``NEVER_PASSTHROUGH`` or add the entry to
      the extra-denied file). Wired into ``sandbox.env_scrubbed`` so
      operators see it in trace-line audits.
    - ``allowlist_source`` is one of ``"manifest"``, ``"file"``,
      ``"default"`` -- whichever source contributed the largest set of
      names; ties resolve to the more explicit source.
    - ``refused_family_counts`` (v0.5.2 module_02) is a dict mapping
      each family bucket ("loader", "interpreter", "trust_store",
      "egress", "git_tool", "editor", "windows_module",
      "build_cache", "credential", "glob_shape", "other") to the
      count of denied allowlist entries in that bucket. Every entry
      counted in ``never_passthrough_denied`` also increments one
      bucket here. Empty dict when no denials fired.
    """

    env: dict[str, str]
    scrubbed_count: int = 0
    never_passthrough_denied: int = 0
    credential_shaped_unblocked_count: int = 0
    allowlist_source: str = "default"
    refused_family_counts: dict[str, int] = field(default_factory=dict)


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
    # multiple sources still lands in the union once. On Windows the
    # ``_platform_case_key`` helper folds keys to upper-case so
    # ``LD_PRELOAD`` and ``ld_preload`` are the SAME union entry --
    # first-source-wins for attribution (v0.5.2 module_02, DA-A M-4 +
    # Ox Alpha co-build Fork 3). Original spelling of the first
    # declaration is preserved in ``union_original`` for downstream
    # use (WARN log, env intersect).
    union: dict[str, str] = {}  # key -> source
    union_original: dict[str, str] = {}  # key -> original spelling
    for name in manifest_passthrough:
        k = _platform_case_key(name)
        if union.setdefault(k, "manifest") == "manifest" and k not in union_original:
            union_original[k] = name
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
            k = _platform_case_key(name)
            union.setdefault(k, "file")
            union_original.setdefault(k, name)
    if include_default:
        for name in DEFAULT_ALLOWLIST:
            k = _platform_case_key(name)
            union.setdefault(k, "default")
            union_original.setdefault(k, name)

    # Apply NEVER_PASSTHROUGH denies. SP Q3(a) amendment: use
    # case-insensitive prefix + exact match so a manifest entry like
    # ``aws_access_key_id`` or ``AWS_*`` still refuses. SP Q3(b)
    # amendment: log a REDACTED form of the name so audits see the
    # refusal family without leaking the specific env var name.
    #
    # v0.5.1 wiring module_04 SP Q6 amendment: also count (but do NOT
    # deny) allowlist entries that are credential-SHAPED (suffix
    # match on _TOKEN, _KEY, _SECRET, etc.) but that the deny surface
    # did not catch. A non-zero count is a signal to close a deny-set
    # gap; keep backward-compat by passing the name through (some
    # legitimate build systems declare ``BUILD_SIGNING_KEY_PATH``, so
    # a hard deny here would break real users).
    #
    # v0.5.2 module_02 amendment: every denied entry ALSO increments
    # a ``refused_family_counts`` bucket so an auditor grepping the
    # ``sandbox.env_scrubbed`` trace event can see "loader-hijack tried
    # 3x this session" without any name leaking to the trace.
    extra_denied_set = frozenset(extra_denied)
    denied_hits = 0
    credential_shaped_unblocked = 0
    scrubbed_env: dict[str, str] = {}
    denied_keys: set[str] = set()
    refused_family_counts: dict[str, int] = {}
    for key, source in union.items():
        name = union_original.get(key, key)
        if _is_never_passthrough(name, extra_denied_set):
            denied_hits += 1
            denied_keys.add(key)
            family = _classify_refused_family(name)
            refused_family_counts[family] = refused_family_counts.get(family, 0) + 1
            _LOG.warning(
                "sandbox_env: denied allowlist entry %r (source=%s, "
                "family=%s); in NEVER_PASSTHROUGH — the substrate "
                "refuses to pass library-injection / credential-shaped "
                "names into the sandbox",
                _redact_name_for_log(name),
                source,
                family,
            )
            continue
        if _is_credential_shaped_but_not_denied(name, extra_denied_set):
            credential_shaped_unblocked += 1
            _LOG.warning(
                "sandbox_env: allowlist entry %r (source=%s) looks "
                "credential-shaped but is NOT in NEVER_PASSTHROUGH. "
                "The name is passed through (backward-compat); if "
                "this is a credential family the substrate does not "
                "recognise, add it to NEVER_PASSTHROUGH or to "
                "``.ract/never_passthrough_extra.allowlist``.",
                _redact_name_for_log(name),
                source,
            )
        # Intersect against process env. On Windows the process env
        # is case-insensitive so we look up by the folded key against
        # every process_env entry (there may be multiple case variants
        # if the process was launched by a POSIX shim -- shouldn't
        # happen but defensive). On POSIX, exact match against the
        # original spelling.
        if sys.platform == "win32":
            for env_name, env_val in env_source.items():
                if _platform_case_key(env_name) == key:
                    scrubbed_env[env_name] = env_val
                    break
        else:
            if name in env_source:
                scrubbed_env[name] = env_source[name]

    # Count names in process env that were NOT allowlisted. On Windows
    # fold both sides via _platform_case_key so `ld_preload` in the
    # process env counts as scrubbed against a `LD_PRELOAD` denied key.
    scrubbed_count = 0
    for env_name in env_source:
        k = _platform_case_key(env_name)
        if k not in union or k in denied_keys:
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
        credential_shaped_unblocked_count=credential_shaped_unblocked,
        allowlist_source=primary,
        refused_family_counts=dict(refused_family_counts),
    )


def default_allowlist_path(project_dir: Path) -> Path:
    """Return the canonical location of the project's allowlist file."""
    return Path(project_dir) / ".ract" / ALLOWLIST_FILE_NAME


__all__ = [
    "ALLOWLIST_FILE_NAME",
    "AllowlistFileMalformed",
    "DEFAULT_ALLOWLIST",
    "NEVER_PASSTHROUGH",
    "NEVER_PASSTHROUGH_PREFIXES",
    "SandboxEnvResult",
    "build_sandbox_env",
    "default_allowlist_path",
    "load_allowlist_file",
    # v0.5.2 module_02:
    "_classify_refused_family",
    "_platform_case_key",
]


# RACT 0.5.1
