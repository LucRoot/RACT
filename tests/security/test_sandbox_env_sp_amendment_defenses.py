"""SP-amendment library-injection defenses -- v0.5.2 module_02.

Regression tests for the DEFECT folds surfaced by Ox Alpha SP Q1
(coverage gaps) + Q2 (prefix false-positive risk):

- ``GCONV_PATH`` -- glibc iconv dlopen (classic .so injection).
- ``OPENSSL_CONF`` / ``OPENSSL_MODULES`` / ``OPENSSL_ENGINES``.
- ``GIT_CONFIG_COUNT`` + ``GIT_CONFIG_KEY_N`` / ``GIT_CONFIG_VALUE_N``
  smuggle path that bypassed ``GIT_CONFIG_GLOBAL`` / ``SYSTEM`` denial.
- ``BASH_FUNC_*`` ShellShock-legacy exported-function injection.
- .NET profiler injection (``COR_ENABLE_PROFILING`` / ``COR_PROFILER`` /
  ``COR_PROFILER_PATH`` / CoreCLR variants).
- JVM build-tool javaagent injection (``MAVEN_OPTS`` / ``GRADLE_OPTS`` /
  ``SBT_OPTS``).
- Version-manager root redirects (``RUSTUP_HOME`` / ``PYENV_ROOT``).
- ``DOTNET_ROOT`` / ``MSBUILD_EXE_PATH`` toolchain redirects.
- Container runtime tool subversion (``DOCKER_HOST`` / ``DOCKER_CONFIG``
  / ``KUBECONFIG``).
- Go proxy / sumdb (``GOPROXY`` / ``GOSUMDB``).
- Kerberos config redirect (``KRB5_CONFIG``).
- Q2 fold: ``NPM_CONFIG_LOGLEVEL`` and ``PIP_NO_INDEX`` LEGIT pass
  through after prefix drop; ``PIP_CONFIG_FILE`` still denied.
"""

from __future__ import annotations

import pytest

from ract.security.sandbox_env import build_sandbox_env


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- glibc dlopen (GCONV_PATH)
# ---------------------------------------------------------------------------


def test_gconv_path_denied() -> None:
    """GCONV_PATH refused -- classic glibc iconv_open() dlopen vector.

    Not caught by the LD_ prefix. Ox Alpha SP Q1 primary defect.
    """
    seeded = {"GCONV_PATH": "/tmp/attacker/gconv"}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=("GCONV_PATH",))
    assert "GCONV_PATH" not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts["loader"] == 1


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- OpenSSL engine / module injection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("OPENSSL_CONF", "/tmp/attacker.cnf"),
        ("OPENSSL_MODULES", "/tmp/attacker-providers"),
        ("OPENSSL_ENGINES", "/tmp/attacker-engines"),
        ("GNUTLS_SYSTEM_PRIORITY_FILE", "/tmp/attacker-priority.cfg"),
    ],
)
def test_openssl_config_dlopen_vectors_denied(name: str, value: str) -> None:
    """OPENSSL_CONF (+ modules/engines) refused -- engine dlopen primitive.

    ``[openssl_init] engines = evil_engine`` + ``dynamic_path = /path/foo.so``
    dlopens attacker code. Classic vector Ox Alpha flagged as textbook.
    """
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts["interpreter"] == 1


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- GIT_CONFIG_COUNT smuggle bypass
# ---------------------------------------------------------------------------


def test_git_config_count_smuggle_denied() -> None:
    """GIT_CONFIG_COUNT + GIT_CONFIG_KEY_N + GIT_CONFIG_VALUE_N bypass.

    Primary commit denied GIT_CONFIG_GLOBAL / GIT_CONFIG_SYSTEM. Ox Alpha
    SP Q1 caught that GIT_CONFIG_COUNT is a separate git-config injection
    surface: an attacker sets
    ``GIT_CONFIG_COUNT=1;GIT_CONFIG_KEY_0=core.fsmonitor;GIT_CONFIG_VALUE_0=/tmp/evil.sh``
    and every git command executes ``/tmp/evil.sh`` via the fsmonitor
    hook, bypassing the GIT_CONFIG_GLOBAL denial entirely.

    Fix: GIT_CONFIG_ prefix in NEVER_PASSTHROUGH_PREFIXES catches
    GIT_CONFIG_COUNT + GIT_CONFIG_KEY_N + GIT_CONFIG_VALUE_N for any N.
    """
    seeded = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "/tmp/evil.sh",
    }
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=(
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_KEY_0",
            "GIT_CONFIG_VALUE_0",
        ),
    )
    assert "GIT_CONFIG_COUNT" not in result.env
    assert "GIT_CONFIG_KEY_0" not in result.env
    assert "GIT_CONFIG_VALUE_0" not in result.env
    assert result.never_passthrough_denied == 3
    assert result.refused_family_counts["git_tool"] == 3


def test_git_config_key_high_index_still_denied() -> None:
    """GIT_CONFIG_KEY_99 still denied -- prefix catches arbitrary N."""
    seeded = {"GIT_CONFIG_KEY_99": "core.pager"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("GIT_CONFIG_KEY_99",)
    )
    assert "GIT_CONFIG_KEY_99" not in result.env


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- BASH_FUNC ShellShock legacy
# ---------------------------------------------------------------------------


def test_bash_func_exported_function_denied() -> None:
    """BASH_FUNC_evil%% refused -- ShellShock-legacy exported-function inject."""
    # BASH_FUNC_ name shape from ShellShock; the '%' end suffix indicates
    # an exported function.  Any bash launched with this in env would
    # define the function.
    seeded = {"BASH_FUNC_ls%%": "() { rm -rf /; }"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("BASH_FUNC_ls%%",)
    )
    assert "BASH_FUNC_ls%%" not in result.env
    assert result.never_passthrough_denied == 1
    # Falls under interpreter (bash) family:
    assert result.refused_family_counts["interpreter"] == 1


def test_bash_xtracefd_denied_via_prefix() -> None:
    """BASH_ prefix also catches BASH_XTRACEFD / BASH_ENV etc."""
    seeded = {"BASH_XTRACEFD": "3"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("BASH_XTRACEFD",)
    )
    assert "BASH_XTRACEFD" not in result.env


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- .NET profiler injection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("COR_ENABLE_PROFILING", "1"),
        ("COR_PROFILER", "{deadbeef-cafe-babe-face-0123456789ab}"),
        ("COR_PROFILER_PATH", "/tmp/attacker.dll"),
        ("CORECLR_ENABLE_PROFILING", "1"),
        ("CORECLR_PROFILER", "{deadbeef-cafe-babe-face-0123456789ab}"),
        ("CORECLR_PROFILER_PATH", "/tmp/attacker.dll"),
        ("CORECLR_PROFILER_PATH_64", "/tmp/attacker64.dll"),
    ],
)
def test_dotnet_profiler_injection_denied(name: str, value: str) -> None:
    """.NET profiler env vars refused -- textbook CLR code-injection.

    COR_ / CORECLR_ prefixes catch every profiler-family variant.
    """
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.never_passthrough_denied == 1


def test_complus_prefix_denied() -> None:
    """COMPlus_ (legacy .NET runtime knobs) denied via prefix."""
    seeded = {"COMPlus_TieredCompilation": "0"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("COMPlus_TieredCompilation",)
    )
    assert "COMPlus_TieredCompilation" not in result.env


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- JVM build-tool javaagent injection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("MAVEN_OPTS", "-javaagent:/tmp/evil.jar"),
        ("GRADLE_OPTS", "-javaagent:/tmp/evil.jar"),
        ("SBT_OPTS", "-javaagent:/tmp/evil.jar"),
        ("LEIN_JVM_OPTS", "-javaagent:/tmp/evil.jar"),
        ("ANT_OPTS", "-javaagent:/tmp/evil.jar"),
    ],
)
def test_jvm_build_tool_opts_denied(name: str, value: str) -> None:
    """JVM build-tool option env vars refused -- javaagent inject bypass."""
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.never_passthrough_denied == 1


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- version-manager root redirects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("RUSTUP_HOME", "/tmp/attacker-rustup"),
        ("PYENV_ROOT", "/tmp/attacker-pyenv"),
        ("PYENV_VERSION", "3.7.attacker"),
        ("RBENV_ROOT", "/tmp/attacker-rbenv"),
        ("NVM_DIR", "/tmp/attacker-nvm"),
        ("VOLTA_HOME", "/tmp/attacker-volta"),
        ("ASDF_DATA_DIR", "/tmp/attacker-asdf"),
    ],
)
def test_version_manager_root_denied(name: str, value: str) -> None:
    """Version-manager roots refused -- toolchain redirect primitive."""
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts["build_cache"] == 1


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- .NET host redirect
# ---------------------------------------------------------------------------


def test_dotnet_root_denied() -> None:
    """DOTNET_ROOT redirect refused -- every `dotnet` command hijacked."""
    seeded = {"DOTNET_ROOT": "/tmp/attacker-dotnet"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("DOTNET_ROOT",)
    )
    assert "DOTNET_ROOT" not in result.env


def test_msbuild_exe_path_denied() -> None:
    """MSBUILD_EXE_PATH refused -- msbuild binary hijack."""
    seeded = {"MSBUILD_EXE_PATH": "C:\\attacker\\msbuild.exe"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("MSBUILD_EXE_PATH",)
    )
    assert "MSBUILD_EXE_PATH" not in result.env


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- container runtime tool subversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("DOCKER_HOST", "tcp://attacker:2375"),
        ("DOCKER_CERT_PATH", "/tmp/attacker-certs"),
        ("DOCKER_CONTEXT", "attacker-context"),
        ("DOCKER_CONFIG", "/tmp/attacker-docker"),
        ("CONTAINER_HOST", "tcp://attacker:8080"),
        ("BUILDKIT_HOST", "tcp://attacker:8080"),
        ("KUBECONFIG", "/tmp/attacker-kubeconfig"),
    ],
)
def test_container_runtime_env_denied(name: str, value: str) -> None:
    """Container runtime env vars refused -- every docker/kubectl hijacked."""
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.never_passthrough_denied == 1


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- Go proxy / sumdb / npm cafile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("GOPROXY", "https://attacker/mod"),
        ("GOSUMDB", "off"),
        ("GOPRIVATE", "*"),
        ("NPM_CONFIG_CAFILE", "/tmp/attacker.pem"),
        ("NPM_CONFIG_STRICT_SSL", "false"),
        ("NPM_CONFIG_IGNORE_SCRIPTS", "false"),
        ("NPM_CONFIG_SCRIPT_SHELL", "/tmp/evil.sh"),
        ("COMPOSER_HOME", "/tmp/attacker-composer"),
    ],
)
def test_supply_chain_env_denied(name: str, value: str) -> None:
    """Supply-chain redirection env vars refused."""
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- Kerberos config redirect
# ---------------------------------------------------------------------------


def test_krb5_config_denied() -> None:
    """KRB5_CONFIG refused -- rogue KDC / weak enctype config."""
    seeded = {"KRB5_CONFIG": "/tmp/attacker.krb5"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("KRB5_CONFIG",)
    )
    assert "KRB5_CONFIG" not in result.env


# ---------------------------------------------------------------------------
# Ox Alpha SP Q1 DEFECT -- misc language/tool subversions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,value",
    [
        ("PHPRC", "/tmp/attacker.ini"),
        ("PHP_INI_SCAN_DIR", "/tmp/attacker"),
        ("ERL_FLAGS", "-noshell -eval 'os:cmd(\"evil\")'"),
        ("LUA_CPATH", "/tmp/attacker/?.so"),
        ("LUA_INIT", "@/tmp/attacker.lua"),
        ("WGETRC", "/tmp/attacker.wgetrc"),
        ("CURL_HOME", "/tmp/attacker-curl"),
        ("SYSTEMD_UNIT_PATH", "/tmp/attacker-units"),
        ("HOSTALIASES", "/tmp/attacker.hosts"),
    ],
)
def test_misc_interpreter_denied(name: str, value: str) -> None:
    """Misc runtime / tool subversion vectors from Ox Alpha SP Q1."""
    seeded = {name: value}
    result = build_sandbox_env(process_env=seeded, manifest_passthrough=(name,))
    assert name not in result.env
    assert result.never_passthrough_denied == 1


# ---------------------------------------------------------------------------
# SP Q2 DEFECT -- prefix false-positive narrowing
# ---------------------------------------------------------------------------


def test_npm_config_loglevel_legit_passthrough() -> None:
    """SP Q2 fold: NPM_CONFIG_LOGLEVEL is legit CI knob, not denied.

    Primary commit had NPM_CONFIG_ as a prefix in NEVER_PASSTHROUGH_PREFIXES
    which blanket-denied NPM_CONFIG_LOGLEVEL, NPM_CONFIG_REGISTRY,
    NPM_CONFIG_PREFIX, and other legitimate CI patterns. SP Q2 verdict
    from cross-family reviewer + Ox Alpha: narrow to enumerated
    dangerous specifics.
    """
    seeded = {"NPM_CONFIG_LOGLEVEL": "warn"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("NPM_CONFIG_LOGLEVEL",)
    )
    assert result.env["NPM_CONFIG_LOGLEVEL"] == "warn"
    assert result.never_passthrough_denied == 0


def test_pip_no_index_legit_passthrough() -> None:
    """SP Q2 fold: PIP_NO_INDEX=true for offline builds not denied.

    Primary had `PIP_` blanket prefix denying PIP_NO_INDEX (legit
    offline-CI flag). Narrowed to enumerated dangerous names.
    """
    seeded = {"PIP_NO_INDEX": "true"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("PIP_NO_INDEX",)
    )
    assert result.env["PIP_NO_INDEX"] == "true"
    assert result.never_passthrough_denied == 0


def test_pip_config_file_still_denied_after_prefix_drop() -> None:
    """SP Q2 fold: PIP_CONFIG_FILE (dangerous) still denied after prefix drop.

    Regression: prefix drop must NOT open the specifically-dangerous
    pip env vars. PIP_CONFIG_FILE, PIP_INDEX_URL, PIP_TRUSTED_HOST,
    PIP_TARGET, PIP_INSTALL_OPTION are all enumerated as exact names.
    """
    seeded = {"PIP_CONFIG_FILE": "/tmp/attacker.pip"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("PIP_CONFIG_FILE",)
    )
    assert "PIP_CONFIG_FILE" not in result.env
    assert result.never_passthrough_denied == 1


def test_npm_config_cafile_still_denied_after_prefix_drop() -> None:
    """SP Q2 fold: NPM_CONFIG_CAFILE (trust-store hijack) still denied."""
    seeded = {"NPM_CONFIG_CAFILE": "/tmp/attacker.pem"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("NPM_CONFIG_CAFILE",)
    )
    assert "NPM_CONFIG_CAFILE" not in result.env


# RACT 0.5.2
