# Cold-reader pass (ux-gap, package E)

A fresh virtual environment, an empty directory, and the README quickstart followed as written.
The fake model server stood in for the model where a run needs one (the README's `ract run`
lines point at a server that is not running; `ract.yaml` was pointed at the fake server for
those lines only). Commands were run with `ract.exe` from the new environment, RACT 0.5.2.

| # | Where the doc and the behavior differ | Captured output | Status |
|---|---|---|---|
| 1 | README: `ract fence inspect --file src/hello.py`. `ract init --template python-package` creates `src/<package>/__init__.py`, not `src/hello.py`. | file missing (see 3) | fixed in README: `src/<package>/__init__.py` |
| 2 | README: `ract provenance verify src/hello.py`. Same missing file. | - | fixed in README: `<file>` |
| 3 | `ract fence inspect --file <missing file>` exits 0 and prints an empty brief with `Confidence: 0.0`. It does not say the file is missing. | `Chesterton's Fence brief ... Confidence: 0.0 ... coldws` | handoff: `cli.py` fence verb (BUILDER). Change: exit 2 with `no file named src/hello.py in this project; check the path` |
| 4 | README: `ract memory init` builds three indexes. The semantic one fails without embedding weights; the command still exits 0 and the README does not say so. | `semantic_builder: embed batch of 1 chunks failed ... dropped` | fixed in README: a paragraph under the run examples names `RACT_EMBED_MODEL_ROOT` and `RACT_EMBED_ONLINE=1` |
| 5 | `ract memory init` also prints `LspClient.references_of: LSP call failed for test_version` on a fresh project. Internal detail on the terminal (standard 12). | the line, before the index lines | handoff: the LSP and semantic builders (BUILDER). Change: log to the run's log file; print only `memory init: semantic index skipped (no embedding weights)` |
| 6 | `ract doctor` prints `Provenance: files written by ract runs are not signed with a Rootknot in this release.` (standard 12). | the line in the doctor footer | handoff: `src/ract/cli.py:1681` (BUILDER). Change: the plain sentence used in the session notice |
| 7 | README: `ract run "..." --config ract.yaml` (no `--dry-run`) on a fresh project stops with `Novelty budget exhausted`, and the generic hint says `run ract doctor --check-providers`, which does not match the cause. | `failed: Novelty budget exhausted: new_file (3pts) ...`, then the generic hint | README note added under the run examples (the budget and `--allow-novelty-overrun`). The wrong hint is a handoff: the budget error needs its own hint (`src/ract/cli.py`, BUILDER) |
| 8 | README: `ract run ... --dry-run` prints the plan with a confidence and a quality score. Matches. | `▸ confidence: 0.85`, `▸ quality score: 0.637` | no difference |
| 9 | `ract --version` prints `RACT 0.5.2`. Matches the README's version statements. | `RACT 0.5.2` | no difference |
| 10 | `ract init` prints `initialized python-package project at ...` and lists the files. Matches. | the file list | no difference |
| 11 | Interactive `ract` at 80 and 60 columns: covered by `docs/ux/width_a/` and `docs/ux/c_journeys/`. | captures | no difference after package A |

## Check of the session guide

`docs/SESSION_GUIDE.md` said the checklist, approval and `/help` did not fold at 60 columns, and
that `/resume` wrapped mid-word at 80. Both are false now (`docs/ux/ux_bar_check.md`,
`docs/ux/c_journeys/resume_80.txt`). The guide's known-issues section is updated. The guide's
samples are unchanged (no sample shows output a fix changed). The generator
(`scratchpad/build_guide.py`) is outside the repository, so its known-issues text was
edited in `docs/SESSION_GUIDE.md` directly; the handoff is to move the generator into the repository.

## Found by the cold reader in the session (fixed in lane)

- The resume offer on the start screen printed `....` after a cut request. Fixed in `src/ract/repl.py`
  (`_resume_offer`); red then green in `tests/test_ux_gap_c.py`.
