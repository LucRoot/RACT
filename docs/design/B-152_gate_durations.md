# B-152: why the full gate takes an hour, and what makes it shorter

Status: report and plan. The changes and the two measured gate runs follow.

## The baseline

Gate on `8e7268e`, run on 2026-10-31 on the shared machine, with `--durations=50`:
6512 passed, 60 skipped, 0 failed, in 57:38 (3458 s), with 6570 tests collected.
The card's figure of 47 minutes was measured on a quieter machine.

The 50 slowest test phases add up to 749 s, or 22% of the run. The other 78% is the long tail:
about 6500 tests at half a second each. A target of 35 minutes (2100 s) means saving about
1360 s. Fixing only the slowest tests cannot reach that. The plan has to make the common
case cheaper.

## The slowest phases and their causes

| Seconds | Test | Cause |
|---:|---|---|
| 127.7 | `test_wheel_smoke.py::test_wheel_builds_and_entry_points_work` | Builds the wheel, makes a fresh virtual environment and installs the wheel **with its dependencies** through pip (resolver and package cache, and the network when the cache misses) |
| 63.0 | `test_cli_json_cheat_sheet.py::test_cli_json_cheat_sheet_commands_exist` | Two `python -m ract.cli` processes per listed command (`--help`, then the JSON form) |
| 45.6 | `test_benchmark_refactor_token_usage.py::test_benchmark_contender_is_strictly_better` | Runs both loop runners three times, five iterations each, in process |
| 34.3 | `integration/test_step_base_snapshot.py::test_run_prints_the_left_out_notice` | A real `ract` run in a git workspace with generated files (CLI subprocess plus git) |
| 22.9 | `property/test_transaction_atomicity.py::test_rollback_is_ten_second_verifiable` | A property test whose own name sets a ten-second bound per rollback |
| 8 to 20 each | `test_headless.py`, `security/test_repository_trust.py` (82.8 s in all), `integration/test_kill_mid_step_resume.py`, `test_bare_run_asks.py`, `test_egress_ledger.py`, `test_cut_off_and_unparsable_files.py`, `journeys/*` | Each starts the real CLI as a subprocess against the fake model server, often more than once, in a fresh git workspace |

The other 37 rows are mostly the same last kind. All ten of the slowest files checked start a
subprocess, through `subprocess` or the `run_baseline` helpers. Across the suite, 126 call
sites start `python -m ract...` directly.

## The common cost: starting the CLI

`python -c "import ract.cli"` takes 1.4 s on this machine. Bare Python takes 0.28 s. The
import profile (`python -X importtime`) shows where the time goes:

| Module imported by `ract.cli` at load time | Cumulative ms |
|---|---:|
| `ract.doctor` (and `ract.harness` under it) | 238 |
| `ract.core.keys` (and the executor and core packages) | 184 |
| `ract.builtin_skill_library` (skills registry, manager) | 103 |
| `ract.complexity_router` (providers) | 92 |
| `ract.tui` (rich console) | 73 |

Most CLI commands use none of `doctor`, the skill library or the TUI. Every subprocess test
pays for them anyway.

## The plan

Each change keeps every test and every assertion. None is deleted or skipped.

1. **Import these modules only where used.** In `ract.cli`, `doctor`, the skill library
   and the TUI move into the commands that use them. That saves about 0.4 s for every CLI
   start, in tests and for users. Check: the architecture import tests and the CLI tests.
2. **The wheel smoke test installs only the wheel.** It makes the virtual environment with
   `--system-site-packages` and installs with `--no-deps --no-index`. It still builds the
   wheel, installs it into a fresh environment and checks the version and every entry point.
   Expected saving: about 100 s. It also stops a gate from reaching the package index.
3. **The cheat-sheet test runs each command once in process.** It calls the CLI's `main`
   with the arguments and captures stdout. One subprocess check stays, to show
   `python -m ract.cli` itself starts. The assertions are unchanged: each command exists,
   and its JSON parses. Expected saving: about 55 s.
4. **Gate shards.** `tools/gate_shards.py` splits the test files into N groups, balanced by
   the previous run's durations. It runs one pytest process per group at the same time and
   adds up the counts, keeping the same count check. This is the only change that reaches
   35 minutes on a loaded machine. Two shards should bring the wall time close to half.
   Before it is used for a gate, one run must show that no test shares state across
   processes (fixed ports, the user state folder, the source tree), and the counts must
   equal a serial run's. The MANAGER decides whether a sharded run counts as the gate. It
   uses more cores at once on a shared machine.

Changes 1 to 3 together should save roughly 300 to 500 s; the measured runs will say. The
target needs change 4.

## Measurement

The card asks for two gate runs on the same machine after the changes, each with
`--durations=50`. The counts must match the baseline: the same collected number, and 0 failed.
