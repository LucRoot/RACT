# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Configuration diagnostics for RACT.

``rootact doctor`` inspects ``rootact.yaml`` and the surrounding project structure,
reports common misconfiguration problems, and gives the user a clear pass/fail
summary before they invoke the model.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from rootact.harness import _default_manager_prompt_path
from rootact.providers.router import ProviderRouter


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
        if check_providers:
            results.extend(self._check_provider_reachability(config))
        results.append(self._check_prompt_file(config))
        results.append(self._check_skills(config))
        return results

    def _load_config(self, results: list[CheckResult]) -> dict[str, Any] | None:
        try:
            raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            results.append(
                CheckResult(
                    name="config_parse",
                    passed=False,
                    message=f"Failed to parse rootact.yaml: {exc}",
                )
            )
            return None
        if not isinstance(raw, dict):
            results.append(
                CheckResult(
                    name="config_parse",
                    passed=False,
                    message="rootact.yaml is not a YAML mapping.",
                )
            )
            return None
        results.append(
            CheckResult(
                name="config_parse", passed=True, message="rootact.yaml parses cleanly."
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
            message=f"Configuration file not found: {self.config_path}",
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
            message="Missing project.name in rootact.yaml.",
        )

    def _check_manager_provider(self, config: dict[str, Any]) -> CheckResult:
        manager = config.get("manager_provider")
        if not manager:
            return CheckResult(
                name="manager_provider",
                passed=False,
                message="manager_provider is not set.",
            )
        providers = config.get("providers", {})
        if manager not in providers:
            return CheckResult(
                name="manager_provider",
                passed=False,
                message=f"manager_provider '{manager}' is not defined in providers.",
            )
        return CheckResult(
            name="manager_provider",
            passed=True,
            message=f"Manager provider '{manager}' is configured.",
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


# RACT 0.1.1 - Trust and tooling
