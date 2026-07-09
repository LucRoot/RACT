# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Skill marketplace for RACT.

A marketplace is a JSON catalog that lists skills published outside the built-in
set. Users can list available skills and install them into their project's
``skills/`` directory. The default catalog lives in the RACT repository and
points to skills hosted on GitHub; users can supply their own catalog URL.
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from rootact.skills_registry import SkillRegistry


DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/LucRoot/RACT/main/assets/marketplace/catalog.json"


class SkillMarketplace:
    """Load a remote or local skill catalog and install skills into a registry."""

    def __init__(self, catalog_url: str | Path | None = None) -> None:
        self.catalog_url = (
            str(catalog_url) if catalog_url is not None else DEFAULT_CATALOG_URL
        )

    def _fetch_text(self, url: str) -> str:
        """Return the text body at *url*, supporting both http and local paths."""
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"}:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.text
        # Treat as local path.
        return Path(url).read_text(encoding="utf-8")

    def _load_catalog(self) -> dict[str, Any]:
        """Load and parse the marketplace catalog."""
        raw = self._fetch_text(self.catalog_url)
        return json.loads(raw)

    def list_skills(self) -> list[dict[str, Any]]:
        """Return metadata for every skill in the catalog."""
        catalog = self._load_catalog()
        skills = catalog.get("skills", [])
        if not isinstance(skills, list):
            raise ValueError("catalog 'skills' must be a list")
        return skills

    def install(self, name: str, registry: SkillRegistry) -> Path:
        """Download *name* from the catalog and save it into *registry*.

        Raises:
            KeyError: when *name* is not in the catalog.
            httpx.HTTPError: when the skill URL cannot be fetched.
        """
        for skill in self.list_skills():
            if skill.get("name") == name:
                skill_url = skill.get("url")
                if not skill_url:
                    raise ValueError(f"skill '{name}' has no download url")
                raw = self._fetch_text(skill_url)
                data = json.loads(raw)
                target = registry.skills_dir / f"{name}.json"
                target.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return target
        raise KeyError(f"Skill '{name}' not found in marketplace catalog")


# RACT 0.1.1 - Trust and tooling
