"""`ract setup`: from an empty directory to a working ract.yaml (B-015).

LR:: A first-time user had to know a preset name, a local URL, an
environment variable and a model size before RACT would run. Setup checks
the machine, offers a model server that is already running, and otherwise
asks local or cloud: for local it recommends a model for the memory the
user gives it and prints how to start one (it never downloads); for cloud
it names the environment variable for the key and checks only that it is
set. It writes ract.yaml atomically, never over an existing one, then runs
one tiny completion to prove the config works.

No key is read, written or printed by setup: the config holds ``${NAME}``
and the provider reads the value when it sends a request, as on any run.
"""

from __future__ import annotations

import difflib
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ract.provider_presets import get_preset, list_presets
from ract.setup import host_probe, local_probe, tiers

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INTERRUPTED = 5
EXIT_PROVIDER = 6

CONFIG_NAME = "ract.yaml"
DRAFT_NAME = "ract.yaml.draft"

DEFAULT_ANSWERS = """\
# Answers for `ract setup --answers FILE`. Every field is optional.
provider: local          # local or cloud
local:
  url: null              # null: use the first server that answers on a default port
  model: null            # null: the first model the server reports
cloud:
  preset: openai         # one of: {cloud}
  model: null            # null: the preset's default model
check: true              # run one tiny completion with the written config
git_init: false          # run `git init` when this directory is not a repository
reconfigure: false       # write ract.yaml.draft next to an existing ract.yaml
"""

_ENV_VARS = {
    name: str(get_preset(name)["providers"][name].get("api_key", ""))[2:-1]
    for name in list_presets()
    if name != "local"
}


class SetupError(Exception):
    """A setup that cannot continue; ``code`` is the process exit code."""

    def __init__(self, message: str, code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Answers:
    provider: str = "local"
    local_url: str | None = None
    local_model: str | None = None
    cloud_preset: str = "openai"
    cloud_model: str | None = None
    check: bool = True
    git_init: bool = False
    reconfigure: bool = False

    @classmethod
    def from_yaml(cls, text: str) -> Answers:
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise SetupError("the answers file must be a YAML mapping")
        local = data.get("local") or {}
        cloud = data.get("cloud") or {}
        answers = cls(
            provider=str(data.get("provider", "local")),
            local_url=local.get("url"),
            local_model=local.get("model"),
            cloud_preset=str(cloud.get("preset", "openai")),
            cloud_model=cloud.get("model"),
            check=bool(data.get("check", True)),
            git_init=bool(data.get("git_init", False)),
            reconfigure=bool(data.get("reconfigure", False)),
        )
        if answers.provider not in {"local", "cloud"}:
            raise SetupError(
                f"provider must be local or cloud, not {answers.provider!r}"
            )
        if answers.provider == "cloud" and answers.cloud_preset not in _ENV_VARS:
            raise SetupError(
                f"unknown cloud preset {answers.cloud_preset!r}; one of: "
                + ", ".join(sorted(_ENV_VARS))
            )
        return answers


def print_defaults() -> str:
    return DEFAULT_ANSWERS.format(cloud=", ".join(sorted(_ENV_VARS)))


@dataclass
class Health:
    ok: bool
    seconds: float
    detail: str


# --------------------------------------------------------------- config


def build_config(
    directory: Path, answers: Answers, server: local_probe.Server | None
) -> dict[str, Any]:
    if answers.provider == "cloud":
        config = get_preset(answers.cloud_preset)
        if answers.cloud_model:
            config["providers"][answers.cloud_preset]["model"] = answers.cloud_model
    else:
        config = get_preset("local")
        settings = config["providers"]["local"]
        if server is not None:
            settings["url"] = server.url
            # A model the server does not list (a recommendation made before
            # the server was found) would fail every request.
            chosen = answers.local_model
            if chosen is None or (server.models and chosen not in server.models):
                chosen = server.models[0] if server.models else "local-model"
            settings["model"] = chosen
        else:
            if answers.local_url:
                settings["url"] = answers.local_url
            if answers.local_model:
                settings["model"] = answers.local_model
    config["project"] = {"name": directory.resolve().name or "my-ract-project"}
    return config


def _atomic_write(path: Path, text: str) -> None:
    """Write ``path`` through a temporary file and one rename (never half a file)."""
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def write_config(
    directory: Path, config: dict[str, Any], *, reconfigure: bool
) -> tuple[Path, str]:
    """Write the config. Returns the path written and a diff (reconfigure only)."""
    text = yaml.safe_dump(config, sort_keys=False)
    target = directory / CONFIG_NAME
    if target.exists():
        if not reconfigure:
            raise SetupError(
                f"{CONFIG_NAME} already exists here; nothing was changed. To draft a new "
                f"one next to it: ract setup --reconfigure. To check this one: ract doctor "
                "--check-providers"
            )
        draft = directory / DRAFT_NAME
        _atomic_write(draft, text)
        diff = "".join(
            difflib.unified_diff(
                target.read_text(encoding="utf-8").splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=CONFIG_NAME,
                tofile=DRAFT_NAME,
            )
        )
        return draft, diff
    _atomic_write(target, text)
    from ract.harness import _default_manager_prompt_path

    prompt = directory / str(config.get("prompts_dir", "prompts")) / "manager.txt"
    if not prompt.exists():
        prompt.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            prompt, _default_manager_prompt_path().read_text(encoding="utf-8")
        )
    return target, ""


def health_check(config_path: Path) -> Health:
    """One tiny completion with the provider the config names."""
    from ract.providers.local_http_provider import LocalHttpProvider
    from ract.providers.openai_provider import OpenAICompatibleProvider

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    name = config["manager_provider"]
    settings = dict(config["providers"][name])
    settings.setdefault("max_retries", 1)
    adapter = settings.get("adapter")
    provider = (
        LocalHttpProvider(settings)
        if adapter == "local_http"
        else OpenAICompatibleProvider(settings)
    )
    started = time.perf_counter()
    try:
        result = provider.complete(
            [{"role": "user", "content": "Reply with the single word: ready"}],
            max_tokens=8,
            temperature=0.0,
        )
    finally:
        provider.close()
    seconds = time.perf_counter() - started
    if result.is_ok():
        return Health(True, seconds, "the model answered")
    return Health(False, seconds, result.error or "the request failed")


def _is_git_repository(directory: Path) -> bool:
    out = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=directory,
        capture_output=True,
        text=True,
    )
    return out.returncode == 0 and out.stdout.strip() == "true"


# --------------------------------------------------------------- the flow


@dataclass
class Io:
    """How setup talks to the user; replaced in tests."""

    ask: Callable[[str], str] = input
    say: Callable[[str], object] = print
    detect: Callable[[tuple[str, ...]], list[local_probe.Server]] = local_probe.detect
    probe: Callable[[], host_probe.HostProfile] = host_probe.probe_host
    health: Callable[[Path], Health] = health_check
    environ: Any = field(default_factory=lambda: os.environ)


def _extra(answers: Answers) -> tuple[str, ...]:
    return (answers.local_url,) if answers.local_url else ()


def _yes(reply: str, default: bool) -> bool:
    reply = reply.strip().lower()
    return default if not reply else reply in {"y", "yes"}


def _choose_server(
    io: Io, servers: list[local_probe.Server], answers: Answers, interactive: bool
) -> local_probe.Server | None:
    for server in servers:
        models = ", ".join(server.models[:5]) or "no models listed"
        io.say(f"  found {server.label} at {server.url} ({models})")
    if not servers:
        return None
    if answers.local_url:
        return next(
            (s for s in servers if s.url == answers.local_url.rstrip("/")), None
        )
    server = servers[0]
    if interactive:
        if not _yes(io.ask(f"Use the server at {server.url}? [Y/n] "), True):
            return None
        if len(server.models) > 1:
            listing = "\n".join(f"  {n}) {m}" for n, m in enumerate(server.models, 1))
            io.say(f"It reports {len(server.models)} models:\n{listing}")
            pick = io.ask("Which one? [1] ").strip() or "1"
            if pick.isdigit() and 1 <= int(pick) <= len(server.models):
                answers.local_model = server.models[int(pick) - 1]
    return server


def _local_guidance(io: Io, profile: host_probe.HostProfile, answers: Answers) -> None:
    gb = host_probe.GB
    available = (
        None
        if profile.available_ram_bytes is None
        else profile.available_ram_bytes / gb
    )
    suggested = tiers.default_dedicated_gb(available)
    prompt = (
        f"How many GB of memory should the model use? [{suggested:g}] "
        if suggested is not None
        else "How many GB of memory should the model use? (memory size unknown) "
    )
    reply = io.ask(prompt).strip()
    try:
        dedicated = float(reply) if reply else suggested
    except ValueError:
        dedicated = suggested
    advice = tiers.recommend(dedicated)
    io.say(
        f"Suggested model: {advice.tier.display} (about {advice.tier.weights_gb:g} GB): {advice.reason}."
    )
    io.say(f"  {advice.tier.note}")
    io.say("Start it with one of these (setup does not download anything):")
    for line in tiers.install_steps(advice.tier):
        io.say(f"  {line}")
    io.say(f"Guidance reviewed {advice.reviewed}; sizes are approximate.")
    if answers.local_model is None and advice.tier.ollama:
        # Used when the user writes the config before starting a server.
        answers.local_model = advice.tier.ollama


def _cloud(io: Io, answers: Answers, interactive: bool) -> None:
    names = sorted(_ENV_VARS)
    if interactive:
        listing = "\n".join(
            f"  {n}) {name}  (key in {_ENV_VARS[name]})"
            for n, name in enumerate(names, 1)
        )
        io.say(f"Cloud providers:\n{listing}")
        pick = io.ask("Which one? [1] ").strip() or "1"
        if pick.isdigit() and 1 <= int(pick) <= len(names):
            answers.cloud_preset = names[int(pick) - 1]
    variable = _ENV_VARS[answers.cloud_preset]
    # Presence only: the value is never read here.
    if variable in io.environ:
        io.say(f"  {variable} is set; ract.yaml will refer to it as ${{{variable}}}.")
    else:
        io.say(
            f"  {variable} is not set. ract.yaml will refer to it as ${{{variable}}}; set it "
            "in your shell before running RACT. Setup never reads or stores the key."
        )


def run(
    directory: Path,
    *,
    answers: Answers | None = None,
    interactive: bool,
    io: Io | None = None,
) -> int:
    """Run setup in ``directory``. Returns the process exit code."""
    io = io or Io()
    answers = answers or Answers()
    try:
        return _run(directory, answers, interactive, io)
    except KeyboardInterrupt:
        io.say("\nsetup stopped; nothing was written.")
        return EXIT_INTERRUPTED
    except EOFError:
        io.say(
            "\nsetup needs an answer and the input ended; nothing was written. "
            "hint: ract setup --answers FILE, or ract setup --yolo"
        )
        return EXIT_USAGE
    except SetupError as exc:
        io.say(f"error: {exc}")
        return exc.code


def _run(directory: Path, answers: Answers, interactive: bool, io: Io) -> int:
    if (directory / CONFIG_NAME).exists() and not answers.reconfigure:
        raise SetupError(
            f"{CONFIG_NAME} already exists here; nothing was changed. To draft a new one "
            "next to it: ract setup --reconfigure. To check this one: ract doctor "
            "--check-providers"
        )
    io.say("Machine:")
    profile = io.probe()
    for line in host_probe.describe(profile):
        io.say(f"  {line}")
    io.say(
        "  network: not tested; setup contacts only the default model-server "
        "addresses on this machine and the provider you choose"
    )

    server: local_probe.Server | None = None
    if answers.provider == "local":
        io.say("Looking for a model server on this machine (default ports only):")
        server = _choose_server(io, io.detect(_extra(answers)), answers, interactive)
        if server is None and interactive:
            choice = io.ask(
                "No server chosen. Use a local model or a cloud provider? [L/c] "
            )
            answers.provider = (
                "cloud" if choice.strip().lower().startswith("c") else "local"
            )
            if answers.provider == "local":
                _local_guidance(io, profile, answers)
                again = io.ask(
                    "Start the server, then press Enter to look again, or type skip to "
                    "write a config for Ollama's default address now: "
                )
                if again.strip().lower() != "skip":
                    server = _choose_server(
                        io, io.detect(_extra(answers)), answers, interactive
                    )
        elif server is None:
            io.say(
                "  none found; writing a config for "
                + (answers.local_url or "Ollama's default address")
            )
    if answers.provider == "cloud":
        _cloud(io, answers, interactive)

    config = build_config(directory, answers, server)
    path, diff = write_config(directory, config, reconfigure=answers.reconfigure)
    if diff or path.name == DRAFT_NAME:
        io.say(f"Wrote {path.name}. Differences from {CONFIG_NAME}:")
        io.say(diff or "  (none)")
        io.say(
            f"Review it, then replace {CONFIG_NAME} with it to use it, or delete it."
        )
        return EXIT_OK
    io.say(f"Wrote {CONFIG_NAME} and prompts/manager.txt.")

    code = EXIT_OK
    settings = config["providers"][config["manager_provider"]]
    key_missing = (
        answers.provider == "cloud"
        and _ENV_VARS[answers.cloud_preset] not in io.environ
    )
    if not answers.check:
        io.say("Skipped the health check (check: false).")
    elif key_missing:
        io.say(
            "Skipped the health check: the key variable is not set yet. Then run: ract doctor --check-providers"
        )
    else:
        io.say(f"Checking {settings['url']} with one tiny request:")
        health = io.health(path)
        if health.ok:
            io.say(f"  ok: {health.detail} in {health.seconds:.1f} s")
        else:
            from ract.session_turn import hint_for

            io.say(f"  failed: {health.detail}")
            io.say(f"  hint: {hint_for(health.detail)}")
            code = EXIT_PROVIDER

    if not _is_git_repository(directory):
        io.say(
            "This directory is not a git repository. RACT records each step on its own "
            "branch, so it works best in one. Command: git init"
        )
        run_init = answers.git_init or (
            interactive and _yes(io.ask("Run git init here now? [y/N] "), False)
        )
        if run_init:
            subprocess.run(["git", "init", "-q"], cwd=directory, check=False)
            io.say("  ran: git init")

    io.say(
        'Next: run `ract` to open a session here, or try: ract -p --ask "what does this project do?"'
    )
    return code


def main(argv: list[str]) -> int:
    """`ract setup [--answers FILE | --yolo | --print-defaults] [--reconfigure]`."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="ract setup",
        description="Check this machine, choose a model, and write a working ract.yaml.",
    )
    parser.add_argument(
        "--answers", type=Path, help="answer the questions from a YAML file"
    )
    parser.add_argument(
        "--yolo", action="store_true", help="use every default; no questions"
    )
    parser.add_argument(
        "--print-defaults", action="store_true", help="print an answers template"
    )
    parser.add_argument(
        "--reconfigure",
        action="store_true",
        help=f"write {DRAFT_NAME} and show how it differs from {CONFIG_NAME}",
    )
    args = parser.parse_args(argv)
    if args.print_defaults:
        print(print_defaults(), end="")
        return EXIT_OK
    answers = Answers()
    if args.answers is not None:
        try:
            answers = Answers.from_yaml(args.answers.read_text(encoding="utf-8"))
        except (OSError, SetupError, yaml.YAMLError) as exc:
            print(f"error: could not use {args.answers}: {exc}", file=sys.stderr)
            return EXIT_USAGE
    if args.reconfigure:
        answers.reconfigure = True
    # Both ends: on Windows the null device reports itself as a terminal.
    interactive = (
        args.answers is None
        and not args.yolo
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )
    if args.answers is None and not args.yolo and not interactive:
        print(
            "error: setup asks questions and there is no terminal. hint: ract setup "
            "--answers FILE (template: ract setup --print-defaults), or ract setup --yolo",
            file=sys.stderr,
        )
        return EXIT_USAGE
    return run(Path.cwd(), answers=answers, interactive=interactive)


__all__ = [
    "Answers",
    "Health",
    "Io",
    "SetupError",
    "build_config",
    "health_check",
    "main",
    "print_defaults",
    "run",
    "write_config",
]
