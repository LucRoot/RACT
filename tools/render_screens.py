"""Render the pure screens at 80, 60 and 40 columns into docs/ux captures (B-125 to B-127 and the
B-111, B-113 screens). No model, no network, no terminal: each capture is the screen's own text.

Run from the repository root:  python tools/render_screens.py
Writes one file per screen and width under docs/ux/screens/. The captures are regenerated, never
edited by hand; a plain capture has no markup and a NO_COLOR capture is the same text.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ract.ui import git_screens, network_screens, sandbox_screens  # noqa: E402

OUT = ROOT / "docs" / "ux" / "screens"
WIDTHS = (80, 60, 40)


def _sandbox(width: int) -> list[str]:
    posture = sandbox_screens.SandboxPosture(
        "windows-job", sandbox_screens.BEST_EFFORT, "wall 900 s"
    )
    return sandbox_screens.doctor_sandbox_lines(posture, width)


def _commit(width: int) -> list[str]:
    req = git_screens.CommitRequest(message="fix add()", files=("src/calc.py",))
    return git_screens.commit_prompt_lines(req, width)


def _push(width: int) -> list[str]:
    return git_screens.push_prompt_lines("origin", "main", width)


def _fetch(width: int) -> list[str]:
    req = network_screens.FetchRequest(
        url="https://docs.example.org/api",
        host="docs.example.org",
        allowlist_match=None,
        size_cap_kib=512,
    )
    return network_screens.fetch_prompt_lines(req, width)


SCREENS = {
    "sandbox_doctor": _sandbox,
    "commit_prompt": _commit,
    "push_prompt": _push,
    "fetch_prompt": _fetch,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, render in SCREENS.items():
        for width in WIDTHS:
            text = "\n".join(render(width)) + "\n"
            (OUT / f"{name}_{width}.txt").write_text(
                text, encoding="utf-8", newline="\n"
            )
    print(f"wrote {len(SCREENS) * len(WIDTHS)} captures to {OUT}")


if __name__ == "__main__":
    main()
