from __future__ import annotations


"""Configuration diagnostics for RACT.

``ract doctor`` inspects ``ract.yaml`` and the surrounding project structure,
reports common misconfiguration problems, and gives the user a clear pass/fail
summary before they invoke the model.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ract.session_events import safe_text

from ract.config_check import find_config_problems, resolve_manager_provider
from ract.harness import _default_manager_prompt_path
from ract.doctor_advice import KeyFacts, Memory, advise
from ract.providers import reasoning
from ract.providers.capability_probe import ProviderProbe, probe_configured
from ract.providers.openai_provider import _host, key_hosts
from ract.setup import host_probe
from ract.providers.router import ProviderRouter


@dataclass
class CheckResult:
    """A single diagnostic check."""

    name: str
    passed: bool
    message: str


class RactDoctor:
    """Run configuration and environment diagnostics for a RACT project.

    LR:: The doctor does not call model providers by default. It only checks
    local files, config shape, and environment variables so it is fast and safe
    to run in CI or on first install.
    """

    def __init__(self, config_path: Path) -> None:
        self.config_path = Path(config_path)
        self.project_dir = self.config_path.parent
        # Filled by diagnose(check_providers=True): one probe per provider (B-056).
        self.probes: list[ProviderProbe] = []
        # Advice lines from the last diagnose() (B-059).
        self.advice: list[str] = []

    def diagnose(self, *, check_providers: bool = False) -> list[CheckResult]:
        """Return a list of diagnostic checks.

        Set *check_providers* to True to actually ping each configured provider
        endpoint. This is slower and may require network access, so it is opt-in.
        """
        results: list[CheckResult] = []
        exists = self._check_config_exists()
        results.append(exists)
        if not exists.passed:
            return results

        config = self._load_config(results)
        if config is None:
            return results

        results.append(self._check_project_name(config))
        results.append(self._check_manager_provider(config))
        results.append(self._check_providers(config))
        layout = self._check_config_layout(config)
        if layout is not None:
            results.append(layout)
        if check_providers:
            results.extend(self._check_provider_reachability(config))
            self.probes = probe_configured(config.get("providers", {}))
            results.extend(self._check_provider_capabilities(self.probes))
        results.append(self._check_prompt_file(config))
        results.append(self._check_skills(config))
        results.append(self._check_operator_key())
        self.advice = advise(config, _memory(), self.probes, _key_facts(config))
        return results

    def _load_config(self, results: list[CheckResult]) -> dict[str, Any] | None:
        try:
            raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            results.append(
                CheckResult(
                    name="config_parse",
                    passed=False,
                    message=f"Failed to parse ract.yaml: {exc}",
                )
            )
            return None
        if not isinstance(raw, dict):
            results.append(
                CheckResult(
                    name="config_parse",
                    passed=False,
                    message="ract.yaml is not a YAML mapping.",
                )
            )
            return None
        results.append(
            CheckResult(
                name="config_parse", passed=True, message="ract.yaml parses cleanly."
            )
        )
        return raw

    def _check_config_exists(self) -> CheckResult:
        if self.config_path.is_file():
            return CheckResult(
                name="config_exists", passed=True, message=f"Found {self.config_path}."
            )
        return CheckResult(
            name="config_exists",
            passed=False,
            message=(
                f"Configuration file not found: {self.config_path}. "
                "Run `ract setup` here to create one."
            ),
        )

    def _check_project_name(self, config: dict[str, Any]) -> CheckResult:
        project = config.get("project", {})
        name = project.get("name") if isinstance(project, dict) else None
        if name:
            return CheckResult(
                name="project_name",
                passed=True,
                message=f"Project name is '{name}'.",
            )
        return CheckResult(
            name="project_name",
            passed=False,
            message="Missing project.name in ract.yaml.",
        )

    def _check_manager_provider(self, config: dict[str, Any]) -> CheckResult:
        manager, error = resolve_manager_provider(config)
        if manager is None:
            return CheckResult(
                name="manager_provider",
                passed=False,
                message=error or "manager_provider is not set.",
            )
        if not config.get("manager_provider"):
            # The runner tolerates this by picking a provider; doctor is the
            # strict check, so it asks for the explicit line.
            return CheckResult(
                name="manager_provider",
                passed=False,
                message=(
                    f"manager_provider is not set; RACT would fall back to "
                    f"'{manager}'. Add a top-level line "
                    f"'manager_provider: {manager}' to make this explicit."
                ),
            )
        return CheckResult(
            name="manager_provider",
            passed=True,
            message=f"Manager provider '{manager}' is configured.",
        )

    def _check_config_layout(self, config: dict[str, Any]) -> CheckResult | None:
        """Report misplaced or unread keys; ``None`` when the layout is clean."""
        problems = find_config_problems(config)
        if not problems:
            return None
        return CheckResult(
            name="config_layout",
            passed=False,
            message=" ".join(problems),
        )

    def _check_providers(self, config: dict[str, Any]) -> CheckResult:
        providers = config.get("providers", {})
        if not providers:
            return CheckResult(
                name="providers", passed=False, message="No providers configured."
            )
        issues: list[str] = []
        for name, settings in providers.items():
            if not isinstance(settings, dict):
                issues.append(f"provider '{name}' is not a mapping")
                continue
            if "adapter" not in settings:
                issues.append(f"provider '{name}' missing adapter")
            if "reasoning_effort" in settings:
                try:
                    reasoning.check_config(settings["reasoning_effort"])
                except ValueError as exc:
                    issues.append(f"provider '{name}': {exc}")
            for field, value in settings.items():
                # Only api_key expands ${VAR}; anywhere else the text would be
                # sent as written (S-025, G-045).
                if field != "api_key" and isinstance(value, str) and "${" in value:
                    issues.append(
                        f"provider '{name}' field '{field}' uses ${{...}}, which only "
                        "api_key expands; write the value itself"
                    )
            api_key = settings.get("api_key")
            if (
                isinstance(api_key, str)
                and api_key.startswith("${")
                and api_key.endswith("}")
            ):
                env_var = api_key[2:-1]
                if not os.environ.get(env_var):
                    issues.append(f"provider '{name}' requires env var {env_var}")
        if issues:
            return CheckResult(
                name="providers",
                passed=False,
                message="; ".join(issues),
            )
        return CheckResult(
            name="providers",
            passed=True,
            message=f"{len(providers)} provider(s) configured.",
        )

    def _check_provider_reachability(self, config: dict[str, Any]) -> list[CheckResult]:
        """Ping each configured provider and report reachability."""
        providers = config.get("providers", {})
        valid_names = [n for n, c in providers.items() if isinstance(c, dict)]
        if not valid_names:
            return []

        router = ProviderRouter({n: providers[n] for n in valid_names})
        results: list[CheckResult] = []
        for name in valid_names:
            rooted = router.health_check(name)
            if rooted.is_ok() and rooted.unwrap():
                results.append(
                    CheckResult(
                        name=f"provider_reachable:{name}",
                        passed=True,
                        message=f"Provider '{name}' is reachable.",
                    )
                )
            else:
                error = rooted.error or "health check returned False"
                results.append(
                    CheckResult(
                        name=f"provider_reachable:{name}",
                        passed=False,
                        message=f"Provider '{name}' is not reachable: {error}",
                    )
                )
        return results

    def _check_provider_capabilities(
        self, probes: list[ProviderProbe]
    ) -> list[CheckResult]:
        """One row per provider. It passes when chat works; the detail lines are
        printed by the CLI, which has the full findings."""
        results: list[CheckResult] = []
        for probe in probes:
            failed = [f for f in probe.findings if f.status in {"failed", "not tried"}]
            if probe.chat_works:
                message = "chat works"
                gaps = [f.label for f in probe.findings if f.status == "not supported"]
                if gaps:
                    message += f"; not supported: {', '.join(gaps)}"
            else:
                message = safe_text(failed[0].detail) if failed else "chat did not work"
            results.append(
                CheckResult(
                    name=f"provider_capabilities:{safe_text(probe.name)}",
                    passed=probe.chat_works or not probe.probed,
                    message=message,
                )
            )
        return results

    def _check_prompt_file(self, config: dict[str, Any]) -> CheckResult:
        prompts_dir = config.get("prompts_dir", "prompts")
        prompt_path = self.project_dir / prompts_dir / "manager.txt"
        if prompt_path.is_file():
            return CheckResult(
                name="prompt_file",
                passed=True,
                message=f"Manager prompt found at {prompt_path}.",
            )
        default = _default_manager_prompt_path()
        if default.is_file():
            return CheckResult(
                name="prompt_file",
                passed=True,
                message=f"Project prompt missing; bundled default at {default} will be used.",
            )
        return CheckResult(
            name="prompt_file",
            passed=False,
            message="Manager prompt not found and no bundled default is available.",
        )

    def _check_operator_key(self) -> CheckResult:
        """How the operator key is kept on this machine (B-111, D-123), said honestly."""
        from ract.policy.operator_key import protection
        from ract.policy.unlock import window_note

        note = window_note()
        return CheckResult(
            name="operator_key",
            passed=True,
            message=f"Operator key: {protection()}." + (f" {note}." if note else ""),
        )

    def _check_skills(self, config: dict[str, Any]) -> CheckResult:
        skill = config.get("skill")
        if not skill:
            return CheckResult(
                name="skills",
                passed=True,
                message="No skill configured; optional.",
            )
        skill_path = self.project_dir / "skills" / f"{skill}.json"
        if skill_path.is_file():
            return CheckResult(
                name="skills",
                passed=True,
                message=f"Configured skill '{skill}' found.",
            )
        return CheckResult(
            name="skills",
            passed=False,
            message=f"Configured skill '{skill}' not found at {skill_path}.",
        )


@dataclass(frozen=True)
class SandboxStatus:
    """What command sandboxing this build provides on this machine.

    LR:: The Linux and macOS backends render a bubblewrap command or a
    Seatbelt profile and never execute it, and no Landlock or seccomp call
    exists (THREAT_MODEL, "What the code enforces today"). ``ract doctor``
    reports that from facts rather than from the design, and is written so
    the report changes by itself when a backend starts executing.
    """

    platform: str
    backend: str
    backend_binary: str | None
    executes_commands: bool
    properties: dict[str, str]


# Flip a backend here only in the commit that makes it execute the rendered
# command; the doctor output and its tests follow from this table.
_BACKEND_EXECUTES: dict[str, bool] = {
    "linux-bwrap": False,
    "macos-sandbox-exec": False,
    "none": False,
}

# Flip only in the commit that makes `ract run` give the substrate loop a
# manifest and a sandbox backend. Until then step subprocesses, like the
# test and lint commands of loop mode, inherit the operator's environment;
# only hook commands are scrubbed (AUD-007).
_RUN_PATH_SCRUBS_STEP_ENV = False


def sandbox_status(system: str | None = None) -> SandboxStatus:
    """Return the sandbox facts for ``system`` (default: this machine).

    Only looks for binaries on PATH. Starts no process.
    """
    import platform as _platform
    import shutil

    name = system or _platform.system()
    if name == "Linux":
        backend, binary = "linux-bwrap", shutil.which("bwrap")
    elif name == "Darwin":
        backend, binary = "macos-sandbox-exec", shutil.which("sandbox-exec")
    else:
        backend, binary = "none", None
    executes = _BACKEND_EXECUTES[backend] and binary is not None
    state = "enforced" if executes else "not enforced in this build"
    properties = {
        "filesystem": state,
        "network": state,
        "process limits": state,
        "environment": (
            "scrubbed by allowlist for every command RACT starts"
            if executes and _RUN_PATH_SCRUBS_STEP_ENV
            else "scrubbed by allowlist for hook commands; inherited from your "
            "shell for test, lint and step commands"
        ),
        # B-114: tier-3 commands (run_tests, the verifiers, git push) run inside
        # the backend once its self-test passes; doctor itself starts no process.
        "tier-3 commands": (
            f"run inside {backend} when its self-test passes at the first command; "
            "otherwise not confined"
            if name == "Linux" and binary is not None
            else "not confined on this platform (sandbox: best_effort)"
        ),
    }
    return SandboxStatus(name, backend, binary, executes, properties)


# RACT 0.1.1 - Trust and tooling


GB = 1024**3


def _memory() -> Memory:
    """Total and free memory from the host, in GB. No network."""
    total, available = host_probe.memory()
    return Memory(
        total_gb=None if total is None else total / GB,
        free_gb=None if available is None else available / GB,
    )


def _key_facts(config: dict[str, Any]) -> list[KeyFacts]:
    """Presence and host pairing for each ``${VAR}`` key. Never the value."""

    providers = config.get("providers")
    facts: list[KeyFacts] = []
    for name, settings in (providers or {}).items():
        if not isinstance(settings, dict):
            continue
        match = re.fullmatch(
            r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(settings.get("api_key", ""))
        )
        url = settings.get("url") or settings.get("base_url")
        if not match or not isinstance(url, str):
            continue
        variable = match.group(1)
        host = _host(url)
        facts.append(
            KeyFacts(
                provider=name,
                variable=variable,
                is_set=bool(os.environ.get(variable)),
                host=host,
                paired=host in key_hosts(variable),
            )
        )
    return facts
