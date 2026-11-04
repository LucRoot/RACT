# Slice (c) walkthrough: J4 with run_tests under a grant (B-112)

A real pseudo-terminal walk (D-003) of J4 at 80, 60 and 40 columns, recorded by
`python -m tests.ux.run_slice_c` against the fake model server. **No command
runs in it:** `RACT_FAKE_RUNNER` points the run at a scripted runner, every
result it gives says it ran nothing, and such a run never verifies a turn.
The grant is signed with a throwaway key in a temporary user config folder.
The PATH holds a placeholder `python` (never run) and git's own folder, so the
prompt names no program of the recording machine. The walk runs this
checkout's code (`python -m ract.cli`, `PYTHONPATH` on its `src`).

## Journeys

| Id | What it walks | Ends with |
|---|---|---|
| SC1 | `tests/test_calc.py::test_add fails, fix it` with a signed grant: the fix's step is approved, then the named test asks to run (`Tier 3: run a command? python -m pytest tests/test_calc.py::test_add`, the program, the folder, network off and not enforced, the sandbox not enforced, the rule, the model's reason) and the operator says yes. | the scripted run; "not verified: the scripted runner answered; no command ran" |
| SC2 | The same, and the operator says no. | "not verified: you declined the command; nothing ran" |
| SC3 | The same with no grant. | nothing asked; "not verified: tier 3 is off: no grant" |

## Answers per task (condition 3)

| Task | 80 | 60 | 40 |
|---|---|---|---|
| fix a failing test and run it | 2 | 2 | 2 |
| fix it, decline the run | 2 | 2 | 2 |
| fix it with no grant | 1 | 1 | 1 |

The median is 2, under the package's limit of 3.

## What a real run adds

With the real runner (not in this walk, since no command runs in RACT's own
recordings), a yes runs the command and the summary says `verified: verified`
or `failed`, shows `ran: python -m pytest tests/test_calc.py::test_add, exit
0`, ends the verdict with "the named test passed." or "failed.", and says
"command records are in the trace; they are not part of the signed Rootknot".
`tests/test_j4_named_test_runs.py` checks those lines with a stand-in runner
that executes nothing.

## Not in this walk

- The hosted model (the run, with a real grant and the real runner on the
  operator's machine).
- The allowlist mode (slice d), shell mode, enforced limits (slice e).
- the screens for the slice.
