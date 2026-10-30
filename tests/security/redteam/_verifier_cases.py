"""B-027: the attacks on each verifier tool (run_build, run_lint, run_typecheck, run_format).

Each tool's module calls these with its kind, so a new verifier gets the same
attacks by adding a three-line module (the coverage test asks for it).
"""

from __future__ import annotations

from tests.security.redteam._world import RULES, call, nothing_ran

HOSTILE_PATHS = [
    "--fix",
    "-c",
    "--config=/etc/x",
    "../outside.py",
    "/etc/passwd",
    "a\x00b",
]


def options_and_outside_paths_are_refused(world, kind: str) -> None:
    for bad in HOSTILE_PATHS:
        rooted, asked, runner = call(world, f"run_{kind}", {"paths": [bad]})
        assert not rooted.is_ok() and asked == [] and nothing_ran(runner), bad


def a_grant_without_the_rule_runs_nothing(world, kind: str) -> None:
    world.resign(rules=_without(kind))
    rooted, asked, runner = call(world, f"run_{kind}")
    assert (
        not rooted.is_ok()
        and f"not run, because the grant has no {kind} rule" in rooted.error
    )
    assert asked == [] and nothing_ran(runner)


def _without(kind: str) -> str:
    entries = [e for e in RULES.split("    - id: ") if e]
    return "".join(f"    - id: {e}" for e in entries if not e.startswith(f"{kind}\n"))


def a_no_runs_nothing(world, kind: str) -> None:
    rooted, _asked, runner = call(world, f"run_{kind}", answer=False)
    assert not rooted.is_ok() and nothing_ran(runner)


def the_result_is_structured_and_counted(world, kind: str) -> None:
    rooted, _asked, runner = call(world, f"run_{kind}")
    assert rooted.is_ok(), rooted.error
    facts = rooted.unwrap().facts
    assert facts["kind"] == kind and facts["runner"] == "fake"
    assert len(facts["output_sha256"]) == 64 and facts["command_id"].startswith("a-")


def a_changed_entry_point_asks_in_allowlist(world, kind: str) -> None:
    (world.project / "pyproject.toml").write_text("[tool.x]\n", encoding="utf-8")
    _rooted, asked, _runner = call(world, f"run_{kind}", mode="allowlist")
    assert len(asked) == 1 and asked[0]["entry_points"]


ALL = (
    options_and_outside_paths_are_refused,
    a_grant_without_the_rule_runs_nothing,
    a_no_runs_nothing,
    the_result_is_structured_and_counted,
    a_changed_entry_point_asks_in_allowlist,
)
