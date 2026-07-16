# Internal Learnings from the RACT Build

This file captures concrete upgrades to the Internal/[REDACTED] runtime inspired by building and dogfooding RACT.

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
