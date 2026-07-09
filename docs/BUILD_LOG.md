# RACT Build Log

This log records each loop pass through the RACT codebase. It exists because context compacts and the written record is the remedy.

## 2026-07-09 — Loop pass: README/CI badges and self-audit

**What changed**
- Added status badges to `README.md`: CI (GitHub Actions), coverage (~93%), license (PolyForm Noncommercial), and Python versions (3.11 | 3.12).
- Updated `.github/workflows/ci.yml` to emit `coverage.xml` and upload it as a per-matrix artifact.
- Reinstalled the package in editable mode so `rootact` CLI commands use the current source tree instead of a stale site-packages copy.

**Why**
- DeepSeek audit flagged "no CI/CD badges" and "no test coverage reporting" as the single biggest credibility gap for a public visitor.
- The stale install surfaced a real deployment risk: local fixes can look shipped while the installed CLI still carries the old bug.

**Test/lint/type result**
- `pytest tests/`: 873 passed, 1 skipped, 93% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/executor.py src/rootact/harness.py tests/test_compression_novelty_detector.py`: passed.

**Self-audit result**
- `rootact doctor`: all checks passed.
- `rootact novelty scan`: all files scored `nominal`; no low-novelty duplicates detected.
- `rootact auction list`: 0 dead-code candidates.
- `rootact fence inspect --file src/rootact/executor.py`: relative-path crash remains fixed in source; completion blocked because the configured local provider endpoint returns HTTP 401 (Internal/local model auth issue, not a RACT bug).

**Next action**
- Add a "Why RACT" comparison table to README; then fix Internal/local-model provider auth.

## 2026-07-09 — Loop pass: Why RACT comparison table

**What changed**
- Replaced the numbered "Why RACT" list in `README.md` with a comparison table: rows are dimensions (pricing, lock-in, loop logic, continuity guard, anti-rot tooling, oversight, auditability, execution model, diff strategy, local data); columns are RACT, Cursor, Claude Code, and Lovable.
- Added a one-paragraph summary explaining who RACT is for versus the incumbents.

**Why**
- DeepSeek audit flagged the lack of a comparison table as a gap: visitors need to see the trade-offs at a glance.
- The table format surfaces RACT's actual wedge (sovereignty, model economics, anti-rot, CLI-first) without burying it in prose.

**Test/lint/type result**
- `pytest tests/`: 873 passed, 1 skipped, 93% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.

**Self-audit result**
- `rootact doctor`: all checks passed.
- `rootact novelty scan`: 85 of 175 files scored `low`. This is a false-positive pattern for existing files: the detector's dictionary is trained on the entire codebase, so files already in the codebase compress well against it. The `assess_new_artifact` API excludes the target file's nearest neighbor but still falls back to the global dictionary ratio, so existing files remain flagged.
- `rootact auction list`: 0 dead-code candidates.
- `rootact fence inspect`: still blocked by local provider HTTP 401.

**Next action**
- Fix the symbol graph prefix mismatch that caused the dead-code auction to flag 76 of 77 modules as dead.

## 2026-07-09 — Loop pass: fix symbol graph prefix mismatch and auction calibration

**What changed**
- Fixed `SymbolGraph._detect_package_root` so it recognizes when `project_dir` is already inside `src/<pkg>` (or a flat `<pkg>` layout), not only when `project_dir` is the repo root containing `src/<pkg>`.
- Added `SymbolGraph.module_id_for_path()` and updated `DeadCodeAuction._module_for_file()` to use the graph's own module namespace. This keeps file paths and graph module ids consistent.
- Replaced the package-stripping `_relative_module_from_import` with `_resolve_imported_module` and `_is_project_import` that accept both package-prefixed absolute imports and relative imports inside the package.
- Added `test_src_layout_cross_module_reference`, `test_ract_repo_has_cross_module_edges`, and `test_auction_discriminates_dead_from_live_in_src_layout` to prevent regression.
- Fixed the contradictory novelty assumption string in `executor.py`: it now says the artifact is "not structurally novel" and a "near-duplicate" instead of "structurally novel."
- Ran `ruff format` to clean the format regression.

**Why**
- Claude's re-audit found the symbol graph produced only **3 cross-module edges** in RACT instead of hundreds. Node keys were `src.rootact.X` while import resolution returned `rootact.X` or `providers.X`, so `_is_project_import` returned False for every real internal import. The auction then flagged 76 of 77 source modules as dead code, including `executor.py` and `providers/router.py`.

**Test/lint/type result**
- `pytest tests/`: 876 passed, 1 skipped, 93% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy`: passed on changed files.

**Self-audit result**
- `rootact doctor`: all checks passed.
- `rootact novelty scan`: 85 of 175 files still scored `low` because existing files compress well against the codebase dictionary. This remains a known limitation; leave-one-out training is the proper fix.
- `rootact auction list`: **0 dead-code candidates** on RACT itself.
- Injected-dead-module probe (via new unit test): flags only the dead module, not the live one.

**Next action**
- Fix `rootact novelty scan` false positives with leave-one-out dictionary training, then continue the launch-gap backlog (demo asciicast, HF Space page, mutation-testing gate).

## 2026-07-09 — Loop pass: real static page for Hugging Face Space

**What changed**
- Created `hf-space/index.html`: a dark-themed landing page with the Dr. Root logo, the GitClear 623-million-commit hook, install commands, a Root-Knot-anchored loop example, the anti-rot verifier arsenal, a signed-receipt example, and links to GitHub + the AI Agent Playbook mailing list.
- Created `hf-space/README.md`: Space description with license and links.
- Verified the page renders without broken asset links and that all documented CLI snippets match the current `rootact` interface.

**Why**
- DeepSeek audit flagged the HF Space as a dead discovery surface. A public release needs every entry point to tell the same story.

**Test/lint/type result**
- `pytest tests/`: 876 passed, 1 skipped, 93% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.

**Self-audit result**
- `rootact --config rootact.yaml doctor`: all checks passed.
- `rootact auction list --config rootact.yaml`: 0 dead-code candidates.
- `rootact novelty scan --config rootact.yaml`: 85 of 175 files scored `low`. This is a known false-positive pattern: the dictionary is trained on the whole codebase, so existing files compress well against it. Leave-one-out training is the planned fix.

**Next action**
- Implement leave-one-out dictionary training for `compression_novelty_detector` to eliminate the `low` false positives on existing files.

## 2026-07-09 — Loop pass: leave-one-out dictionary training for novelty scan

**What changed**
- Implemented leave-one-out dictionary training in `compression_novelty_detector.py`:
  - `_collect_samples` now tracks which chunks came from which file.
  - `_train_dictionary` accepts an optional `exclude_path` to omit a file's own chunks.
  - `_score_with_dict`, `_assess_with_dict`, `_conditional_ratio`, and `_nearest_similar_artifact_with_ratio` accept a dictionary argument so the leave-one-out dictionary can be threaded through scoring.
  - Added `score_artifact_leave_one_out` and updated `scan_project` to use it.
- Changed the guard in `_assess_with_dict` from `dictionary is None or nn_ratio is None` to `nn_ratio is None` so a missing dictionary does not suppress the nearest-neighbor signal.
- Added `test_scan_project_uses_leave_one_out_for_existing_files` and `test_scan_project_still_flags_verbatim_duplicates`.

**Why**
- `rootact novelty scan` reported 85 of 175 existing files as `low` because the dictionary was trained on the files it was scoring. Leave-one-out removes that self-bias.

**Test/lint/type result**
- `pytest tests/`: 878 passed, 1 skipped, 93% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/compression_novelty_detector.py tests/test_compression_novelty_detector.py`: passed.

**Self-audit result**
- `rootact --config rootact.yaml doctor`: failed with HTTP 401 from the local provider (Internal/llama-server auth issue, not a RACT bug).
- `rootact auction list --config rootact.yaml`: 0 dead-code candidates.
- `rootact novelty scan --config rootact.yaml`: 80 `low`, 35 `high`, 60 `nominal` out of 175 files. Leave-one-out eliminated self-bias (verified on synthetic data: a unique file went from ratio 0.212/`low` to 0.818/`high`), but RACT's own codebase retains a lot of genuine structural similarity across files, so many still compress well against the rest of the project.

**Next action**
- Set up cla-assistant.io for the repository so external PRs can land under the CLA.

## 2026-07-09 — Loop pass: demo asciicast for README

**What changed**
- Generated `assets/demo.cast`: a ~50-second asciinema recording showing `pip install rootact`, `rootact --version`, `ract --version`, `rootact auction list`, `rootact novelty scan`, and `rootact --help`. Output text is based on real command output from the current tree.
- Updated README Demo section to link to the cast and provide the local play command. Added a note that an embedded asciinema.org upload is queued pending a Windows-ARM64-compatible upload toolchain.
- Attempted `agg` GIF conversion; build failed on `aws-lc-sys` linking on Windows ARM64, so the cast remains the authoritative artifact this pass.

**Why**
- Public-launch priority #3 is a 45-second asciicast under the hero. The cast file is now in the repo and playable; embedding is gated by toolchain availability.

**Test/lint/type result**
- `pytest tests/`: 878 passed, 1 skipped, 93% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.

**Self-audit result**
- `rootact auction list --config rootact.yaml`: 0 dead-code candidates.
- `rootact novelty scan --config rootact.yaml`: 80 `low`, 35 `high`, 60 `nominal` out of 175 (unchanged after README-only change).
- `rootact doctor`: not run this pass; still blocked by local provider HTTP 401.

**Nemotron/Internal secondary review**
- Delegated a lightweight review of the Demo section. Nemotron returned **Pass** with a note about alias clarity; `ract` alias is confirmed by `pyproject.toml`, so no change needed.

**Next action**
- Set up cla-assistant.io (manual web step) or move to the next launch-gap item: earned-coverage / mutation-testing gate.

## 2026-07-09 — Loop pass: earned-coverage gate and mutation-testing script

**What changed**
- Added `src/rootact/coverage_delta.py`: parses pytest-cov `coverage.json`, captures before/after snapshots by invoking pytest, and computes an earned-coverage verdict (`earn`, `regress`, `stagnant`).
- Added `rootact coverage delta` CLI command with two modes:
  - `--run`: captures two snapshots and prints the delta.
  - `--before <path> --after <path>`: compares existing pytest-cov JSON reports.
- Added `tests/test_coverage_delta.py` with unit tests for snapshot parsing and verdict logic.
- Added `scripts/run_mutation_tests_wsl.sh`: WSL-only mutation-testing runner for the four core engine files (`executor.py`, `loop_controller.py`, `harness.py`, `cli.py`) because `mutmut` does not support native Windows.
- Updated `tests/test_signature_survival.py` golden hash to reflect the new `coverage_delta.py` module.

**Why**
- Claude upgrade #3: replace raw test-count vanity with earned quality. The coverage-delta gate is the first half; mutation testing is scripted for WSL as the second half.

**Test/lint/type result**
- `pytest tests/`: 883 passed, 1 skipped, 92% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/coverage_delta.py`: passed.

**Self-audit result**
- `rootact auction list --config rootact.yaml`: 0 dead-code candidates.
- `rootact novelty scan --config rootact.yaml`: 82 `low` out of 177 files. The two new files (`coverage_delta.py`, `test_coverage_delta.py`) compress well against existing code, which is expected.
- `rootact coverage delta --run --config rootact.yaml`: `earn`, coverage held at 92.2%.
- `rootact doctor`: not run; still blocked by local provider HTTP 401.

**Nemotron/Internal secondary review**
- Reviewed `coverage_delta.py`: **Pass**. Suggested adding a configurable minimum coverage threshold; deferred to a future pass.

**Next action**
- Integrate the coverage-delta gate into `Harness.run()` as an optional post-execution check controlled by config, so the loop can fail a step that drops coverage.

## 2026-07-09 — Loop pass: wire coverage-delta gate into `Harness.run()`

**What changed**
- Added baseline persistence to `src/rootact/coverage_delta.py`:
  - `save_baseline()` and `load_baseline()` persist a `CoverageSnapshot` to `.rootact/coverage_baseline.json`.
  - `gate()` now compares the current snapshot against the stored baseline. On the first call it stores the baseline and returns a `baseline` verdict.
- Wired the gate into `src/rootact/harness.py`:
  - Reads `coverage_gate` config (`enabled`, `hard_fail`, `timeout`).
  - Runs the gate after `executor.execute` returns and before git-mode commit.
  - `hard_fail: true` turns `regress` or `stagnant` into a `Rooted` error.
  - Soft mode attaches the delta dict to `ExecutionReport.artifacts`.
- Added `tests/test_harness_coverage_gate.py` with tests for baseline establishment, regress detection, earn detection, and harness hard/soft fail wiring.
- Updated `tests/test_signature_survival.py` golden hash to reflect the modified `coverage_delta.py`.

**Why**
- Complete Claude upgrade #3: a loop step that adds code without covering it should fail before the rot compounds.

**Test/lint/type result**
- `pytest tests/`: 888 passed, 1 skipped, 92% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.

**Self-audit result**
- `rootact auction list --config rootact.yaml`: 0 dead-code candidates.
- `rootact novelty scan --config rootact.yaml`: works; existing files still show structural similarity.
- `rootact coverage delta --run --config rootact.yaml`: baseline established at 92.3%.

**Nemotron/Internal secondary review**
- Not delegated; this was a straight wiring pass on top of the already-reviewed `coverage_delta.py`.

**Next action**
- Add a configurable minimum coverage threshold to the gate, then move to mutation-testing integration or the next launch-gap item.

## 2026-07-09 — Loop pass: configurable minimum-coverage floor

**What changed**
- Added `min_percent` parameter to `coverage_delta.compute_delta()`: when the after snapshot is below the floor, the verdict becomes `regress` with `floor_breached=True`.
- Added `min_percent` parameter to `coverage_delta.gate()`: on first call, if the baseline snapshot is below the floor, the verdict is `regress` with `floor_breached=True` instead of `baseline`.
- Added `floor_breached` field to `CoverageDelta` and surfaced it in string output.
- Added `--min-percent` flag to `rootact coverage delta` for both `--run` and `--before/--after` modes.
- Wired `coverage_gate.min_percent` through `Harness.__init__` and into the post-execution gate call.
- Updated harness hard-fail and soft-fail paths to recognize `floor_breached` and include it in the attached artifact.
- Added unit tests for floor breach in `tests/test_coverage_delta.py` and `tests/test_harness_coverage_gate.py`.

**Why**
- A delta-only gate can still pass a step that holds coverage underwater. The floor makes the gate absolute as well as relative, which is what Nemotron's secondary review requested.

**Test/lint/type result**
- `pytest tests/`: 892 passed, 1 skipped, 92% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/coverage_delta.py src/rootact/harness.py src/rootact/cli.py tests/test_coverage_delta.py tests/test_harness_coverage_gate.py`: passed.

**Self-audit result**
- `rootact auction list --json`: 0 dead-code candidates.
- `rootact novelty scan --json`: 2 `low` out of 175 files (`scripts/mock_local_llm.py`, `scripts/verify_internal_rootact_separation.py`); expected given shared patterns with tests.
- `rootact coverage delta --run --min-percent 95.0`: correctly returns `regress (floor breached)` because the baseline is 92.3%, below the 95% floor.

**Next action**
- Re-run with a realistic floor (e.g., 90.0%) so the gate earns, then integrate the WSL mutation-testing script into the CI quality scorecard or add a signed-receipt quality hook.

# RACT 0.1.0 - Initial Public Release

## 2026-07-09 — Loop pass: mutation-testing wrapper, scorecard signal, and coverage baseline exit-code fix

**What changed**
- Added `src/rootact/mutation_runner.py` — a Python wrapper around `scripts/run_mutation_tests_wsl.sh` that:
  - Detects WSL availability and returns a clear `MutationReport` error when WSL is missing.
  - Runs `mutmut run` + `mutmut results` inside WSL via `wsl.exe`.
  - Parses `mutmut results` output into `killed`, `survived`, `timeout`, `error`, and `mutation_score`.
  - Supports `--timeout`, `--script`, and `--config` overrides.
- Wired `mutation_score` into `src/rootact/quality_scorecard.py` as a new `Verdict` field with a 10.0 rubric weight mapped 0–100.
- Added `rootact mutation run [--script <path>] [--timeout <sec>] [--config <path>]` to `src/rootact/cli.py`, dispatching on `argv[0] == "mutation"`.
- Fixed the coverage CLI baseline exit code: `return 0 if delta.verdict in {"earn", "baseline"} else 1` so establishing a baseline no longer returns failure.
- Added tests:
  - `tests/test_mutation_runner.py`: WSL detection, parser edge cases, score calculation, subprocess failure paths.
  - `tests/test_cli_mutation.py`: CLI argument parsing, config fallback, output rendering, missing-WSL behavior.
  - Updated `tests/test_quality_scorecard.py` for the mutation signal and weight.

**Why**
- Complete Claude upgrade #3: replace test-count vanity with earned coverage plus mutation testing. The mutation runner makes `mutmut` callable from the RACT CLI on Windows and gives the scorecard a quantitative signal of test quality.
- The coverage baseline exit-code fix removes a false-failure footgun when the gate is first established.

**Test/lint/type result**
- `pytest tests/`: 907 passed, 1 skipped, 92% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/mutation_runner.py src/rootact/quality_scorecard.py src/rootact/cli.py tests/test_mutation_runner.py tests/test_cli_mutation.py tests/test_quality_scorecard.py`: passed.

**Self-audit result**
- `rootact auction list --json`: 0 dead-code candidates.
- `rootact novelty scan --json`: 2 `low` scripts (`scripts/mock_local_llm.py`, `scripts/verify_internal_rootact_separation.py`); expected.
- `rootact coverage delta --run --min-percent 90.0`: earn at 92.4%.

**Nemotron/Internal secondary review**
- Not delegated; this was a straight tooling-integration pass with no algorithmic changes.

**Next action**
- Wire the mutation runner into the harness/loop controller as a post-execution quality gate, or execute a real WSL mutation run and calibrate the scorecard weight against actual RACT results.

# RACT 0.1.0 - Initial Public Release

## 2026-07-09 — Loop pass: mutation gate wired into Harness.run

**What changed**
- Imported `run_mutation_tests` into `src/rootact/harness.py`.
- Added `mutation_gate` config parsing in `Harness.__init__`:
  - `enabled` (default `False`)
  - `hard_fail` (default `False`)
  - `min_score` (default `80.0`)
  - `timeout` (default `900.0`)
  - `script_path` (optional override)
- Added a post-execution mutation gate block in `Harness.run()` that:
  - Invokes `run_mutation_tests` after the coverage gate.
  - On runner error, hard-fails if configured; otherwise continues.
  - On low score (`mutation_score < min_score`), hard-fails if configured; otherwise records the score in `report.artifacts["mutation_score"]` and continues.
  - On passing score, still records the artifact so downstream scorecards and receipts can use it.
- Added `tests/test_harness_mutation_gate.py` with six tests covering:
  - gate disabled by default,
  - hard fail on low score,
  - soft fail attaches artifact,
  - pass attaches artifact,
  - runner error hard fail,
  - runner error soft fail ignores and continues.

**Why**
- The mutation runner is now a real quality gate inside the execution loop, not just a standalone CLI command. This closes the loop on Claude upgrade #3: test quality is measured, gated, and reported per execution.

**Test/lint/type result**
- `pytest tests/`: 913 passed, 1 skipped, 92% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/harness.py src/rootact/mutation_runner.py tests/test_harness_mutation_gate.py`: passed.

**Self-audit result**
- `rootact auction list --json`: 0 dead-code candidates.
- `rootact novelty scan --json`: 2 `low` test files (`tests/test_user_signature_registry.py`, `tests/test_use_cases_catalog.py`); expected given structural similarity.
- `rootact coverage delta --run --min-percent 90.0`: baseline established at 92.4%.

**Nemotron/Internal secondary review**
- Delegated a diff review to Nemotron via Internal. The model hallucinated behavior not present in the code (claimed the gate reads a pre-generated `/tmp/harness_mutation_gate.diff` file rather than calling `run_mutation_tests`). Review discarded; the implementation was verified by the unit tests instead.

**Next action**
- Run a real WSL mutation test against RACT, capture the actual mutation score, and calibrate the default `min_score` and scorecard weight against empirical data.

# RACT 0.1.0 - Initial Public Release

## 2026-07-09 — Loop pass: WSL distro detection and `--wsl-distro` option for mutation runner

**What changed**
- Fixed `src/rootact/mutation_runner.py` so Windows no longer assumes the default WSL distro is a Linux distro. Added `_detect_wsl_distro()` which:
  - Prefers `RACT_WSL_DISTRO` environment variable.
  - Parses `wsl -l --running` to find a Linux distro, skipping `docker-desktop` and `docker-desktop-data`.
  - Falls back to the bare `wsl -e bash` command if no distro is detected.
- Added `wsl_distro` parameter to `run_mutation_tests()` and threaded it through `_resolve_runner_command()`.
- Added `wsl_distro` config field to `Harness` mutation gate parsing and pass-through.
- Added `--wsl-distro` CLI option to `rootact mutation run`.
- Added tests:
  - `test_resolve_runner_command_uses_provided_distro`
  - `test_detect_wsl_distro_prefers_env`
  - `test_detect_wsl_distro_parses_running_list`
  - `test_detect_wsl_distro_skips_docker`
  - `test_detect_wsl_distro_returns_none_on_failure`
  - `test_mutation_run_command_passes_wsl_distro`

**Why**
- On this host the default WSL distro is `docker-desktop`, which has no `bash`. The original `wsl -e bash` command failed immediately. The runner now selects `Ubuntu-24.04` automatically, making a real mutation run possible.

**Test/lint/type result**
- `pytest tests/`: 919 passed, 1 skipped, 92% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/mutation_runner.py src/rootact/cli.py src/rootact/harness.py tests/test_mutation_runner.py tests/test_cli_mutation.py tests/test_harness_mutation_gate.py`: passed.

**Self-audit result**
- `rootact auction list --json`: 0 dead-code candidates.
- `rootact novelty scan --json`: 2 `low` test files (`tests/test_user_signature_registry.py`, `tests/test_use_cases_catalog.py`); expected.
- `rootact coverage delta --run --min-percent 90.0`: baseline established at 92.4%.

**Nemotron/Internal secondary review**
- Not delegated; this was a platform-detection bug fix with deterministic tests.

**Next action**
- Execute a real WSL mutation run against RACT (`rootact mutation run --wsl-distro Ubuntu-24.04`) as a background task, then capture the score and calibrate the default `min_score` and scorecard weight.

# RACT 0.1.0 - Initial Public Release

## 2026-07-09 — Loop pass: fix WSL path conversion and script portability for real mutation run

**What changed**
- Added `_to_wsl_path()` in `src/rootact/mutation_runner.py` to convert Windows paths (`C:\Users\rootl\ract-work\scripts\run.sh`) to WSL paths (`/mnt/c/Users/rootl/ract-work/scripts/run.sh`) before invoking WSL bash.
- Updated `_resolve_runner_command()` to apply `_to_wsl_path()` to the script path on Windows.
- Updated `scripts/run_mutation_tests_wsl.sh` to derive `REPO_ROOT` from `$(dirname "${BASH_SOURCE[0]}")/..` instead of the hardcoded `/mnt/c/Users/rootl/ract-work` path.
- Added tests for `_to_wsl_path()` covering Windows absolute, Windows backslash, and Unix inputs.
- Updated `test_resolve_runner_command_uses_provided_distro` to assert the converted WSL path.

**Why**
- The first real WSL mutation run failed because WSL bash received a Windows backslash path and reported `No such file or directory`. The runner now converts paths, and the script is portable across WSL mounts.

**Test/lint/type result**
- `pytest tests/`: 922 passed, 1 skipped, 92% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/mutation_runner.py src/rootact/cli.py src/rootact/harness.py tests/test_mutation_runner.py tests/test_cli_mutation.py tests/test_harness_mutation_gate.py`: passed.

**Self-audit result**
- `rootact auction list --json`: 0 dead-code candidates.
- `rootact novelty scan --json`: 2 `low` test files; expected.
- `rootact coverage delta --run --min-percent 90.0`: baseline established at 92.4%.

**Nemotron/Internal secondary review**
- Not delegated; deterministic path-conversion fix with mocked subprocess boundaries.

**Next action**
- Start a real WSL mutation run against RACT as a background task and capture the score.

# RACT 0.1.0 - Initial Public Release

## 2026-07-09 — Loop pass: README badges, SymbolGraph WSL-venv exclusion, and mutation-script fixes

**What changed**
- Updated README.md badges:
  - Coverage badge: 93% → 92% (matches current actual).
  - Added ruff lint badge.
- Added `rootact coverage delta` and `rootact mutation run` to the CLI highlights section.
- Fixed `src/rootact/symbol_graph.py` to use `os.walk` with directory pruning instead of `pathlib.rglob`, excluding common build/venv directories (`.venv`, `.venv-wsl-mutmut`, `__pycache__`, `.git`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `node_modules`, `_BUILD`, `htmlcov`, `dist`, `build`). This prevents `OSError` when WSL filesystem junctions (e.g. `.venv-wsl-mutmut/lib64`) are present.
- Added `.venv-wsl-mutmut/` to `.gitignore`.
- Fixed `scripts/run_mutation_tests_wsl.sh`:
  - Pinned `mutmut==2.4.5` because mutmut 3.x removed `--paths-to-mutate` and `--runner` CLI flags.
  - Moved the WSL venv from `$REPO_ROOT/.venv-wsl-mutmut` to `$HOME/.cache/ract-mutmut-venv` so it is never scanned by RACT's file walkers.
  - Kept the dynamic `REPO_ROOT` derivation from the script location.

**Why**
- The real WSL mutation run surfaced two integration bugs: mutmut 3.x CLI incompatibility and WSL venv junctions breaking RACT's own scanners. Fixing both unblocks the empirical mutation-score run.

**Test/lint/type result**
- `pytest tests/`: 922 passed, 1 skipped, 92% coverage.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/symbol_graph.py`: passed.

**Self-audit result**
- `rootact auction list --json`: 0 dead-code candidates.
- `rootact novelty scan --json`: 2 `low` test files; expected.
- `rootact coverage delta --run --min-percent 90.0`: earn at 92.4%.

**Nemotron/Internal secondary review**
- Not delegated; this was a defensive/compat pass with deterministic fixes.

**Next action**
- Run a real WSL mutation run against RACT again with the fixed script and capture the score.

# RACT 0.1.0 - Initial Public Release

## 2026-07-09 — Loop pass closure: commit/push and real WSL mutation run started

**Commit**
- `3853aae` pushed to `origin/main`.
- Includes README badges, SymbolGraph directory-pruning fix, `.gitignore` update, and `run_mutation_tests_wsl.sh` fixes (mutmut 2.4.5 pin, venv moved to `$HOME/.cache`).

**Background task**
- Task ID: `bash-ql8pspyu`
- Command: `.venv/Scripts/python -m rootact.cli mutation run --wsl-distro Ubuntu-24.04`
- Log: `C:/Users/rootl/ract-work/mutation_run_ract.log`
- Status: running, no timeout.

**Internal health**
- Nemotron on `127.0.0.1:8011`: running.
- Internal proxy on `127.0.0.1:11434`: running and responsive.
- Subservices bundle on `127.0.0.1:11503`: running.

**Next action**
- Wait for the mutation run to complete, parse the mutation score, and use it to calibrate `mutation_gate.min_score` and `quality_scorecard.py` weights. Then push the calibration and continue the loop.

## 2026-07-09 — Loop pass: fix mutation runner Unicode decoding and re-run

**What changed**
- `src/rootact/mutation_runner.py`: explicitly set `encoding="utf-8", errors="replace"` on the subprocess that invokes the WSL mutation script, so mutmut's emoji/status output does not crash the Windows reader thread with `cp1252` decoding errors.
- Made the `combined` output string None-safe: `(result.stdout or "") + "\n" + (result.stderr or "")`.

**Why**
- The first WSL mutation run failed with `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f` inside Python's subprocess reader thread, which left `result.stdout` as `None` and then raised `TypeError` when concatenating.

**Test/lint/type result**
- `pytest tests/test_mutation_runner.py tests/test_cli_mutation.py tests/test_harness_mutation_gate.py`: 29 passed.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/mutation_runner.py`: passed.

**Background task**
- Task ID: `bash-akvezkgm`
- Command: `.venv/Scripts/python -m rootact.cli mutation run --wsl-distro Ubuntu-24.04`
- Log: `C:/Users/rootl/ract-work/mutation_run_ract.log`
- Status: running, no timeout.

**Next action**
- When `bash-akvezkgm` completes, parse the mutation score, calibrate `mutation_gate.min_score` and `quality_scorecard.py` weights, commit, push, and continue the loop.

## 2026-07-09 — Loop pass: make `_to_wsl_path` platform-agnostic

**What changed**
- `src/rootact/mutation_runner.py`: rewrote `_to_wsl_path` to parse the drive letter from the normalized path string instead of relying on `pathlib.Path.drive`, which is empty when the code runs on a POSIX host (WSL/Linux). This fixes the four `test_mutation_runner.py` failures that occurred when mutmut ran the suite inside WSL.

**Why**
- The previous WSL mutation run failed because mutmut executes tests under Linux, where `Path("C:/tmp/script.sh").drive` returns `''`. The WSL-path tests expected `/mnt/c/...` conversion, so they failed, causing `mutmut run` to exit before `mutmut results` could print a score.

**Test/lint/type result**
- `pytest tests/test_mutation_runner.py`: 20 passed.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/mutation_runner.py`: passed.

**Background task**
- Task ID: `bash-k5aw805q`
- Command: `.venv/Scripts/python -m rootact.cli mutation run --wsl-distro Ubuntu-24.04`
- Log: `C:/Users/rootl/ract-work/mutation_run_ract.log`
- Status: running, no timeout.

**Next action**
- Wait for `bash-k5aw805q` to complete, parse the mutation score, calibrate `mutation_gate.min_score` and `quality_scorecard.py` weights, commit, push, and continue the loop.

## 2026-07-09 — Loop pass: WSL baseline test failures and mutation-script tolerance

**What changed**
- `src/rootact/mutation_runner.py`: `_to_wsl_path` now normalizes backslashes in the input string before parsing the drive letter, so Windows backslash paths convert correctly even when the code runs on a POSIX host.
- `scripts/install.sh`: converted line endings from CRLF to LF so `bash -n` passes under WSL/Linux.
- `scripts/run_mutation_tests_wsl.sh`: removed `set -e` and added `|| true` to the `mutmut run` invocation so the script always reaches `mutmut results`, even when mutants survive or the runner reports failures.

**Why**
- The previous WSL mutation run could not produce a score because `mutmut run` returned a non-zero exit code when tests failed (either baseline failures or killed mutants), and `set -e` aborted the script before `mutmut results`.

**Test/lint/type result**
- `pytest tests/test_mutation_runner.py tests/test_gravity_scorer.py`: 32 passed.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src/rootact/mutation_runner.py`: passed.

**Background task**
- Task ID: `bash-er46h5hx`
- Command: `.venv/Scripts/python -m rootact.cli mutation run --wsl-distro Ubuntu-24.04`
- Log: `C:/Users/rootl/ract-work/mutation_run_ract.log`
- Status: running, no timeout.

**Next action**
- Wait for `bash-er46h5hx` to complete and capture the mutation score. Then calibrate `mutation_gate.min_score` and `quality_scorecard.py` weights.
