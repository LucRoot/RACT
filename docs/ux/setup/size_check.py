"""B-163 check (G-260): is the pseudo-terminal really 60 columns, and does `ract setup` print unwrapped lines?

Usage: python size_check.py <repo_root> <out_dir>
1. A child Python prints the terminal size it sees and COLUMNS, under cols=60.
2. `ract setup` runs once against a fake server at the same width; the record's first line is the
   size the child saw, then every line longer than 60 characters is listed with its length.
Throwaway HOME and folder; no key is used.
"""

import os
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
RACT = Path(sys.executable).with_name("ract.exe")
PROBE = "import os,shutil;print('SIZE', os.get_terminal_size(), 'COLUMNS', os.environ.get('COLUMNS'), 'shutil', shutil.get_terminal_size())"

with tempfile.TemporaryDirectory() as tmp, FakeModelServer("j1_no_tools") as server:
    home = Path(tmp) / "home"
    home.mkdir()
    ws = Path(tmp) / "proj"
    ws.mkdir()
    env = {**_env(), "HOME": str(home), "USERPROFILE": str(home), "PYTHONPATH": str(REPO / "src")}
    env_probe = {**env, "COLUMNS": "60"}
    with spawn([sys.executable, "-c", PROBE], cwd=str(ws), env=env_probe, cols=60, rows=40) as s:
        s.wait_quiet(2.0, timeout=60.0)
        probe = s.close().plain
    env_setup = {**env, "RACT_BASE_URL": server.base_url, "COLUMNS": "60"}
    with spawn([str(RACT), "setup"], cwd=str(ws), env=env_setup, cols=60, rows=40) as s:
        s.wait_quiet(4.0, timeout=60.0)
        s.send_line("y")
        s.wait_quiet(4.0, timeout=60.0)
        s.send_line("n")
        s.wait_quiet(4.0, timeout=60.0)
        setup = s.close().plain
    long_lines = [(i + 1, len(line)) for i, line in enumerate(setup.splitlines()) if len(line) > 60]
    report = [probe.strip(), "setup record, lines longer than 60:"] + [f"  line {n}: {k} characters" for n, k in long_lines]
    (OUT / "size_check_60.txt").write_text("\n".join(report) + "\n\n" + setup, encoding="utf-8")
    print("\n".join(report))
