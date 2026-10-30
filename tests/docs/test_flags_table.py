"""Package S: every flag the parsers accept is in docs/FLAGS.md, and no user doc names a
flag the parser lacks. The allowlist names each exception and why it is one."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from docs import flags_table  # noqa: E402

USER_DOCS = (
    "README.md",
    "docs/QUICKSTART.md",
    "docs/PROVIDER_SETUP.md",
    "docs/UPGRADING.md",
    "docs/SESSION_GUIDE.md",
    "docs/DOC_COMMANDS.md",
    "docs/EVENTS_SESSION.md",
    "docs/EGRESS.md",
    "docs/PROVENANCE.md",
    "docs/THREAT_MODEL.md",
    "docs/troubleshooting.md",
    "docs/cli_json_cheat_sheet.md",
)

# Each exception: the flag, and the reason it is not a flag of ract's parser.
ALLOWLIST = {
    "--local": "scripts/install.sh option (the install script, not a ract parser)",
    "--venv": "scripts/install.sh option (the install script, not a ract parser)",
    "--host": "llama-server option named in docs/PROVIDER_SETUP.md (not a ract flag)",
    "--port": "llama-server option named in docs/PROVIDER_SETUP.md (not a ract flag)",
    "--cached": "git option in docs/UPGRADING.md (not a ract flag)",
    "--oneline": "git option in docs/UPGRADING.md (not a ract flag)",
    "--no-disk-check": "parser of 'ract memory verify-consistency'; its --help prints the parent help (handoff to the BUILDER: src/ract/memory/cli_memory.py)",
    "--json-schema": "named in docs/EVENTS_SESSION.md; defined in src/ract/core/predicate.py, not on a verb's --help (handoff)",
    "--strict": "named in docs/PROVENANCE.md; defined in src/ract/core/provenance.py, not on a verb's --help (handoff)",
    "--allow-unenforced-sandbox": "designed in docs/THREAT_MODEL.md; defined in src/ract/executor/loop.py, not on a verb's --help (handoff)",
    "--contains": "executor internal named in docs/THREAT_MODEL.md (handoff: say it is internal)",
    "--soft": "executor internal named in docs/THREAT_MODEL.md (handoff: say it is internal)",
    "--force-overwrite": "designed, not built (docs/THREAT_MODEL.md says so)",
    "--by": "the session command `/cost --by purpose|step|role` (V7-08), not a ract parser flag",
}
# Flags that appear in help prose, not as options.
PROSE_ONLY = {"--cold"}


def test_the_committed_flags_table_is_fresh():
    committed = (ROOT / "docs" / "FLAGS.md").read_text(encoding="utf-8")
    assert committed == flags_table.render(flags_table.collect())


def test_every_option_in_the_help_text_is_in_the_table():
    from ract import cli

    table = (ROOT / "docs" / "FLAGS.md").read_text(encoding="utf-8")
    seen: set[str] = set()
    for verb in sorted(cli.CLI_VERBS):
        text = flags_table._help_text([verb])
        seen.update(re.findall(r"(--[a-zA-Z][\w-]*)", text))
        for sub in flags_table._subcommands(text):
            seen.update(
                re.findall(r"(--[a-zA-Z][\w-]*)", flags_table._help_text([verb, sub]))
            )
    missing = sorted(flag for flag in seen - PROSE_ONLY if f"`{flag}`" not in table)
    assert missing == [], missing


@pytest.mark.parametrize("doc", USER_DOCS)
def test_a_user_doc_names_only_flags_the_parser_accepts(doc):
    known = {flag for flag, _, _ in flags_table.collect()}
    path = ROOT / doc
    if not path.is_file():
        pytest.skip(f"{doc} is not in this tree")
    named = set(
        re.findall(
            r"(?<![\w-])(--[a-z][a-z0-9-]+)",
            path.read_text(encoding="utf-8", errors="replace"),
        )
    )
    unknown = sorted(
        flag for flag in named if flag not in known and flag not in ALLOWLIST
    )
    assert unknown == [], f"{doc} names flags the parser lacks: {unknown}"


def test_the_allowlist_only_names_flags_the_docs_actually_mention():
    mentioned: set[str] = set()
    for doc in USER_DOCS:
        path = ROOT / doc
        if path.is_file():
            mentioned.update(
                re.findall(
                    r"(?<![\w-])(--[a-z][a-z0-9-]+)",
                    path.read_text(encoding="utf-8", errors="replace"),
                )
            )
    stale = sorted(flag for flag in ALLOWLIST if flag not in mentioned)
    assert stale == [], f"allowlist entries no doc names any more: {stale}"
