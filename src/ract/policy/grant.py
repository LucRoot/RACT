"""The tier-3 grant: ``.ract/policy.yaml`` signed by the operator key (ADR-0048 D3).

LR:: A project opens tier 3 only through a grant the operator signed with
the key pinned in their user config. ``load_grant`` decides, once per
session, whether the project's grant holds, and says why when it does not:
no grant, not signed, signed by another key (a cloned repository's policy
grants nothing), a bad signature, a policy that does not validate, bound to
another folder or another repository, not yet valid, expired, or revoked
(a revoked digest stays refused even when the file comes back from git
history). Any error refuses the whole grant: a partly valid grant grants
nothing. Validation errors name the file, line, field and fix.

The signature covers the exact bytes of ``policy.yaml`` with a domain
prefix; ``policy.yaml.sig`` is ``ract-policy-sig/1`` JSON (key id, SHA-256
of the bytes, signature). Tools can write neither file (ADR-0047 D3).
"""

from __future__ import annotations

import re
import base64
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from ract.policy import config_dir
from ract.policy.operator_key import PublicKey, pinned

POLICY_FILE = "policy.yaml"
SIGNATURE_FILE = "policy.yaml.sig"
SIG_FORMAT = "ract-policy-sig/1"
_DOMAIN = b"ract-policy/1\n"
MAX_DAYS = 365
DEFAULT_DAYS = 90
# An interpreter or shell alone runs any code: a rule must name what it runs.
_TOO_BROAD = {
    "python",
    "python3",
    "py",
    "node",
    "deno",
    "bun",
    "ruby",
    "perl",
    "php",
    "bash",
    "sh",
    "zsh",
    "fish",
    "cmd",
    "cmd.exe",
    "powershell",
    "pwsh",
    "powershell.exe",
    "pwsh.exe",
    "python.exe",
    "env",
    "npx",
    "uv",
    "uvx",
}


# Wrappers that the matcher does not strip: they run a command given after
# them, so a rule may not start with one (G-213 G2, G-214 M2).
_RUNTIME_RUNNERS = {
    "command",
    "exec",
    "flock",
    "setsid",
    "taskset",
    "strace",
    "chroot",
    "unshare",
    "xvfb-run",
    "fakeroot",
    "npx",
    "uvx",
    "pipx",
}
# Modules that install or run arbitrary code (``python -m pip install x``).
_CODE_MODULES = {"pip", "ensurepip", "runpy", "code", "idlelib"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Binding(_Strict):
    project_root: str = Field(min_length=1)
    repo_root_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


_PINNED_IMAGE = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}$"
)


class AllowRule(_Strict):
    id: str = Field(min_length=1, max_length=64)
    argv: list[str] = Field(min_length=1, max_length=32)
    network: bool = False
    cwd: str = "step_worktree"
    timeout_s: int = Field(default=900, ge=1, le=3600)
    max_output_bytes: int = Field(default=1_048_576, ge=1, le=64 * 1_048_576)
    home: Literal["isolated", "real"] = "isolated"
    env_extra: list[str] = Field(default_factory=list)
    git_hooks: bool = False
    # B-028 (D-142): where the command runs. host is this machine; wsl2 runs
    # the program WSL resolves; container runs it in an image pinned by
    # digest. Until those backends are wired, their rules are refused at run.
    backend: Literal["host", "wsl2", "container"] = "host"
    image: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _image_pinned(self) -> "AllowRule":
        if self.backend == "container":
            if not self.image or not _PINNED_IMAGE.match(self.image):
                raise ValueError(
                    "a container rule names its image pinned by digest "
                    "(name@sha256:<64 hex>); a tag alone can change under the grant"
                )
        elif self.image is not None:
            raise ValueError("image belongs to a rule with backend: container")
        return self

    @field_validator("argv")
    @classmethod
    def _narrow(cls, argv: list[str]) -> list[str]:
        if any(not part or "\x00" in part for part in argv):
            raise ValueError("an argv element is empty")
        if len(argv) == 1 and Path(argv[0]).name.lower() in _TOO_BROAD:
            raise ValueError(
                f"{argv} is too broad: an interpreter alone runs any code. hint: name "
                "the module or script, for example [python, -m, pytest]"
            )
        from ract.policy import matcher

        name = matcher._name(argv[0])
        # G-213 G2: rules the matcher's floor would never let match, refused at
        # load so the operator is not misled into thinking they allow something.
        if (
            name in matcher._SHELLS
            or matcher.inline_code(name, argv[1:])
            or matcher.wrapped_code(argv[1:])
        ):
            raise ValueError(
                f"{argv} runs code given on the command line (a shell or inline code); "
                "hint: name the module or script, for example [python, -m, pytest]"
            )
        if (
            name in matcher._WRAPPERS
            or name in matcher._NEVER
            or name in _RUNTIME_RUNNERS
        ):
            raise ValueError(
                f"{argv} starts with {name}, which runs a command chosen elsewhere; "
                "hint: name the command itself"
            )
        if argv[:2] == ["uv", "run"]:
            raise ValueError(
                f"{argv}: uv run runs whatever follows; hint: name the command itself"
            )
        if (
            name in {"python", "pypy", "py"}
            and argv[1:2] == ["-m"]
            and (argv[2:3] and argv[2] in _CODE_MODULES)
        ):
            raise ValueError(
                f"{argv}: python -m {argv[2]} installs or runs arbitrary code; "
                "hint: name the test module, for example [python, -m, pytest]"
            )
        return argv

    @field_validator("cwd")
    @classmethod
    def _cwd(cls, cwd: str) -> str:
        if cwd != "step_worktree" and not cwd.startswith("step_worktree/"):
            raise ValueError("cwd is step_worktree or step_worktree/<relative path>")
        if ".." in cwd.split("/"):
            raise ValueError("cwd may not leave the step worktree")
        return cwd


class DenyRule(_Strict):
    argv: list[str] = Field(min_length=1)


class Commands(_Strict):
    allow: list[AllowRule] = Field(default_factory=list)
    deny: list[DenyRule] = Field(default_factory=list)


class Shell(_Strict):
    enabled: bool = False


class WebFetch(_Strict):
    allow_domains: list[str] = Field(default_factory=list)


class NetworkTools(_Strict):
    web_fetch: WebFetch | None = None


class Limits(_Strict):
    max_procs: int = Field(default=64, ge=1, le=4096)
    memory_mb: int = Field(default=4096, ge=64, le=1_048_576)
    cpu_seconds: int = Field(default=900, ge=1, le=86_400)


class Policy(_Strict):
    @field_validator("max_mode")
    @classmethod
    def _no_unrestricted(cls, value: str) -> str:
        # D4: unrestricted needs a backend that confines commands; none exists yet.
        if value == "unrestricted":
            raise ValueError(
                "max_mode: unrestricted is refused: no sandbox confines commands on "
                "this machine; use ask or allowlist"
            )
        return value

    version: Literal[1]
    binding: Binding
    issued_at: datetime
    expires_at: datetime
    key_id: str = Field(pattern=r"^ed25519:[0-9a-f]{16}$")
    max_mode: Literal["ask", "allowlist", "unrestricted"] = "ask"
    sandbox: Literal["enforced", "best_effort"]
    commands: Commands = Field(default_factory=Commands)
    shell: Shell = Field(default_factory=Shell)
    network_tools: NetworkTools = Field(default_factory=NetworkTools)
    limits: Limits = Field(default_factory=Limits)

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        # A time written without a zone is read as UTC, so comparisons hold.
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class PolicyInvalid(Exception):
    """``policy.yaml`` does not validate; each line names file, line, field and fix."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _lines(text: str) -> dict[tuple[Any, ...], int]:
    """The 1-based line of each mapping key and sequence item, by its path."""
    out: dict[tuple[Any, ...], int] = {}
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return out

    def walk(node: Any, path: tuple[Any, ...]) -> None:
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                here = (*path, key.value)
                out[here] = key.start_mark.line + 1
                walk(value, here)
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                here = (*path, i)
                out[here] = item.start_mark.line + 1
                walk(item, here)

    if root is not None:
        walk(root, ())
    return out


def parse_policy(text: str, name: str = POLICY_FILE) -> Policy:
    """Validate *text* as policy schema v1; ``PolicyInvalid`` names each problem."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = f":{mark.line + 1}" if mark is not None else ""
        raise PolicyInvalid([f"{name}{line}: not YAML: {exc}"]) from exc
    if not isinstance(data, dict):
        raise PolicyInvalid(
            [f"{name}: the policy is a mapping (version, binding, ...)"]
        )
    try:
        policy = Policy.model_validate(data)
    except ValidationError as exc:
        lines = _lines(text)
        problems = []
        for err in exc.errors():
            loc = tuple(err["loc"])
            at_line = next(
                (lines[loc[:n]] for n in range(len(loc), 0, -1) if loc[:n] in lines),
                None,
            )
            where = f"{name}:{at_line}" if at_line else name
            dotted = "".join(
                f"[{p}]" if isinstance(p, int) else (f".{p}" if i else str(p))
                for i, p in enumerate(loc)
            )
            message = str(err["msg"]).removeprefix("Value error, ")
            problems.append(f"{where} {dotted}: {message}")
        raise PolicyInvalid(problems) from exc
    problems = []
    lines = _lines(text)
    span = policy.expires_at - policy.issued_at
    if span <= timedelta(0):
        problems.append(
            f"{name}:{lines.get(('expires_at',), '?')} expires_at: is not after issued_at"
        )
    elif span > timedelta(days=MAX_DAYS):
        problems.append(
            f"{name}:{lines.get(('expires_at',), '?')} expires_at: a grant lasts at most "
            f"{MAX_DAYS} days. hint: the default is {DEFAULT_DAYS}"
        )
    if problems:
        raise PolicyInvalid(problems)
    return policy


def sandbox_confines_commands() -> bool:
    """True where RACT confines a tier-3 command (ADR-0048 D7, B-114).

    Only where the platform's backend exists and its self-test, run once per
    process, proved that a write outside the workspace and a network
    connection are refused (``security.command_sandbox``). Windows has no
    backend yet (B-028) and macOS's profile is not run, so there a grant says
    ``sandbox: best_effort`` and the interface says so; a grant that says
    ``enforced`` there does not hold.
    """
    from ract.security.command_sandbox import enforcing_backend

    backend, _why = enforcing_backend()
    return backend is not None


def _message(data: bytes) -> bytes:
    return _DOMAIN + data


def _repo_root_commit(project: Path) -> str | None:
    from ract.executor.worktree import repo_root_commit

    return repo_root_commit(project)


def _same_folder(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(
        os.path.realpath(b)
    )


# ------------------------------------------------------------------ signing


def sign(project: Path | str, private_key: Any, key: PublicKey) -> str:
    """Sign the project's ``.ract/policy.yaml`` with the unlocked operator key.

    The policy must validate, name this key and be bound to this folder (and
    to this repository's first commit when it says one). Returns the digest.
    """
    project = Path(project)
    path = project / ".ract" / POLICY_FILE
    data = path.read_bytes()
    policy = parse_policy(data.decode("utf-8"))
    if policy.key_id != key.key_id:
        raise PolicyInvalid(
            [f"{POLICY_FILE} key_id: {policy.key_id} is not your key ({key.key_id})"]
        )
    if not _same_folder(policy.binding.project_root, project):
        raise PolicyInvalid(
            [
                f"{POLICY_FILE} binding.project_root: {policy.binding.project_root} is not "
                f"this folder ({os.path.realpath(project)})"
            ]
        )
    digest = hashlib.sha256(data).hexdigest()
    signature = private_key.sign(_message(data))
    sig = {
        "format": SIG_FORMAT,
        "key_id": key.key_id,
        "sha256": digest,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    out = project / ".ract" / SIGNATURE_FILE
    temp = out.with_name(out.name + ".tmp")
    temp.write_text(json.dumps(sig, indent=2), encoding="utf-8")
    os.replace(temp, out)
    # B-113 (G-214): what the entry points were at signing, kept outside the
    # project, so a later change to one puts its command back to the question.
    from ract.policy import allowlist

    allowlist.record_signed(project, digest)
    return digest


# ------------------------------------------------------------------ revocation


def _revoked_file(config: Path | None) -> Path:
    return (config or config_dir()) / "revoked_grants.json"


class RevocationListUnreadable(Exception):
    """The revocation list exists and cannot be read: no grant holds (G-213 G1)."""


def revoked(config: Path | None = None) -> set[str]:
    """The revoked grant digests. A missing list is empty; an unreadable one raises.

    A list that exists and cannot be read must not let a revoked grant back
    in, so it refuses every grant until it is fixed (G-213 G1).
    """
    path = _revoked_file(config)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RevocationListUnreadable(str(exc)) from exc
    if not isinstance(data, list):
        raise RevocationListUnreadable("it is not a list of digests")
    return {d for d in data if isinstance(d, str)}


def revoke(project: Path | str, *, config: Path | None = None) -> str | None:
    """Delete the signature and list the grant's digest as revoked; the digest or None."""
    project = Path(project)
    policy_path = project / ".ract" / POLICY_FILE
    sig_path = project / ".ract" / SIGNATURE_FILE
    digest = (
        hashlib.sha256(policy_path.read_bytes()).hexdigest()
        if policy_path.is_file()
        else None
    )
    if digest is not None:
        listed = revoked(config) | {digest}
        out = _revoked_file(config)
        out.parent.mkdir(parents=True, exist_ok=True)
        temp = out.with_name(out.name + ".tmp")
        temp.write_text(json.dumps(sorted(listed)), encoding="utf-8")
        os.replace(temp, out)  # never a half-written list (G-213 G1)
    if sig_path.exists():
        sig_path.unlink()
    return digest


# ------------------------------------------------------------------ loading


def pin_digest(project: Path | str) -> str:
    """One digest of ``policy.yaml`` and its signature, as the session found them.

    ADR-0048 D3: the grant is loaded once at session start and pinned; a
    change to either file during the session suspends tier 3 until the
    operator confirms at the terminal.
    """
    project = Path(project)
    parts = []
    for name in (POLICY_FILE, SIGNATURE_FILE):
        path = project / ".ract" / name
        parts.append(path.read_bytes() if path.is_file() else b"")
    return _pin_of(*parts)


def _pin_of(policy: bytes, signature: bytes) -> str:
    return hashlib.sha256(policy + b"\0" + signature).hexdigest()


Status = Literal[
    "none", "unsigned", "invalid", "not-yet", "expired", "revoked", "suspended", "ok"
]


@dataclass(frozen=True)
class GrantState:
    """Whether the project's grant holds, and why not."""

    status: Status
    reason: str = ""
    policy: Policy | None = None
    digest: str | None = None
    problems: list[str] = field(default_factory=list)
    # The digest of the bytes this decision read (policy and signature), the
    # session's pin (G-213 G3); pin_digest of the same bytes gives the same.
    pin: str | None = None

    @property
    def holds(self) -> bool:
        return self.status == "ok"


def load_grant(
    project: Path | str,
    *,
    config: Path | None = None,
    now: datetime | None = None,
) -> GrantState:
    """Decide whether the project's tier-3 grant holds (ADR-0048 D3).

    Each file is read once; the decision and its ``pin`` are of those bytes.
    """
    project = Path(project)
    now = now or datetime.now(timezone.utc)
    policy_path = project / ".ract" / POLICY_FILE
    sig_path = project / ".ract" / SIGNATURE_FILE
    data = policy_path.read_bytes() if policy_path.is_file() else None
    sig_bytes = sig_path.read_bytes() if sig_path.is_file() else None
    pin = _pin_of(data or b"", sig_bytes or b"")
    digest = hashlib.sha256(data).hexdigest() if data is not None else None

    def state(
        status: Status, reason: str, policy: Policy | None = None, problems=None
    ) -> GrantState:
        return GrantState(status, reason, policy, digest, list(problems or []), pin)

    if data is None:
        return state("none", "no grant")
    try:
        if digest in revoked(config):
            return state("revoked", "this grant was revoked")
    except RevocationListUnreadable as exc:
        return state("invalid", f"the revocation list cannot be read ({exc})")
    if sig_bytes is None:
        return state("unsigned", "the policy is not signed")
    key = pinned(config)
    if key is None:
        return state("unsigned", "no operator key is pinned on this machine")
    try:
        sig = json.loads(sig_bytes.decode("utf-8"))
        signature = base64.b64decode(sig["signature"], validate=True)
        ok_format = sig.get("format") == SIG_FORMAT
    except (ValueError, KeyError, TypeError) as exc:
        return state("invalid", f"the signature file cannot be read ({exc})")
    if not ok_format or sig.get("key_id") != key.key_id:
        return state("invalid", "the grant is not signed by your operator key")
    if sig.get("sha256") != digest or not key.verify(signature, _message(data)):
        return state("invalid", "the signature does not match policy.yaml")
    try:
        policy = parse_policy(data.decode("utf-8"))
    except (PolicyInvalid, UnicodeDecodeError) as exc:
        problems = exc.problems if isinstance(exc, PolicyInvalid) else [str(exc)]
        return state("invalid", "policy.yaml does not validate", problems=problems)
    if policy.key_id != key.key_id:
        return state("invalid", "the grant names another key")
    if not _same_folder(policy.binding.project_root, project):
        return state("invalid", "the grant is bound to another folder")
    if policy.binding.repo_root_commit is not None and (
        _repo_root_commit(project) != policy.binding.repo_root_commit
    ):
        return state("invalid", "the grant is bound to another repository")
    if policy.sandbox == "enforced" and not sandbox_confines_commands():
        # A grant says what this machine does: no backend confines commands.
        return state(
            "invalid",
            "the grant says sandbox: enforced, and this machine cannot confine "
            "commands; it must say sandbox: best_effort",
            policy,
        )
    if now < policy.issued_at - timedelta(minutes=5):
        return state("not-yet", "the grant is not valid yet", policy)
    if now >= policy.expires_at:
        return state(
            "expired", f"grant expired {policy.expires_at.date().isoformat()}", policy
        )
    return state("ok", "", policy)


__all__ = [
    "pin_digest",
    "GrantState",
    "Policy",
    "PolicyInvalid",
    "load_grant",
    "parse_policy",
    "revoke",
    "revoked",
    "sign",
]
