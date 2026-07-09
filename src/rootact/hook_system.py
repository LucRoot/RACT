from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from rootact.manager import Plan, Step

_ROOT_KNOT = object()


@dataclass
class HookManager:
    """
    Register and run pre-step and post-step hooks.
    """

    base_dir: Path = field(default_factory=lambda: Path(".rootact/hooks"))

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
        env = os.environ.copy()
        env.update({f"ROOTACT_{k.upper()}": str(v) for k, v in context.items()})

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
            expected_artifact="src/rootact/hook_system.py",
        )
    ],
)
# RACT 0.1.1 - Trust and tooling
