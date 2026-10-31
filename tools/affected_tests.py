"""List, and with ``--run`` run, the test files a change touches (B-141).

The full suite is the landing gate; this is for the fixes between gates. A
changed file maps to test files by these rules:

- a test file (``tests/**/test_*.py``) is itself;
- a source module ``src/ract/a/b.py`` maps to every test that imports
  ``ract.a.b`` (``import ract.a.b``, ``from ract.a.b import ...`` or
  ``from ract.a import b``) and to every test file named ``test_b*.py``;
- a test helper (any other ``.py`` under ``tests/``) maps to the tests that
  import it (``from tests.x import ...``, ``import tests.x``);
- any other file (README.md, a doc, a fixture, ``pyproject.toml``) maps to
  the tests that name it (its path, or its file name when that has a dot).

``tests/architecture``, the release-surface set and the source-digest test are
always included. A changed ``tests/conftest.py`` is named in a note: it reaches
every test, and only the full suite covers it.

Usage, from the repository root::

    python tools/affected_tests.py                 # changes against main, listed
    python tools/affected_tests.py --base REF      # against another ref
    python tools/affected_tests.py --run           # run each, one line per file
    python tools/affected_tests.py src/ract/x.py   # these paths instead of git

It reads files and asks git for the changed paths; ``--run`` starts pytest
once per target with the interpreter running this script.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Always run: the structure rules, the release surface and the digest
# (docs/HANDOFF.md, "Focused tests").
ALWAYS = (
    "tests/architecture",
    "tests/test_public_provenance.py",
    "tests/test_use_cases_catalog.py",
    "tests/test_source_digest.py",
    "tests/test_release_surface.py",
    "tests/unit/test_readme_verb_index_matches_parser.py",
)


def _is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return (
        rel.startswith("tests/") and name.startswith("test_") and name.endswith(".py")
    )


def _test_files(root: Path) -> list[str]:
    return sorted(
        p.relative_to(root).as_posix()
        for p in (root / "tests").rglob("test_*.py")
        if "__pycache__" not in p.parts
    )


def _module_of(rel: str) -> str | None:
    """``src/ract/a/b.py`` -> ``ract.a.b``; ``tests/x/y.py`` -> ``tests.x.y``."""
    if not rel.endswith(".py"):
        return None
    parts = rel[: -len(".py")].split("/")
    if parts[:2] == ["src", "ract"]:
        parts = parts[1:]
    elif parts[0] != "tests":
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(module: str) -> re.Pattern[str]:
    """A pattern for the lines that import *module* or take it from its package."""
    package, _, leaf = module.rpartition(".")
    forms = [
        rf"import\s+{re.escape(module)}\b",
        rf"from\s+{re.escape(module)}\s+import\b",
    ]
    if package:
        forms.append(
            rf"from\s+{re.escape(package)}\s+import\s+[^\n#]*\b{re.escape(leaf)}\b"
        )
    return re.compile("|".join(forms))


def affected(changed: list[str], root: Path = ROOT) -> tuple[list[str], list[str]]:
    """The test targets for *changed* paths (repository-relative), and notes."""
    tests = _test_files(root)
    texts: dict[str, str] = {}

    def text(rel: str) -> str:
        if rel not in texts:
            texts[rel] = (root / rel).read_text(encoding="utf-8", errors="replace")
        return texts[rel]

    targets: set[str] = set()
    notes: list[str] = []
    for rel in sorted(set(changed)):
        rel = rel.replace("\\", "/")
        if _is_test_file(rel):
            if (root / rel).is_file():
                targets.add(rel)
            continue
        if rel == "tests/conftest.py":
            notes.append(
                "tests/conftest.py changed: it reaches every test; the full suite covers it"
            )
            continue
        module = _module_of(rel)
        if module is not None:
            found = _imports(module)
            targets.update(t for t in tests if found.search(text(t)))
            stem = rel.rsplit("/", 1)[-1][: -len(".py")]
            if module.startswith("ract") and stem != "__init__":
                targets.update(
                    t for t in tests if t.rsplit("/", 1)[-1].startswith(f"test_{stem}")
                )
            continue
        name = rel.rsplit("/", 1)[-1]
        needles = {rel} | ({name} if "." in name else set())
        targets.update(t for t in tests if any(n in text(t) for n in needles))
    always = [a for a in ALWAYS if (root / a).exists()]
    return sorted(targets - set(always)) + always, notes


def changed_paths(base: str, root: Path = ROOT) -> list[str]:
    """Paths changed since *base* (committed, staged and in the working tree)."""
    out: set[str] = set()
    for args in (
        ["diff", "--name-only", f"{base}...HEAD"],
        ["diff", "--name-only", "HEAD"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        out.update(line for line in proc.stdout.splitlines() if line)
    return sorted(out)


def _summary(output: str) -> str:
    lines = [
        line
        for line in output.splitlines()
        if re.search(r"\b(passed|failed|error|errors|no tests ran)\b", line)
    ]
    return lines[-1].strip("= ") if lines else "no summary"


def run(targets: list[str], root: Path = ROOT) -> int:
    """Run each target on its own; one line per target; 1 when any failed."""
    worst = 0
    for target in targets:
        started = time.monotonic()
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
                target,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            check=False,
        )
        # Exit 5 is "no tests collected" (a folder of helpers): not a failure.
        if proc.returncode not in (0, 5):
            worst = 1
        took = time.monotonic() - started
        print(f"{target} | {_summary(proc.stdout)} | {took:.0f} s", flush=True)
    return worst


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="changed paths (default: from git)")
    parser.add_argument("--base", default="main", help="the ref to compare with")
    parser.add_argument("--run", action="store_true", help="run each target")
    args = parser.parse_args(argv)
    changed = args.paths or changed_paths(args.base)
    targets, notes = affected(changed)
    for note in notes:
        print(f"note: {note}")
    if not args.run:
        print("\n".join(targets))
        return 0
    return run(targets)


if __name__ == "__main__":
    raise SystemExit(main())
