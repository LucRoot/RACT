from __future__ import annotations

_SENTINEL = object()


class _SentinelType:
    """Sentinel for default arguments."""


_SENTINEL_DEFAULT: _SentinelType = _SentinelType()

import argparse
from pathlib import Path
from typing import List, Optional

from ract.session_config import SessionConfig


def parse_cli_args(
    argv: Optional[List[str]] | _SentinelType = _SENTINEL_DEFAULT,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RACT CLI toggles")
    parser.add_argument(
        "--yolo", action="store_true", help="Enable fully autonomous mode"
    )
    parser.add_argument("--auto", action="store_true", help="Approval-gated mode")
    parser.add_argument(
        "--reload", action="store_true", help="Dry-run and reload after changes"
    )
    parser.add_argument(
        "--session", dest="session_id", type=str, help="Specify a session ID"
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume an existing session"
    )
    if isinstance(argv, _SentinelType):
        resolved: Optional[List[str]] = []
    else:
        resolved = argv
    args, unknown = parser.parse_known_args(resolved)
    if unknown:
        parser.error("-- " + " ".join(unknown))
    return args


def main(argv: Optional[List[str]] | _SentinelType = _SENTINEL_DEFAULT) -> int:
    args = parse_cli_args(argv)
    config_path = Path("~/.ract/session.json").expanduser()
    if args.resume:
        try:
            config = SessionConfig.from_file(config_path)
        except FileNotFoundError:
            raise SystemExit("No existing session to resume.")
    else:
        config = SessionConfig()
    if args.yolo:
        config.yolo = True
    if args.auto:
        config.auto = True
    if args.reload:
        config.reload = True
    if args.session_id is not None:
        config.session_id = args.session_id
    config.save(config_path)
    return 0


# RACT 0.1.1 - Trust and tooling
