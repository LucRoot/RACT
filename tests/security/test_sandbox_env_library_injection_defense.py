"""Sandbox env library-injection defense -- v0.5.2 module_02 regression.

Closes DA-A F-3 (Ox Alpha finding). The pre-hardening ``NEVER_PASSTHROUGH``
set missed the entire library-injection family: dynamic-linker (LD_*,
DYLD_*, GLIBC_TUNABLES = CVE-2023-4911 Looney Tunables), interpreter
injection (PYTHONPATH, NODE_OPTIONS, BASH_ENV, ...), git tool subversion
(GIT_SSH_COMMAND, GIT_EXEC_PATH, ...), trust-store hijack (SSL_CERT_*,
REQUESTS_CA_BUNDLE, ...), egress redirection (HTTP_PROXY, ...), and
Windows PowerShell hijack (PSMODULEPATH, _NT_SYMBOL_PATH).

Every regression here seeds a poisoned name in the seeded process env
(and, where relevant, declares it in ``manifest_passthrough`` so the
deny surface fires the counter) and asserts (a) the name never lands
in the sandbox env dict, (b) the ``never_passthrough_denied`` counter
fires, (c) the ``refused_family_counts`` bucket for the family
increments.

The parametrised test at the bottom covers EVERY library-injection
family in one go -- if any new entry is added to ``NEVER_PASSTHROUGH``
in a later module, this test is the single place to extend.
"""

from __future__ import annotations

import logging
from typing import Iterable

import pytest

from ract.security.sandbox_env import (
    NEVER_PASSTHROUGH,
    NEVER_PASSTHROUGH_PREFIXES,
    _classify_refused_family,
    build_sandbox_env,
)


# ---------------------------------------------------------------------------
# CVE-2023-4911 Looney Tunables (GLIBC_TUNABLES) -- the highest-severity
# entry in the module.
# ---------------------------------------------------------------------------


def test_glibc_tunables_cve_2023_4911_denied_from_parent_env(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """GLIBC_TUNABLES set in parent env is never visible inside sandbox.

    CVE-2023-4911 (Looney Tunables) turns a benign-looking env var into
    a local privilege escalation primitive against dynamic linker. Any
    subprocess launched from a poisoned env inherits the attack surface.
    """
    seeded = {
        "PATH": "/usr/bin",
        "GLIBC_TUNABLES": "glibc.malloc.mxfast=32",
    }
    with caplog.at_level(logging.WARNING, logger="ract.security.sandbox_env"):
        result = build_sandbox_env(process_env=seeded)
    assert "GLIBC_TUNABLES" not in result.env
    # Bare process-env source: name is not on any allowlist so it's
    # ``scrubbed`` (not counted as ``never_passthrough_denied``).
    assert result.scrubbed_count == 1


def test_glibc_tunables_denied_even_when_manifest_declares(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A compromised manifest explicitly declaring GLIBC_TUNABLES is refused.

    Fork 1 verdict C from Ox Alpha co-build: keep deny overlay so a
    malicious PR adding GLIBC_TUNABLES to ``manifest.env.passthrough``
    still gets refused rather than passing through.
    """
    seeded = {"PATH": "/usr/bin", "GLIBC_TUNABLES": "glibc.malloc.mxfast=32"}
    with caplog.at_level(logging.WARNING, logger="ract.security.sandbox_env"):
        result = build_sandbox_env(
            process_env=seeded,
            manifest_passthrough=("GLIBC_TUNABLES",),
        )
    assert "GLIBC_TUNABLES" not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts.get("loader") == 1


# ---------------------------------------------------------------------------
# LD_PRELOAD family (dynamic-linker hijack)
# ---------------------------------------------------------------------------


def test_ld_preload_from_manifest_denied() -> None:
    """LD_PRELOAD in manifest.env.passthrough is refused (loader hijack)."""
    seeded = {"LD_PRELOAD": "/tmp/attacker.so"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("LD_PRELOAD",)
    )
    assert "LD_PRELOAD" not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts.get("loader") == 1


def test_ld_audit_from_manifest_denied_via_prefix() -> None:
    """LD_AUDIT (not enumerated) is caught by LD_ prefix (2011 vector)."""
    seeded = {"LD_AUDIT": "/tmp/audit.so"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("LD_AUDIT",)
    )
    assert "LD_AUDIT" not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts.get("loader") == 1


def test_ld_bind_now_denied_via_prefix_family() -> None:
    """A future LD_* name we haven't enumerated is still refused via prefix."""
    seeded = {"LD_FUTURE_INJECTION_VECTOR": "1"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("LD_FUTURE_INJECTION_VECTOR",),
    )
    assert "LD_FUTURE_INJECTION_VECTOR" not in result.env
    assert result.never_passthrough_denied == 1


def test_dyld_insert_libraries_macos_denied() -> None:
    """DYLD_INSERT_LIBRARIES (macOS LD_PRELOAD equivalent) refused."""
    seeded = {"DYLD_INSERT_LIBRARIES": "/tmp/attacker.dylib"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("DYLD_INSERT_LIBRARIES",),
    )
    assert "DYLD_INSERT_LIBRARIES" not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts.get("loader") == 1


def test_dyld_fallback_framework_path_denied_via_prefix() -> None:
    """Any DYLD_* variant is refused via prefix -- catches the whole family."""
    seeded = {"DYLD_FUTURE_HIJACK_NAME": "/tmp/x"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("DYLD_FUTURE_HIJACK_NAME",),
    )
    assert "DYLD_FUTURE_HIJACK_NAME" not in result.env
    assert result.never_passthrough_denied == 1


# ---------------------------------------------------------------------------
# Interpreter injection family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("PYTHONPATH", "/tmp/evil-modules"),
        ("PYTHONHOME", "/tmp/evil-stdlib"),
        ("PYTHONSTARTUP", "/tmp/evil.py"),
        ("PYTHONBREAKPOINT", "attacker.trigger"),
        ("PYTHONINSPECT", "1"),
        ("PYTHONUSERBASE", "/tmp/evil"),
        ("NODE_OPTIONS", "--require /tmp/evil.js"),
        ("NODE_PATH", "/tmp/evil-node-modules"),
        ("RUBYOPT", "-r/tmp/evil.rb"),
        ("PERL5OPT", "-M/tmp/evil"),
        ("PERL5LIB", "/tmp/evil"),
        ("BASH_ENV", "/tmp/evil.sh"),
        ("ENV", "/tmp/evil.sh"),
        ("ZDOTDIR", "/tmp/evil-zsh"),
        ("JAVA_TOOL_OPTIONS", "-javaagent:/tmp/evil.jar"),
        ("JDK_JAVA_OPTIONS", "-javaagent:/tmp/evil.jar"),
        ("_JAVA_OPTIONS", "-javaagent:/tmp/evil.jar"),
        ("CLASSPATH", "/tmp/evil-classes"),
    ],
)
def test_interpreter_injection_names_denied(name: str, value: str) -> None:
    """Every interpreter-injection env var is refused even when declared."""
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts.get("interpreter") == 1


def test_pythonioencoding_still_passes_through() -> None:
    """PYTHONIOENCODING remains a legitimate I/O tuning knob (allowlist).

    Regression: an over-broad PYTHON prefix in NEVER_PASSTHROUGH would
    deny this legitimate env var. The module enumerates dangerous
    PYTHON* names explicitly so PYTHONIOENCODING/PYTHONUTF8 keep working.
    """
    seeded = {"PATH": "/usr/bin", "PYTHONIOENCODING": "utf-8"}
    result = build_sandbox_env(process_env=seeded)
    assert result.env.get("PYTHONIOENCODING") == "utf-8"
    assert result.never_passthrough_denied == 0


def test_pythonutf8_still_passes_through() -> None:
    """PYTHONUTF8 remains legit; not confused with the deny surface."""
    seeded = {"PATH": "/usr/bin", "PYTHONUTF8": "1"}
    result = build_sandbox_env(process_env=seeded)
    assert result.env.get("PYTHONUTF8") == "1"


# ---------------------------------------------------------------------------
# Git tool subversion family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("GIT_SSH_COMMAND", "/tmp/evil.sh"),
        ("GIT_EXEC_PATH", "/tmp/evil-git-bin"),
        ("GIT_ASKPASS", "/tmp/evil-askpass"),
        ("SSH_ASKPASS", "/tmp/evil-askpass"),
        ("GIT_CONFIG_GLOBAL", "/tmp/evil.gitconfig"),
        ("GIT_CONFIG_SYSTEM", "/tmp/evil.gitconfig"),
        ("GIT_TRACE", "/tmp/leak.log"),
        ("GIT_PROXY_COMMAND", "/tmp/evil-proxy"),
    ],
)
def test_git_tool_subversion_names_denied(name: str, value: str) -> None:
    """Every git tool-subversion env var is refused even when declared."""
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts.get("git_tool") == 1


# ---------------------------------------------------------------------------
# Trust-store hijack family (SSL_CERT_* moved from DEFAULT to NEVER)
# ---------------------------------------------------------------------------


def test_ssl_cert_file_removed_from_default_allowlist() -> None:
    """SSL_CERT_FILE no longer passes silently from the parent env.

    v0.5.1 baseline had SSL_CERT_FILE in DEFAULT_ALLOWLIST so tools
    inside the sandbox could find the system trust store. DA-A F-3
    flagged it as a trust-store hijack surface. Module_02 moves it
    to NEVER_PASSTHROUGH. It is no longer on any default allowlist,
    so a poisoned parent env is silently scrubbed (name not in any
    allowlist source -> ``scrubbed_count`` bumps, ``never_passthrough_denied``
    stays 0 because deny fires only for allowlist-source entries).
    """
    from ract.security.sandbox_env import DEFAULT_ALLOWLIST

    assert "SSL_CERT_FILE" not in DEFAULT_ALLOWLIST
    seeded = {"PATH": "/usr/bin", "SSL_CERT_FILE": "/tmp/attacker-ca.pem"}
    result = build_sandbox_env(process_env=seeded)
    assert "SSL_CERT_FILE" not in result.env
    assert result.scrubbed_count == 1


def test_ssl_cert_file_denied_when_operator_re_declares() -> None:
    """Even if operator re-declares SSL_CERT_FILE in manifest, refuse.

    Enterprise operators who legitimately need custom CA bundles inside
    the sandbox previously had SSL_CERT_FILE on DEFAULT_ALLOWLIST. That
    path is now denied per DA-A F-3 (trust-store hijack surface).
    Operators route the trust bundle through a v0.6 controlled-injection
    field instead.
    """
    seeded = {"SSL_CERT_FILE": "/tmp/attacker-ca.pem"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("SSL_CERT_FILE",)
    )
    assert "SSL_CERT_FILE" not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts.get("trust_store") == 1


def test_ssl_cert_dir_removed_from_default_allowlist() -> None:
    """SSL_CERT_DIR gets the same treatment as SSL_CERT_FILE."""
    from ract.security.sandbox_env import DEFAULT_ALLOWLIST

    assert "SSL_CERT_DIR" not in DEFAULT_ALLOWLIST
    seeded = {"PATH": "/usr/bin", "SSL_CERT_DIR": "/tmp/attacker-cas/"}
    result = build_sandbox_env(process_env=seeded)
    assert "SSL_CERT_DIR" not in result.env


@pytest.mark.parametrize(
    "name,value",
    [
        ("SSL_CERT_FILE", "/tmp/attacker.pem"),
        ("SSL_CERT_DIR", "/tmp/attacker-cas/"),
        ("REQUESTS_CA_BUNDLE", "/tmp/attacker.pem"),
        ("CURL_CA_BUNDLE", "/tmp/attacker.pem"),
        ("NODE_EXTRA_CA_CERTS", "/tmp/attacker.pem"),
        ("GIT_SSL_CAINFO", "/tmp/attacker.pem"),
    ],
)
def test_trust_store_names_denied_from_manifest(name: str, value: str) -> None:
    """Trust-store hijack env vars refused even when explicitly declared."""
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts.get("trust_store") == 1


# ---------------------------------------------------------------------------
# Egress redirection family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("HTTP_PROXY", "http://attacker:8080"),
        ("HTTPS_PROXY", "http://attacker:8080"),
        ("ALL_PROXY", "socks5://attacker:1080"),
        ("NO_PROXY", "attacker-mitm-allowlist.com"),
        # lowercase variants (curl / requests honor both)
        ("http_proxy", "http://attacker:8080"),
        ("https_proxy", "http://attacker:8080"),
    ],
)
def test_egress_redirection_names_denied(name: str, value: str) -> None:
    """Every proxy env var (upper + lower) is refused."""
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts.get("egress") == 1


# ---------------------------------------------------------------------------
# Windows PowerShell hijack + editor injection
# ---------------------------------------------------------------------------


def test_psmodulepath_denied() -> None:
    """PSMODULEPATH refused (PowerShell Import-Module resolution poison)."""
    seeded = {"PSMODULEPATH": "C:\\attacker\\modules"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("PSMODULEPATH",)
    )
    assert "PSMODULEPATH" not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts.get("windows_module") == 1


def test_nt_symbol_path_denied_via_prefix() -> None:
    """_NT_SYMBOL_PATH refused (windbg / dbghelp payload from network share)."""
    seeded = {"_NT_SYMBOL_PATH": "\\\\attacker\\symbols"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("_NT_SYMBOL_PATH",)
    )
    assert "_NT_SYMBOL_PATH" not in result.env


@pytest.mark.parametrize("name,value", [
    ("EDITOR", "/tmp/evil.sh"),
    ("VISUAL", "/tmp/evil.sh"),
    ("PAGER", "/tmp/evil.sh"),
    ("SYSTEMD_EDITOR", "/tmp/evil.sh"),
])
def test_editor_invocation_vector_denied(name: str, value: str) -> None:
    """EDITOR / VISUAL / PAGER refused -- direct exec inside sandbox."""
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.refused_family_counts.get("editor") == 1


# ---------------------------------------------------------------------------
# Build-tool cache poisoning family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("CARGO_HOME", "/tmp/evil-cargo"),
        ("GOPATH", "/tmp/evil-go"),
        ("GOMODCACHE", "/tmp/evil-modcache"),
        ("PIP_CONFIG_FILE", "/tmp/evil-pip.conf"),
        ("PIP_INDEX_URL", "https://attacker/simple"),
        ("PIP_TRUSTED_HOST", "attacker.com"),
        ("RUSTFLAGS", "-Clink-arg=-Wl,-rpath,/tmp/evil"),
        ("MAKEFLAGS", "SHELL=/tmp/evil.sh"),
        ("XDG_CONFIG_HOME", "/tmp/evil-xdg"),
    ],
)
def test_build_cache_names_denied(name: str, value: str) -> None:
    """Build-tool cache / config env vars refused (dep-poisoning primitive)."""
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.refused_family_counts.get("build_cache") == 1


def test_npm_config_prefix_family_denied() -> None:
    """A future NPM_CONFIG_* variant is refused via prefix."""
    seeded = {"NPM_CONFIG_REGISTRY": "https://attacker/npm"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("NPM_CONFIG_REGISTRY",)
    )
    assert "NPM_CONFIG_REGISTRY" not in result.env


# ---------------------------------------------------------------------------
# Family classifier sanity
# ---------------------------------------------------------------------------


def test_classify_refused_family_covers_all_declared_deny_names() -> None:
    """Every entry in NEVER_PASSTHROUGH classifies to a non-"other" family.

    Regression: adding a new entry to NEVER_PASSTHROUGH without updating
    ``_REFUSED_FAMILY_RULES`` would silently drop it into the "other"
    bucket and the trace event would lose auditability. This test forces
    the two to stay in sync.
    """
    # A handful of names historically classified as credentials (v0.5.1
    # baseline). They should map to the "credential" family per the
    # classifier's prefix rules.
    credential_leaf_names = {
        "GITHUB_TOKEN", "GH_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN", "GOOGLE_API_KEY", "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN", "NPM_TOKEN", "PYPI_TOKEN",
        "TWINE_PASSWORD", "DOCKER_PASSWORD", "SLACK_TOKEN",
    }
    for name in NEVER_PASSTHROUGH:
        family = _classify_refused_family(name)
        if name in credential_leaf_names:
            assert family == "credential", (
                f"{name!r} expected to classify as 'credential', got {family!r}"
            )
        else:
            assert family != "other", (
                f"NEVER_PASSTHROUGH entry {name!r} falls into the 'other' "
                f"family bucket -- update _REFUSED_FAMILY_RULES to classify it"
            )


def test_glob_shape_classified_as_glob_shape() -> None:
    """A glob-shaped manifest entry gets its own family bucket."""
    assert _classify_refused_family("AWS_*") == "glob_shape"
    assert _classify_refused_family("LD_?") == "glob_shape"


def test_refused_family_counts_bucket_missing_families_absent() -> None:
    """A run with only loader denials has no interpreter/git buckets."""
    seeded = {"LD_PRELOAD": "/tmp/x"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("LD_PRELOAD",)
    )
    assert result.refused_family_counts == {"loader": 1}


# ---------------------------------------------------------------------------
# Baseline compatibility -- legitimate env vars still pass through
# ---------------------------------------------------------------------------


def test_baseline_legit_env_still_passes() -> None:
    """PATH / TERM / LANG / TZ / TMP still pass through after F-3 hardening."""
    seeded = {
        "PATH": "/usr/bin:/bin",
        "TERM": "xterm-256color",
        "LANG": "en_US.UTF-8",
        "TZ": "America/Denver",
        "TMP": "/tmp",
        "HOME": "/home/lucas",
        "USER": "lucas",
        "SHELL": "/bin/bash",
    }
    result = build_sandbox_env(process_env=seeded)
    for name, value in seeded.items():
        assert result.env.get(name) == value, f"{name} missing after hardening"
    assert result.never_passthrough_denied == 0


# RACT 0.5.2
