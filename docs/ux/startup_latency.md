# Startup and latency (package L, ux-next)

Ten runs each on this machine, 2026-10-26, Windows 11, Python 3.11.15, after the
package H matrix. Raw numbers in `docs/ux/startup_latency_raw.txt`. Times are wall clock
from the command line to the end of the output (or to the first prompt for the REPL).

| Measure | Median | Worst (n=10) |
|---|---|---|
| `ract --help` | 1.36 s | 1.47 s |
| `ract --version` | 1.33 s | 1.58 s |
| REPL start to the `ract> ` prompt | 1.64 s | 2.27 s |
| `/help` in the REPL, from send to output quiet for 1 s (the 1 s is subtracted) | 0.07 s | 0.08 s |

## Five slowest imports at REPL start (`python -X importtime`, cumulative)

These are the imports that `ract --version` triggers (the same chain the REPL start uses).

| Module (cumulative) | Owner | Saving if lazy |
|---|---|---|
| `httpx` (293 ms, via `ract`) | providers (not MASON's lane) | up to about 290 ms at start for commands that never call a provider |
| `ract.providers.schema` (214 ms, via `ract.providers.conformance`) | providers (not MASON's lane) | about 210 ms |
| `ract.core.keys` (161 ms) | core (not MASON's lane) | about 160 ms |
| `ract.builtin_skill_library` and `ract.skills_registry` (275 ms, shared with `ract.manager`, imported at the top of `src/ract/cli.py` lines 16 and 52) | CLI verbs (BUILDER) | about 270 ms if the skill library loads on first use |
| `ract.harness` (145 ms) | harness (senior-only) | about 140 ms |

## What is in MASON's lane

The modules MASON owns (`ract.tui` 4 ms, the renderer, the REPL command text) cost nothing
at startup: `ract.repl` and `ract.session_render` are not imported by `ract --version`.
No lazy import in the lane saves more than 100 ms, so none was made. The measured savings
above are the handoffs.

## Handoffs (owner, file, change)

- BUILDER, `src/ract/cli.py` lines 16 and 52: import `BuiltinSkillLibrary` and `SkillRegistry`
  inside the functions that use them. Saving about 270 ms on `--help`, `--version` and the REPL start.
- Providers (BUILDER): import `httpx` inside the adapters that send requests, and `ract.providers.schema`
  where the conformance check needs it. Saving up to about 500 ms together.
- Core (senior-only): `ract.core.keys` at import time (161 ms).
- Harness (senior-only): `ract.harness` at import time (145 ms).

## After B-087 (2026-10-29)

Ten runs of `python -m ract.cli --version` each, same machine, same day, before and after.

| Measure | Before (`de3fb1c`) | After |
|---|---|---|
| `ract --version`, median | 1.155 s | 0.975 s |
| `ract --version`, fastest and slowest | 1.131 s, 1.369 s | 0.930 s, 1.007 s |
| `import ract.cli` (`-X importtime`, cumulative) | 1.004 s | 0.724 s |

What loads on first use now: the provider conformance suite and the structured-output schema
(`ract.providers.conformance`, `ract.providers.schema`), the response validator
(`ract.providers.validator`, which pulled in `ract.core.actions`), and the loop controller and
loop planner in `ract.cli`. Names importable from `ract.providers` are unchanged (PEP 562).

Not done, and why: `httpx` (about 170 ms) is imported at module level by `ract.egress_ledger`,
whose transport classes subclass `httpx` types, and by four other modules; making it load on first
use is a change to the egress ledger and is left as its own card. The `ract` package's
re-exports (about 200 ms) are kept: the package lists them so the dead-code auction sees those
modules as used, and loading them on first use would hide them from it. The median is below
1.0 s, so the card's second part (`ract.core.keys`, `ract.harness`) was not started.

## After B-087b (2026-10-30)

Ten runs each of `python -m ract.cli --version` and `--help`, same machine, same hour, before
(the feature tip with B-087) and after.

| Measure | Before (B-087) | After |
|---|---|---|
| `ract --version`, median | 1.107 s | 0.970 s |
| `ract --version`, fastest and slowest | 1.071 s, 1.143 s | 0.927 s, 1.024 s |
| `ract --help`, median | 1.146 s | 0.940 s |
| `import ract.cli` (`-X importtime`, cumulative) | 0.943 s | 0.809 s |

`httpx` is no longer imported at start. The egress ledger builds its transport classes when the
first client is made (`egress_ledger.client`); `ract.cli` imports `httpx` only in the one command
that catches its error; the OpenAI-compatible provider, the MCP adapter and the capability probe
take it through `ract.lazy_import.lazy_module`, which imports it at the first attribute read. What
a request sends or records is unchanged; the egress tests pass as they were.

Against the first measurement (1.33 s), `ract --version` is now about 0.36 s faster, short of the
0.4 s the card names. The largest parts left are the `ract` package's re-exports (kept for the
dead-code auction, see above) and `ract.core.keys`.
