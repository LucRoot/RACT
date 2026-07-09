# RACT Roadmap

Post-audit upgrade queue. Items are ordered by leverage for the public launch.

## P0 — Trust and correctness

1. **Enforcing novelty gate**
   - Flip `allow_novelty_overrun` default to `False`.
   - Change duplication/novelty failure action from "warn and proceed" to "reject the write and require an edit of the existing module."
   - Update `executor.py` and `novely_budget.py` tests.

2. **Real import resolution in symbol graph**
   - Move `symbol_graph.py` from name-matching to AST-based import resolution.
   - Make `load_bearing_guard.py`, `duplication_guard.py`, and `dead_code_auction.py` inherit the accurate reference graph.

3. **Coverage floor + mutation testing**
   - Add a per-step coverage-delta gate in `harness.py`.
   - Run `mutmut` or `cosmic-ray` against `executor.py`, `loop_controller.py`, `harness.py`, and `cli.py`.

4. **CI/CD pipeline**
   - GitHub Actions workflow running `ruff check`, `ruff format --check`, `mypy`, and `pytest`.
   - Add status badges to `README.md`.
   - Publish coverage badge.

## P1 — Product differentiation

5. **Model inspection tools**
   - Let the management model invoke `read`, `grep`, and `list-tree` tools before writing.
   - Close the duplication hole at the source.

6. **Consolidation mode**
   - New command: `rootact consolidate`.
   - Scans the repo for near-duplicate modules, proposes merges with diff preview, and routes through the operator handshake queue.

7. **Example project walkthrough**
   - A complete `init` → `--loop` example in `docs/` or the HF Space.

8. **Signed-receipt examples**
   - Show sample JSON receipts and explain the public-leaderboard plan.

## P2 — Ecosystem and scale

9. **Native Internal provider**
   - First-class provider that routes across local Strix Halo slots.

10. **Public leaderboard backend**
    - Accept and compare signed receipts from users who opt in.

11. **VS Code extension**
    - Surface loop status, handshakes, and receipts inside the editor.

12. **Benchmark results**
    - Compare RACT against Cursor/Claude Code on code-quality metrics.

13. **Community channel**
    - Discord or Slack for early adopters.

## Blockers

- Animated asciicast/GIF is blocked until a terminal recorder supports Windows ARM64.
- CLA assistant is blocked at the OAuth handshake step; the setup URL is open.
<!-- RACT 0.1.1 - Trust and Tooling -->
