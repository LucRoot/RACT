#!/usr/bin/env python3
"""The 0.6.0 release script: typed yes before every machine-leaving step (B-167).

The operator types the steps of RELEASE_COMMANDS.md at the machine; this
script exists so no step that leaves the machine runs from a typo. It holds
an ordered copy of sections A to C of the BOARD's RELEASE_COMMANDS.md (the
R-001 history repair, the v0.5.3 cut, and the pushes), parses that copy into
steps, and then:

- refuses to start before its pre-flight passes: the repository mirror
  backup and the repair kit paths exist, the repository's closed-terms gate
  (the same pytest the release-surface gate runs) is clean, every author and
  committer on ``main..HEAD`` is the operator, and the working tree is clean
  on ``main``;
- before each step that leaves the machine (the pushes C2, C3, C4) prints
  the exact command, its target and the undo from RELEASE_COMMANDS.md, and
  waits for the literal word ``yes`` typed on a TTY; anything else stops the
  release. Without a TTY the step is refused unless ``--i-understand NAMES``
  it, and even then the full ask is printed first. The gate never answers
  itself;
- ``--dry-run`` prints the whole ordered plan with the leave-machine flags
  and the pre-flight results, and runs nothing.

The paths RELEASE_COMMANDS.md names (the repository folder and its
``_backup_r001.git``/``_release`` siblings, the repair kit, the patch
folder) are required arguments with no defaults, so this file names none
of them and no credential appears here. Step B2 depends on the operator's
variant decision (B1: release commits only, B2: plus the content scrub), so
``--variant b1|b2`` is required; without it the script refuses.

Every command is run through Git Bash exactly as RELEASE_COMMANDS.md prints
it (``bash -c <command>``), because several commands use shell syntax
(``$(...)``, globs, ``cd -``). The tag in step B4 is created on this
computer only; it leaves the machine through the gated push of step C4.

Usage::

    python scripts/release_060.py --repo R --backup B --release L \
        --kit K --patches P --variant b1 [--python Y] [--dry-run] \
        [--i-understand C2] [--i-understand C3,C4]

Exit code 0 when the plan completed, 1 when a check failed, 2 when a gate
refused or argparse rejected the arguments.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

OPERATOR = "Dr. Lucas Root, Ph.D. <info@lucasroot.com>"
RELEASE_BRANCH = "release/v0.5.3-security"
EXPECTED_VERSION = "RACT v0.5.3 - Security Patch"
EXPECTED_TAG_MESSAGE = "RACT v0.5.3 - Security Patch"

# The ordered copy of RELEASE_COMMANDS.md sections A to C. The paths
# RELEASE_COMMANDS.md pins are placeholders ({repo}, {backup}, {release},
# {kit}, {patches}, {python}) filled from the required arguments. The
# commands, checks, LEAVES THE MACHINE marks and undo lines are quoted
# verbatim; the pasted stand-in outputs are omitted.
RELEASE_COMMANDS_AC = """\
## A. The history repair (R-001). Stays on this computer.

### A1. Make a backup of the whole repository

```
git clone --mirror --no-local {repo} {backup}
```

What it does: copies every branch and tag into a new folder. Nothing in the
repository folder changes.

Check: the two counts are the same.

```
git -C {backup} for-each-ref refs/heads refs/tags | wc -l
git -C {repo} for-each-ref refs/heads refs/tags | wc -l
```

Undo: `rm -rf {backup}`

### A2. Run the repair into a new folder

```
bash {kit}/run_r001.sh {repo} {release}
```

What it does: clones the repository into the release folder, then rewrites
the names and commit messages there. The file contents stay the same. The
original is not changed.

Check: the last four lines read as below.

```
== verification ==
refs checked: 205, trees changed: 0
messages naming a private term: 0
identities other than the operator on the refs to push: 0
RESULT: OK (trees unchanged on every ref)
```

Two more checks, the same files with new commit ids:

```
git -C {repo} rev-parse "main^{tree}"; git -C {release} rev-parse "main^{tree}"
git -C {release} log main --format='%an <%ae>' | sort | uniq -c
```

Undo: `rm -rf {release}`

### A3. Run the full test suite in the new folder

```
cd {release} && PYTHONPATH="{release}/src;{release}" {python} -m pytest -q -o addopts= -p no:cacheprovider; cd -
```

What it does: runs every test on the rewritten copy. PYTHONPATH makes the
tests use this folder's code; without it the virtual environment would test
the original folder's code.

Check: the last line says `0 failed` (one environment test that needs
`multilspy` may be the only failure; it fails the same way on the original).

Undo: nothing to undo.

## B. v0.5.3 on the repaired release branch. Stays on this computer.

### B1. Switch the new folder to the release branch

```
git -C {release} switch release/v0.5.3-security
```

What it does: checks out the branch that holds the six security fixes.
Check: `git -C {release} branch --show-current` prints
`release/v0.5.3-security`.
Undo: `git -C {release} switch main`

### B2. Add the prepared commits: you choose variant B1 or variant B2

**Variant B1, the release commits only** (two patches: changelog, advisory,
version):

```
git -C {release} am {patches}/*.patch
```

**Variant B2, the release commits plus the content scrub** (four patches: the
same two, then the two content commits of `scrub/private-refs`, M-002):

```
git -C {release} am {patches}/with_scrub/*.patch
```

Check:

```
cat {release}/VERSION
git -C {release} log --oneline -3
```

Undo: `git -C {release} reset --hard HEAD~2` for variant B1, `HEAD~4` for
variant B2

### B3. Run the full test suite on the release branch

Same command as A3, in the same folder, now on the release branch. Expect
`1 failed, <n> passed` where the one failure is the `multilspy` environment
test; it fails the same way on 0.5.2.

Undo: nothing to undo.

### B4. Tag v0.5.3 (on this computer only)

```
git -C {release} tag -a v0.5.3 -m "RACT v0.5.3 - Security Patch"
```

What it does: marks the release commit with an annotated tag.
Check: `git -C {release} tag -n1 v0.5.3` prints the tag and its message.
Undo: `git -C {release} tag -d v0.5.3`

The tag is local; it leaves the machine only through the gated push of step
C4.

## C. The pushes. LEAVES THE MACHINE.

Git asks for your GitHub sign-in in its own window or prompt. Push exactly
these refs and nothing else: `main`, the ten `v*` tags, and (for v0.5.3)
`release/v0.5.3-security` with the `v0.5.3` tag. Never `git push --mirror`,
`--all` or `--tags`.

### C1. Point the new folder at GitHub

```
git -C {release} remote add origin https://github.com/LucRoot/RACT.git
```

What it does: the repair removed the remote; this names GitHub again.
Nothing is sent yet.
Check: `git -C {release} remote -v` shows the GitHub address twice.
Undo: `git -C {release} remote remove origin`

### C2. Replace main on GitHub. **LEAVES THE MACHINE.**

```
git -C {release} push --force origin main
```

What it does: GitHub's `main` becomes the repaired history.
Check: the two ids are the same.

```
git -C {release} ls-remote origin main; git -C {release} rev-parse main
```

Undo (also leaves the machine): `git -C {backup} push --force https://github.com/LucRoot/RACT.git main`

### C3. Replace the version tags on GitHub. **LEAVES THE MACHINE.**

```
git -C {release} push --force origin $(git -C {release} tag -l 'v*')
```

What it does: moves the ten `v*` tags to the repaired commits. Only `v*`
tags: the five local `backup-v0.5.1-pre*` tags must never be pushed. Do not
use `--tags`.

Check: `git -C {release} ls-remote --tags origin` lists each `v*` tag with
the same id as `git -C {release} show-ref --tags`.

Undo (also leaves the machine): `git -C {backup} push --force https://github.com/LucRoot/RACT.git $(git -C {backup} tag -l 'v*')`

### C4. Publish the v0.5.3 branch and tag. **LEAVES THE MACHINE.**

```
git -C {release} push origin release/v0.5.3-security v0.5.3
```

What it does: publishes the release branch and its tag. `main` stays at
0.5.2, so the 0.6.0 work can later move `main` forward without a merge.

Check: `git -C {release} ls-remote origin release/v0.5.3-security` shows
the same id as `git -C {release} rev-parse release/v0.5.3-security`.

Undo (also leaves the machine): `git -C {release} push origin --delete release/v0.5.3-security v0.5.3`
"""

# The release-surface gate the pre-flight runs, the same test the full gate
# runs: ``tests/test_release_surface.py::test_no_closed_ip_terms_in_tracked_files``.
CLOSED_TERMS_GATE = (
    "tests/test_release_surface.py::test_no_closed_ip_terms_in_tracked_files"
)

_PUSH_WORD = re.compile(r"\bpush\b")
_URL = re.compile(r"https://\S+")


@dataclass
class Step:
    """One step parsed from a ``###`` heading of the embedded copy."""

    id: str
    title: str
    section: str
    leaves: bool
    commands: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    undo: list[str] = field(default_factory=list)
    variants: dict[str, list[str]] = field(default_factory=dict)

    def commands_for(self, variant: str) -> list[str]:
        if self.variants:
            return self.variants[variant]
        return self.commands


def command_leaves_machine(command: str) -> bool:
    """True when *command* sends refs to a remote (a ``git push``).

    The release copy marks its leaving steps; this is the independent check
    the runner applies to every command before it runs, so a mislabeled step
    still cannot push without the typed yes.
    """
    return bool(_PUSH_WORD.search(command))


def parse_steps(blob: str = RELEASE_COMMANDS_AC) -> list[Step]:
    """Parse the embedded RELEASE_COMMANDS copy into ordered steps.

    A ``## X.`` line opens section ``X``; a ``### ID. title`` line opens a
    step, and ``**LEAVES THE MACHINE.**`` on that line marks it. Fenced code
    blocks before any check paragraph are the step's commands; blocks after
    a ``Check``/``Output on the stand-in`` paragraph are its checks; blocks
    after a ``**Variant B1``/``**Variant B2`` marker belong to that variant.
    ``Undo:`` lines contribute their backticked commands. Step B3 names no
    command of its own (``Same command as A3``), so it reuses A3's.
    """
    steps: list[Step] = []
    section = ""
    step: Step | None = None
    context = "run"
    lines = blob.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            section = line[3:].split(".", 1)[0].strip()
        elif line.startswith("### "):
            heading = line[4:].strip()
            step_id, _, title = heading.partition(".")
            step = Step(
                id=step_id.strip(),
                title=title.replace("**LEAVES THE MACHINE.**", "").strip(),
                section=section,
                leaves="**LEAVES THE MACHINE.**" in heading,
            )
            steps.append(step)
            context = "run"
        elif step is not None and line.startswith("```"):
            block: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            commands = [b for b in block if b.strip()]
            if context in ("b1", "b2"):
                step.variants.setdefault(context, []).extend(commands)
            elif context == "check":
                step.checks.extend(commands)
            else:
                step.commands.extend(commands)
        elif step is not None and line.startswith("**Variant B"):
            context = "b" + line[len("**Variant B") :].strip()[:1]
        elif step is not None and (
            line.startswith("Check")
            or line.startswith("Output on the stand-in")
            or line.startswith("Two more checks")
        ):
            context = "check"
        elif step is not None and line.startswith("Undo"):
            step.undo.extend(re.findall(r"`([^`]+)`", line))
        i += 1
    by_id = {s.id: s for s in steps}
    for s in steps:
        if not s.commands and not s.variants and "Same command as A3" in blob:
            s.commands = list(by_id["A3"].commands)
    return steps


# ---------------------------------------------------------------------------
# Running commands and verifying checks
# ---------------------------------------------------------------------------


def run_command(command: str) -> subprocess.CompletedProcess:
    """Run one RELEASE_COMMANDS line through Git Bash, as the BOARD directs."""
    return subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _render(step: Step, params: dict[str, str], variant: str) -> list[str]:
    return [c.format(**params) for c in step.commands_for(variant)]


def _git(params: dict[str, str], folder: str, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", params[folder], *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def verify(
    step: Step,
    params: dict[str, str],
    variant: str,
    ran: list[subprocess.CompletedProcess],
) -> list[str]:
    """The RELEASE_COMMANDS check for *step*; empty when it holds."""
    release = params["release"]
    if step.id == "A1":
        backup_n = run_command(
            f"git -C {params['backup']} for-each-ref refs/heads refs/tags | wc -l"
        ).stdout.strip()
        repo_n = run_command(
            f"git -C {params['repo']} for-each-ref refs/heads refs/tags | wc -l"
        ).stdout.strip()
        if backup_n != repo_n:
            return [f"A1 check: backup holds {backup_n} refs, repo holds {repo_n}"]
    elif step.id == "A2":
        original = _git(params, "repo", "rev-parse", "main^{tree}").strip()
        repaired = _git(params, "release", "rev-parse", "main^{tree}").strip()
        if original != repaired:
            return [f"A2 check: main's tree differs ({original} != {repaired})"]
        authors = _git(params, "release", "log", "main", "--format=%an <%ae>")
        foreign = {a for a in authors.splitlines() if a and a != OPERATOR}
        if foreign:
            return [
                f"A2 check: identities other than the operator on main: {sorted(foreign)}"
            ]
    elif step.id in ("A3", "B3"):
        done = (
            ran[-1]
            if ran
            else run_command(step.commands_for(variant)[0].format(**params))
        )
        if done.returncode != 0:
            summary = [ln for ln in done.stdout.splitlines() if ln.strip()]
            tail = summary[-1] if summary else done.stderr.strip()
            return [f"{step.id} check: the suite did not pass ({tail})"]
    elif step.id == "B1":
        current = _git(params, "release", "branch", "--show-current").strip()
        if current != RELEASE_BRANCH:
            return [f"B1 check: on {current!r}, expected {RELEASE_BRANCH!r}"]
    elif step.id == "B2":
        version = run_command(f"cat {release}/VERSION").stdout.strip()
        if version != EXPECTED_VERSION:
            return [
                f"B2 check: VERSION reads {version!r}, expected {EXPECTED_VERSION!r}"
            ]
        terms = [
            ln.strip()
            for ln in Path(params["kit"], "terms.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if ln.strip()
        ]
        for where in ("messages", "files"):
            hits = 0
            for term in terms:
                if where == "messages":
                    out = _git(
                        params,
                        "release",
                        "log",
                        "main",
                        "-i",
                        "-F",
                        f"--grep={term}",
                        "--format=%H",
                    )
                else:
                    done = subprocess.run(
                        [
                            "git",
                            "-C",
                            release,
                            "grep",
                            "-I",
                            "-i",
                            "-F",
                            "-l",
                            "-e",
                            term,
                            "main",
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                    out = done.stdout
                hits += len([ln for ln in out.splitlines() if ln.strip()])
            if where == "messages" and hits:
                return [f"B2 check: {hits} message hit(s) name a private term"]
            if where == "files" and variant == "b2" and hits:
                return [
                    f"B2 check: variant B2 must scrub the files, found {hits} hit(s)"
                ]
    elif step.id == "B4":
        out = _git(params, "release", "tag", "-n1", "v0.5.3")
        if EXPECTED_TAG_MESSAGE not in out:
            return ["B4 check: tag -n1 v0.5.3 does not print the tag message"]
    elif step.id == "C1":
        out = _git(params, "release", "remote", "-v")
        if out.count("https://github.com/LucRoot/RACT.git") < 2:
            return ["C1 check: remote -v does not show the GitHub address twice"]
    elif step.id == "C2":
        remote = _git(params, "release", "ls-remote", "origin", "main").split()[0]
        local = _git(params, "release", "rev-parse", "main").strip()
        if remote != local:
            return [f"C2 check: GitHub's main is {remote}, local main is {local}"]
    elif step.id == "C3":
        remote = _git(params, "release", "ls-remote", "--tags", "origin")
        local = _git(params, "release", "show-ref", "--tags")
        remote_ids = {
            ln.split("refs/")[-1]: ln.split()[0] for ln in remote.splitlines()
        }
        local_ids = {ln.split("refs/")[-1]: ln.split()[0] for ln in local.splitlines()}
        pushed = {r: i for r, i in local_ids.items() if r.startswith("tags/v")}
        for ref, wanted in pushed.items():
            if remote_ids.get(ref) != wanted:
                return [
                    f"C3 check: {ref} is {remote_ids.get(ref)} on GitHub, {wanted} locally"
                ]
    elif step.id == "C4":
        remote = _git(params, "release", "ls-remote", "origin", RELEASE_BRANCH).split()[
            0
        ]
        local = _git(params, "release", "rev-parse", RELEASE_BRANCH).strip()
        if remote != local:
            return [
                f"C4 check: GitHub's {RELEASE_BRANCH} is {remote}, local is {local}"
            ]
    return []


# ---------------------------------------------------------------------------
# The typed-yes gate
# ---------------------------------------------------------------------------


def _gate_text(
    step: Step, commands: list[str], undo: list[str], params: dict[str, str]
) -> list[str]:
    target = ", ".join(sorted({u for c in commands + undo for u in _URL.findall(c)}))
    lines = [
        f"=== step {step.id}: {step.title} ===",
        "LEAVES THE MACHINE: this step publishes to GitHub.",
        f"Target: {target if target else 'GitHub'} (remote 'origin').",
        "Command(s):",
    ]
    lines += [f"  {c}" for c in commands]
    lines.append("Rollback / undo (from RELEASE_COMMANDS):")
    lines += [f"  {u}" for u in undo]
    if any(command_leaves_machine(u) for u in undo):
        lines.append("  (the undo also leaves the machine)")
    return lines


def _undo_for(step: Step, variant: str) -> list[str]:
    if step.id == "B2":
        back = "2" if variant == "b1" else "4"
        return [f"git -C {{release}} reset --hard HEAD~{back}"]
    return step.undo


def confirm_step(
    step: Step,
    *,
    params: dict[str, str],
    variant: str,
    understand: set[str],
    interactive: bool,
    input_fn=input,
    out=print,
) -> bool:
    """The typed-yes gate for a machine-leaving step.

    Prints the exact command(s), their target and the undo, then requires
    the literal word ``yes`` on a TTY. Without a TTY the step is refused
    unless ``--i-understand`` names this step's id; even then the full ask
    is printed and the flag is recorded. Never answers itself.
    """
    commands = _render(step, params, variant)
    undo = [u.format(**params) for u in _undo_for(step, variant)]
    for line in _gate_text(step, commands, undo, params):
        out(line)
    if not interactive:
        if step.id in understand:
            out(
                f"no TTY: proceeding only because --i-understand named "
                f"{step.id}; the typed yes above was not given."
            )
            return True
        out(
            f"refusing step {step.id}: not a TTY, so there is no one to "
            f"type yes, and --i-understand does not name {step.id}."
        )
        return False
    typed = input_fn(
        f"Type yes to run step {step.id} (leaves the machine); "
        f"anything else stops the release: "
    )
    if typed.strip() != "yes":
        out(f"refusing step {step.id}: typed {typed.strip()!r}, not 'yes'.")
        return False
    return True


# ---------------------------------------------------------------------------
# The pre-flight
# ---------------------------------------------------------------------------


def preflight(params: dict[str, str], python: str) -> list[str]:
    """Every check that must hold before step A1; the failures, empty when clean."""
    failures: list[str] = []

    repo = Path(params["repo"])
    backup = Path(params["backup"])
    kit = Path(params["kit"])
    patches = Path(params["patches"])
    variant = params["variant"]

    if not repo.is_dir():
        failures.append(f"repo: {repo} does not exist")
    else:
        inside = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            failures.append(f"repo: {repo} is not a git work tree")
        else:
            branch = subprocess.run(
                ["git", "-C", str(repo), "symbolic-ref", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if branch != "main":
                failures.append(f"repo: on {branch!r}, expected 'main'")
            dirty = subprocess.run(
                ["git", "-C", str(repo), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if dirty:
                failures.append(
                    f"repo: working tree is dirty ({len(dirty.splitlines())} path(s)); commit or stash first"
                )

    if not backup.is_dir():
        failures.append(
            f"backup: {backup} is missing; make the mirror backup first "
            f"(step A1 of RELEASE_COMMANDS) and pass its path via --backup"
        )
    else:
        bare = subprocess.run(
            ["git", "-C", str(backup), "rev-parse", "--is-bare-repository"],
            capture_output=True,
            text=True,
            check=False,
        )
        if bare.returncode != 0 or bare.stdout.strip() != "true":
            failures.append(f"backup: {backup} is not a git bare repository")
        elif repo.is_dir():
            backup_refs = run_command(
                f"git -C {backup} for-each-ref refs/heads refs/tags | wc -l"
            ).stdout.strip()
            repo_refs = run_command(
                f"git -C {repo} for-each-ref refs/heads refs/tags | wc -l"
            ).stdout.strip()
            if backup_refs != repo_refs:
                failures.append(
                    f"backup: mirror holds {backup_refs} refs, repo holds {repo_refs}; re-make it"
                )

    if not (kit / "run_r001.sh").is_file():
        failures.append(f"kit: {kit / 'run_r001.sh'} is missing")
    if not (kit / "terms.txt").is_file():
        failures.append(f"kit: {kit / 'terms.txt'} is missing")
    pattern = "*.patch" if variant == "b1" else os.path.join("with_scrub", "*.patch")
    if not list(patches.glob(pattern)):
        failures.append(f"patches: no {variant} patch(es) at {patches / pattern}")

    if repo.is_dir():
        env = dict(os.environ)
        src = str(repo / "src")
        env["PYTHONPATH"] = src + os.pathsep + str(repo)
        gate = subprocess.run(
            [
                python,
                "-m",
                "pytest",
                CLOSED_TERMS_GATE,
                "-q",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
            ],
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if gate.returncode != 0:
            tail = [ln for ln in gate.stdout.splitlines() if ln.strip()]
            failures.append(
                f"closed terms: {CLOSED_TERMS_GATE} failed"
                + (f" ({tail[-1]})" if tail else "")
            )
        authors = subprocess.run(
            ["git", "-C", str(repo), "log", "main..HEAD", "--format=%an <%ae>"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        ).stdout.splitlines()
        foreign = {a for a in authors if a.strip() and a.strip() != OPERATOR}
        if foreign:
            failures.append(
                f"authorship: main..HEAD has non-operator identity/identities: {sorted(foreign)}"
            )
    return failures


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def print_plan(
    steps: list[Step], params: dict[str, str], variant: str, out=print
) -> None:
    out("Release plan (RELEASE_COMMANDS.md sections A to C):")
    for step in steps:
        flag = "LEAVES THE MACHINE" if step.leaves else "stays on this computer"
        out(f"  {step.id}. {step.title} [{flag}]")
        for command in _render(step, params, variant):
            out(f"      {command}")


def run_plan(
    steps: list[Step],
    params: dict[str, str],
    *,
    variant: str,
    understand: set[str],
    interactive: bool,
    out=print,
    input_fn=input,
) -> int:
    for step in steps:
        commands = _render(step, params, variant)
        leaves = step.leaves or any(command_leaves_machine(c) for c in commands)
        out(f"--- step {step.id}: {step.title} ---")
        if leaves and not confirm_step(
            step,
            params=params,
            variant=variant,
            understand=understand,
            interactive=interactive,
            input_fn=input_fn,
            out=out,
        ):
            out(f"release stopped at step {step.id}: the typed yes was not given.")
            return 2
        ran: list[subprocess.CompletedProcess] = []
        for command in commands:
            if command.lstrip().startswith("git clone"):
                destination = shlex.split(command)[-1]
                if Path(destination).exists():
                    out(
                        f"step {step.id}: {destination} already exists; not "
                        f"re-running the clone, verifying it instead"
                    )
                    continue
            if step.id == "A2" and Path(params["release"]).exists():
                out(
                    f"step {step.id}: {params['release']} already exists; not "
                    f"re-running the repair, verifying it instead"
                )
                continue
            done = run_command(command)
            ran.append(done)
            if done.returncode != 0:
                out(
                    f"step {step.id}: command failed ({done.stderr.strip() or 'no output'}): "
                    f"{command}"
                )
                return 1
            if step.id == "A2" and "RESULT: FAILED" in done.stdout:
                out(
                    "step A2: the repair printed RESULT: FAILED; stop and tell the BUILDER."
                )
                return 1
            if step.id == "A2" and "RESULT: OK" not in done.stdout:
                out("step A2: the repair printed no RESULT: OK line; stopping.")
                return 1
        failures = verify(step, params, variant, ran)
        if failures:
            for failure in failures:
                out(failure)
            out(f"release stopped at step {step.id}: its check failed.")
            return 1
        out(f"step {step.id}: done")
    out(
        "release plan complete: every step of sections A to C ran and every check held."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="The 0.6.0 release script: typed yes before every "
        "machine-leaving step; refuses without backups and pre-checks."
    )
    parser.add_argument(
        "--repo", required=True, help="the repository folder (git work tree on main)"
    )
    parser.add_argument(
        "--backup", required=True, help="the mirror backup of the repository (bare)"
    )
    parser.add_argument("--release", required=True, help="the repaired release folder")
    parser.add_argument(
        "--kit",
        required=True,
        help="the R-001 repair kit folder (run_r001.sh, terms.txt)",
    )
    parser.add_argument(
        "--patches", required=True, help="the prepared v0.5.3 patches folder"
    )
    parser.add_argument(
        "--variant",
        required=True,
        choices=("b1", "b2"),
        help="the B2 decision from RELEASE_COMMANDS: b1 = release commits only, b2 = plus the content scrub",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="the python for the test-suite steps (default: this interpreter)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and the pre-flight results, run nothing",
    )
    parser.add_argument(
        "--i-understand",
        action="append",
        default=[],
        metavar="STEP",
        help="without a TTY, the only way a machine-leaving step may run: name it (repeatable, comma-separated). The full ask is still printed.",
    )
    args = parser.parse_args(argv)

    params = {
        "repo": str(Path(args.repo)),
        "backup": str(Path(args.backup)),
        "release": str(Path(args.release)),
        "kit": str(Path(args.kit)),
        "patches": str(Path(args.patches)),
        "python": args.python,
        "variant": args.variant,
    }
    steps = parse_steps()
    understand = {
        name.strip()
        for group in args.i_understand
        for name in group.split(",")
        if name.strip()
    }

    if args.dry_run:
        print_plan(steps, params, args.variant)
        print()
    failures = preflight(params, args.python)
    for line in [
        "pre-flight: the repository mirror backup and repair kit exist",
        "pre-flight: the repository's closed-terms gate is clean",
        f"pre-flight: every author and committer on main..HEAD is {OPERATOR}",
        "pre-flight: the working tree is clean on main",
    ]:
        print(line)
    if failures:
        print("pre-flight: FAILED; nothing has been run.")
        for failure in failures:
            print(f"  failing check: {failure}")
        return 1
    print("pre-flight: every check passed.")
    if args.dry_run:
        return 0
    return run_plan(
        steps,
        params,
        variant=args.variant,
        understand=understand,
        interactive=sys.stdin.isatty(),
    )


if __name__ == "__main__":
    sys.exit(main())
