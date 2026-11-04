# G6 evidence: UPGRADING walked from a 0.5.2 install with keys in the old layout

Date: 2026-11-02. Base: `5085226` (branch `work/builder/n3-b9-upgrading-walk`).
Scope item: SCOPE_0.6.0 section 5 (G6) - "UPGRADING walked from a 0.5.2 install
with keys in the old layout". A full gate was running on this machine, so no
test suite was run; the evidence is the walked commands themselves, run against
the tree at `F:/RACT_wt/n3_b9upg/src` via `PYTHONPATH`.

## Verdict

**UPGRADING.md walks clean from the old layout after one docs fix.** The first
walk found one gap (the session-store move was undocumented; finding 1 below);
`docs/UPGRADING.md` was amended (docs only, no `src/ract` change, so no digest
relock) and the re-walk of every step in order finished with every command at
exit 0 and an empty `git status --short`.

## State isolation (hard safety rule)

Every `python -m ract.cli` run had the user state redirected into the temp dir
with the env overrides the code honors (`src/ract/core/keys.py:109`
`_default_state_dir` and `src/ract/policy/__init__.py:16` `config_dir`):

- `LOCALAPPDATA=C:/Users/you/AppData/Local/Temp/n3_upgwalk_rewalk/localappdata`
  (the user state dir, `%LOCALAPPDATA%\ract`: per-repo keys at
  `keys/<repo digest>/{sandbox,alm}/...`)
- `APPDATA=C:/Users/you/AppData/Local/Temp/n3_upgwalk_rewalk/appdata`
  (the user config dir, `%APPDATA%\ract`: `operator/recompile.key`)
- `PYTHONPATH=F:/RACT_wt/n3_b9upg/src` (the branch's tree)
- all `RACT_*` variables stripped (same hygiene as
  `tests/integration/test_upgrade_from_v052.py`)

No run could touch the real `%APPDATA%\ract` or `%LOCALAPPDATA%\ract`; nothing
was written outside the temp dir. The main checkout was not touched;
all work happened in a dedicated worktree on a separate drive.

## What the old layout is (from the migration code)

- Sessions: `.ract_sessions/<id>.json` in the project
  (`src/ract/session_store.py:65` `OLD_DEFAULT_DIR`, B-079). New:
  `.ract/sessions/` with a one-time copy and a `.moved-from-ract_sessions` mark
  (`copy_old_sessions`, notice printed by `src/ract/cli.py:4226`).
- Intent-recompile key: `.ract/operator.key` in the project; new place is the
  user config dir `operator/recompile.key` (`src/ract/key_paths.py:37`), still
  read from the old place with a stderr warning this release
  (`src/ract/core/intent_recompile.py:119`).
- Per-run sandbox and ALM keys: `.ract/sandbox/archive/<run_id>.key` and
  `.ract/alm/archive/<run_id>.key` (`src/ract/security/keys.py:129`,
  `src/ract/security/alm_verifier_key.py:127`); new place is the user state dir
  `keys/<repo digest>/{sandbox,alm}/archive/<run_id>.key`
  (`src/ract/key_paths.py:28`). `ract policy migrate-keys` moves them
  (`src/ract/key_paths.py:129`), naming anything it leaves, and overwrites
  nothing.

## Fabricated 0.5.2-era state (setup, not a doc step)

Temp dir `C:/Users/you/AppData/Local/Temp/n3_upgwalk{,_rewalk}/ws`, a fresh
git repository:

- commit `init`: `src/calc.py` (buggy `add`), `ract.yaml` (a v0.5.2-style
  config: `manager_provider: local`, `local_http` provider on an unroutable
  port, `max_retries: 0`), `prompts/manager.txt`.
- commit `rootact step 1: fix add`: the source fix plus
  `.ract/gravity_index.json`, tracked, as a v0.5.2 step commit left it. The
  worktree copy of `gravity_index.json` was then removed, because this branch
  does not maintain it - matching UPGRADING.md's "git status shows it as
  deleted" line.
- untracked old-layout state, as v0.5.2 left it:
  - `.ract_sessions/s-old.json` - a v0.5.2 session file
    (`{"intent": "fix add", "plan": {"assumption": "fix add", "confidence":
    0.85, "steps": []}, "artifacts": {}, "outcomes": []}`)
  - `.ract/operator.key` - 32 random bytes (the raw recompile key 0.5.2 kept)
  - `.ract/sandbox/archive/a1b2....key` and `.ract/alm/archive/a1b2....key` -
    real PEM Ed25519 private keys (generated with `cryptography`), run id
    `a1b2c3d4e5b6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2`

Initial `git status --short`: ` D .ract/gravity_index.json` plus untracked
`.ract/alm/`, `.ract/operator.key`, `.ract/sandbox/`, `.ract_sessions/` -
exactly the situation the "From 0.5.2" section addresses.

## First walk: findings

Step 1 (`ract doctor`), step 2 (`git log --oneline -3`), step 3
(`git rm --cached -r .ract` + `.gitignore` + commit) and step 4
(`ract policy migrate-keys`) all behaved as documented: doctor exited 8/8 with
code 0; the step commit was visible; after the untrack, `.ract/` no longer
appeared in `git status`; migrate-keys moved all three keys (operator key to
`%APPDATA%\ract\operator\recompile.key`, sandbox and ALM keys to
`%LOCALAPPDATA%\ract\keys\<digest>\{sandbox,alm}\archive\...`), exit 0, old
places empty, a second run said "nothing to move: no key is kept inside this
project". The "still read with a warning on stderr" claim was confirmed
verbatim:

```
warning: read a key from .ract\sandbox\archive\a1b2....key, inside the project;
`ract policy migrate-keys` moves it out (the old place stops being read after
this release)
```

The "overwrites nothing" claim was confirmed by placing a different key at
`.ract/operator.key` after the move: migrate-keys answered
`left ...: <target> already holds another key` and exited 1. The moved sandbox
key still loads via `SandboxKey.load_archived` from the user state dir.

**Finding 1 (the only gap).** The B-079 session-store move - sessions leave
`.ract_sessions/` for `.ract/sessions/` with a one-time copy and a stderr
notice - appeared nowhere in the "From 0.5.2" section. The old doc's "What to
run" listed steps 1-4 with no session step, and "What changes" had no sessions
bullet. An operator who followed the old doc was never told the copy happens
on the first `ract session` use, and was left with `?? .ract_sessions/` in
`git status` after step 3 with no guidance (the first walk observed exactly
that line). Fixed in `docs/UPGRADING.md`:

- "What changes": new bullet "Sessions move into the state folder." (now line
  82), after the "Keys leave the project" bullet.
- "What to run": new step 4 "Let the sessions move, then drop the old folder"
  (now line 107); the key step is renumbered to 5 (line 112).
- "What carries over": the Sessions bullet now cross-references the move.

## Re-walk of the amended doc (clean)

Fresh fabrication in `n3_upgwalk_rewalk`, same recipe. Full transcript
(`rewalk.log` in the temp dir); every command exited 0:

1. `python -m ract.cli doctor` - 8/8 checks PASS, exit 0.
2. `git log --oneline -3` - shows `rootact step 1: fix add`; kept, as the doc
   allows.
3. `git rm --cached -r .ract` (only `gravity_index.json` was tracked),
   `.gitignore` with `.ract/`, commit; `git status --short` then showed only
   `?? .ract_sessions/`.
4. `python -m ract.cli session list` -
   `ract: sessions are now kept in .ract\sessions; copied 1 from
   .ract_sessions, which is left as it was and can be removed.` then `s-old`;
   `.ract/sessions/` holds `s-old.json` and the `.moved-from-ract_sessions`
   mark; the old folder still held its copy. `rm -rf .ract_sessions` per the
   new step; `git status --short` empty.
5. `python -m ract.cli policy migrate-keys` -
   `moved ... .ract\operator.key to ...\appdata\ract\operator\recompile.key`
   and both run keys to
   `...\localappdata\ract\keys\953f64a7c5437911\{sandbox,alm}\archive\...`,
   exit 0. `.ract/` then held only the sessions; a second migrate-keys run
   printed "nothing to move" with exit 0.

Final state: `git status --short` is empty; `git log --oneline -3` is
`Stop tracking the RACT state folder` / `rootact step 1: fix add` / `init`;
sessions live in `.ract/sessions/`; keys live in the redirected user config
and state dirs.

## Notes

- The legacy-key warning and the post-move key load are not UPGRADING.md
  steps; they were verified with module-level probes (quoted above) because no
  single CLI verb exercises them without a fabricated run directory.
- `ract doctor` reports "no operator key on this machine" because it looks in
  the (redirected) user config dir, not at the legacy `.ract/operator.key`;
  that matches the doc, which says the old place is read with a warning only
  when a key is actually read.
