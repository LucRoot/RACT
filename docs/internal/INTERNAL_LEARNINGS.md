# Internal Learnings from the RACT Build

## 2026-07-22 — Duplicate Qwen server and short build-func timeout caused smoke-test hangs

**Observation**
The Qwen smoke test hung for >50 minutes. Two `llama-server.exe` processes were simultaneously bound to port `8106`, starving each other so that prompt processing stalled mid-slot. After removing the duplicate, the restarted run still risked failure because the low-complexity `build-func` client timeout was only 600 s, while the CPU-only Qwen3.6-35B-A3B q3_k_m build averages ~1.5-3 t/s and a 768-token completion plus prefill can take ~10 min.

**Upgrade**
1. Harden `council_server_watchdog.py` so `start_server()` consolidates duplicate processes on the same port before reporting `already_running`.
2. Raise Qwen `build-func` timeouts: low-complexity 600 s → 1200 s, normal complexity 1200 s → 1800 s.
3. Keep model server launches visible in Task Manager and log PIDs so duplicates are easy to spot.

**Result**
A single Qwen server is kept alive, and slow-but-progressing generations are no longer discarded by a fixed short timeout.

**Applies to**
Any [REDACTED] deployment where a CPU-bound local model is shared by watchdog, smoke tests, and the production council loop.

## 2026-07-22 — Qwen CLI-function builds emit raw code, not FILE blocks

**Observation**
Qwen3.6-35B-A3B-UD-IQ3-XXS, when asked to rewrite a single CLI handler in `src/rootact/cli.py`, ignored the FILE-block format and emitted the function as plain code starting with `# Rooted by Dr. Lucas Root, Ph.D.`, `from __future__ import annotations`, the Root Knot markers, and `def _version_command(...)`. The council's `_build_full_func_pair()` rejected this because it only accepted fenced FILE blocks or fenced bare code blocks.

The smoke-test harness also masked the failure: it considered a run successful as long as council state was updated, but rework items update state too. The smoke backlog also targeted non-existent commands, making real application impossible.

**Upgrade**
1. Add a raw-code fallback `_extract_raw_function_code()` that strips leading comments, recognizes Root Knot markers / future imports / `def`, and extracts the target function block by indentation.
2. Harden `_build_full_func_pair()` to try FILE blocks → fenced bare blocks → raw function code → unclosed FILE blocks before raising.
3. Make the smoke test verify real application (status `done`) and target an existing CLI command.
4. Always restore the production backlog after a smoke test.

**Result**
Qwen smoke test now applies a real change to `_handshakes_command`, passes pytest, and is accepted by council review.

**Applies to**
Any council loop that asks Qwen for single-function rewrites where the model may drop FILE-block formatting.

## 2026-07-20 — [REDACTED] thermal monitor makes concurrency decisions data-driven

**Observation**
The council loop's thermal guard pointed to `http://127.0.0.1:11435/v1/health`, but nothing was serving it, so every thermal read returned `None` and the guard fell back to a soft "unreadable" pass-through. Meanwhile, running the Grove Forge Qwen eval and a council Qwen job concurrently stretched both call latencies because there was no heat-based gate.

**Upgrade**
1. Build a tiny WMI-based thermal monitor (`[REDACTED]/monitor/thermal_monitor.py`) that serves `/v1/health` with `thermal.max_temp_c`.
2. Start it hidden via `pythonw.exe` and have `council_manager.py` ensure it is running before each cycle.
3. Keep the existing 99 °C hard ceiling and 97 °C concurrency-pause thresholds (already high per operator preference).

**Result**
The monitor now reports live SoC temperature (e.g., ~85 °C, 36 zones). Council manager will skip launching new cycles when the SoC is at or above 97 °C, giving the existing thermal guard real input instead of an unavailable endpoint.

**Applies to**
Any [REDACTED] deployment on Windows/Snapdragon where local model concurrency must be thermally gated.

## 2026-07-20 — Grove Forge Cycle 9: chat-tuned Qwen3.6 needs chat completions, thinking off, and nested-function recovery

**Observation**
Grove Forge Cycle 9 reported HumanEval 0/10 and MBPP 0/10 on Qwen3.6-35B-A3B-UD-IQ3_XXS. Three separate issues were at play:
1. **Endpoint mismatch**: the raw `/completion` endpoint emitted mixed-script gibberish because Qwen3.6 is chat-tuned.
2. **Thinking mode**: `/v1/chat/completions` with default settings spent the entire 256-token budget on a reasoning trace and never emitted code.
3. **Echo/nesting**: when thinking was disabled, Qwen echoed the original function signature and placed the real implementation inside a nested inner function.

**Upgrade**
1. Route code-generation benchmarks through `/v1/chat/completions` when the model carries a chat template.
2. Pass `enable_thinking: false` for Qwen3.6 code-generation calls so tokens go to code, not reasoning trace.
3. Add a post-processor that extracts the innermost function body from the model output and splices it onto the original signature. This survives both the nested-output case and a clean single-function output.
4. Raise backend timeouts (900 s) and `max_tokens` (256) to accommodate Snapdragon inference speed.

**Result**
HumanEval/0 passes 3/3 tests after the fix. A trimmed base-stack eval (10 HumanEval + 10 MBPP) is running to measure the new pass rate.

**Applies to**
Any local code-generation benchmark that uses a chat-tuned model through llama-server.

## 2026-07-18 — Two recurring CLI-verb failure modes: missing keyword mappings and unclosed FILE blocks

**Observation**
Wave 4 stalled on three CLI export/verb items:
- `RACT Assumption Register CLI Verb` failed because `_infer_cli_function()` had no mapping for the keyword `assumption`.
- `RACT Audit HTML Export` and `RACT Explain CSV Output` failed because Qwen emitted `### FILE: src/rootact/cli.py` and an opening fence for the long `_audit_command` / `_explain_command` functions but ran out of attention before the closing fence, so `parse_file_blocks()` returned nothing.

A review of completed work shows the same patterns already happened and were recovered by luck:
- `RACT Handshake Review JSON Output`, `RACT Leaderboard HTML Export`, and `RACT Quality Scorecard HTML Export` all needed the bare-code-block fallback for `src/rootact/cli.py`.
- `RACT Receipt Verify CLI Verb` needed the bare-code-block fallback for its test file.
- `RACT Assumption Register and Decision Log`, `Init Template List CLI Verb`, `Symbol Renamer Preview CLI Verb`, and the skill-marketplace/skill-library items were completed while the keywords `assumption`, `init`, `rename`, `symbol renamer`, `skill`, and `skills` were absent from `_infer_cli_function()`. They succeeded only by matching other keywords or by being built as core modules rather than CLI verbs.

The longest CLI handlers are the most likely to trigger unclosed blocks: `_audit_command` (179 lines), `_coverage_command` (185 lines), `_session_command` (127 lines), and `_auction_command` (108 lines).

**Upgrade**
1. Extend `_infer_cli_function()` with explicit mappings for: `assumption`, `init`, `rename`, `symbol renamer`, `skill`, `skills`.
2. Add `_extract_unclosed_file_blocks()` as a fallback in `_build_full_func_pair()`: if `parse_file_blocks()` finds no `src/rootact/cli.py` block and the bare-code-block fallback also fails, grab the unclosed FILE block content. The fallback must split on each `### FILE:` header so a properly-closed test block does not hide an unclosed `src/rootact/cli.py` block.
3. For functions longer than ~120 lines, do not ask the model to rewrite the entire function in one FILE block. Instead, split the work: emit a small SEARCH/REPLACE patch for the new branch, or move the new format logic into a helper module and only patch a thin CLI wrapper.
4. Record both failure modes in `learning_feed.jsonl` so the pacer recognizes them on future cron passes.

**Result**
Patches applied to `[REDACTED]/council/council_loop.py`, including a corrected `_extract_unclosed_file_blocks()` that handles the common case where the test FILE block is closed but the long `src/rootact/cli.py` block is not. The failed/rework items will be reset and rerun with the patched loop.

**Applies to**
Any council loop that extends large CLI handler functions or adds new CLI verbs whose titles do not start with the literal `ract <verb>` pattern.

## 2026-07-18 — New-module tasks need the same two-step pipeline that CLI verbs use

**Observation**
CLI verbs that use the `_build_full_func_pair` two-step pipeline (function first, then deterministic/subprocess test) land reliably. New-module tasks that ask Qwen to emit both `src/rootact/*.py` and `tests/*.py` FILE blocks in a single call repeatedly fail: Qwen keeps the module and drops the test block, causing the gate to reject the build. After six total cycles across two runs, `RACT Assumption Register and Decision Log`, `RACT Session Store Backup and Restore`, and `RACT Coverage Badge SVG Generation` had not landed.

**Upgrade**
1. Apply a two-step pipeline to new-module tasks: first call asks for ONLY the module FILE block, second call asks for ONLY the test FILE block given the module.
2. Add a deterministic test fallback for new modules: parse the module AST, extract public functions/classes, and synthesize minimal smoke tests so a missing test block does not stall the item.
3. If a new-module item fails three times even with the two-step pipeline, treat it as a candidate for manual implementation rather than burning more cycles.

**Result**
The three stuck items are being implemented manually to restore council throughput; the loop improvement will be patched into `council_loop.py` before the next wave.

**Applies to**
Any council loop where new core modules must be created alongside tests.

## 2026-07-18 — Deterministic command-extraction test generator succeeds; open-ended FILE-block generation does not

**Observation**
After patching `council_loop.py` to use a two-step full-function pipeline with a deterministic test generator (extract test commands from `cli.py` and emit exact assertions), the council landed a large batch of CLI export/JSON/CSV verbs in a single 3-cycle run. Items that required the model to invent an open-ended module from a prose description (`RACT Session Store Backup and Restore`, `RACT Coverage Badge SVG Generation`) repeatedly produced no FILE blocks and exhausted their rework cycles. `RACT Assumption Register and Decision Log` reached pytest failure with no test files produced, suggesting the use case itself is under-specified for the generator.

**Upgrade**
1. Keep the deterministic command-extraction test generator for CLI verbs; it is the most reliable automation discovered so far.
2. For open-ended modules (new core logic, file I/O, SVG generation), provide a title-specific scaffold or example file in the prompt rather than asking the model to invent the module from scratch.
3. If an item fails twice with "no FILE blocks", split it into a tiny core module slice plus a thin CLI/test slice, and route the core slice to Qwen with explicit FILE-block examples.
4. Update the survival hash immediately after a green run if new signed files were added; do not let the next cron fire discover the mismatch.

**Result**
Twelve CLI verbs landed in one run. Three broader module tasks failed. The deterministic generator is now the preferred path for CLI work.

**Applies to**
Any council loop mixing CLI extension with new core-module invention.


This file captures concrete upgrades to the Internal/[REDACTED] runtime inspired by building and dogfooding RACT.

## 2026-07-18 — Splitting the task exposed a routing mismatch: Qwen should not own patches it cannot generate

**Observation**
After splitting `Rot Trend Baseline CLI Verb` into core module + CLI verb, the council in cycle 106 assigned the CLI verb to Qwen and the core module to Bonsai. Qwen still failed the CLI patch with the same `IndentationError`, while Bonsai failed the core module tests. The split helped planning but did not route the work to the model best suited for each slice.

**Upgrade**
1. When a model repeatedly fails the same artifact type (e.g., Qwen cannot patch `cli.py`), force that slice to the other builder or mark it for manual completion after one attempt.
2. Use the complexity tags plus a per-title routing override for known failure patterns.
3. Build the core module with Qwen (new-module FILE blocks) and the CLI patch with Bonsai (small patch) — or vice versa — based on observed strengths, not just generic complexity.

**Result**
The split is in progress; next run will experiment with routing the CLI patch away from Qwen if it fails again.

**Applies to**
Any council loop where one model has a consistent blind spot for a specific file or patch type.

## 2026-07-17 — The hard thermal ceiling must override the "keep moving" directive

**Observation**
During the split run, thermal climbed to 96.85 °C, exceeding the 96 °C hard ceiling. The active Qwen call was stopped immediately. After a 90-second cooldown, the SoC dropped to 51.85 °C, showing the spike was transient and recoverable.

**Upgrade**
1. Treat the hard ceiling as a non-negotiable stop rule: kill active model work when it is reached or exceeded.
2. Do not wait for the model call to finish once the hard ceiling is breached; inference generates heat and will push the system further.
3. After stopping, clear the orphaned lock, reset the interrupted item, wait for a sizable cooldown (e.g., below 70 °C or at least 90 s), then resume.

**Result**
Stopped the council at 96.85 °C, cooled to 51.85 °C, and resumed without hardware risk.

**Applies to**
Any local-model council loop with thermal governance.

## 2026-07-17 — Re-check thermal before aborting an active model call

**Observation**
During cycle 103 the thermal sensor reported 95.85 °C, just under the 96 °C hard ceiling. The first reading suggested an immediate stop was needed, but a second reading 30 seconds later showed 93.85 °C and falling. The spike was caused by the active Qwen inference and dissipated quickly once the heat spread to the sensor or the workload shifted.

**Upgrade**
1. When thermal is near but below the hard ceiling, take a second reading before stopping an active model call.
2. A single hot reading during inference is less dangerous than a sustained plateau above the fallback threshold.
3. If the second reading is at or above the hard ceiling, stop immediately; if it is falling and below the fallback, let the cycle finish.

**Result**
Avoided aborting a likely-valid Qwen build. The council continued, and thermal returned to the safe range.

**Applies to**
Any thermal-governed loop where sensor readings can spike during heavy inference.

## 2026-07-17 — When a title-specific hint fails three times, split the task instead of hinting harder

**Observation**
The `Rot Trend Baseline CLI Verb` task failed six total council cycles across three separate runs: first with a test syntax error, then twice with the same `IndentationError` in `src/rootact/cli.py` even after a detailed `_extend_cli_hint()` was added. The pattern showed Qwen could not reliably produce a correct SEARCH/REPLACE patch for this CLI verb, regardless of how specific the hint became.

**Upgrade**
1. After a hinted run still produces the same gate failure for three or more cycles, stop adding hints and split the task.
2. Move all non-trivial logic into a new module built with FILE blocks (Qwen's strength), leaving the CLI slice as a thin wrapper patch.
3. Update `BACKLOG_TITLES` order so the dependency (core module) is built before the consumer (CLI verb).

**Result**
Split the monolithic CLI verb into `Rot Trend Baseline Core Module` + `Rot Trend Baseline CLI Verb`. The council is now retrying with two input-sized slices.

**Applies to**
Any extend-cli task where the model repeatedly fails on the same cli.py patch pattern.

## 2026-07-17 — Repeated identical extend-cli gate failures need a title-specific code template

**Observation**
The second council run on `Rot Trend Baseline CLI Verb` failed three consecutive cycles with the exact same `IndentationError` in `src/rootact/cli.py`. Qwen kept generating a SEARCH/REPLACE patch with an `if` statement that had no indented body. Generic instructions like "preserve indentation" were not enough; the model needed a concrete code template showing the exact handler shape.

**Upgrade**
1. After two rework cycles with the same gate failure, add a title-specific `_extend_cli_hint()` that provides a copy-pasteable code block for the new CLI branch.
2. Include in the hint: exact imports, the JSON print shape, and explicit warnings against empty `if` bodies and against changing sibling indentation.
3. If a hinted run still fails with the same error, split the task: first build a helper module with FILE blocks, then wire it into the CLI with a tiny patch.

**Result**
Added a detailed hint for `ract rot baseline --json` and reset the item. The council is retrying with the template.

**Applies to**
Any extend-cli task where the model repeatedly produces indentation or empty-block syntax errors.

## 2026-07-17 — A thermal spike during an active model call is not a runaway; do not abort mid-inference

**Observation**
During cycle 100 on `Rot Trend Baseline CLI Verb`, the SoC temperature rose from 73.85 °C at cycle start to 94.85 °C while Qwen was actively generating. The concurrent-streams decision had already been made at cycle start when thermal was safe; the rise was caused by the ongoing inference, not by a new concurrent dispatch.

**Upgrade**
1. Once a model call is in flight, let it finish unless the hard ceiling (96 °C) is reached or exceeded.
2. Use the concurrency-fallback threshold (94 °C) only for deciding whether to start a *new* cycle concurrently, not for aborting active work.
3. Log the thermal delta per cycle so the pacer can distinguish between a steady-state hot run and a transient spike.

**Result**
The council continued its active build cycle. The next cycle will automatically serialize if thermal stays above 94 °C, balancing throughput and safety.

**Applies to**
Any long-running local-model builder loop with thermal governance.

## 2026-07-17 — Vague natural-language test assertions in use cases produce syntax errors

**Observation**
The first council attempt on `Rot Trend Baseline CLI Verb` generated a test with the invalid line `assert "snapshot" contains the four metrics`. Qwen interpreted the natural-language instruction "asserts valid JSON with direction 'stable' and snapshot containing the four metrics" as Python pseudo-code instead of real assertion syntax.

**Upgrade**
1. For council use cases that include test assertions, write the exact Python expression the test should use (e.g., `data["direction"] == "stable"`, `set([...]).issubset(data["snapshot"].keys())`).
2. Avoid verbs like "contains", "has", or "valid JSON" without showing the `json.loads()` call and the exact key access.
3. Gate failures due to `SyntaxError` are a strong signal that the use-case language is ambiguous; patch the use case before the next reset, not after multiple rework cycles.

**Result**
Patched the use case with explicit assertions and reset the item. The council is retrying with the clearer spec.

**Applies to**
Any [REDACTED] backlog item whose acceptance criteria include test assertions.

## 2026-07-17 — The pacer must not interrupt an active council build cycle

**Observation**
During the `Rot Trend Baseline CLI Verb` run, the council entered cycle 97 with the item `in_progress` and Qwen actively building. The cron-fired pacer correctly chose not to reset the item even though the previous cycle produced no applied files, because the item had not yet been marked `rework`. Resetting mid-build would have discarded the in-flight Qwen call and wasted compute.

**Upgrade**
1. Only reset an item when it is explicitly `rework` for two or more consecutive cycles.
2. When an item is `in_progress`, treat the pacer step as a status-check-and-wait action; document thermal and progress, then exit.
3. If the background task is running but output has not advanced for a very long time (e.g., > model timeout + pytest timeout), only then consider it hung and clear the lock.

**Result**
The council continued its active build cycle uninterrupted. The pacer stayed out of the way while still verifying thermal safety.

**Applies to**
Any autonomous pacer that monitors a long-running builder loop.

## 2026-07-17 — Council background runs need no-timeout scheduling

**Observation**
The first [REDACTED] council run on `Rot Trend Baseline CLI Verb` was killed after 600 s by the default background-task timeout while mid-cycle 97. The process left an active `council.lock` and an `in_progress` item, which blocked any new run. Cycle 96 had already completed without applying files, so the timeout wasted a planning call and created an orphaned lock.

**Upgrade**
1. Start council runs with no timeout or a timeout longer than `cycles × (model timeout + pytest timeout + gate time)`.
2. If a run is killed mid-cycle, treat the lock as orphaned when the background task is terminal, remove it, reset the interrupted item to `pending`, and restart.
3. Add a heartbeat/log-tail check to the pacer so it can detect a hung council process versus a merely long one.

**Result**
Cleared the orphaned lock, reset the item, and restarted the council without a timeout. The loop is now moving again.

**Applies to**
Any long-running builder loop that runs as a background task and uses a file lock.

## 2026-07-17 — A finished backlog should be refilled with the next user-facing slice, not left idle

**Observation**
After the `Longitudinal Rot Trend Report` module was completed and all 89 backlog items were marked `done`, the council loop had no work. Letting it sit idle wastes the armed cron and the trained council setup. The most valuable next slice is one that exposes a recently landed module through the CLI, turning a library feature into an observable user command.

**Upgrade**
1. When council status shows zero pending items, immediately append one high-leverage, user-facing slice to the backlog.
2. Prefer slices that wire the most recently landed module into the CLI or docs; this keeps the product surface coherent and gives the new feature a discoverable entry point.
3. Scope the use case as input-sized (one verb, one test file) so Qwen can finish it within a few cycles without splitting.

**Result**
Added `Rot Trend Baseline CLI Verb` (`ract rot baseline --history <path> --json`) and started the council on it. The new command consumes the `rot_trend` module and produces a JSON trend report for CI.

**Applies to**
Any [REDACTED]-style closed loop where backlog exhaustion would otherwise stall the builders.

## 2026-07-17 — New modules with numeric/dataclass logic need explicit type-safety scaffolding in the council seed

**Observation**
Qwen failed five cycles on `Longitudinal Rot Trend Report`, emitting broken code each time: top-level `import rootact`, an uninitialized `TrendReport` class, `history_path.write(snapshot)`, and tests that called `tmp_path()` as a function. After the syntax errors were fixed, mypy rejected the slope calculation (`Any | None` arithmetic) and the snapshot dict inference. The model kept producing plausible-looking but type-unsafe snippets because the generic new-module prompt did not constrain numeric/dataclass shape or require `from __future__ import annotations`.

**Upgrade**
1. For new modules that compute numeric deltas or use dataclasses, seed the prompt with:
   - `from __future__ import annotations` plus explicit imports (`Path`, `datetime`, `dataclass`, `typing.Any/Optional`).
   - A dataclass skeleton with field types already filled in.
   - A note that all nullable numeric lists must be filtered with `[v for v in values if v is not None]` before arithmetic.
   - A reminder that `dict` literals first assigned a string value should be annotated `dict[str, Any]`.
2. Run `mypy` as a separate gate before pytest for new modules; model-generated code often passes tests but fails type checking.
3. Cap rework attempts at a small number for new-module tasks; if the model repeatedly invents invalid syntax, fall back to manual completion from the seed rather than burning more cycles.

**Result**
The module was completed manually from Qwen's structural seed, the full suite is green, and the golden hash was updated to include the new signed module.

**Applies to**
Any [REDACTED] backlog item that introduces a new dataclass/numeric module where type safety is enforced by CI.

## 2026-07-17 — High-complexity new-module tasks must route to Qwen, and the prompt must include exact code templates

**Observation**
The first pass at `Statistically Defensible Provider Scorecard` was assigned to Bonsai and failed three cycles: Bonsai could not group receipts, compute medians, or return a proper dict. After forcing it to Qwen via a high-complexity tag, Qwen still failed repeatedly because the generic new-module prompt gave no structural template. Qwen eventually produced correct module logic once `_new_module_hint()` injected an exact grouping/return pattern, but it never emitted the required `tests/*.py` FILE block, so the build gate kept rejecting it.

**Upgrade**
1. Route extend-cli tasks AND any item tagged `high-complexity` to Qwen; reserve Bonsai for low-complexity, non-extend slices.
2. Add `_new_module_hint()` for title-specific code templates (grouping with `setdefault/append`, dict return shapes, etc.).
3. For stats-heavy modules, consider splitting into a core aggregation slice plus a statistics slice so each prompt stays small enough for the model to also emit tests.

**Result**
Provider scorecard landed after routing and hint fixes; council cycle time dropped because Qwen no longer wastes attempts on tasks that require design reasoning.

**Applies to**
Any [REDACTED] backlog containing mixed-complexity new-module work.

## 2026-07-17 — Extend-cli tasks need explicit JSON-shape hints and test-file creation rules

**Observation**
Council attempts on `ract fence inspect --json` failed repeatedly because Qwen:
1. Wrapped a string in `list()` to produce a fake "regions" array.
2. Used the wrong helper (`ChestertonsFence.inspect`) instead of `LoadBearingGuard.scan_file`.
3. Failed to create the inspected files inside the subprocess tests.
4. Wrote literal `...` inside a list comprehension instead of a real comprehension.
Similar smaller mistakes appeared in `ract provider health --json`.

**Upgrade**
Added a title-specific hint system (`_extend_cli_hint`) to `[REDACTED]/council/council_loop.py` that injects exact code patterns for known CLI verbs. The generic extend-cli preamble now also states:
- Implement the JSON shape from the use case exactly, even if it requires a different helper module.
- Do not call `list()` on a string.
- Keep the final `return` at its original indentation.
- LFM review instructions now explicitly ignore pytest-cov "no data collected" warnings.

**Result**
`ract fence inspect --json` landed on the next build cycle after the patch and passed full review; the full RACT suite remains green.

**Applies to**
Any [REDACTED]-style extend-cli task where the JSON output shape differs from the human-readable output or where the model has repeatedly tripped on the same type error.

## 2026-07-16 — Thermal-aware concurrency switch

**Observation**
Running the Qwen (8106) and Bonsai (8101) council workers concurrently on the same machine drove the SoC past 95 °C, causing thermal throttling and operator stops.

**Upgrade**
Added a thermal probe to `[REDACTED]/council/council_loop.py` that reads `http://127.0.0.1:11435/v1/health` before each cycle. If the reported `max_temp_c` is ≥ 70 °C or unreadable, the council falls back to sequential streams instead of concurrent Qwen+Bonsai threads.

**Result**
The loop keeps moving without operator intervention, but it no longer compounds heat under load. Default behavior is safe (sequential) when sensors are missing.

**Applies to**
Any Internal subloop that runs multiple local model servers concurrently.

## 2026-07-16 — Pacer should not interrupt an in-progress council item

**Observation**
The first council-pacer cron fire occurred while the [REDACTED] council loop was mid-cycle (`Tamper-Evident Receipt Chain` was `in_progress`). Resetting a `rework` item at that moment would have wasted the active Bonsai call and could have left the working tree in an inconsistent state.

**Upgrade**
The pacer now checks council status and only intervenes (start, reset, split) when the loop is idle. If an item is `in_progress`, the pacer documents status and waits for the cycle to finish.

**Result**
The pacer advances the loop without racing the council workers. Rework triage happens at cycle boundaries, not mid-call.

**Applies to**
Any autonomous pacer that monitors a long-running builder loop.

## 2026-07-16 — Stuck rework items should be split, not just retried

**Observation**
After two full council cycles, `Public Receipt Leaderboard` and `Tamper-Evident Receipt Chain` remained in `rework`. The model kept generating similar file blocks and failing the same tests, suggesting the use-case scope was too large or the acceptance criteria were unclear.

**Upgrade**
The pacer will reset a rework item once after it idles, then edit the use case/backlog to split the task into smaller input-sized slices if it fails again. Smaller tasks reduce output-budget pressure and make test failures easier to diagnose.

**Result**
The council spends fewer cycles on the same failing prompt and more cycles landing complete, tested slices.

**Applies to**
Any model-driven build loop that reaches a rework plateau.

## 2026-07-16 — Existing runs need an emergency thermal ceiling too

**Observation**
The pacer correctly refused to start new council runs above 80 °C, but an existing sequential run kept going while the SoC climbed past 90 °C. Without an upper bound, the machine could reach thermal throttle levels before the next fire.

**Upgrade**
Add an emergency stop rule: if thermal exceeds 95 °C during a council run, the pacer stops the active council background task and documents the pause. The run can resume once the machine cools below 80 °C.

**Result**
The council loop stays safe even when a long sequential item runs during a warming trend.

**Applies to**
Any background model worker that may outlast a single pacer interval.

## 2026-07-16 — Pacer interval should match the longest expected model call

**Observation**
A single BONSAI build call for `Public Receipt Leaderboard` spanned multiple 5-minute pacer fires with no output, leaving the pacer with nothing to do but document status. The 1200 s Bonsai backstop is longer than the pacer interval.

**Upgrade**
For pacer-paced work, cap per-item model timeouts at or below the pacer interval (e.g., 300 s) and split tasks so each call finishes within one interval. This gives the pacer a chance to intervene, reset, or stop between calls.

**Result**
The pacer can respond to thermal trends and stuck items on every fire instead of being blocked by one long-running call.

**Applies to**
Any autonomous loop that fires more frequently than its longest model call.

## 2026-07-16 — Three rework cycles is the triage threshold

**Observation**
`Public Receipt Leaderboard` failed in council cycles 19, 20, and 21. The model kept producing near-identical outputs and failing the same tests, indicating the use case was either too large or the acceptance criteria were not encoded in the prompt.

**Upgrade**
The pacer will treat three consecutive rework cycles as a hard triage signal: reset the item, then rewrite the use case/backlog entry into smaller, input-sized slices with explicit acceptance criteria before allowing another build attempt.

**Result**
The council stops burning cycles on prompts that have proven unresolvable in their current form.

**Applies to**
Any autonomous builder loop with a rework state.

## 2026-07-16 — Applied split: Public Receipt Leaderboard and Tamper-Evident Receipt Chain

**Applied**
After `Public Receipt Leaderboard` failed three consecutive council cycles and `Tamper-Evident Receipt Chain` failed twice, both use cases were split into smaller input-sized slices:
- `Public Receipt Leaderboard` → `Public Receipt Leaderboard - HTML Headers` + `Public Receipt Leaderboard - JSON Loader`
- `Tamper-Evident Receipt Chain` → `Tamper-Evident Receipt Chain - Append Hash` + `Tamper-Evident Receipt Chain - Verify Hash`

The `BACKLOG_TITLES` list in `[REDACTED]/council/council_loop.py` was updated to the new titles, and four focused use cases were appended to `_BUILD/rootact_use_cases.jsonl`. Each new slice is scoped to fit within a single model call and has explicit import/header constraints.

**Result**
The council can now retry with narrower deliverables instead of repeatedly failing the same monolithic prompt.

**Applies to**
The RACT backlog and any future council task that hits a rework plateau.

## 2026-07-16 — 15-minute pacer interval aligns with council item duration

**Observation**
Under a 5-minute pacer, most fires occurred while a single BONSAI/Qwen call was still in progress, producing repetitive status-only log entries. The shortest successful council item took ~10 minutes.

**Upgrade**
Switched the pacer cron from `*/5 * * * *` to `*/15 * * * *`.

**Result**
Each pacer fire now lands near a natural cycle boundary, giving the pacer a chance to start, reset, or stop the council instead of just noting "still running."

**Applies to**
Any autonomous loop whose model-call duration is longer than the pacer interval.

- **Thermal governance must stop active runs, not just gate new starts.** The pacer and council_loop currently disable concurrency at 70 °C but only the pacer manually stops work when crossing 80 °C. Future improvement: add an in-loop thermal kill switch that checks the LM Studio health endpoint each cycle and pauses the council until cooldown.

- **Bonsai repeatedly fails to emit the required FILE blocks for leaderboard tasks, and both builders are failing on the receipt-chain hash tasks.** The council plan should split these into smaller, test-only slices or route the JSON/HTML loader work to Qwen until Bonsai can reliably follow the FILE-block protocol. A meta-prompt or a stricter output-format guard in `council_loop.py` (e.g., refuse to parse until FILE blocks are present, then retry once) would reduce stale rework.

- **Use-case descriptions must not contain pseudo-code or requirement prose that looks like code.** Models (even Qwen) can paste those phrases verbatim into files, causing `py_compile` gate failures. Future use cases should specify behavior in plain English and give exact Python expressions only when they are intended to be copied literally.
- **Thermal cadence for this machine is ~1 cycle every 10 minutes before crossing 80 °C.** Running `--cycles 3` reliably heats past the threshold before finishing. Consider shorter `--cycles 1` runs or active thermal kill-switch inside `council_loop.py` to auto-pause between cycles.

- **Qwen on CPU can hang for the full hour timeout on high-complexity items, blocking the council and wasting thermal budget.** Add a lightweight completion probe before each council run and fall back to Bonsai for the item if Qwen does not respond within a short window (e.g., 60 s). Consider reducing the Qwen timeout from 3600 s to 300 s with one retry so hung calls surface quickly instead of starving the loop.

## 2026-07-17 — Operator thermal threshold should be a runtime override

**Observation**
The hard-coded `THERMAL_THRESHOLD_C` had to be edited and the council restarted twice in one session because the operator's risk tolerance changed faster than the code. A 70 °C default that later became 85 °C and then 92 °C required stopping the loop, editing the file, and clearing the lock each time.

**Upgrade**
Read `THERMAL_THRESHOLD_C` from an environment variable (`RACT_THERMAL_THRESHOLD_C`) with a sensible default (85 °C). The file default protects hardware; an operator can raise or lower the limit without restarting the loop from scratch.

**Result**
Thermal policy becomes tunable at runtime. The council loop can be restarted with a new threshold via the environment, and future pacers can warn when the operator-set threshold is within a few degrees of the current sensor reading.

**Applies to**
Any long-running autonomous loop whose safety limits need operator-adjustable bounds.

## 2026-07-17 — Council builders still miss basic hygiene on tiny tasks

**Observation**
On two input-sized tasks (`MCP Adapter Health Probe`, `Coverage Delta JSON Export`), the council models emitted code that failed trivial gates: Qwen forgot the required test file entirely, and Bonsai emitted a test that used `json.load` without importing `json`. Both failures were faster to fix manually than to cycle through another council retry.

**Upgrade**
Add a stricter pre-application lint gate inside `council_loop.py`: before running pytest, run `py_compile` on every emitted file and a lightweight AST check for obvious issues (missing imports referenced in the file, undefined names). Fail fast with a clear classification so the model can retry once with a tighter prompt, or the pacer can route to manual implementation.

**Result**
Fewer wasted thermal/model cycles on errors a static analyzer catches instantly. The council spends its budget on design problems, not import hygiene.

**Applies to**
Any model-driven build loop that applies generated files to a live repo.

## 2026-07-17 — Docs/markdown tasks run cooler than code-generation tasks

**Observation**
When the council works on README/asciicast docs items, the SoC temperature stays in the mid-80s °C under concurrent streams. Code-generation items (Python modules + pytest) consistently push the machine toward the 90 °C ceiling within a single cycle.

**Upgrade**
Use docs/markdown backlog items as thermal-balancing work. When the machine is hot after a code cycle, route the next item to a docs task or reduce concurrency rather than pausing entirely. This keeps the loop moving during cooldown.

**Result**
Higher throughput per thermal dollar: the council does not have to sit idle waiting for cooldown after every code item.

**Applies to**
Any autonomous build loop whose tasks vary in compute intensity.

## 2026-07-17 — Partially-implemented docs tasks confuse model builders

**Observation**
`README Badges and Quickstart Header` and `RACT Demo Asciicast Embed` already had substantial content in the repo (badges, Demo section, `assets/demo.cast`). The council models kept emitting duplicate or mismatched content and failing tests because the use case did not acknowledge the existing state.

**Upgrade**
Before assigning a docs/task item, the pacer should run a quick audit of the target file and prepend a "current state" note to the prompt: "README already contains badges and a Demo section; do not duplicate them. Add only the missing Quickstart section and asciinema image link." This prevents the model from rewriting existing content.

**Result**
Fewer false starts on "extend" tasks where most of the work is already done.

**Applies to**
Any backlog item that says "extend" rather than "implement from scratch."

## 2026-07-17 — Thermal ceiling must pause mid-cycle, not just gate starts

**Observation**
The [REDACTED] council checks thermal only at cycle boundaries. During cycle 26 the SoC climbed from 85 °C to 95.85 °C while Bonsai/Qwen were actively generating. By the time the next cycle boundary arrived, the machine was already past the 92 °C ceiling.

**Upgrade**
Add a mid-stream thermal probe inside `council_loop.py` that reads the sensor every 60 seconds during long model calls. If the temperature crosses the ceiling, abort the active call, restore the snapshot, and enter `wait_for_cooldown()` before any further work.

**Result**
The loop respects the thermal ceiling even when a single model call is long. Hardware stays within the operator-defined safe band.

**Applies to**
Any long-running builder loop where individual calls can last several minutes.

## 2026-07-17 — Repeated thermal spikes confirm need for mid-cycle kill switch

**Observation**
Across multiple council runs, the SoC repeatedly climbed past 90 °C and hit 94.85 °C. The current `wait_for_cooldown()` only runs between cycles, so a long Qwen/Bonsai call can overheat the machine before the next boundary check.

**Upgrade**
Implement a mid-call thermal watchdog: spawn a lightweight thread that polls `http://127.0.0.1:11435/v1/health` every 30 seconds while a model call is active. If `max_temp_c` exceeds `THERMAL_THRESHOLD_C`, cancel the request (close the urllib connection or set a shared abort flag) and restore the snapshot. Then enter `wait_for_cooldown()`.

**Result**
The council respects the thermal ceiling inside individual model calls, not just at cycle boundaries. This prevents the repeated emergency stops we've seen today.

**Applies to**
Any autonomous loop that makes long-running model calls on thermally constrained hardware.

## 2026-07-17 — Split thermal thresholds: concurrency cutoff below pause ceiling

**Observation**
A single 92 °C threshold was used both to disable concurrency and to pause the loop. The machine repeatedly started cycles concurrently at ~75–85 °C, then spiked past 92 °C before the next boundary check could pause it.

**Upgrade**
Introduced two thresholds in `council_loop.py`:
- `CONCURRENCY_THRESHOLD_C = 80.0` — fall back to sequential streams.
- `THERMAL_THRESHOLD_C = 92.0` — hard pause; `call_model()` now calls `wait_for_cooldown(target_c=THERMAL_THRESHOLD_C)` before every request.

**Result**
Concurrency (the main heat multiplier) is reduced earlier, while the hard ceiling still blocks new work if the machine is already hot. This should eliminate the mid-cycle 94 °C spikes.

**Applies to**
Any multi-model local loop where concurrent work generates more heat than sequential work.

## 2026-07-17 — Extend tasks can silently delete existing code

**Observation**
Bonsai implemented `Dead Code Auction HTML Report` as an "extend" task and emitted a new `src/rootact/dead_code_auction.py` containing only `render_html_report`. The original `DeadCodeAuction` class and `AuctionItem` dataclass were removed, breaking `src/rootact/cli.py` and the full test suite.

**Upgrade**
Before applying any model-generated "extend" file, diff it against the existing file. If the diff removes symbols that are imported elsewhere in the codebase, reject the patch and ask the model to preserve existing exports. Add a lint gate that checks `git diff --stat` and `git diff --name-only` for unexpected deletions.

**Result**
Existing APIs survive extension tasks. The council stops producing build-wedges where a new feature breaks an old one.

**Applies to**
Any model-driven loop where tasks say "extend" or "add a function to" an existing module.

## 2026-07-17 — Hard thermal ceiling needs margin below CPU throttling

**Observation**
Raising the council's hard thermal ceiling from 92 °C to 94 °C caused the machine to ride at 94.85–95.85 °C immediately on cycle start. That is within a few degrees of typical CPU thermal throttling and produced an unsafe, sustained load.

**Upgrade**
Keep the hard ceiling at 92 °C and use a concurrency cutoff 8 °C below it (84 °C) so the loop falls back to sequential streams before the hard gate engages. Raise the cooldown target only to 80 °C, not the ceiling, so resumption still has thermal headroom.

**Result**
The loop stays in its productive band (below ~90 °C) instead of oscillating against the hardware limit. Sustained 95 °C operation is avoided.

**Applies to**
Any local model loop that uses a configurable thermal ceiling on consumer hardware.

## 2026-07-17 — Cron coalescing hides missed checks during long turns

**Observation**
The pacer cron fired with `coalescedCount=3`, meaning three 15-minute intervals collapsed into one fire because the session was busy. A simple "every 15 minutes" assumption would have made it look like only one pass happened.

**Upgrade**
Treat `coalescedCount > 1` as "only the latest state matters" and immediately run a full status/thermal audit rather than assuming incremental progress. Use the cron only as a wakeup, not as a precise schedule.

**Result**
No false assumptions about missed council cycles. Each fire starts with a fresh status check.

**Applies to**
Any long-running autonomous loop driven by a recurring cron that may be delayed by busy turns.

## 2026-07-17 — Qwen 3.6 can hang past its configured HTTP timeout on small CLI-verb tasks

**Observation**
Qwen was assigned `Leaderboard CLI Verb`, a small CLI extension (~40 lines). It sat for over 14 minutes without producing output, well past the council's 600 s endpoint timeout. The endpoint was reachable, so the request itself stalled rather than failing fast.

**Upgrade**
Add a tighter per-call watchdog inside `council_loop.py`: wrap `urllib.request.urlopen` in a socket-level timeout and/or spawn a watcher thread that aborts the connection after the configured timeout. When a model exceeds its budget, mark the item for manual implementation rather than letting the whole cycle stall.

**Result**
No more indefinite council stalls on a single hung builder. The pacer can route timed-out high-complexity items to manual or to another model.

**Applies to**
Any multi-model council where one model's endpoint can become unresponsive without raising an error.

## 2026-07-17 — Full novelty scan is O(n²) and times out on RACT itself

**Observation**
`ract novelty scan --json` consistently exceeded the 120 s tool timeout. Profiling showed the scan computes a leave-one-out dictionary and a conditional compression ratio against every other file for each project file, making it O(n²) zstd compressions.

**Upgrade**
Add a `--fast` mode that uses dictionary-only scoring (`scan_project_fast`), returning valid novelty signals in seconds. Keep the full scan available for deep audits but make the fast path the default for CI.

**Result**
Novelty scanning is usable in automation. Operators can still run the deep scan when they need nearest-neighbor duplicate detection.

**Applies to**
Any codebase-scale analysis that has both a cheap heuristic mode and an expensive exact mode.

## 2026-07-17 — Council models repeatedly fail simple CLI-verb tasks

**Observation**
Both Qwen and Bonsai failed `RACT Version CLI Flag` and `Config Validation CLI Verb` across two council cycles each. The failures suggest the models struggle to integrate new subparsers into the existing `cli.py` dispatch without breaking existing imports or tests.

**Upgrade**
For CLI-verb backlog items, the pacer should pre-compute the exact insertion points (dispatch `if` block, import line, subcommand function placement) and include them in the prompt. A tighter prompt with structural scaffolding reduces the chance of malformed integration.

**Result**
Manual implementation with the same scaffolding took minutes and passed tests. The council can retry similar items once given an explicit integration template.

**Applies to**
Any model-driven loop adding subcommands or extensions to a large existing CLI module.

## 2026-07-17 — Internal provider must be registered in the router defaults

**Observation**
The `internal` provider adapter existed in `providers/internal_provider.py` and was exported from `providers/__init__.py`, but it was not registered in `ProviderRouter`'s `_ADAPTER_CLASSES`. This meant `adapter: internal` in `rootact.yaml` resolved to "Unknown provider adapter".

**Upgrade**
Register `InternalProvider` in `providers/router.py` under the `"internal"` adapter name so it can be configured like any other built-in provider.

**Result**
The provider health CLI can now exercise the internal adapter in tests, and users can route prompts to local scripts without custom registration.

**Applies to**
Any provider adapter that is implemented but not yet wired into the router registry.

## 2026-07-17 — README/docs tests are cheap and high-leverage release guards

**Observation**
Adding small tests for `README.md` and `CHANGELOG.md` caught gaps in the public-facing documentation and prevented silent drift. These tests run in milliseconds and do not heat the machine.

**Upgrade**
For every docs/marketing task, add a corresponding test that asserts the expected strings/sections exist. Treat docs as code that the release gate must keep current.

**Result**
Public-launch docs stay accurate as the CLI surface grows. The release gate can reject a PR that adds a CLI verb but forgets to document it.

**Applies to**
Any project where the README is a primary user interface.

## 2026-07-17 — Subcommand refactoring should preserve existing positional flags

**Observation**
Extending `ract session list` into `ract session list|export|import` required switching from a flat `choices=["list"]` parser to subparsers. The existing test `test_cli_session_list.py` passed `--store <dir>` after `list`; keeping `--store` on the `list` subparser maintained backward compatibility while allowing new export/import subcommands to have their own required arguments.

**Upgrade**
When promoting an action argument to a subparser, duplicate shared flags (like `--store`) on each subparser rather than moving them to the top level. This prevents breaking existing CLI invocations and tests.

**Result**
The session command surface expanded without regressing the original `ract session list` behavior.

**Applies to**
Any CLI that grows a single-action command into a multi-subcommand command.

## 2026-07-17 — Small CLI verbs should reuse existing primitives

**Observation**
`Receipt Diff CLI Verb` and `Symbol Renamer Preview CLI Verb` were each implemented in minutes by composing existing library functions (`load_receipt` + `diff_fingerprints`, `SymbolRenamer.preview_rename`) rather than inventing new comparison or tokenization logic inside `cli.py`.

**Upgrade**
Before adding a new CLI verb, scan the package for an existing function that already solves the core problem. Wrap that function with argument parsing and output formatting, and add a focused subprocess test. This keeps `cli.py` thin and ensures the underlying logic is unit-testable outside the CLI.

**Result**
Both verbs landed with only a few lines of CLI glue and passed the full suite immediately. The same primitives are now available to other callers (tests, the council, future API surfaces).

**Applies to**
Any CLI surface that exposes behavior already present in the project's library modules.

## 2026-07-17 — Dry-run previews belong in the library, not just the CLI

**Observation**
Adding `--dry-run` to `ract skills install` required knowing the built-in skill source path, the target registry path, and the skill metadata. Implementing this logic only in `cli.py` would couple the preview to argument parsing and duplicate knowledge the library already had.

**Upgrade**
Add a `preview_install()` method to `BuiltinSkillLibrary` that returns the same metadata `install()` would use, without writing files. The CLI only formats and prints the result. This keeps the library authoritative and makes the dry-run behavior unit-testable without subprocess.

**Result**
The CLI `--dry-run` flag is a thin wrapper. Future callers (tests, API, council) can reuse `preview_install()` directly.

**Applies to**
Any command that has a destructive action and a corresponding safe preview.

## 2026-07-17 — Argparse choices hide custom error semantics

**Observation**
`--init-provider` used `choices=list_presets()`, which produced an argparse error and exit code 2 for unknown presets. The desired behavior was a project-branded error message and exit code 1, matching RACT's other CLI error paths.

**Upgrade**
Remove the `choices=` list and validate the preset manually inside the handler. This lets the CLI print a consistent `[rootact] unknown provider preset: ...` message and return 1.

**Result**
Preset validation is now consistent with the rest of the CLI surface and easier to test for the exact error string and exit code.

**Applies to**
Any CLI option where the default argparse error behavior does not match the project's error conventions.

## 2026-07-17 — Subprocess CLI tests must avoid local package shadowing

**Observation**
The `ract coverage badge` test created a temporary `rootact/` package inside the temp project and set `cwd` to that project. The subprocess then imported the local dummy `rootact` package instead of the real RACT package, causing `No module named rootact.cli`.

**Upgrade**
Run subprocess CLI tests from the actual RACT project root (so `python -m rootact.cli` resolves to the real package) and pass absolute `--config` paths so the command still operates on the temporary fixture project.

**Result**
Coverage-badge test passes without shadowing, and the pattern applies to any CLI test that needs a fixture project with a package whose name matches RACT's.

**Applies to**
Any subprocess test for a CLI tool that creates fixture packages.

## 2026-07-17 — Dataclass entries serialize cleanly to JSON

**Observation**
The handshake registry returns `HandshakeItem` dataclass instances. Adding `--json` to `ract handshakes` required converting them to dictionaries; `dataclasses.asdict` handled nested metadata automatically and kept the JSON output consistent with the registry's on-disk format.

**Upgrade**
For CLI commands backed by dataclasses, import `asdict` once and use it for all JSON output paths. This avoids hand-rolled field lists that drift when the dataclass changes.

**Result**
Handshake JSON output stays in sync with the registry schema without extra maintenance.

**Applies to**
Any CLI surface that serializes dataclass-backed domain objects to JSON.

## 2026-07-17 — Reusing plan serializers keeps JSON output stable

**Observation**
`ract explain --json` needed a structured representation of a `Plan`. `step_to_dict` was already imported for plan diff, so reusing it for explain output kept the JSON schema consistent with the plan serialization format.

**Upgrade**
Before inventing a new JSON shape for a CLI verb, check `plan_serializers`, `receipt`, or other existing serialization helpers. Consistent schemas reduce surprise for users and tests.

**Result**
Explain JSON output matches the plan JSON format; tests can build plans with the same dict shape used elsewhere.

**Applies to**
Any CLI command that emits structured data derived from core domain objects.

## 2026-07-17 — Diff appliers must match context, not just line offsets

**Observation**
`DiffApplier` was replacing a fixed-length slice starting at the hunk's target line without checking whether the removed/context lines actually matched the file. A "broken" patch that changed a non-existent line still returned `applied=True`, and patches without `diff --git` headers produced no results at all.

**Upgrade**
Replaced the naive slice replacement with context verification: the hunk's context and removed lines are compared against the target file slice before writing. If they do not match, the hunk fails. Header parsing now also derives the target path from `--- a/...` / `+++ b/...` lines (stripping the git prefixes) as well as from `diff --git` lines.

**Result**
`ract diff apply --json` now returns `applied=False` for mismatched patches and correctly handles both git-style and plain unified diffs. The tool behaves like a real patch applier for the common cases.

**Applies to**
Any tool that applies unified-diff hunks to existing files.

## 2026-07-17 — JSON mode must keep stdout clean of human diagnostics

**Observation**
`ract retrieval search --json` printed a fallback message to stdout (`"No retrieval adapter configured..."`) before the JSON array, causing `json.loads` to fail in tests and scripts.

**Upgrade**
Route diagnostic/fallback messages to `sys.stderr` when the command is invoked with `--json`. Only the structured payload goes to stdout.

**Result**
Subprocess and pipeline consumers of RACT's JSON CLI verbs get parseable output even when the tool falls back to a default adapter.

**Applies to**
Any CLI command that offers a `--json` output mode.

## 2026-07-17 — Table-based CLI commands can adopt --json uniformly

**Observation**
`ract mcp list` and `ract skills list` rendered human tables via `console.table`. Adding `--json` to each required only switching the output path to `json.dumps(...)` using the same list-of-dicts the table already consumed.

**Upgrade**
For any CLI verb that builds a list of dictionaries solely to render a table, add a `--json` flag that short-circuits to JSON serialization. The data structure is already correct; only the formatter changes.

**Result**
`ract mcp list --json` and `ract skills list --json` landed with minimal code and passed subprocess tests immediately.

**Applies to**
Any CLI surface that currently prints a table from an in-memory list of records.

## 2026-07-17 — Stale backlog titles make the council redo finished work

**Observation**
The running [REDACTED] council started working on `Skills List JSON Output` because the `BACKLOG_TITLES` list still contained that title after it had been manually implemented. The manual work was recorded under the full title `Skills List JSON Output`, but the backlog entry was briefly mismatched, so the council did not recognize it as complete. Qwen also burned a cycle on `MCP List JSON Output` before the manual fix.

**Upgrade**
Update `BACKLOG_TITLES` and `_BUILD/rootact_use_cases.jsonl` immediately when an item is completed manually, before restarting the council. Remove or replace finished titles so the next council cycle picks only genuinely pending work.

**Result**
The restarted council now targets only `Marketplace List JSON Output` and `Run Fingerprint JSON Output`, avoiding wasted model calls on already-landed features.

**Applies to**
Any hybrid manual/council build loop where the backlog is the shared schedule.

## 2026-07-17 — Council models repeatedly fail to emit FILE blocks for CLI JSON tasks

**Observation**
On three consecutive items (`Marketplace List JSON Output`, `Leaderboard JSON Output`, and `Mutation Run JSON Output`) the council produced either no FILE blocks or a malformed test file, burning two full cycles without applying any code. Qwen in particular returned prose explanations instead of the required `### FILE:` blocks.

**Upgrade**
For CLI JSON verbs, fall back to manual implementation after one council cycle with no FILE blocks. The manual pass takes minutes and passes tests; waiting for additional model cycles wastes thermal budget and time. Keep the council reserved for tasks where it has already demonstrated reliable FILE-block output.

**Result**
All six CLI JSON verbs landed cleanly via manual implementation, and the full suite stayed green.

**Applies to**
Any model-driven build loop that relies on a structured output format (e.g., FILE blocks) that the model does not consistently emit.

## 2026-07-17 — Stale pending entries must be archived before the council restarts

**Observation**
Two old pending titles (`Public Receipt Leaderboard` and `Tamper-Evident Receipt Chain`) remained in `council_state.json` after their split children were already implemented manually. Left in place, they would have stalled the council or caused duplicate work because the backlog parser treats any `pending` entry as available work.

**Upgrade**
Before each council restart, audit `council_state.json` for `pending` entries whose scope has been superseded by smaller implemented slices. Archive them with a reason so the council starts with a clean, actionable backlog.

**Result**
The restarted council immediately picked the two new public-launch items (`ract consolidate --json` and `RACT CLI JSON Cheat Sheet`) instead of revisiting finished work.

**Applies to**
Any backlog-driven loop where tasks are split or re-scoped after partial implementation.

## 2026-07-17 — Council build prompt must branch on task type

**Observation**
The generic build prompt opened every task with "Implement this use case as new module(s) plus pytest test(s)." When the use case actually required extending `src/rootact/cli.py`, Qwen created a new `consolidate_json.py` module full of hallucinated imports. When the use case required creating `docs/cli_json_cheat_sheet.md`, Bonsai created `src/rootact/cli_json_cheat_sheet.py` with a top-level `rootact` import that violated the use-case constraint.

**Upgrade**
Added `_detect_task_type`, `_read_target_file`, and `_task_preamble` to `council_loop.py`. The prompt now explicitly branches for:
- `extend_cli`: "Modify the EXISTING src/rootact/cli.py; do NOT create a new module," with the current cli.py content included.
- `create_docs`: "Create the markdown file; do NOT create a Python module."
- `new_module`: default behavior for creating new `src/rootact/*.py` modules.
Both branches repeat the test constraints (subprocess only, no top-level imports).

**Result**
The prompt's strongest framing now matches the actual task. The council was restarted with the patched prompt on `ract version --json` and `RACT Troubleshooting Guide`.

**Applies to**
Any model-driven builder whose backlog mixes "extend existing file", "create docs", and "create new module" tasks.

## 2026-07-17 — Pacer cron prompt must stay in sync with code thermal thresholds

**Observation**
The `council_loop.py` thermal ceiling was raised to 96 °C, but the pacer cron prompt still told future instances to hold at 80 °C. After context compaction, the written cron prompt becomes the effective policy; an out-of-sync prompt would keep the council idle even when the code allows work.

**Upgrade**
Whenever the code thermal threshold changes, update the cron prompt at the same time and document the new job ID in `docs/BUILD_LOG.md`. Keep a small headroom rule in the prompt (hold if within 2 °C of ceiling) so fires do not start right at the edge.

**Result**
The pacer now uses the same 96 °C ceiling as `council_loop.py`, with an explicit caution against starting when the sensor is near the limit.

**Applies to**
Any autonomous pacer whose policy is encoded in both code and a cron prompt.

## 2026-07-17 — Repeated syntax errors on large-file edits need a hard triage cutoff

**Observation**
After the prompt was patched to target the right file, Qwen still produced an unclosed parenthesis in `src/rootact/cli.py` and Bonsai produced an unterminated string literal in a test file. Both models repeated the exact same errors across cycles 43 and 44, burning time and thermal budget without converging.

**Upgrade**
Treat two consecutive identical `py_compile` syntax errors as a hard triage signal: stop the council, manually implement the item, and add a learning. Do not wait for a third rework cycle. For extend-cli.py items specifically, consider pre-compressing the context block or routing them straight to manual implementation.

**Result**
`ract version --json` and `RACT Troubleshooting Guide` were implemented manually in minutes, the full suite stayed green, and the council moved on to the next backlog items.

**Applies to**
Any model-driven build loop where the fix-and-iterate path gets stuck on the same mechanical error.

## 2026-07-17 — Docs-guide council items fail on bad tests, not bad docs

**Observation**
On `RACT Security Best Practices Guide`, Bonsai generated a plausible markdown doc but also created `tests/test_security_best_practices.py` that imported `rootact.provider_presets.openai`, a non-existent symbol. The same pattern appeared on earlier docs tasks. The model's test-generation is the failure point, not the docs content.

**Upgrade**
For docs-only backlog items, either (a) provide a ready-made minimal test template in the use case so the model only has to fill in assertions, or (b) skip the council entirely and create the doc + a trivial structure test manually. Do not rely on the model to invent correct imports for a docs test.

**Result**
Manual implementation of `docs/security_best_practices.md` and `docs/troubleshooting.md` with trivial structure tests landed cleanly and passed the full suite.

**Applies to**
Any model-driven loop where docs tasks require a companion test file.

## 2026-07-17 — Extend-cli.py JSON verbs are a manual-implementation category

**Observation**
Across `ract consolidate --json`, `ract version --json`, and `ract load-bearing list --json`, the council never produced a passing implementation. Even after the prompt patch targeted the right file, Qwen emitted syntax errors or no FILE blocks, and Bonsai was not routed to these tasks. The common factor is editing an existing 3000+ line `cli.py` under a strict FILE-block and subprocess-test protocol.

**Upgrade**
Classify "extend src/rootact/cli.py" tasks as manual-implementation items. Keep them in the backlog so they are tracked, but route them straight to a manual pass instead of burning council cycles. Reserve the council for new modules and simple docs where it has a better success rate.

**Result**
The CLI JSON backlog is being cleared reliably via manual implementation while the council is freed up for other work.

**Applies to**
Any codebase where a single large file is the touchpoint for many small CLI features.

## 2026-07-17 — New modules must be wired into production before the dead-code auction passes

**Observation**
Adding `src/rootact/config_diff.py` caused `test_ract_auction_reports_zero_dead_modules` to fail because the module had no inbound references. The RACT dead-code auction is a release gate: every source file must be referenced by production code.

**Upgrade**
Whenever a new module is added, immediately expose it through an existing CLI command or another production entry point. For `config_diff.py`, adding a `ract config diff` subcommand satisfied the auction and made the feature usable.

**Result**
The dead-code auction stayed green, and the new config-diff capability is reachable from the CLI.

**Applies to**
Any project with a dead-code or orphan-module release gate.

## 2026-07-17 — Council test generation is the current bottleneck

**Observation**
The council failed on three different task types in a row (extend-cli, docs, new module). In each case the implementation file was often reasonable, but the accompanying test file was missing, malformed, or violated project constraints (subprocess-only, no top-level imports, wrong paths).

**Upgrade**
For the current RACT build, treat the council as a planner/drafter and manual implementation as the closer. Run the council for 2-3 cycles, then if it has not landed, stop it and manually implement the item with a correct test. This keeps the loop moving without wasting thermal budget on repeated mechanical failures.

**Result**
Public-launch backlog items are landing reliably; the council still runs and occasionally succeeds, but it is no longer the critical path.

**Applies to**
Any model-driven build loop where test-generation quality is lower than implementation quality.

## 2026-07-18 — Extend-cli tasks should not be hard-routed to Qwen regardless of complexity

**Observation**
`council_loop.py` originally sent every extend-cli task to Qwen because patches were considered high-risk. For `Rot Trend Baseline CLI Verb`, Qwen failed the `cli.py` patch nine times across three runs, always with the same `IndentationError`. Meanwhile Bonsai failed the core module tests. The hard routing prevented the council from trying the model better suited for the thin wrapper.

**Upgrade**
1. Change the routing rule so that extend-cli tasks tagged `low-complexity` go to Bonsai; only medium/high-complexity extend-cli tasks default to Qwen.
2. Use tags actively to express where each slice should go, not just how hard it is in the abstract.
3. When a model fails the same artifact type repeatedly, use tags to force the other model on the next run rather than adding more hints.

**Result**
Patched `council_loop.py` routing and retagged the split use cases. The next run will test whether Bonsai can land the thin CLI wrapper while Qwen lands the core module.

**Applies to**
Any council loop that hard-routes task types to specific models.

## 2026-07-18 — Tag-based routing overrides can fix model/artifact mismatches quickly

**Observation**
After retagging `Rot Trend Baseline Core Module` as `high-complexity` and `Rot Trend Baseline CLI Verb` as `low-complexity`, and patching `council_loop.py` to let low-complexity extend-cli tasks go to Bonsai, cycle 109 correctly assigned Qwen to the core module and Bonsai to the CLI verb. The plan also enabled concurrent streams because thermal was safe.

**Upgrade**
1. Use complexity tags as routing levers, not just descriptive labels.
2. When a model has a repeated blind spot for an artifact type, change the tag to move that slice to the other builder.
3. Keep the routing rule explicit and small so the override is easy to reason about and revert.

**Result**
The council is now running the split tasks on the models best suited for each slice.

**Applies to**
Any multi-model council where task-to-model routing needs to adapt based on observed failure patterns.

## 2026-07-18 — Concurrent streams on two models produce transient thermal spikes; re-check before aborting

**Observation**
Cycle 110 ran Qwen and Bonsai concurrently. The thermal sensor reported 95.85 °C, but a second reading 30 seconds later showed 93.85 °C and falling. The concurrent workload creates sharper, shorter spikes than sequential streams, but the SoC cools quickly when neither model is in a sustained heavy inference phase.

**Upgrade**
1. With concurrent streams, use a shorter polling interval for thermal checks during active cycles.
2. Take two readings spaced 20–30 seconds apart near the fallback threshold before deciding to stop.
3. If the second reading is still climbing or above the hard ceiling, stop; otherwise let the cycle continue.

**Result**
Avoided an unnecessary stop. The council continued its concurrent build attempt.

**Applies to**
Any multi-model council that runs streams concurrently.

## 2026-07-18 — Subprocess CLI tests must pass each token separately; models often collapse multi-word commands

**Observation**
Bonsai's test for `ract rot baseline` repeatedly failed because it passed the string `"rot baseline"` as a single element in the subprocess argument list. `argparse` then saw it as one positional token and printed a usage error. This happened across multiple council cycles despite the prompt specifying a `baseline` subparser.

**Upgrade**
1. In prompts that ask models to write subprocess CLI tests, include an explicit example showing each token as a separate list element: `[sys.executable, "-m", "rootact.cli", "rot", "baseline", ...]`.
2. Add a project-level lint or review note: any subprocess test that calls the CLI with a multi-word command must split the words.
3. Consider adding a simple CLI-test template to the council few-shot examples that demonstrates token splitting.

**Result**
Manually-written test passed immediately once tokens were separated. The failure mode is now documented for future council items.

**Applies to**
Any CLI command with subparsers tested via subprocess.

## 2026-07-18 — Set an explicit cycle cap per item and fall back to manual implementation

**Observation**
The `Rot Trend Baseline` slice burned six council cycles (106–111) without landing. The core module failure was a persistent inability to emit parseable FILE blocks; the CLI verb failure was a persistent inability to write a correct subprocess test. Both were mechanical issues that manual implementation fixed in minutes.

**Upgrade**
1. Cap any council item at 3 cycles of identical failure mode before manual takeover.
2. When manual takeover happens, keep the council running on a different item rather than stopping the whole loop.
3. Capture the corrected implementation as a few-shot seed for the next similar item.

**Result**
The backlog item is now done and the codebase is clean. Thermal budget and clock time were preserved.

**Applies to**
Any model-driven council where repeated mechanical failures exceed the cost of manual closure.


## 2026-07-18 — A broken thermal probe should gate model work, not documentation work

**Observation**
The thermal endpoint returned `UNKNOWN` during a cron fire. The council loop was idle with no pending items, so the natural next step would have been to start it on a new backlog item. Because the prompt explicitly forbids starting model work with an unreadable sensor, I instead ran the recurse and audit steps. Validation passed and audit completed without model inference.

**Upgrade**
1. Treat thermal-governance failures as hard gates for model work but not for local tooling, docs, or validation.
2. When the sensor is unreadable, log the state and use the cycle for non-thermal work: recurse (tests/lint/mypy), audit (doctor/auction/fence), or documentation.
3. Periodically retry the thermal probe; do not assume it is permanently offline.

**Result**
The cron pass was still productive despite the missing sensor. No thermal risk was taken.

**Applies to**
Any automated build loop that uses an external thermal sensor to gate compute-heavy model work.


## 2026-07-18 — Replenish the backlog from public-launch gaps, not just pre-curated use cases

**Observation**
When all `BACKLOG_TITLES` items reached `done`, the council loop had nothing to do. The pre-curated use-case file also contained no remaining public-launch items. The gap that mattered most was packaging: source tests pass, but there was no automated check that the 0.1.2 wheel builds and its entry points work.

**Upgrade**
1. When the backlog empties, scan the project for public-launch gaps (version strings, entry points, packaging, README accuracy, installability) rather than waiting for new use cases.
2. Add the smallest slice that closes the gap as a new backlog item.
3. Keep the item input-sized so the council can complete it in one cycle if possible.

**Result**
The council is now running again with a concrete, high-leverage release-blocking task.

**Applies to**
Any project where a model council consumes a curated backlog and risks running out of work before launch readiness.


## 2026-07-18 — A running council cycle is a state, not an event; cron passes should observe without interrupting

**Observation**
The first cron pass after starting the council found it mid-cycle 113. The natural reflex is to "do something," but the council was healthy: lock active, Bonsai assigned to the wheel smoke test, thermal well below the fallback. Interrupting would have wasted the inference already spent.

**Upgrade**
1. When the council is running and thermal is safe, treat the cron pass as a checkpoint, not an intervention.
2. Only reset an item after it has hit rework in two consecutive cycles.
3. Use the idle time between council runs for recurse/audit, not during an active cycle.

**Result**
Bonsai continues its build attempt uninterrupted. Thermal and lock state are monitored.

**Applies to**
Any closed-loop system where model work is expensive and should not be restarted unless it is actually stuck.


## 2026-07-18 — A 600 s background timeout can kill a healthy council mid-cycle

**Observation**
The council completed cycle 113 in ~8 minutes and started cycle 114, then the background task hit its default 600 s timeout. The lock was left active and the item was stuck `in_progress`. The work already done was wasted because the process was killed rather than allowed to finish its 3-cycle run.

**Upgrade**
1. Start council runs with no timeout or with a timeout that exceeds the expected duration of 3 cycles plus cooldown waits.
2. When a timeout kills a council run, immediately clear the stale lock and reset the item to pending before restarting.
3. Do not treat a timeout-induced failure as a model failure until a full uninterrupted run completes.

**Result**
Restarted the council without a timeout so it can complete its 3-cycle plan without interruption.

**Applies to**
Any multi-cycle background task where each cycle may take several minutes.


## 2026-07-18 — When both models fail the same task, the prompt or slice is the problem, not the model

**Observation**
The wheel smoke test failed under both Bonsai (cycle 114, no FILE blocks) and Qwen (cycle 115, empty model response). This means the failure is not a model-specific blind spot; the council is not eliciting the right output format from either builder for this particular use case.

**Upgrade**
1. After two consecutive cycles with different models failing the same item, stop and rewrite the use-case description to explicitly request the expected artifacts (e.g., a single pytest file using subprocess, plus a build script).
2. Split the task into smaller input-sized slices so each slice has a clearer deliverable.
3. Add a worked example of a packaging smoke test to the learning feed / few-shot context.

**Result**
Will let cycle 116 finish, then reset and refine the task rather than running more blind cycles.

**Applies to**
Any multi-model council where an item fails across different builders.


## 2026-07-18 — Packaging smoke tests need explicit UTF-8 subprocess encoding on Windows

**Observation**
The first draft of `tests/test_wheel_smoke.py` failed because `ract doctor` outputs Unicode box-drawing characters. On Windows, `subprocess.run(..., text=True)` defaults to the console code page (cp1252), which cannot decode the output and crashes the reader thread, leaving `stdout` as `None`.

**Upgrade**
1. Always pass `encoding="utf-8"` and `errors="replace"` to subprocess calls in tests when the invoked CLI may emit rich text or Unicode.
2. Add this as a project convention note for future council-generated subprocess tests.
3. Consider making the CLI itself force UTF-8 output on Windows, but the test fix is the immediate, safe change.

**Result**
The wheel smoke test now passes reliably and the 0.1.2 release installability is verified.

**Applies to**
Any Windows project whose CLI outputs Unicode and is tested via subprocess.


## 2026-07-18 — Keep one lightweight docs item in the backlog as council ballast

**Observation**
After the wheel smoke test landed, the backlog emptied again. Rather than waiting for a new curated use case, I added a small, high-visibility docs item: correcting the README demo version. This keeps the council moving on public-launch gaps and provides a natural fallback item when heavier implementation tasks are blocked.

**Upgrade**
1. Maintain a rolling "docs polish" item in the backlog that is always safe to pick up.
2. Source these items from visible inconsistencies (version strings, README examples, help text) rather than abstract feature ideas.
3. Let the council attempt the docs edit; if it fails, manual closure is cheap and the gap is still closed.

**Result**
The council is running again on a concrete, low-risk task while the codebase stays clean.

**Applies to**
Any project where a model council needs a steady stream of small, verifiable tasks between larger features.


## 2026-07-18 — Models sometimes emit literal placeholders in FILE blocks; add a pre-apply syntax check

**Observation**
Qwen's cycle 118 attempt produced a file path `relative/path.py` with literal content `<full file content>`. The council's gate check caught it via py_compile, but the cycle was wasted. This is the same class of error as Bonsai's collapsed subprocess token: the model knows it should output a file but substitutes a placeholder when uncertain.

**Upgrade**
1. In council prompts, explicitly forbid placeholder text like `<full file content>` or `<insert code here>` and warn that such outputs break the build.
2. Treat any gate failure containing placeholder text as a prompt issue, not a code issue, and refine the use-case description.
3. Consider adding a council pre-filter that rejects FILE blocks containing known placeholder strings before py_compile.

**Result**
Cycle 118 was rejected safely; cycle 119 is retrying with Bonsai.

**Applies to**
Any model-driven build loop that parses FILE blocks from model output.


## 2026-07-18 — Docs edits with no executable test are hard for the council to validate; pair them with a README lint test

**Observation**
The README version accuracy task failed three council cycles. The models could not reliably produce a correct README edit that also satisfied whatever implicit validation the council applied. Because there was no concrete test file specifying the expected strings, the council had to guess at success criteria.

**Upgrade**
1. For docs tasks, add a small test that asserts the expected strings exist (e.g., `test_readme_version.py` checking for `Version: 0.1.2` and `ract rot baseline`).
2. Give the council the test file as part of the task so it knows exactly what must pass.
3. If the council still fails after two cycles, the manual fix is trivial and the test prevents regression.

**Result**
Manual README fix is in place. Future docs tasks should include an explicit test harness.

**Applies to**
Any model council working on documentation or other non-executable artifacts.


## 2026-07-18 — Sequence docs tasks as edit-then-test to give the council a concrete pass condition

**Observation**
After manually fixing the README, the next backlog item is a README lint test. This creates a natural sequence: the test validates the edit that just landed. If the council can write the test, it locks in the docs fix; if it fails, manual closure is still small and the regression guard is worth the cost.

**Upgrade**
1. Pair every docs/UX fix with a follow-up lint or assertion test in the backlog.
2. The test should be the deliverable, not an afterthought, so the council knows exactly when it is done.
3. Use these paired items as training material for the council's few-shot examples.

**Result**
The council is now running on a well-scoped test with a clear expected output.

**Applies to**
Any project where documentation or configuration drift is a public-launch risk.


## 2026-07-18 — Three-cycle failures on the same model call for a simple test suggest a prompt/schema mismatch

**Observation**
The README lint test was assigned to Qwen for cycles 122 and 123, and likely 124. Both completed cycles failed with "tests failed" and restored snapshots. The task is objectively simple (read README.md, assert two strings exist), yet Qwen could not land it. This points to the council prompt or FILE-block expectations being mismatched with what Qwen is emitting, not the test logic itself.

**Upgrade**
1. For ultra-simple tests, consider a dedicated prompt template that tells the model to produce only the test file and nothing else.
2. If a model fails the same simple task three times, switch to manual implementation and use the result as a negative example in the learning feed.
3. Track per-task model failure counts so the router can automatically fall back to manual after a cap.

**Result**
Cycle 124 will determine whether to continue or manually close.

**Applies to**
Any model council where simple tasks repeatedly fail with the same model.


## 2026-07-18 — Ultra-simple tests can still fail in the council if the prompt schema is not explicit

**Observation**
The README lint test is two trivial assertions, yet Qwen and Bonsai failed it across three cycles. The failure was not in test logic but in the council's file-generation pipeline: models either produced malformed FILE blocks or tests that did not satisfy the implicit validation gate. Manual implementation took under a minute.

**Upgrade**
1. For trivial test-only tasks, add a dedicated "test-only" path in the council that skips file-block parsing and asks the model to return only the test source in a fenced code block.
2. After two failures on a trivial task, bypass the council entirely and write it manually; the training value is low compared to the time and thermal cost.
3. Use manually-written trivial tests as positive examples in the few-shot feed.

**Result**
README drift is now guarded by a passing lint test. The council can move on to meatier work.

**Applies to**
Any model council where trivial regression tests consume disproportionate cycles.


## 2026-07-18 — Turn observed audit timeouts into backlog items

**Observation**
The cron audit `ract novelty scan --json` timed out on the full RACT source tree. Rather than skipping the audit or running it only with `--fast`, I promoted the timeout into a public-launch backlog item. This converts a monitoring observation into actionable product work.

**Upgrade**
1. When a recurring audit step fails or times out, create a backlog item to fix the underlying tool rather than working around it.
2. Tag the item with both the affected subsystem and `public-launch` so it is prioritized.
3. Include the observed behavior (timeout duration, project size) in the use-case description to ground the fix.

**Result**
The council is now working on a timeout guard that will make novelty scan usable on real codebases.

**Applies to**
Any project where recurring audits surface performance or reliability issues.


## 2026-07-18 — Stop model work before the hard ceiling, not at it

**Observation**
The thermal sensor climbed from 70.85 °C at cycle start to 95.85 °C during the first council cycle on the novelty scan timeout guard. Rather than waiting for the 96 °C hard ceiling, I stopped the council, cleared the lock, and let the system cool. The temperature dropped to 60.85 °C within minutes.

**Upgrade**
1. Treat the 94 °C concurrency fallback as an early-warning threshold, not just a concurrency switch.
2. When thermal rises quickly and is within 1–2 °C of the hard ceiling, proactively stop model work before hardware protection triggers.
3. Use the cooldown period for low-thermal work: lint, type checks, and non-LLM audits.

**Result**
No thermal emergency. Validation and audits completed during cooldown. Council ready to resume.

**Applies to**
Any automated loop running compute-heavy model inference on thermally constrained hardware.


## 2026-07-18 — Use ThreadPoolExecutor with a timeout as a non-intrusive guard for slow CLI operations

**Observation**
Implementing a true interruptible timeout inside `CompressionNoveltyDetector` would require rewriting its loops. Instead, wrapping the scan call in a `ThreadPoolExecutor(max_workers=1)` and using `future.result(timeout=...)` provides a wall-clock timeout boundary without touching the detector's internals. On timeout, the main thread returns a partial/empty result while the worker thread continues as a daemon until process exit.

**Upgrade**
1. For long-running CLI operations, add a `--timeout` flag and wrap the call in a single-worker thread pool.
2. Return a stable, documented result shape on timeout so callers can detect and handle it.
3. Add tests that monkeypatch the slow method to sleep, avoiding flaky real-world timing.

**Result**
`ract novelty scan` now defaults to a 60-second timeout and no longer appears to hang.

**Applies to**
Any CLI tool with potentially unbounded CPU-bound operations.



## 2026-07-18 — Train [REDACTED] by capping rework cycles and shrinking fix prompts

**Observation**
The council burned cycles 126–128 on `RACT Novelty Scan Default Timeout Guard` with repeated failures: Bonsai invented a nonexistent `rootact.novelty_scan` module, and Qwen returned empty content during the fix phase. Manual completion was faster and cheaper than a fourth cycle.

**Upgrade**
1. Hard-cap every backlog item at three cycles (initial build + two fix attempts). After that, mark the item `failed` and let manual triage take over.
2. Shrink extend-cli fix prompts by dropping the redundant repo layout blob; the prior attempt plus the current handler function provide enough context and keep the prompt inside the model's context window.
3. Add an explicit IMPORT RULE: builders may only import from existing `src/rootact/` modules and must not create new modules for CLI-only features.
4. Continue adding title-specific hints for new CLI verbs so the model knows the exact JSON shape and helper imports.

**Result**
Council is now running on two new scorecard CLI verbs with the improved prompts and a failure cap.

**Applies to**
Any model council where repeated rework is caused by prompt length or invented APIs rather than genuine complexity.


## 2026-07-18 — Concurrent council streams spike thermal fast; monitor through the cycle

**Observation**
Starting two concurrent council streams at 68.85 °C drove the SoC to 94.85 °C within minutes. The hard ceiling is 96 °C, so there is very little margin once concurrent streams begin.

**Upgrade**
1. Let the current cycle finish rather than aborting mid-model-call; aborting wastes inference and can corrupt the working tree.
2. Rely on the council's own concurrency fallback for the next cycle when thermal is above 94 °C.
3. If thermal is within 1–2 °C of the hard ceiling while streams are active, prepare to stop immediately after the current cycle completes.

**Result**
Cycle 130 is completing under close watch; no intervention yet.

**Applies to**
Any automated multi-model loop on thermally constrained hardware.


## 2026-07-18 — Extend-cli failures cluster around import scope and wrong verb wiring

**Observation**
Two concurrent scorecard CLI attempts failed for predictable mechanical reasons:
1. Provider scorecard patch used `Path` inside `src/rootact/cli.py` but lost/broke the local binding.
2. Quality scorecard patch wired the command under the wrong top-level subparser, so `ract quality scorecard --json` was unrecognized.

**Upgrade**
1. For extend-cli patches, add a title-specific hint that explicitly names the existing import line to preserve (`from pathlib import Path`) and the exact subparser to extend.
2. Include a one-line example invocation in the use-case description so the model knows the expected CLI surface.
3. After one extend-cli failure, consider giving the model the full existing handler function as the SEARCH block instead of asking it to find the right snippet.

**Result**
Cycle 131 is attempting fixes with these failure modes logged; if it fails, manual implementation will use these exact corrections.

**Applies to**
Any extend-cli council task where the model struggles with parser wiring or local imports.


## 2026-07-18 — Manual fallback after three council cycles is the right training boundary

**Observation**
The council failed both scorecard CLI verbs across cycles 130–132. The failure modes were mechanical (import scope, wrong parser wiring) rather than architectural. Manual implementation took minutes and produced passing tests; a fourth council cycle would have cost more time and heat with no new learning.

**Upgrade**
1. Enforce the 3-cycle cap strictly: after initial build + two fixes, manual implementation is the cheaper path for small CLI-only slices.
2. Use the manual implementation as a positive example in the learning feed and, where useful, as a few-shot pattern for future extend-cli tasks.
3. Before sending a CLI-only slice to the council, add a title-specific hint with the exact existing handler function, import line, and subparser name.

**Result**
Two public-launch CLI verbs landed cleanly after the cap triggered. The council can now move on to meatier non-CLI work.

**Applies to**
Any model council where repetitive mechanical failures consume disproportionate cycles.


## 2026-07-18 — Concurrent model streams are not viable on this thermally constrained host

**Observation**
Every multi-model council run spiked the SoC from the 70s to the mid-90s °C within one cycle. Two runs were stopped at 95.85 °C to avoid hitting the 96 °C hard ceiling. The cooling solution cannot sustain two local LLMs simultaneously.

**Upgrade**
1. Force sequential execution whenever the council schedules more than one builder stream.
2. Keep the single-stream thermal threshold so a lone model call still respects heat limits.
3. Accept slower throughput in exchange for not interrupting cycles with emergency stops.

**Result**
Council will now serialize Qwen and Bonsai work, keeping thermal rises gradual and manageable.

**Applies to**
Any multi-model local loop running on hardware without enough thermal headroom for concurrent inference.


## 2026-07-18 — Count total rework cycles, not fix attempts, for the council failure cap

**Observation**
The `RACT Config Diff CLI Verb README Index` task failed three council cycles but never incremented `fix_attempts` because the model produced no FILE blocks. The original cap only checked `fix_attempts >= 2`, so the task would have looped indefinitely.

**Upgrade**
1. Track `rework_cycles` and increment it on every failure path (no FILE blocks, gate failures, test failures, patch apply failures).
2. Cap at 3 rework cycles regardless of whether the model produced files.
3. Reset `rework_cycles` to 0 only when an item is successfully applied.

**Result**
The cap now reliably triggers after three failed attempts, manual fallback happens on schedule, and heat/time are not wasted on unproductive loops.

**Applies to**
Any automated model loop where failure modes include empty or unparseable outputs.


## 2026-07-18 — Docs-only README edits are outside the council's reliable capability

**Observation**
Four consecutive docs-only README index tasks failed across both Qwen and Bonsai. The failure mode was consistent: the model produced no FILE blocks, or the output did not match the required format. Manual implementation took seconds each.

**Upgrade**
1. Stop sending docs-only README edits to the council; handle them manually during pacer passes.
2. Reserve council cycles for code and test tasks where the FILE/PATCH block format is more natural for the models.
3. If a README edit must be council-generated, wrap it as a test-driven task (e.g., "add a test that asserts README contains X") so the model has a concrete Python target.

**Result**
README index gaps are now closed manually. Future backlog items will favor code/test slices.

**Applies to**
Any model council where a specific task type consistently fails with empty or misformatted output.

## 2026-07-18 — A council item can be 99% done and still blocked by a one-line runtime error

**Observation**
The council produced a working `export_json` implementation and tests for `DependencyGraph`, but failed to verify the file-write path because `from pathlib import Path` was missing. The symptom appeared only when the test passed a `Path` to `export_json`; the string-return smoke test passed. This is a classic gap between "model generated code" and "actually runs" — the model understood the API but missed the import, and the council's own gates did not catch it because the failing test was part of the generated test suite that never executed successfully under thermal constraints.

**Upgrade**
1. Before marking a council item done, always run the generated test file in isolation, even if the full council pytest gate is skipped due to time/heat.
2. When a model generates a new method that uses `Path`, include an explicit prompt instruction to verify all imports are present in the source file.
3. Add a lightweight `py_compile` + import check for every modified module as a pre-test gate, independent of the generated tests.
4. If thermal limits prevent the council from finishing a small fix, the pacer should fall back to manual repair rather than letting the item sit in rework.

**Result**
The missing-import blocker was fixed in seconds once identified manually. Future council prompts will require import verification for any new file I/O method.

**Applies to**
Any automated code-generation loop where generated code is syntactically valid but fails at runtime due to missing imports or incomplete environment assumptions.

## 2026-07-18 — Even Bonsai-sized tasks can hit the thermal fallback threshold

**Observation**
The `RACT AI SBOM Unit Tests` item was intentionally scoped as a tiny, low-complexity Bonsai task (a 10-statement module with three simple tests). Despite this, the single Bonsai stream pushed the host from 67.85 °C to 94.85 °C within one council cycle, forcing a timeout and manual fallback. The model generation itself did not complete in the 5-minute window, suggesting either slow token generation or thermal-induced throttling.

**Upgrade**
1. Treat "small" model tasks as thermally equivalent to "large" ones on this host: the act of loading and running any local LLM is the dominant heat source, not the output size.
2. Set a per-stream wall-clock cap (e.g., 3 minutes) for low-complexity items; if the model cannot produce a small test file in that time, fallback to manual immediately rather than waiting for a full timeout.
3. Prefer pure-manual implementation for any task that fits in a single small file when thermal headroom is below 80 °C, reserving council cycles for multi-file or genuinely complex work where model assistance is worth the heat cost.
4. Log thermal at item start and end so the operator can see the temperature delta per task.

**Result**
The coverage gap was closed without burning additional thermal budget. Future pacer passes will bias toward manual implementation for small single-file tasks when the host is warm.

**Applies to**
Any local-model council running on hardware where a single inference stream is enough to approach thermal limits.

## 2026-07-18 — The council planning phase alone can consume significant thermal budget

**Observation**
When restarting the council on `RACT Leaderboard Loader Unit Tests` with the host at 53.85 °C, the temperature climbed to 85.85 °C during the council meet/planning phase before any builder model (Qwen/Bonsai) was actively generating code. The LFM coordinator model and the surrounding context-gathering (AST parsing, file globbing, health probes) produced enough heat to consume most of the safe margin.

**Upgrade**
1. Measure thermal before the council meet phase, not just before builder streams start. The planning phase is not thermally free.
2. When the host is above ~70 °C at council start, skip the council entirely and implement small items manually.
3. Keep a "warm-start" threshold (e.g., 70 °C) separate from the "running" threshold (94 °C); starting cold vs. starting warm produces very different thermal trajectories.
4. Cache repo context (AST summaries, file lists) between council cycles so the planning phase does less repeated work.

**Result**
Two consecutive council attempts were stopped early due to rapid thermal climb. Manual fallback closed both items cleanly. Future pacer passes will check pre-meet temperature and default to manual when warm.

**Applies to**
Any local-model council where the planning/coordination phase involves file system scanning, AST parsing, or context summarization before code generation begins.

## 2026-07-18 — Manual fallback can sustain backlog velocity when the council is thermally blocked

**Observation**
After two consecutive council starts were aborted due to rapid thermal climb, three small unit-test backlog items (`RACT Dependency Graph JSON Export`, `RACT AI SBOM Unit Tests`, `RACT Leaderboard Loader Unit Tests`, `RACT Receipt Export Unit Tests`) were completed manually in one pacer period. Each took only minutes to implement and validate, and the codebase advanced without further thermal risk.

**Upgrade**
1. Maintain a parallel "manual track" in the pacer loop: when the council is blocked by thermal, auth, or provider issues, immediately switch to manual implementation for items that are small and well-specified.
2. Use the council for exploratory or multi-file work where model reasoning adds value, and use manual implementation for single-file test/code slices where the spec is clear.
3. Track manual completions in the same council_state.json so the backlog status remains the single source of truth.
4. When the council fails to start or is stopped for environment reasons, do not let the loop idle — pick the next item and implement it manually.

**Result**
Backlog velocity remained high despite the council being thermally constrained. Operator trust is preserved because progress is continuous and documented.

**Applies to**
Any automated build loop where environmental constraints (thermal, network, provider health) can interrupt model-driven work.

## 2026-07-18 — The council cannot be started reliably even from a cool host

**Observation**
Three council start attempts were made at different starting temperatures (85 °C, 53.85 °C, 53.85 °C). All three had to be stopped: the first two reached 94.85 °C and 85.85 °C during meet/planning, and the third climbed from 53.85 °C to 71.85 °C in 20 seconds. The rate of rise (~1 °C per second initially) means there is very little safe runway before hitting the 94 °C fallback threshold.

**Upgrade**
1. Treat the council as a thermally expensive operation that is only safe when the host is well below 50 °C and has been idle for a sustained period.
2. Add a pre-start thermal slope check: if temperature has risen more than 5 °C in the last 30 seconds, abort before launching the meet phase.
3. For the current hardware profile, default the pacer to manual implementation for all single-file test/code slices and reserve council cycles for overnight or actively-cooled operation.
4. Document this hardware limitation in the pacer prompt so future sessions do not waste cycles retrying a thermally blocked configuration.

**Result**
The pacer now defaults to manual fallback for small items, preserving backlog velocity and hardware safety. Council cycles will only be attempted after explicit thermal clearance.

**Applies to**
Any local-model council running on thermally constrained hardware where repeated starts confirm an unsafe thermal trajectory.

## 2026-07-18 — Self-audit surfaced a real public-launch usability bug

**Observation**
During a routine AUDIT pass, `ract novelty scan` timed out after 60 seconds on the RACT project itself. Running the same command with `--fast` completed immediately. The default behavior was therefore broken for whole-project use, yet the tool shipped with the slow path as default.

**Upgrade**
1. Run every first-party tool on its own codebase before release; a tool that cannot analyze itself should not ship.
2. Distinguish "write-time gate" defaults from "whole-project audit" defaults in the CLI: the slow, precise mode should be opt-in (`--deep`), and the fast mode should be default.
3. When a command has both a slow-precise and a fast-approximate mode, default to the one that finishes reliably on the project's own codebase.
4. Add a regression test that exercises the default path end-to-end so the default cannot silently become unusable again.

**Result**
`ract novelty scan` now completes by default on `C:/RootClaw/rootact`. The deep leave-one-out scan remains available via `--deep` for per-write gates.

**Applies to**
Any CLI tool with multiple accuracy/performance trade-offs where the default mode must work on real-world project sizes.

## 2026-07-18 — Prompt-driven council failures require task-type detection, not just more retries

**Observation**
Recent council traces showed three recurring failure modes that survived repeated rework cycles:
1. **Module hallucination**: README-only edits and test-only tasks triggered generation of bogus `src/rootact/*.py` modules because the default preamble said "Implement this use case as new module(s) plus pytest test(s)".
2. **API invention**: Bonsai emitted calls to `rootact.signature_guardian()` and other nonexistent top-level APIs instead of importing the actual class.
3. **Stream mis-assignment**: LFM placed `low-complexity` items in the high stream, leaving Bonsai idle and wasting Qwen on trivial work.

**Upgrade**
1. Detect task type from the use-case description (`extend cli.py`, `create docs/`, `update README.md`, `add tests/test_*.py`, or new module) and route each type to a purpose-built prompt.
2. For `update_readme`, require SEARCH/REPLACE patches against README.md, forbid new Python modules, and only require a test file if the use case explicitly asks.
3. For `add_tests`, forbid creating `src/rootact/*.py` modules, require direct imports from existing modules, and provide title-specific hints so the model does not invent APIs.
4. For `council_meet`, make stream assignment deterministic by tag: `high-complexity` -> Qwen, `low-complexity` -> Bonsai, neither -> default high only when uncertain; if all items are low, still promote the hardest to Qwen.
5. Extend patch parsing to support markdown fences so README edits can use the same SEARCH/REPLACE machinery as CLI edits.

**Result**
`[REDACTED]/council/council_loop.py` now has task-aware prompts and patch handling. The first live test (artifact store unit tests) still required a thermal fallback, but the prompt changes address the root cause of the prior repeated build failures.

**Applies to**
Any local-model coding council where a one-size-fits-all "build module + tests" prompt causes models to hallucinate implementation for docs/test-only tasks.

## 2026-07-18 — Trained council prompts are still blocked by thermal runway

**Observation**
After patching `council_loop.py` with task-type-aware prompts and stream-assignment rules, two council cycles were attempted from cool hosts (49.85–56.85 °C). Both climbed to 92.85 °C within ~60 seconds. The second cycle showed an initial slower rise (10 °C in 20 s) but then jumped 33 °C in the next 20 s, indicating the SoC heat budget is exhausted almost immediately under any model load.

**Upgrade**
1. Accept that local-model concurrency is not viable on this hardware during active work; treat the council as a training/experiment tool, not the primary build engine.
2. Preserve the prompt improvements so that when thermals allow (active cooling, overnight, different hardware), the council can run correctly.
3. Continue manual implementation for all single-file slices with immediate validation; this preserves backlog velocity.
4. Add a pre-start thermal slope guard: if the host is above 55 °C or has risen more than 10 °C in 30 s, skip the council attempt and go straight to manual fallback.

**Result**
Backlog velocity is maintained by manual fallback, while the council loop now has the correct task-type routing for future use.

**Applies to**
Any local-model council that is prompt-correct but thermally constrained by the host hardware.

## 2026-07-18 — Even a single Bonsai item exceeds thermal runway

**Observation**
A third council attempt was made with a deliberately small, low-complexity item assigned to Bonsai. Starting temperature was 43.85 °C. The item was still in progress when temperature reached 93.85 °C ~50 seconds later. This confirms that the heat source is not concurrent model load or high-complexity work per se, but simply loading any local LLM backend.

**Upgrade**
1. Stop attempting council cycles until the host has active cooling or a fundamentally different thermal profile.
2. Keep the council prompts and state machine maintained so the loop can resume instantly when conditions change.
3. Use manual implementation as the primary build mode; reserve model calls for single-shot questions/audits rather than iterative build loops.
4. Add a hard personal threshold: do not start a council cycle above 40 °C or if the host has been under load in the last 5 minutes.

**Result**
No further thermal risk was taken after the third spike. Backlog velocity is maintained manually.

**Applies to**
Any local-model setup where even one loaded model pushes the SoC past safe operating temperatures.

## 2026-07-18 — Manual coverage closure is a stable, thermally safe cadence

**Observation**
After confirming the council is thermally blocked, manual implementation of small test-coverage items became the reliable mode. Each cron pass can close one small public-launch gap (a few tests, a README line) and run the full RECURSE/AUDIT suite in ~3 minutes without loading any LLM backend.

**Upgrade**
1. Treat each cron fire as a "one small slice + full validation" cycle rather than a council dispatch.
2. Keep a running list of input-sized public-launch gaps so the next item is always ready.
3. Run the full validation chain every pass; the small cost prevents regressions from accumulating.
4. Leave the trained council prompts in place for overnight or cooled hardware without retrying them during active work.

**Result**
Backlog velocity is steady and validation stays green. No thermal spikes occur because model servers are not loaded.

**Applies to**
Any pacer loop that must fall back to manual work when automated model execution is resource-blocked.

## 2026-07-18 — Redirect real filesystem paths in tests with monkeypatch

**Observation**
`cli_toggles.main()` writes to `~/.rootact/session.json` by default. Testing the resume/save branches required touching the user's actual home directory, which is unsafe and non-hermetic. Setting `HOME` and `USERPROFILE` via `monkeypatch` redirected `Path.expanduser()` to `tmp_path` without changing the implementation.

**Upgrade**
1. For any function that touches `~/<path>`, use `monkeypatch.setenv("HOME", str(tmp_path))` (and `USERPROFILE` on Windows) instead of mocking the implementation.
2. This keeps tests hermetic and parallel-safe while exercising the real `expanduser()` behavior.
3. Apply this pattern to future tests for modules that use default home-directory paths.

**Result**
`tests/test_cli_toggles.py` now covers all branches of `cli_toggles.py` without writing outside the test temp directory.

**Applies to**
Any test that needs to exercise code paths touching the user's home directory.


## 2026-07-18 — A warm start makes even single-stream Bonsai builds thermally unsafe; small coverage gaps should default to manual

**Observation**
The council run on "RACT Rot Report Missing Coverage" started at 85.0 °C and reached 94.85 °C within about three minutes while Bonsai was generating a tiny test file. The item was low-complexity and single-stream, yet the SoC had no thermal runway left after the preceding RECURSE pass and other system load. Stopping the council and implementing the test manually took seconds and produced a correct, fully-covered result.

**Upgrade**
1. Treat small coverage-gap items (one untested branch, one missing assertion) as manual-first rather than council-first; the council's value is in design-heavy slices, not one-line test additions.
2. Before starting any local-model build, require the host to be genuinely cold (e.g., <50 °C) *and* expect it to climb 10–15 °C almost immediately.
3. If a council run starts above ~80 °C, skip it and implement manually; the thermal guard will likely trigger before the build finishes.
4. Keep the fallback path fast: clear the lock, reset the item, and write the test directly so the cron loop does not stall waiting for a cooldown.

**Result**
Closed the `rot_report.py` coverage gap in one manual step with full RECURSE + AUDIT green, avoiding a likely thermal emergency.

**Applies to**
Any small, well-understood test-coverage item in a thermal-constrained local-model council loop.


## 2026-07-18 — Cross-platform path assertions must use `Path.parts`, not string suffixes

**Observation**
The first draft of `test_default_path_expands_user` asserted `str(path).endswith(".rootact/session.json")`, which passed on POSIX but failed on Windows because the separator is `\`. The failure wasted a test run and would have been emitted by a model or a collaborator on a different OS.

**Upgrade**
1. For path assertions, compare `Path.name` and `Path.parent.name` (or `Path.parts`) instead of string suffixes containing slashes.
2. Avoid hard-coding `/` or `\` in test expectations; rely on `pathlib` semantics.
3. Treat a Windows CI/run as the default expectation for path-shaped tests, not an afterthought.

**Result**
Rewrote the assertion to use `path.name == "session.json" and path.parent.name == ".rootact"`; test passes on Windows and is OS-agnostic.

**Applies to**
Any test that asserts about file-system paths across platforms.


## 2026-07-18 — Coverage gaps in symmetrical diff utilities need explicit branch tests for each asymmetric case

**Observation**
`diff_fingerprints` had tests for shared-differing keys and keys only in the second dict, but line 30 (key only in first dict) was uncovered. A symmetrical function can still have asymmetric branches, and the standard "differing keys + identical" tests do not exercise all branches.

**Upgrade**
1. For any `diff(a, b)` style function, write three minimal tests: shared keys that differ, key only in `a`, and key only in `b`.
2. Treat 100% branch coverage as the goal for small utility modules; it often requires less code than the false confidence of high line coverage.
3. Keep diff tests tiny and focused so the intent of each branch is obvious.

**Result**
One additional test closed the last branch in `run_fingerprint.py` and brought it to 100% coverage.

**Applies to**
Any symmetrical or near-symmetrical utility where branch coverage can hide behind high line coverage.


## 2026-07-18 — Security-critical verification code needs both positive and negative coverage

**Observation**
`receipt_chain.py` only had a test for `append_receipt` link hashes. The `verify_chain` function — the tamper-detection surface — was entirely untested. A public-launch release cannot claim an append-only receipt chain without tests that prove verification succeeds on valid chains and fails on corrupted ones.

**Upgrade**
1. Treat verification/integrity functions as higher priority than their producers; a broken verifier is worse than a broken appender because it gives false confidence.
2. For chain/integrity modules, always add three tests: missing/empty input, valid input passes, and a tampered input fails at the expected index.
3. When a module crosses 100% coverage, confirm that the negative case (failure branch) is included, not just the happy path.

**Result**
`receipt_chain.py` now has verified tamper detection and 100% coverage before release.

**Applies to**
Any integrity, verification, or cryptographic-check module where the failure branch is the most important behavior.


## 2026-07-18 — Import aliases prevent shadowing when CLI wires multiple renderers

**Observation**
`src/rootact/cli.py` already imported `render_html_report` from `rootact.dead_code_auction`. When wiring `RunReporter.render_html_report()` from `rootact.run_reporter`, a direct import shadowed the auction renderer and broke `tests/test_cli_auction_html.py` with `AttributeError: 'list' object has no attribute 'get'`.

**Upgrade**
1. When a CLI module imports renderers with identical names from different submodules, alias them explicitly (`render_run_html_report`, `render_run_markdown`).
2. After adding a new import to a crowded CLI file, run the full RECURSE suite immediately; shadowing errors can surface in apparently unrelated tests.
3. Keep the existing function name in the caller signature unchanged to minimize diff noise.

**Result**
The report command now supports Markdown and HTML without regressing the dead-code auction HTML report.

**Applies to**
Any CLI aggregator that wires multiple format renderers from different submodules.


## 2026-07-18 — Literal placeholders in council prompts leak into generated artifacts

**Observation**
The council format specs used `### FILE: relative/path.py` as a generic example. Qwen copied the placeholder verbatim and wrote a file at `[REDACTED]/council/staging/ract_handshake_interactive_review_queue/relative/path.py` containing `<full file content>`, which immediately failed the py_compile gate.

**Upgrade**
1. Never use literal placeholders like `relative/path.py` or `<full file content>` in format specs; models will reproduce them literally under pressure.
2. Use concrete examples (`src/rootact/cli.py`, `src/rootact/<actual_module_name>.py`) and add an explicit rule: "NEVER use 'relative/path.py' or any placeholder path."
3. After a placeholder-path failure, patch the format spec before the next cycle rather than retrying with the same prompt.

**Result**
`PATCH_FORMAT_SPEC` and `FILE_FORMAT_SPEC` now use concrete path templates and an anti-placeholder rule.

**Applies to**
Any local-model coding council or agent prompt that includes file-path examples.


## 2026-07-18 — Local LLM build calls can hang silently; endpoint health is not enough

**Observation**
The Bonsai build call for `RACT Rot Trend ASCII Visualization` hung for several minutes. The `/v1/health` endpoint showed no active models and the `/v1/models` endpoint remained responsive, but the council Python process produced no tokens and no trace output.

**Upgrade**
1. Do not rely solely on endpoint reachability; a responsive endpoint can still have a dead or stuck generation session.
2. If a model call exceeds expected latency (e.g., >5 minutes with no tokens for a small code slice), treat it as hung: stop the cycle, reset the item, and restart.
3. After a hung call, clean the stale lock file and staging directory so the next cycle starts fresh.
4. Add task-specific hints before retrying to reduce the chance of the model producing placeholder or malformed output that wastes thermal budget.

**Result**
Council was restarted with cleaned state and stronger hints; monitoring continues.

**Applies to**
Any local-model coding council where generation latency can spike or connections can stall.


## 2026-07-18 — When a model emits unstructured imports instead of FILE blocks, the task is too large

**Observation**
Qwen's second attempt at `RACT Handshake Interactive Review Queue` produced a long list of `from rootact... import ...` statements with no FILE blocks. The council recorded "no FILE blocks in model output" and the item reached `rework_cycles: 2`.

**Upgrade**
1. A model that starts enumerating imports instead of producing code is signaling that the task scope exceeds its effective working memory.
2. Split the task into input-sized slices with clear dependencies: first build the base command, then add the interactive layer.
3. Archive the oversized item rather than letting it burn cycles on a third rework.

**Result**
`RACT Handshake Interactive Review Queue` was archived and replaced by `RACT Handshake Review JSON Output` and `RACT Handshake Interactive Review Prompt`.

**Applies to**
Any council item that fails with malformed/unstructured output after prompt fixes are in place.


## 2026-07-18 — Small models invent APIs and keys when the real schema is not in the prompt

**Observation**
Bonsai's first `ract rot baseline --plot` attempt used a nonexistent `rot_score` history key and called `rootact.statistics.median`, which does not exist. It also omitted `import json` in the generated test.

**Upgrade**
1. For tasks that read from an existing data structure, list the real field names explicitly in the task hint.
2. Add explicit anti-invention rules: "DO NOT use key X, it does not exist" and "DO NOT call module.function, it does not exist."
3. For generated tests, require the model to include all imports it references.

**Result**
Rot-trend --plot hint now references `rootact.rot_trend.METRIC_KEYS` and bans `rot_score` / `rootact.statistics.median`.

**Applies to**
Any local-model task that consumes existing data structures or generates self-contained test files.


## 2026-07-18 — Hung local-model calls need a short timeout, not indefinite patience

**Observation**
Bonsai build calls repeatedly hung with no tokens generated and no endpoint activity. The council timeout was 1200s, so each hang parked progress for up to 20 minutes.

**Upgrade**
1. Reduce the per-call timeout for the hanging model so a dead connection surfaces as a transient error within minutes, not tens of minutes.
2. Treat repeated hangs as an infrastructure signal: fall back to manual implementation for the affected items and relaunch the council on the remaining backlog.
3. Document the hang pattern and timeout change so future runs benefit.

**Result**
Bonsai timeout reduced from 1200s to 300s in `council_loop.py`. Rot trend plot and README docs were completed manually while the council is prepared to continue on handshake items.

**Applies to**
Any local-model council where one endpoint is prone to stalled generation sessions.


## 2026-07-18 — Don't trust the council coordinator's complexity field; re-derive it from tags

**Observation**
LFM produced a plan that reversed the `complexity` values for two handshake items: it marked the high-complexity interactive prompt as `low` and the low-complexity JSON output as `high`. The execution code trusted the plan's complexity field, which would have routed the hard item to Bonsai.

**Upgrade**
1. Treat use-case tags as the source of truth for complexity, not the coordinator's plan JSON.
2. Normalize each planned item's complexity from its tags before routing to builders.
3. Keep the plan/ratify steps for ordering and rationale, but make the routing decision deterministic from tags.

**Result**
Added tag-based complexity normalization in `council_loop.py` before the Qwen/Bonsai routing filter.

**Applies to**
Any multi-model council where a coordinator model assigns items to workers.


## 2026-07-18 — Task-type detection regex must tolerate natural-language use-case descriptions

**Observation**
`RACT Handshake Interactive Review Prompt` was classified as `new_module` because the description did not start with "Extend src/rootact/cli.py" verbatim. The model then invented a new module with invalid Python instead of patching `_handshakes_command`.

**Upgrade**
1. Make task-type regexes flexible enough to match target paths anywhere in the description, not just immediately after the verb.
2. Add fallback heuristics for common cases (e.g., references to existing `_*_command` functions imply extend-cli).
3. A wrong task-type sends the wrong prompt, which wastes a full model call and thermal budget.

**Result**
`_detect_task_type` now recognizes extend-cli descriptions with mid-sentence target paths and existing `_handshakes_command` references.

**Applies to**
Any use-case-driven agent where prompt routing depends on regex classification of natural-language descriptions.

## 2026-07-18 — Long local-model calls must emit heartbeats to survive background runners

**Observation**
The [REDACTED] council kept dying 30-60 seconds after starting a cycle. There was no Python exception, no thermal breach (93-95 °C, below the 98 °C ceiling), and no stderr. The process simply vanished, leaving `council.lock` orphaned. Running the same code in a foreground Bash tool call worked fine and completed `council_meet()` in ~4 minutes. The difference was stdout activity: the background task runner killed the process for an idle pipe.

**Upgrade**
1. Add a lightweight daemon thread in `call_model()` that logs a heartbeat every 30 seconds until the model stream finishes.
2. Emit a heartbeat from `wait_for_cooldown()` on every poll interval so thermal pauses do not look idle.
3. Wrap each `run_cycle()` in `try/except` so a single unhandled exception logs a traceback and the run continues.
4. Add a top-level fatal-crash handler to flush any truly fatal error to stdout and the trace log.
5. On Windows, use `tasklist` (not `ps -p`) to verify python.exe liveness.

**Result**
Council cycle 143 restarted with heartbeats and remained alive while waiting on LFM; task output showed regular heartbeat lines.

**Applies to**
Any long-running local-model orchestrator launched as a background task.

---

## 2026-07-18 — Council backlog must be refilled before it empties

**Observation**
When the council crash was inspected, the backlog had only 2 active items left (one pending, one in_progress) out of ~229 titles. The user correctly pushed back that there is always more to build.

**Upgrade**
1. Maintain a buffer of at least 10-15 pending items by appending new use cases to `_BUILD/rootact_use_cases.jsonl` and `BACKLOG_TITLES` before the queue runs dry.
2. Mix high-complexity modules (Qwen) with low-complexity CLI/test slices (Bonsai) so both builders stay fed.
3. Prefer concrete, scoped items over vague epics so each cycle can land one complete slice.

**Result**
Added a 15-item wave covering CLI JSON exporters, receipt-chain provenance, session-store backup, coverage badges, and audit/report CSV/JSON outputs.

**Applies to**
Continuous council operation on RACT.

---

## 2026-07-18 — Qwen3.6 UD-Q3_K_XL was broken; reverting to UD-IQ3_XXS restored builder output

**Observation**
The council appeared idle because Qwen calls were returning no usable content. Direct API tests showed Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf on port 8106 produced empty `message.content` and `reasoning_content` that echoed the user prompt. Even simple prompts like "Say hello in one word" returned no answer. This caused every audit/build call to be unparseable, items to accumulate rework cycles, and the council to repeatedly hit the 3-cycle failure cap.

**Upgrade**
1. Kill the broken Q3_K_XL server and reload Qwen3.6-35B-A3B-UD-IQ3_XXS.gguf on port 8106.
2. Patch `call_model()` in `council_loop.py` to strip stray `<think>` / `</think>` tokens and fall back to `reasoning_content` if `content` is empty after stripping.
3. Raise Qwen audit `max_tokens` from 400 to 800 so the JSON verdict is not truncated on larger use cases.
4. Strengthen the Assumption Register hint to explicitly state that `rootact.provenance_tracker` does NOT export a `Provenance` class; only `ProvenanceRecord` and `ProvenanceTracker` exist.
5. Reset failure-capped items (`RACT Handshake Interactive Review Prompt`, `RACT Assumption Register and Decision Log`) to pending so the working model can retry them.

**Result**
IQ3_XXS with `enable_thinking: False` returns clean, parseable content. A 2048-token coding test produced `def add(a, b):\n    return a + b` with no reasoning leakage. Council cycle 143 resumed processing items after the swap.

**Applies to**
Any local-model council where a quantization or server build silently breaks a "loaded" model's output channel.

---

## 2026-07-18 — Thermal endpoint parsing was parking the council on a false "unreadable" reading

**Observation**
After fixing Qwen, the council entered a thermal pause loop: "thermal pause: unreadable >= 98.0°C; sleeping 30.0s". The [REDACTED] health endpoint was reachable, but `get_max_temp_c()` looked for `data["thermal"]["max_temp_c"]` and returned `None` when the key shape differed. `wait_for_cooldown()` then treated `None` as permanently hot and slept forever.

**Upgrade**
1. Rewrite `get_max_temp_c()` to prefer `thermal.max_temp_c` if present, otherwise compute the max across `surfaces.{cpu,gpu,npu}.temperature_c`.
2. Make `wait_for_cooldown()` resilient to unreadable sensors: after 3 consecutive unreadable reads, log a warning and resume, relying on hardware thermal safeguards.
3. Keep the hard ceiling at 98 °C and concurrency fallback at 95 °C as the user requested.

**Result**
The council no longer stalls when the thermal endpoint is transiently unreadable or reshaped. Real SoC max temp is now read correctly (94.85 °C at restart), so sequential-stream operation continues below the 98 °C ceiling.

**Applies to**
Any autonomous loop that gates work on a third-party health endpoint whose schema may drift.

---

## 2026-07-18 — Bonsai relaunch path in `council_manager.py` was pointing to a nonexistent model directory

**Observation**
When Bonsai wedged and was restarted, the manager's `BONSAI_RELAUNCH` command used `C:\RootClaw\models\snapdragon\Ternary-Bonsai-8B-gguf\Ternary-Bonsai-8B-Q2_0.gguf`, but the file actually lives at `C:\RootClaw\models\Ternary-Bonsai-8B-gguf\Ternary-Bonsai-8B-Q2_0.gguf`. The server process exited immediately with "failed to open GGUF file".

**Upgrade**
1. Correct the model path in `council_manager.py` `BONSAI_RELAUNCH`.
2. Also update `QWEN_RELAUNCH` to use the verified `llama-arm64` binary and the working `UD-IQ3_XXS` quantization so auto-relaunch matches the manually-verified setup.
3. When a server fails to relaunch, surface the server stderr log in the manager log for faster diagnosis.

**Result**
Bonsai on port 8101 was relaunched successfully with the correct path and responded to a test prompt with "Hi.". Future manager-driven restarts will use the correct paths.

**Applies to**
Any orchestrator that auto-relaunches local model servers; paths must be validated against the filesystem, not just copied from earlier configs.

---

## 2026-07-18 — Bonsai stream can accept a connection then stop sending chunks indefinitely

**Observation**
Bonsai (Ternary-Bonsai-8B-Q2_0 on CPU) repeatedly caused the council to hang with "heartbeat: still waiting on bonsai" for 5-10 minutes. The server process was alive and the connection stayed open, but no completion chunks arrived. urllib's `timeout` only guards the initial connection; once the stream started, a wedged server could block the council forever.

**Upgrade**
1. Wrap the SSE stream reader in a daemon thread that enqueues chunks.
2. Use `queue.get(timeout=chunk_timeout)` with `chunk_timeout = min(role_timeout, 90s)` so that if no chunk arrives for 90 seconds, the call raises `TimeoutError`.
3. The existing retry loop catches the timeout and retries with backoff, allowing a fresh server or transient CPU stall to recover.
4. Lower Bonsai's server timeout from 300s to 120s in `ENDPOINTS` so the server itself drops stalled requests faster.

**Result**
A wedged Bonsai call now surfaces as a retryable timeout instead of parking the council. The 90s chunk window is wide enough for Bonsai's ~3-5 tok/s CPU generation while catching true stalls.

**Applies to**
Any local-model orchestrator that streams from CPU-bound or unstable servers.

---

## 2026-07-18 — Model-specific hints must be placed in the prompt preamble, not buried in a hint function

**Observation**
The Assumption Register item kept failing because tests imported `Provenance` from `rootact.provenance_tracker`, a class that does not exist. A hint in `_new_module_hint()` forbade it, but the model ignored the instruction and used the import anyway.

**Upgrade**
1. Promote the Provenance rule into the new-module task preamble as an `IMPORT RULE` immediately after `NEW MODULE RULES`.
2. Keep the detailed `_new_module_hint()` as reinforcement.
3. State explicitly: `rootact.provenance_tracker` exports only `ProvenanceRecord` and `ProvenanceTracker`; `Provenance` must never appear.

**Result**
The rule is now in the highest-attention part of the build prompt, making it much harder for the model to hallucinate the missing class.

**Applies to**
Any prompt engineering where a specific factual constraint is repeatedly violated; constraints belong in the preamble, not only in ancillary hints.

---

## 2026-07-18 — A stream that never closes is worse than a failed request; cap total call time

**Observation**
Bonsai calls were hanging for 5-10 minutes. The server accepted the connection and occasionally emitted SSE keepalive lines, so a naive read loop never timed out. Meanwhile the server logs showed "Context size has been exceeded" errors, meaning the model could not produce a completion but did not close the response.

**Upgrade**
1. Add a total-call deadline inside `call_model()`: if `time.time() - t0 > cfg["timeout"]`, raise `TimeoutError`.
2. Combine it with a per-chunk timeout so both stalled streams and overly long genuine generation are bounded.
3. Launch Bonsai with `-np 1` so its 8192-token context is not divided across parallel slots, eliminating "Context size has been exceeded" under moderate load.
4. Keep Bonsai's timeout at 180s — long enough for its ~2.5-minute CPU prefills, short enough to avoid parking the council.

**Result**
A stuck Bonsai call now aborts and retries instead of blocking indefinitely. Subsequent Bonsai calls with `-np 1` process 2500+ token prompts without context errors.

**Applies to**
Any streaming local-model client where the server may keep a connection open despite an internal failure.

---

## 2026-07-18 — Thermal endpoint reads must tolerate slow/flaky responses without stalling work

**Observation**
The [REDACTED] thermal endpoint returns useful data but can take 4-5s to respond when the host is loaded. The original 10s timeout and the fail-safe "treat unreadable as hot" logic caused the council to sleep 30s at a time even though the real SoC temperature was well below the ceiling.

**Upgrade**
1. Increase the thermal HTTP timeout from 10s to 30s.
2. On unreadable reads, retry once after 5s; if still unreadable, log a warning and resume work.
3. Only pause for the full poll interval when a real temperature above the threshold is read.

**Result**
Thermal checks now add at most ~10s of overhead on a flaky read instead of parking the council indefinitely. Real high temperatures still trigger the full pause loop.

**Applies to**
Any loop that gates execution on a soft external sensor with variable latency.

---

## 2026-07-18 — Generated test data needs concrete syntax examples to avoid trivial bracket errors

**Observation**
Qwen repeatedly generated malformed Python list/dict literals in tests for `RACT Assumption Register and Decision Log`, e.g. `results = [{"success": True, "confidence": 0.9]}`. These py_compile gate failures wasted cycles.

**Upgrade**
Add a literal, copy-pasteable TEST DATA SYNTAX EXAMPLE to the task-specific hint, including a reminder to balance brackets.

**Result**
The hint now anchors the model to correct Python literal syntax, reducing a class of trivial gate failures.

**Applies to**
Any generated test file where the model struggles with nested literal syntax.

---

## 2026-07-20 — Manual fallback is required when a CLI verb has no dispatch target; benchmark failures must be read, not just scored

**Observation**
RACT full suite had 9 errors. Council cycles could not produce working Cost Tracker / Status Dashboard CLI verbs because Bonsai's tool cannot add new top-level functions to cli.py, and the existing `_provider_command` had been dropped during prior rewrites, leaving `provider health`/`scorecard` tests failing with `NameError`. Separately, Grove Forge trimmed validation on Qwen3.6-35B-A3B-UD-IQ3_XXS returned HumanEval 0/10 and MBPP 0/10; the debug sample shows the model emitting mixed-script gibberish and broken syntax through the raw `/completion` endpoint.

**Upgrade**
1. Add a dedicated `add_cli_verb` task type and a stable spec-to-test mapping for new verbs so the council does not have to synthesize function names and assertion values.
2. Treat 0/10 benchmark results as diagnostic data, not a verdict: inspect the raw completion. In this case the failure mode is endpoint/prompt mismatch (chat model called via raw `/completion` without a chat template), not quantization quality. Switch Grove Forge to `/v1/chat/completions` with the correct prompt template before judging the quant.
3. For modules consumed only by external council loops or kept as integration stubs, add them to `DeadCodeAuction.DEFAULT_ALLOWLIST` instead of deleting or forcing artificial in-references.

**Result**
- RACT: 1429 passed, 1 skipped.
- Provider health/scorecard verbs restored in `src/rootact/cli.py`.
- Dead-code auction now passes; four modules retained with documented allowlist reasons.
- Grove Forge: root cause identified as `/completion` gibberish on Qwen IQ3_XXS; chat-template route needed.

**Applies to**
Any council-built project where CLI verbs are added to an existing dispatch file, and any local-model benchmark that uses a raw completion endpoint with a chat-tuned model.


---

## 2026-07-21 — Grove Forge post-fix failures are model logic errors, not pipeline errors

**Observation**
After switching Qwen3.6 to `/v1/chat/completions` + `enable_thinking=false` + `splice_innermost_body()`, the extraction pipeline produces valid Python. The remaining failures are attention/logic mistakes (e.g., iterating over `list` instead of the parameter name `paren_string`). The trimmed base-stack eval scores 2/20 (HumanEval 2/10, MBPP 0/10).

**Upgrade**
1. Run `best_of_n` and `council` stacks to determine if sampling diversity fixes the issue before changing the prompt.
2. If logic errors persist, add a lightweight post-processor that detects obvious blunders like iterating over builtins or unused parameter names, or reinforce the system prompt to "use the parameter names from the signature".

**Applies to**
Any local-model code-generation benchmark where extraction works but model output contains subtle logic bugs.

---

## 2026-07-21 — Popup bash windows are not coming from current [REDACTED]/council scripts

**Observation**
Repeated popup windows showed commands like `bash -c "sleep 600 && tail -n 80 /c/RootClaw/[REDACTED]/council/council_run_..."`. `council_loop.py` and `council_manager.py` already use `CREATE_NO_WINDOW` and `pythonw.exe` for headless operation. Process inspection found no active `sleep`/`tail` processes and no [REDACTED] script containing that command.

**Upgrade**
If popups recur, capture the exact PID and command line immediately and trace the parent process. Likely sources are vestigial ad-hoc background bash commands from prior sessions or diagnostic/watchdog skills launched in visible consoles.

**Applies to**
Any long-running Windows automation where visible console windows must be suppressed.

## 2026-07-22 — Smoke-test backlog must be a subset of BACKLOG_TITLES; HTTP chunk timeout must match total budget

**Observation**
- The Qwen smoke test failed with `no pending items; nothing to do` because `smoke_test.py` wrote a backlog title that was not in `council_loop.py`'s `BACKLOG_TITLES`, so `load_backlog()` filtered it out.
- After fixing the title, the audit call failed with `TimeoutError: no stream chunk for 60s` even though the outer budget was 180 s. `council_http_client.py` hard-capped per-chunk waits at 60 s, which is shorter than Qwen's CPU prefill on these prompts.
- Both failures are infrastructure/configuration mistakes, not model quality issues, and both guaranteed a failed run regardless of how good the model output would have been.

**Upgrade**
1. Keep `SMOKE_BACKLOG_TITLES` synchronized with `BACKLOG_TITLES` and give each title a description that routes to the intended task type (e.g., `extend_cli_full_func`).
2. In `council_http_client.py`, use the full remaining call budget as the chunk window; the outer deadline still caps total wall time.
3. Add missing `BACKLOG_TITLES` records to `rootact_use_cases.jsonl` so the production catalog is complete and the council has real pending work after a smoke test.

**Result**
- Smoke-test backlog now seeds a valid pending item.
- HTTP client no longer aborts slow-but-valid local-model calls mid-stream.
- Production backlog catalog covers all 258 registered titles.

**Applies to**
Any [REDACTED] council run on CPU-bound local endpoints where prompt evaluation can exceed tens of seconds.

## 2026-07-22 — Ambiguous stop instructions cause full-file runaway in CLI rewrites

**Observation**
- Qwen's `_build_cli_function()` prompt instructed the model to rewrite one function "from `def` through the final `return`".
- For `RACT Version CLI Flag`, Qwen emitted 1900+ tokens because it interpreted "final return" as the last `return` in `src/rootact/cli.py`, dumping every subsequent function.
- The 1200-token cap did not prevent the behavior because the model ignored or misread the boundary.

**Upgrade**
1. Replace vague stop language with an exact boundary: start at `def <func>(...)` and end immediately after the function's own final `return`; stop before the next top-level definition.
2. Explicitly forbid other functions, imports, prose, and comments in the response.
3. Lower the low-complexity token cap to 768 and the timeout to 600 s so a runaway is caught sooner and cheaper.
4. Record the pattern in the learning feed so future cron passes tighten stop instructions for single-function rewrites.

**Result**
- Smoke test re-run after the fix.
- Extend-cli prompts now have a hard, unambiguous boundary.

**Applies to**
Any single-function rewrite task where the model must not continue into neighboring code.
