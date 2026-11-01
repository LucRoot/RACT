"""B-206 part 2 fix: the hardened argv never spawns an external diff.

``-c diff.external=`` (empty) makes git try to spawn the empty program for a
diff whose path needs one, and the diff dies ("cannot spawn :"). The hardening
disables external diffs with the ``--no-ext-diff`` flag on every subcommand
that can produce a diff, which also overrides a repository's own
``diff.external`` config for that invocation.
"""

from __future__ import annotations

from ract.git_run import git_command

DIFF_CAPABLE = ("diff", "log", "show", "format-patch", "whatchanged", "range-diff")


def test_a_diff_subcommand_carries_no_ext_diff() -> None:
    argv = git_command("diff", "--binary", "a", "b", "--", "f.txt")
    assert "--no-ext-diff" in argv
    assert argv.index("--no-ext-diff") > argv.index("diff")


def test_every_diff_capable_subcommand_is_covered() -> None:
    for verb in DIFF_CAPABLE:
        argv = git_command(verb)
        assert "--no-ext-diff" in argv, verb


def test_a_non_diff_subcommand_is_not_touched() -> None:
    argv = git_command("status", "--porcelain")
    assert "--no-ext-diff" not in argv
