"""Package 5 (handoff 7): a harness that raises prints one sentence on stderr, no traceback.

The enricher returns the error as a Rooted value, but its logger used logger.exception, which
wrote the full traceback to stderr for a locked file (windows_files.md, locked-file case, headless
path). The check runs in a subprocess with no logging configured, the same state as the CLI.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT = """
from ract.harness_report_enricher import enrich_harness_run

class Raising:
    def run(self, intent, **kwargs):
        raise RuntimeError("could not snapshot the working tree: open src/calc.py: Permission denied")

result = enrich_harness_run(Raising(), "add a greeting")
print("ERROR=" + str(result.error))
"""


def test_a_raising_harness_prints_no_traceback_on_stderr():
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=Path(__file__).resolve().parent.parent, timeout=120,
    )
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "could not snapshot" in proc.stdout
