"""B-160 error and reconfigure walks on fake servers (run under a QUIET.md of its own).

Usage: python walk_errors.py <repo_root_windows_path> <out_dir> <scenario_json_path> <case> [cols]
Cases:
  wrong_key    preset openai at a fake server that answers 401 and echoes the key; key paired with that host
  unreachable  preset openai at a closed loopback port
  add_provider a first setup, then `ract setup --add-provider` against the same fake server
  reconfigure  a first setup against a fake server, then `ract setup --reconfigure` with a second
               local address; the draft and the differences are recorded
RACT_NO_NETWORK=1 in every case; PYTHONPATH pinned to the repo root's src; the throwaway key appears
in no record and no written file.
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
SCENARIO = sys.argv[3]
CASE = sys.argv[4]
COLS = int(sys.argv[5]) if len(sys.argv) > 5 else 80
KEY = "sk-" + "throwaway-error-0003"  # split: the source-tree scan sees no key shape
RACT = Path(sys.executable).with_name("ract.exe")


def run(argv, cwd, env, answers):
    with spawn(argv, cwd=str(cwd), env=env, cols=COLS, rows=40) as session:
        session.wait_quiet(4.0, timeout=60.0)
        for answer in answers:
            session.wait_quiet(2.0, timeout=60.0)
            session.send_line(answer)
        session.wait_quiet(6.0, timeout=60.0)
        return session.close().plain


with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp) / "home"
    home.mkdir()
    ws = Path(tmp) / "proj"
    ws.mkdir()
    base = {**_env(), "HOME": str(home), "USERPROFILE": str(home), "RACT_NO_NETWORK": "1", "OPENAI_API_KEY": KEY}
    if CASE == "wrong_key":
        with FakeModelServer(SCENARIO) as server:
            hostport = server.base_url.split("//", 1)[1].split("/", 1)[0]
            env = {**base, "RACT_PRESET_BASE_URL": f"openai={server.base_url}", "RACT_KEY_HOSTS": f"OPENAI_API_KEY={hostport}"}
            text = run([str(RACT), "setup"], ws, env, ["", "c", "6", "n"])
            written = {str(p.relative_to(ws)): p.read_text(encoding="utf-8") for p in ws.rglob("*") if p.is_file()}
            (OUT / f"wrong_key_setup_{COLS}.txt").write_text(text, encoding="utf-8")
            print("wrong_key requests", len(server.chat_requests), "files", sorted(written), "key leaked:", KEY in text or any(KEY in b for b in written.values()))
    elif CASE == "unreachable":
        env = {**base, "RACT_PRESET_BASE_URL": "openai=http://127.0.0.1:9/v1"}
        text = run([str(RACT), "setup"], ws, env, ["", "c", "6", "n"])
        written = {str(p.relative_to(ws)): p.read_text(encoding="utf-8") for p in ws.rglob("*") if p.is_file()}
        (OUT / f"unreachable_setup_{COLS}.txt").write_text(text, encoding="utf-8")
        print("unreachable files", sorted(written), "key leaked:", KEY in text or any(KEY in b for b in written.values()))
    elif CASE == "reconfigure":
        with FakeModelServer("j1_no_tools") as server:
            env = {**base, "RACT_BASE_URL": server.base_url}
            first = run([str(RACT), "setup"], ws, env, ["y", "n"])
            env2 = {**base, "RACT_BASE_URL": server.base_url}
            second = run([str(RACT), "setup", "--reconfigure"], ws, env2, ["y", "n"])
            drafts = sorted(p.name for p in ws.iterdir() if p.is_file())
            (OUT / f"reconfigure_{COLS}.txt").write_text(first + "\n----- reconfigure -----\n" + second, encoding="utf-8")
            print("reconfigure files", drafts, "requests", len(server.chat_requests), "key leaked:", KEY in first + second)
    elif CASE == "add_provider":
        with FakeModelServer("j1_no_tools") as server:
            env = {**base, "RACT_BASE_URL": server.base_url}
            first = run([str(RACT), "setup"], ws, env, ["y", "n"])
            second = run([str(RACT), "setup", "--add-provider"], ws, env, ["y", "n"])
            (OUT / f"add_provider_{COLS}.txt").write_text(first + "
----- add-provider -----
" + second, encoding="utf-8")
            print("add_provider requests", len(server.chat_requests), "key leaked:", KEY in first + second)
    else:
        raise SystemExit(f"unknown case {CASE!r}")
