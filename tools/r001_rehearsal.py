"""Rehearse the R-001 history repair on throwaway clones and print every check (B-153).

Usage:
    python tools/r001_rehearsal.py <source repo> <kit dir> <work dir> <terms file>

The kit dir holds the repair's ``mailmap.txt`` and ``msg_cb.py`` (the
``git filter-repo`` message callback). The terms file holds one private term
per line; it is kept outside the tracked tree so this file names none.

The source repository is only read (``git clone --no-local``). Everything is
written under <work dir>, which the caller deletes afterwards. Needs
``git-filter-repo`` on PATH. Prints a JSON report; exit 0 only when every
check holds:

- the tree of every branch and tag is unchanged, and no ref is lost;
- every tracked file at the feature branch's tip is byte for byte the same;
- no commit message on any ref contains a private term;
- every author and committer on the refs that would be pushed (``main``,
  the tags and the feature branch) is the operator;
- on a second clone standing in for the real repository, adopting the
  rewritten refs and then fetching them back from a mirror backup restores
  every ref exactly (the undo).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

FEATURE = "refs/heads/feat/interactive-session-and-setup-fixes"
RELEASE = "refs/heads/release/v0.5.3-security"
OPERATOR_EMAIL = "<info@lucasroot.com>"


def git(repo: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def clone(src: Path, dst: Path) -> None:
    subprocess.run(["git", "clone", "-q", "--no-local", str(src), str(dst)], check=True)
    for line in git(dst, "branch", "-r").splitlines():
        name = line.strip()
        if "->" in name or not name.startswith("origin/"):
            continue
        git(dst, "branch", "-q", "--track", name[len("origin/") :], name, check=False)
    git(dst, "remote", "remove", "origin")


def trees(repo: Path) -> dict[str, str]:
    out = git(repo, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags")
    return {r: git(repo, "rev-parse", f"{r}^{{tree}}").strip() for r in out.split()}


def tips(repo: Path) -> dict[str, str]:
    out = git(
        repo,
        "for-each-ref",
        "--format=%(refname) %(objectname)",
        "refs/heads",
        "refs/tags",
    )
    return dict(line.split(" ", 1) for line in out.splitlines())


def pushed_refs(repo: Path) -> list[str]:
    """``main``, the feature and release branches and the ``v*`` tags: nothing else is pushed."""
    tags = git(repo, "for-each-ref", "--format=%(refname)", "refs/tags/v*").split()
    heads = git(repo, "for-each-ref", "--format=%(refname)", "refs/heads").split()
    return [r for r in ("refs/heads/main", FEATURE, RELEASE) if r in heads] + tags


def identities(repo: Path, refs: list[str] | None = None) -> list[str]:
    scope = refs if refs is not None else ["--all"]
    out = git(repo, "log", *scope, "--format=%an <%ae>%n%cn <%ce>")
    return sorted(set(out.splitlines()))


def message_hits(repo: Path, terms: list[str]) -> list[int]:
    return [
        len(git(repo, "log", "--all", "-i", "-F", f"--grep={t}", "--format=%H").split())
        for t in terms
    ]


def tag_message_hits(repo: Path, terms: list[str]) -> list[int]:
    """Hits per term in the annotated tag objects (tagger line and message)."""
    out = git(repo, "for-each-ref", "--format=%(objecttype) %(refname)", "refs/tags")
    bodies = [
        git(repo, "cat-file", "-p", ref).lower()
        for kind, ref in (line.split(" ", 1) for line in out.splitlines())
        if kind == "tag"
    ]
    return [sum(t.lower() in body for body in bodies) for t in terms]


def tracked_file_hits(repo: Path, ref: str, terms: list[str]) -> dict[str, int]:
    """Tracked files at ``ref`` naming a term; the wordlist test's two exemptions apply."""
    exempt = {"tests/test_release_surface.py", "assets/demo.cast"}
    hits = {}
    for i, term in enumerate(terms):
        out = git(repo, "grep", "-I", "-i", "-F", "-l", "-e", term, ref, check=False)
        files = [f.split(":", 1)[1] for f in out.splitlines() if ":" in f]
        files = [f for f in files if f not in exempt]
        if files:
            hits[f"term_{i + 1}"] = len(files)
    return hits


def handed_back_state(repo: Path) -> dict:
    """What else the rewritten clone holds besides the branches and tags."""
    every = git(repo, "for-each-ref", "--format=%(refname)").split()
    notes = git(repo, "notes", "list", check=False).split()
    return {
        "refs_outside_heads_and_tags": sorted(
            r for r in every if not r.startswith(("refs/heads/", "refs/tags/"))
        ),
        "notes": len(notes),
        "reflog_entries": len(git(repo, "reflog", "--all", check=False).splitlines()),
        "stash_entries": len(git(repo, "stash", "list", check=False).splitlines()),
    }


def snapshot(repo: Path, terms: list[str]) -> dict:
    refs = trees(repo)
    return {
        "branches": sum(r.startswith("refs/heads/") for r in refs),
        "tags": sorted(r for r in refs if r.startswith("refs/tags/")),
        "commits": int(git(repo, "rev-list", "--all", "--count").strip()),
        "identities_all_refs": identities(repo),
        "identities_pushed_refs": identities(repo, pushed_refs(repo)),
        "message_hits_per_term": message_hits(repo, terms),
        "tag_object_hits_per_term": tag_message_hits(repo, terms),
    }


def main(argv: list[str]) -> int:
    src, kit, work, terms_file = (Path(a) for a in argv[1:5])
    terms = [
        t.strip()
        for t in terms_file.read_text(encoding="utf-8").splitlines()
        if t.strip()
    ]
    report: dict = {}

    rewritten = work / "rewritten"
    clone(src, rewritten)
    before_trees, before_tips = trees(rewritten), tips(rewritten)
    before_files = git(rewritten, "ls-tree", "-r", "--full-tree", FEATURE)
    report["before"] = snapshot(rewritten, terms)

    started = time.monotonic()
    done = subprocess.run(
        [
            "git",
            "filter-repo",
            "--force",
            "--mailmap",
            str(kit / "mailmap.txt"),
            "--message-callback",
            (kit / "msg_cb.py").read_text(encoding="utf-8"),
        ],
        cwd=rewritten,
        capture_output=True,
        text=True,
        check=False,
    )
    report["rewrite_seconds"] = round(time.monotonic() - started, 2)
    if done.returncode != 0:
        report["rewrite_error"] = done.stderr[-2000:]
        print(json.dumps(report, indent=2))
        return 1

    after_trees, after_tips = trees(rewritten), tips(rewritten)
    report["after"] = snapshot(rewritten, terms)
    report["trees_changed"] = sorted(
        r for r, t in before_trees.items() if after_trees.get(r) != t
    )
    report["refs_lost"] = sorted(set(before_trees) - set(after_trees))
    report["refs_with_new_commit_ids"] = sum(
        after_tips.get(r) != c for r, c in before_tips.items()
    )
    report["feature_tip_files"] = len(before_files.splitlines())
    report["feature_tip_files_identical"] = (
        git(rewritten, "ls-tree", "-r", "--full-tree", FEATURE) == before_files
    )

    report["handed_back"] = handed_back_state(rewritten)
    report["refs_to_push"] = [
        r for r in pushed_refs(rewritten) if r.startswith("refs/heads/")
    ] + ["refs/tags/v*"]
    report["tracked_file_hits_at_feature_tip"] = tracked_file_hits(
        rewritten, FEATURE, terms
    )
    kit_tracked = git(
        src, "ls-files", "--", *(str(p) for p in kit.iterdir()), check=False
    )
    report["kit_files_tracked"] = kit_tracked.split()

    stand_in, backup = work / "stand_in", work / "backup.git"
    clone(src, stand_in)
    original = tips(stand_in)
    subprocess.run(
        ["git", "clone", "-q", "--mirror", "--no-local", str(stand_in), str(backup)],
        check=True,
    )
    git(stand_in, "checkout", "-q", "--detach")
    refspecs = ["refs/heads/*:refs/heads/*", "refs/tags/*:refs/tags/*"]
    git(stand_in, "fetch", "-q", "--force", str(rewritten), *refspecs)
    report["adopt_moved_refs"] = sum(
        tips(stand_in).get(r) != c for r, c in original.items()
    )
    git(stand_in, "fetch", "-q", "--force", "--prune", str(backup), *refspecs)
    report["undo_restores_every_ref"] = tips(stand_in) == original

    ok = (
        not report["trees_changed"]
        and not report["refs_lost"]
        and report["feature_tip_files_identical"]
        and not any(report["after"]["message_hits_per_term"])
        and not any(report["after"]["tag_object_hits_per_term"])
        and not report["handed_back"]["refs_outside_heads_and_tags"]
        and not report["handed_back"]["notes"]
        and not report["tracked_file_hits_at_feature_tip"]
        and not report["kit_files_tracked"]
        and all(
            "Lucas Root" in i and i.endswith(OPERATOR_EMAIL)
            for i in report["after"]["identities_pushed_refs"]
        )
        and report["undo_restores_every_ref"]
    )
    report["result"] = "OK" if ok else "FAILED"
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
