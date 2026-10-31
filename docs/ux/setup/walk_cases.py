"""B-160 walk cases for `ract setup` on fake servers (run under a QUIET.md of its own).

Usage: python walk_cases.py <repo_src_root> <out_dir> <case> [cols]
Cases: hosted_key_set, preset, second_endpoint. Each runs in a temporary folder with a
throwaway HOME. The key is a throwaway value and appears only in the environment; the
walk checks that it is absent from every record it writes.

Needs the B-160d override (RACT_PRESET_BASE_URL) to point a hosted preset at the fake
server. Until work/builder/B-160d is landed, only the local and unreachable cases run.
"""

import sys
import tempfile
from pathlib import Path

REPO = Path(sys.argv[1])
sys.path.insert(0, str(REPO))

from tests.fixtures.fake_model_server import FakeModelServer  # noqa: E402
from tests.ux.run_baseline import _env  # noqa: E402
from tests.ux.terminal_driver import spawn  # noqa: E402

OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
CASE = sys.argv[3]
COLS = int(sys.argv[4]) if len(sys.argv) > 4 else 80
KEY = "sk-throwaway-hosted-0002"
RACT = Path(sys.executable).with_name("ract.exe")

# (label, answers) per case. Prompts are answered in order, one at a time.
ANSWERS = {
    # Enter at the address prompt (B-160a), cloud, provider 6 (openai), then git init declined.
    "hosted_key_set": ["", "c", "6", "n"],
    "preset": ["", "c", "6", "n"],
    # Second endpoint: setup again with a local server, then the reconfigure diff.
    "second_endpoint": ["y", "", "n"],
}

if CASE not in ANSWERS:
    raise SystemExit(f"unknown case {CASE!r}; cases: {', '.join(ANSWERS)}")

scenario = "j1_no_tools"
with tempfile.TemporaryDirectory() as tmp, FakeModelServer(scenario) as server:
    home = Path(tmp) / "home"
    home.mkdir()
    ws = Path(tmp) / "proj"
    ws.mkdir()
    env = {**_env(), "HOME": str(home), "USERPROFILE": str(home)}
    # Loopback only: a bare or unnamed preset URL would otherwise reach the real provider (BUILDER L-379).
    env["RACT_NO_NETWORK"] = "1"
    if CASE in ("hosted_key_set", "preset"):
        env["RACT_PRESET_BASE_URL"] = f"openai={server.base_url}"
        env["OPENAI_API_KEY"] = KEY
        if CASE == "hosted_key_set":
            # Pair the throwaway key with the fake server only, so it is sent there and nowhere else.
            hostport = server.base_url.split("//", 1)[1].split("/", 1)[0]
            env["RACT_KEY_HOSTS"] = f"OPENAI_API_KEY={hostport}"
    else:
        env["RACT_BASE_URL"] = server.base_url
    with spawn([str(RACT), "setup"], cwd=str(ws), env=env, cols=COLS, rows=40) as session:
        session.wait_quiet(4.0, timeout=60.0)
        for answer in ANSWERS[CASE]:
            session.wait_quiet(2.0, timeout=60.0)
            session.send_line(answer)
        session.wait_quiet(6.0, timeout=60.0)
        rec = session.close()
    text = rec.plain
    (OUT / f"{CASE}_{COLS}.txt").write_text(text, encoding="utf-8")
    written = {p.name: p.read_text(encoding="utf-8") for p in ws.iterdir() if p.is_file()}
    leaked = KEY in text or any(KEY in body for body in written.values())
    print(CASE, COLS, "requests", len(server.chat_requests), "files", sorted(written), "key leaked:", leaked)
