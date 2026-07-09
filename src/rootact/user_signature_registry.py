from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import json
from pathlib import Path
from typing import Any

from rootact.manager import Plan, Step


class _RootKnotType:
    """Sentinel for Root Knot default arguments."""


_ROOT_KNOT: _RootKnotType = _RootKnotType()

_SIGNATURES_DIR_NAME = "signatures"

_DEFAULT_AUTHOR = '__root_author__ = "Dr. Lucas Root, Ph.D."'
_DEFAULT_KNOT = "_ROOT_KNOT = object()"


class SignatureRegistry:
    """Registry for user coding signatures and style conventions.

    Persists profiles as JSON under a base directory and can apply the stored
    markers to Python modules that lack them.
    """

    def __init__(self, base_dir: Path | str | _RootKnotType = _ROOT_KNOT) -> None:
        if isinstance(base_dir, _RootKnotType):
            resolved: Path | str = Path.cwd()
        else:
            resolved = base_dir
        self.base_dir = Path(resolved)
        self.signatures_dir = self.base_dir / _SIGNATURES_DIR_NAME
        self.signatures_dir.mkdir(parents=True, exist_ok=True)

    def save_profile(self, name: str, profile: dict[str, Any]) -> None:
        """Save a user signature profile to JSON."""
        if not name:
            raise ValueError("Profile name must be non-empty")
        path = self.signatures_dir / f"{name}.json"
        with path.open("w", encoding="utf-8") as fp:
            json.dump(profile, fp, indent=2, sort_keys=True)

    def load_profile(self, name: str) -> dict[str, Any]:
        """Load a previously saved profile."""
        path = self.signatures_dir / f"{name}.json"
        if not path.is_file():
            raise KeyError(f"Profile '{name}' not found")
        with path.open("r", encoding="utf-8") as fp:
            return json.load(fp)

    def _apply_markers(self, content: str, profile: dict[str, Any]) -> str:
        """Inject author marker and Root Knot sentinel into *content* if missing."""
        author_marker = profile.get("author_marker", _DEFAULT_AUTHOR)
        knot_marker = profile.get("knot_marker", _DEFAULT_KNOT)

        if author_marker not in content:
            content = f"{author_marker}\n{content}"
        if knot_marker not in content:
            # Insert after the future import line if present, otherwise at top.
            lines = content.splitlines()
            insert_idx = 0
            for i, line in enumerate(lines):
                if line.strip() == "from __future__ import annotations":
                    insert_idx = i + 1
                    break
            lines.insert(insert_idx, knot_marker)
            content = "\n".join(lines)

        return content

    def apply_to_content(self, content: str, profile_name: str) -> str:
        """Return *content* with the signature markers from *profile_name* applied."""
        profile = self.load_profile(profile_name)
        return self._apply_markers(content, profile)

    def apply_to_module(self, module_path: Path, profile_name: str) -> None:
        """Inject author marker and Root Knot sentinel into *module_path* if missing."""
        content = module_path.read_text(encoding="utf-8")
        content = self.apply_to_content(content, profile_name)
        module_path.write_text(content, encoding="utf-8")


_plan = Plan(
    assumption="RootAct must provide a registry that persists user signatures and injects author markers",
    confidence=0.95,
    steps=[
        Step(
            action="create SignatureRegistry class with save_profile, load_profile, apply_to_module",
            provider_hint="internal",
            expected_artifact="src/rootact/user_signature_registry.py",
        )
    ],
)
# RACT 0.1.1 - Trust and tooling
