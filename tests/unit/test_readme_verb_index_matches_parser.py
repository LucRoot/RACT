"""README's CLI Verb Index tracks :data:`VERB_DESCRIPTIONS` (Lens A M8).

v0.5.1 wiring module_10: the README verb list drifted 4 releases
behind the parser. This gate parses the auto-checked block between
``<!-- BEGIN VERB INDEX -->`` and ``<!-- END VERB INDEX -->`` in
README.md and asserts every entry matches
:data:`ract.cli_help.VERB_DESCRIPTIONS`. Editing one side without
the other fails CI.
"""

from __future__ import annotations

import re
from pathlib import Path

from ract.cli import CLI_VERBS
from ract.cli_help import VERB_DESCRIPTIONS

README = Path(__file__).resolve().parent.parent.parent / "README.md"

BEGIN = "<!-- BEGIN VERB INDEX"
END = "<!-- END VERB INDEX -->"

# Extract lines like: - `ract verbname` — description text.
_LINE_RE = re.compile(r"^-\s+`ract\s+([\w-]+)`\s+[—-]\s+(.+?)\s*$")


def _readme_verb_map() -> dict[str, str]:
    text = README.read_text(encoding="utf-8")
    assert BEGIN in text, "README missing BEGIN VERB INDEX marker"
    assert END in text, "README missing END VERB INDEX marker"
    block = text.split(BEGIN, 1)[1].split(END, 1)[0]
    verbs: dict[str, str] = {}
    for line in block.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        verbs[m.group(1)] = m.group(2)
    return verbs


def test_readme_verb_index_matches_verb_descriptions() -> None:
    """Every README verb entry matches :data:`VERB_DESCRIPTIONS`."""
    readme_verbs = _readme_verb_map()
    for verb, desc in readme_verbs.items():
        assert verb in VERB_DESCRIPTIONS, (
            f"README lists verb {verb!r} that has no VERB_DESCRIPTIONS entry"
        )
        expected = VERB_DESCRIPTIONS[verb]
        assert desc == expected, (
            f"README verb {verb!r} description drift:\n"
            f"  README: {desc!r}\n"
            f"  VERB_DESCRIPTIONS: {expected!r}"
        )


def test_readme_verb_index_covers_every_cli_verb() -> None:
    """Every entry in CLI_VERBS also appears in the README index."""
    readme_verbs = _readme_verb_map()
    missing = [v for v in CLI_VERBS if v not in readme_verbs]
    assert not missing, (
        f"README CLI Verb Index missing verbs: {missing}\n"
        "Regenerate the block between BEGIN/END VERB INDEX markers "
        "from ract.cli_help.VERB_DESCRIPTIONS."
    )


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A M8 regression)
