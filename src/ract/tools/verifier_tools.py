"""``run_build``, ``run_lint``, ``run_typecheck``, ``run_format``: the verifiers (B-023).

LR:: Each is a tier-3 tool like ``run_tests`` (ADR-0048 D5, D6, D11) and
takes the same path, ``tests_tool.run_under_rule``: the grant must hold,
the matcher sees the whole argv, the operator is asked, and the command
runs through ``run_command``. There is no other way to run a command. The
rule is the grant's rule with the tool's kind as its id (``build``,
``lint``, ``typecheck``, ``format``), or the first allow rule that starts
with a known command for that kind. The model may add paths inside the
project, never options. The result is structured (kind, command id, exit
code, time, output digest, capped output), and the turn's verifier counts
every real run: a failed one keeps the turn from done (ADR-0049 D4).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ract.core.threat_model import CapabilityTier
from ract.tools import ToolRefused, ToolResult, ToolSpec

_RESULT_CAP = 64 * 1024

# Known commands per kind, matched as an argv prefix of an allow rule.
KNOWN: dict[str, tuple[tuple[str, ...], ...]] = {
    "build": (
        ("python", "-m", "build"),
        ("npm", "run", "build"),
        ("make",),
        ("cargo", "build"),
    ),
    "lint": (
        ("ruff", "check"),
        ("python", "-m", "ruff", "check"),
        ("flake8",),
        ("python", "-m", "flake8"),
        ("npm", "run", "lint"),
        ("eslint",),
    ),
    "typecheck": (
        ("mypy",),
        ("python", "-m", "mypy"),
        ("pyright",),
        ("npm", "run", "typecheck"),
        ("tsc",),
    ),
    "format": (
        ("ruff", "format", "--check"),
        ("python", "-m", "ruff", "format", "--check"),
        ("black", "--check"),
        ("python", "-m", "black", "--check"),
        ("npm", "run", "format:check"),
    ),
}


class VerifierArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[str] = Field(default_factory=list, max_length=32)
    reason: str = Field(default="", max_length=500)

    @field_validator("paths")
    @classmethod
    def _inside(cls, paths: list[str]) -> list[str]:
        for path in paths:
            posix = path.replace("\\", "/")
            if (
                not path
                or path.startswith("-")
                or "\x00" in path
                or len(path) > 300
                or PurePosixPath(posix).is_absolute()
                or ":" in posix
                or ".." in PurePosixPath(posix).parts
            ):
                raise ValueError(f"{path!r} is not a path inside the project")
        return paths


# Tools that take paths after ``--`` (make, cargo and build treat them as
# targets or arguments of their own, so they take none).
_TAKES_PATHS = {"ruff", "mypy", "black", "flake8", "eslint", "pyright", "npm"}


def takes_paths(argv: list[str] | tuple[str, ...]) -> bool:
    names = [Path(a).name.lower().removesuffix(".exe") for a in argv[:4]]
    return bool(_TAKES_PATHS & set(names))


def rule_for(policy: Any, kind: str) -> Any | None:
    """The grant's rule for *kind*: the one with that id, else a known command."""
    rules = list(getattr(getattr(policy, "commands", None), "allow", []) or [])
    for rule in rules:
        if rule.id == kind:
            return rule
    known = KNOWN[kind]
    return next(
        (r for r in rules if any(tuple(r.argv[: len(k)]) == k for k in known)), None
    )


def _runner(kind: str):
    def run(root: Path, args: VerifierArgs) -> ToolResult:
        from ract.tools.tests_tool import run_under_rule, tier3_context

        ctx = tier3_context()
        rule = rule_for(ctx.grant.policy, kind)
        if rule is None:
            raise ToolRefused(
                f"not run, because the grant has no {kind} rule",
                f"add an allow rule with id {kind} to .ract/policy.yaml and sign it",
            )
        if args.paths and not takes_paths(rule.argv):
            raise ToolRefused(
                f"the {kind} rule {' '.join(rule.argv)} takes no paths",
                "call it without paths; it runs over the whole project",
            )
        argv = [*rule.argv, *(["--"] if args.paths else []), *args.paths]
        return run_under_rule(
            root,
            ctx,
            rule,
            argv,
            args.reason,
            kind=kind,
            refused_hint="name paths inside the project",
            notes=[f"this runs the project's {kind} command with your user's rights"],
        )

    return run


def _spec(kind: str) -> ToolSpec:
    return ToolSpec(
        name=f"run_{kind}",
        tier=CapabilityTier.TIER_3_EXTERNAL,
        args_model=VerifierArgs,
        mutates=True,
        result_cap_bytes=_RESULT_CAP,
        run=_runner(kind),
    )


VERIFIER_TOOLS = tuple(_spec(kind) for kind in KNOWN)

__all__ = ["KNOWN", "VERIFIER_TOOLS", "VerifierArgs", "rule_for"]
