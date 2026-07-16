# RACT Build Log

This log records each pacer pass through the RACT codebase. It exists because context compacts and the written record is the remedy.

## 2026-07-16 — Pacer resumed; GitHub v0.1.2 release shipped; thermal guard added to [REDACTED] council loop

**What changed**
- Recreated the RACT/Internal progress-pacer cron (job `2418862f`, every 5 minutes).
- Shipped the GitHub release for **RACT 0.1.2**: https://github.com/LucRoot/RACT/releases/tag/v0.1.2
- Added a thermal monitor to `[REDACTED]/council/council_loop.py` that disables cross-surface concurrency when the host reports ≥ 70 °C or the thermal sensor is unreadable.
- [REDACTED] council loop is running cycles 19–21 (2 rework items: Public Receipt Leaderboard, Tamper-Evident Receipt Chain).

**Test/lint/type result**
- `ruff check src tests scripts`: passed (last full run).
- `ruff format --check src tests scripts`: passed.
- `mypy src tests`: passed.
- `pytest -q`: 1160 passed, 1 skipped (last full run).

**Self-audit result**
- Thermal status: **94.85 °C** at fire time; council loop correctly fell back to sequential streams.
- Models healthy: qwen (8106), bonsai (8101), lfm (8107) all `{"status":"ok"}`.

**Next action**
- Let the council loop finish its 3-cycle run; if the two rework items still fail, triage the failure logs and either split the tasks smaller or fix the seed tests manually.

## 2026-07-16 — Council pacer pass 1: loop still running, thermal at 85 °C, no intervention

**What changed**
- Council pacer cron fired (job `4fea8255`).
- Council loop `bash-bemf9d0n` is still running cycle 20; `Tamper-Evident Receipt Chain` is in progress on BONSAI.
- `Public Receipt Leaderboard` has landed in `rework` for two consecutive cycles (19 and 20).
- Thermal read 85 °C, so no new model work was started.

**Test/lint/type result**
- Skipped: council is actively modifying files; recuse/audit deferred until idle.

**Self-audit result**
- Thermal status: **85.0 °C** — above the 80 °C pacer start threshold.
- Council lock active; no reset performed because an item is `in_progress`.

**Next action**
- Wait for the current 3-cycle run to finish. If `Public Receipt Leaderboard` is still `rework`, reset it or split the use case smaller before the next council run.

## 2026-07-16 — Council pacer pass 2: cycle 21 started, both items still rework, thermal 87.85 °C

**What changed**
- Council pacer cron fired (job `4fea8255`).
- Council loop finished cycle 20 with no items applied; both `Public Receipt Leaderboard` and `Tamper-Evident Receipt Chain` are now `rework`.
- Cycle 21 began immediately after; lock is still active.
- Thermal read **87.85 °C**; no new council run was started (existing run continues).

**Test/lint/type result**
- Skipped: council is actively modifying files.

**Self-audit result**
- Thermal status: **87.85 °C** — above the 80 °C pacer start threshold.
- Both rework items have failed across cycles 19 and 20. They are likely under-specified or have brittle seed tests.

**Next action**
- Let cycle 21 finish. Once the loop is idle, reset both rework items and, if they fail again, split their use cases into smaller input-sized slices before the next run.

## 2026-07-16 — Council pacer pass 3: cycle 21 BONSAI in progress, thermal climbing to 90.85 °C

**What changed**
- Council pacer cron fired (job `4fea8255`).
- Cycle 21 plan: 0 high, 2 low; `Public Receipt Leaderboard` is `in_progress` on BONSAI.
- Thermal read **90.85 °C** and rising.

**Test/lint/type result**
- Skipped: council is actively modifying files.

**Self-audit result**
- Thermal status: **90.85 °C** — above the 80 °C pacer start threshold.
- Council lock active; no reset performed.

**Next action**
- Continue monitoring. If thermal exceeds 95 °C, stop the current council run to protect hardware; otherwise let cycle 21 finish and then triage the rework items.

## 2026-07-16 — Council pacer pass 4: BONSAI still on Public Receipt Leaderboard, thermal 89.85 °C

**What changed**
- Council pacer cron fired (job `4fea8255`).
- Cycle 21 BONSAI call for `Public Receipt Leaderboard` has been in progress since the last fire; no new output yet.
- Thermal read **89.85 °C** (slightly down but still high).

**Test/lint/type result**
- Skipped: council is actively modifying files.

**Self-audit result**
- Thermal status: **89.85 °C** — below the 95 °C emergency ceiling, so the run continues.
- The BONSAI timeout is 1200 s; the item may still be generating.

**Next action**
- Wait for the next fire. If the item is still in progress and thermal stays high, consider whether the BONSAI timeout/backstop needs to be shorter for pacer-paced work.

## 2026-07-16 — Council pacer pass 5: Public Receipt Leaderboard fails for third consecutive cycle; Tamper-Evident Receipt Chain now in progress

**What changed**
- Council pacer cron fired (job `4fea8255`).
- Cycle 21: `Public Receipt Leaderboard` failed again (third cycle in rework). `Tamper-Evident Receipt Chain` is now `in_progress` on BONSAI.
- Thermal read **85.0 °C**.

**Test/lint/type result**
- Skipped: council is actively modifying files.

**Self-audit result**
- Thermal status: **85.0 °C** — run continues.
- `Public Receipt Leaderboard` has failed in cycles 19, 20, and 21. It needs manual triage or a smaller split after the run finishes.

**Next action**
- Let cycle 21 finish. Once idle, reset `Public Receipt Leaderboard` and split its use case into smaller slices before the next council run.

## 2026-07-16 — Council pacer pass 6 (15-min interval): resumed loop running, BONSAI on HTML Headers, thermal 90.85 °C

**What changed**
- Pacer interval changed to every 15 minutes; cron job `fa640475` fired for the first time.
- Council loop `bash-8312078h` is running cycle 21 with the new split backlog.
- Plan: 0 high (QWEN), 4 low (BONSAI); `Public Receipt Leaderboard - HTML Headers` is `in_progress`.
- Thermal read **90.85 °C**.

**Test/lint/type result**
- Skipped: council is actively modifying files.

**Self-audit result**
- Thermal status: **90.85 °C** — above start threshold; existing run continues.
- 15-minute cadence avoids the status-only fires seen under the 5-minute schedule.

**Next action**
- Wait for the council run to progress. If `Public Receipt Leaderboard - HTML Headers` lands, the JSON Loader slice will be next.

---

# Council Pacer Cron (current)

**Date:** 2026-07-16
**Job ID:** `c430002b`
**Schedule:** `*/15 * * * *` (every 15 minutes)
**Purpose:** Closed build-audit-learn loop that drives the [REDACTED] council instead of doing direct implementation.

**Model roles in the council**
- **Qwen 3.6 35B A3B UD-IQ3_XXS** (`http://127.0.0.1:8106`) — high-complexity builder, plan ratifier, and review ratifier.
- **Ternary Bonsai 8B Q2_0** (`http://127.0.0.1:8101`) — low-complexity builder; currently handles most input-sized backlog slices.
- **LFM 2.5 8B Q4_0** (`http://127.0.0.1:8107`) — council coordinator: plans, splits, audits.

So Qwen is the senior/primary ratifier and high-complexity worker, but Bonsai is the primary implementation worker for the low-complexity slices that make up the current backlog.

**Full prompt (verbatim, so it can be recreated exactly):**

```text
You are the RACT council pacer. This is a closed build-audit-learn loop that drives the [REDACTED] council. Every 15 minutes, advance the loop by exactly one concrete step and document everything.

COUNCIL STATE
- Council script: C:/RootClaw/[REDACTED]/council/council_loop.py
- Status command: /c/RootClaw/rootact/.venv/Scripts/python C:/RootClaw/[REDACTED]/council/council_loop.py --status
- Start command: /c/RootClaw/rootact/.venv/Scripts/python C:/RootClaw/[REDACTED]/council/council_loop.py run --cycles 3
- Reset item command: /c/RootClaw/rootact/.venv/Scripts/python C:/RootClaw/[REDACTED]/council/council_loop.py --reset-item "<TITLE>"
- Backlog titles are defined in BACKLOG_TITLES inside council_loop.py and use cases come from C:/RootClaw/rootact/_BUILD/rootact_use_cases.jsonl.

THE LOOP
1. CHECK COUNCIL STATUS: run the status command and use TaskList/TaskOutput to see if the council loop background task is running.
2. THERMAL CHECK: read http://127.0.0.1:11435/v1/health and extract max_temp_c. If it is >= 80 C or unreadable, DO NOT start new model work. Document and wait for the next fire.
3. BUILD RACT (via the council):
   - If the council loop is not running and temperature is safe, start it in the background with --cycles 3.
   - If it is running, inspect the latest output. If an item has been in rework for two or more consecutive cycles, reset it so the council can retry with a fresh plan, OR edit the use-case/backlog to split the task into smaller input-sized slices.
   - If all current backlog items are done or already_implemented, add the next highest-leverage public-launch task to the backlog. Prefer tasks that close public-launch gaps: README/CI badges, demo asciicast, Why RACT comparison table, HF Space static page, earned-coverage/mutation gate, ract consolidate, native Internal provider, MCP adapter, skill marketplace, run report. Use the Pipeline Skill for complex specs.
4. RECURSE (only when the council is idle): run the test suite, ruff, mypy, and any relevant smoke checks in C:/RootClaw/rootact. Fix regressions immediately.
   - pytest -q
   - ruff check src tests scripts
   - ruff format --check src tests scripts
   - mypy src tests
5. AUDIT (only when the council is idle): run RACT's own tools against RACT. Treat any failure as a bug to fix.
   - ract auction
   - ract novelty scan
   - ract doctor
   - ract fence
6. DOCUMENT OBSESSIVELY: after every meaningful change or status update, write or update a concise log entry in docs/BUILD_LOG.md. Context compacts; the written record is the remedy. Include: what changed, why, test result, thermal, next action.
7. EXTRACT LEARNINGS: every loop pass, note one concrete upgrade inspired by the RACT build (e.g., timeout handling, retry policy, model routing, provider fallback, context curation, error classification, thermal governance, backlog splitting). Append it to docs/INTERNAL_LEARNINGS.md.

NEVER wait for user input. NEVER declare the project "done." Keep the council moving. At the end of each pass, state the next concrete action and why.
```
