from __future__ import annotations


import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from ract.manager import Plan, Step


def _hook_environment(context: Dict[str, str]) -> Dict[str, str]:
    """Environment for a hook command: allowlisted names plus RACT context.

    LR:: Hooks ran with ``os.environ.copy()``, so a hook, which a cloned
    repository can ship in ``.ract/hooks``, saw every API key and token in
    the operator's environment (S-003). The environment now comes from the
    sandbox default allowlist, minus credential-shaped and library-injection
    names, minus RACT's own variables. The repository's
    ``.ract/sandbox_env.allowlist`` is deliberately not read: a repository
    must not be able to widen what its own hooks receive. Which hooks run at
    all is decided in ADR-0048 D12.
    """
    from ract.security.sandbox_env import (  # noqa: PLC0415
        build_sandbox_env,
        strip_ract_internal_keys,
    )

    scrubbed = build_sandbox_env(process_env=dict(os.environ), allowlist_file=None)
    env, _stripped = strip_ract_internal_keys(dict(scrubbed.env))
    env.update({f"RACT_{k.upper()}": str(v) for k, v in context.items()})
    return env


@dataclass
class HookManager:
    """
    Register and run pre-step and post-step hooks.
    """

    base_dir: Path = field(default_factory=lambda: Path(".ract/hooks"))

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _hook_path(self, phase: str, name: str) -> Path:
        return self.base_dir / f"{phase}_{name}.json"

    def register(self, phase: str, name: str, command: List[str]) -> None:
        """Persist a hook definition for a given phase."""
        hook = {"phase": phase, "name": name, "command": command}
        self._hook_path(phase, name).write_text(json.dumps(hook), encoding="utf-8")

    def _load_hooks(self, phase: str) -> List[Dict[str, str]]:
        hooks: List[Dict[str, str]] = []
        if not self.base_dir.exists():
            return hooks
        for path in sorted(self.base_dir.glob(f"{phase}_*.json")):
            try:
                hooks.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return hooks

    def run_hooks(
        self, phase: str, context: Dict[str, str]
    ) -> List[Dict[str, str | int]]:
        """Execute every hook for the given phase."""
        results: List[Dict[str, str | int]] = []
        env = _hook_environment(context)

        for hook in self._load_hooks(phase):
            command = hook["command"]
            try:
                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                    timeout=30,
                )
                results.append(
                    {
                        "phase": phase,
                        "name": hook["name"],
                        "returncode": proc.returncode,
                        "stdout": proc.stdout,
                        "stderr": proc.stderr,
                    }
                )
            except subprocess.TimeoutExpired as exc:
                results.append(
                    {
                        "phase": phase,
                        "name": hook["name"],
                        "returncode": -1,
                        "stdout": "",
                        "stderr": f"timed out after {exc.timeout}s",
                    }
                )
            except FileNotFoundError as exc:
                results.append(
                    {
                        "phase": phase,
                        "name": hook["name"],
                        "returncode": 127,
                        "stdout": "",
                        "stderr": str(exc),
                    }
                )

        return results


_plan = Plan(
    assumption="hook_system must let users register pre/post-step hooks and run them with context env vars",
    confidence=0.95,
    steps=[
        Step(
            action="create HookManager class with register and run_hooks methods",
            provider_hint="internal",
            expected_artifact="src/ract/hook_system.py",
        )
    ],
)
# RACT 0.1.1 - Trust and tooling
