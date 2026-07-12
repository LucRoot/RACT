# Rooted by Dr. Lucas Root, Ph.D.
"""Automate a GitHub release for RACT-style Python projects.

This script is the mechanical counterpart to the ``github-release`` RACT skill.
It bumps ``pyproject.toml``, updates ``CHANGELOG.md``, builds a wheel, tags the
release, pushes to GitHub, and creates a GitHub release with the wheel attached.

It is intentionally conservative: it refuses to run on a dirty working tree and
it requires ``gh`` to be authenticated.
"""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import NoReturn


def _run(
    cmd: list[str], *, cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command and return its result."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _fail(message: str) -> NoReturn:
    print(f"[github-release] error: {message}", file=sys.stderr)
    sys.exit(1)


def _check_gh_auth() -> None:
    """Verify that the GitHub CLI is installed and authenticated."""
    try:
        result = _run(["gh", "auth", "status"], check=False)
    except FileNotFoundError:
        _fail("gh CLI not found. Install it and run 'gh auth login'.")
    if result.returncode != 0:
        _fail("gh CLI is not authenticated. Run 'gh auth login'.")


def _working_tree_is_clean(project_dir: Path) -> bool:
    """Return True if the git working tree has no uncommitted changes."""
    result = _run(["git", "status", "--porcelain"], cwd=project_dir, check=False)
    return result.returncode == 0 and result.stdout.strip() == ""


def _read_version(project_dir: Path) -> str:
    """Parse the current version from pyproject.toml."""
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.is_file():
        _fail(f"{pyproject} not found")
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        _fail("Could not parse version from pyproject.toml")
    return match.group(1)


def _bump_version(version: str, part: str) -> str:
    """Bump a semver version string by the given part."""
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        _fail(f"Version {version!r} is not in MAJOR.MINOR.PATCH format")
    major, minor, patch = map(int, parts)
    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "patch":
        patch += 1
    else:
        _fail(f"Unknown bump part: {part}")
    return f"{major}.{minor}.{patch}"


def _write_version(project_dir: Path, new_version: str) -> None:
    """Update the version line in pyproject.toml."""
    pyproject = project_dir / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    new_text = re.sub(
        r'^(version\s*=\s*")([^"]+)(")',
        lambda m: f"{m.group(1)}{new_version}{m.group(3)}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if new_text == text:
        _fail("version line in pyproject.toml was not updated")
    pyproject.write_text(new_text, encoding="utf-8")


def _update_changelog(project_dir: Path, new_version: str, notes: str) -> None:
    """Prepend a new version section to CHANGELOG.md if it exists."""
    changelog = project_dir / "CHANGELOG.md"
    if not changelog.is_file():
        return
    today = date.today().isoformat()
    header = f"## [{new_version}] - {today}\n\n### Added\n- {notes}\n\n"
    text = changelog.read_text(encoding="utf-8")
    # Insert after the title/intro if present, otherwise prepend.
    if "## [" in text:
        new_text = text.replace("## [", header + "## [", 1)
    else:
        new_text = header + text
    changelog.write_text(new_text, encoding="utf-8")


def _build_wheel(project_dir: Path) -> Path:
    """Build the wheel and return its path."""
    _run([sys.executable, "-m", "build", "--wheel"], cwd=project_dir)
    dist = project_dir / "dist"
    wheels = sorted(dist.glob("*.whl"))
    if not wheels:
        _fail("No wheel found in dist/ after build")
    return wheels[-1]


def _commit_and_tag(project_dir: Path, new_version: str, message: str | None) -> None:
    """Commit the version bump and create an annotated tag."""
    tag = f"v{new_version}"
    commit_message = message or f"RACT {new_version} - Trust and Tooling"
    _run(["git", "add", "-A"], cwd=project_dir)
    _run(["git", "commit", "-m", commit_message], cwd=project_dir)
    _run(["git", "tag", "-a", tag, "-m", commit_message], cwd=project_dir)


def _push(project_dir: Path, tag: str) -> None:
    """Push the current branch and the given tag to origin."""
    _run(["git", "push", "origin", "HEAD"], cwd=project_dir)
    _run(["git", "push", "origin", tag], cwd=project_dir)


def _create_release(
    project_dir: Path,
    new_version: str,
    wheel: Path,
    notes_file: Path | None,
    notes: str | None,
) -> None:
    """Create the GitHub release and attach the wheel."""
    tag = f"v{new_version}"
    title = f"RACT {new_version}"
    cmd = ["gh", "release", "create", tag, "--title", title]
    if notes_file and notes_file.is_file():
        cmd.extend(["--notes-file", str(notes_file)])
    elif notes:
        cmd.extend(["--notes", notes])
    else:
        cmd.append("--generate-notes")
    cmd.append(str(wheel))
    _run(cmd, cwd=project_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Automate a GitHub release for a RACT-style Python project."
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Project root containing pyproject.toml (default: cwd).",
    )
    parser.add_argument(
        "--version",
        help="Exact version to release (e.g., 0.1.2).",
    )
    parser.add_argument(
        "--bump",
        choices=["major", "minor", "patch"],
        help="Bump the current version by this semver part instead of specifying --version.",
    )
    parser.add_argument(
        "--message",
        help="Commit/tag message (default: 'RACT <version> - Trust and Tooling').",
    )
    parser.add_argument(
        "--notes",
        help="Release notes text.",
    )
    parser.add_argument(
        "--notes-file",
        type=Path,
        help="Path to a file containing release notes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without running git/build/release commands.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip building the wheel.",
    )
    parser.add_argument(
        "--skip-release",
        action="store_true",
        help="Skip creating the GitHub release.",
    )
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()

    if args.version and args.bump:
        _fail("Use either --version or --bump, not both.")

    current_version = _read_version(project_dir)
    if args.version:
        new_version = args.version
    elif args.bump:
        new_version = _bump_version(current_version, args.bump)
    else:
        new_version = _bump_version(current_version, "patch")

    print(f"[github-release] current version: {current_version}")
    print(f"[github-release] new version:      {new_version}")

    if args.dry_run:
        print("[github-release] dry run: no changes made")
        return 0

    if not _working_tree_is_clean(project_dir):
        _fail("Working tree is dirty. Commit or stash changes first.")

    _check_gh_auth()

    _write_version(project_dir, new_version)
    _update_changelog(
        project_dir,
        new_version,
        args.notes or "Release bump.",
    )

    wheel: Path | None = None
    if not args.skip_build:
        wheel = _build_wheel(project_dir)
        print(f"[github-release] built {wheel}")

    _commit_and_tag(project_dir, new_version, args.message)
    _push(project_dir, f"v{new_version}")
    print(f"[github-release] pushed v{new_version}")

    if not args.skip_release:
        if wheel is None:
            dist = project_dir / "dist"
            wheels = sorted(dist.glob("*.whl"))
            if not wheels:
                _fail("No wheel found and --skip-build was set")
            wheel = wheels[-1]
        _create_release(project_dir, new_version, wheel, args.notes_file, args.notes)
        print(f"[github-release] created GitHub release v{new_version}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

# RACT 0.1.1 - Trust and Tooling
