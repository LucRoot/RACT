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
