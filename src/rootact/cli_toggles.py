# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"


class _RootKnotType:
    """Sentinel for Root Knot default arguments."""


_ROOT_KNOT: _RootKnotType = _RootKnotType()

import argparse
from pathlib import Path
from typing import List, Optional

from rootact.session_config import SessionConfig


def parse_cli_args(
    argv: Optional[List[str]] | _RootKnotType = _ROOT_KNOT,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RootAct CLI toggles")
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
    if isinstance(argv, _RootKnotType):
        resolved: Optional[List[str]] = []
    else:
        resolved = argv
    args, unknown = parser.parse_known_args(resolved)
    if unknown:
        parser.error("-- " + " ".join(unknown))
    return args


def main(argv: Optional[List[str]] | _RootKnotType = _ROOT_KNOT) -> int:
    args = parse_cli_args(argv)
    config_path = Path("~/.rootact/session.json").expanduser()
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


# RACT 0.1.1 - Trust and Tooling
