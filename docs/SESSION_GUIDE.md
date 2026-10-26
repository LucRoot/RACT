# Session guide

This page shows what a session looks like. Every sample is copied from a
capture in `docs/ux/guide/`. The captures use a fake model server with a
scripted scenario, so they show RACT's output, not a real model's answers.
The header of each capture says how it was made.

## Start a session

Run `ract` with no arguments in the project folder. The session keeps its
settings and the context of each turn until you exit.

(The start screen is not captured in this batch; the first lines of the checklist capture show it.)

```text
 RACT 0.5.2  config: ract.yaml  type an intent, or /help for commands
RACT session fake-coder via local | master | default | T3 off
ract> add a greeting in src/calc.py and two tests
```

## Ask for a change and read the plan

Type what you want changed. RACT plans first. With two or more steps, the plan
prints as a checklist. Each step's line changes as the step starts and ends:
`[ ]` pending, `[>]` running, `[x]` passed, `[!]` failed or refused, `[-]`
skipped. The final block at the end of the turn shows the state of every step.

```text
ract> add a greeting in src/calc.py and two tests
Plan (3 steps):
  assumes: The failing test needs add() fixed, a notes module, and a test for it.
[ ] 1. Fix add() in src/calc.py so it adds -> src/calc.py
[ ] 2. Add src/notes.py with the NOTE constant -> src/notes.py
[ ] 3. Add tests/test_notes.py that checks NOTE -> tests/test_notes.py
[>] 1. Fix add() in src/calc.py so it adds -> src/calc.py
Approve step: [local] Fix add() in src/calc.py so it adds -> src/calc.py? [y/N]:   ... waiting on model (4 s)
y
--- src/calc.py ---
def add(a, b):
    return a + b




def sub(a, b):
    return a - b
[x] 1. Fix add() in src/calc.py so it adds -> src/calc.py (8.5s) passed
```

Read the checklist top to bottom. A step marked `[x]` passed its check. The
duration and the file are on the same line.

## Approve each step

In the default mode RACT asks before each step writes a file. Answer `y` to
run the step, or anything else to decline it.

## Plain output for a screen reader or a log

Start RACT with `--plain`, or set `TERM=dumb`. Plain mode turns off color and
box drawing, and labels the lines you type with `you:`. The same three-step
change, in plain mode:

```text
 RACT 0.5.2  config: ract.yaml  type an intent, or /help for commands
RACT session fake-coder via local | master | default | T3 off
you: add a greeting in src/calc.py and two tests
Plan (3 steps):
  assumes: The failing test needs add() fixed, a notes module, and a test for it.
[ ] 1. Fix add() in src/calc.py so it adds -> src/calc.py
[ ] 2. Add src/notes.py with the NOTE constant -> src/notes.py
[ ] 3. Add tests/test_notes.py that checks NOTE -> tests/test_notes.py
  ... waiting on model (4 s)
[>] 1. Fix add() in src/calc.py so it adds -> src/calc.py
Approve step: [local] Fix add() in src/calc.py so it adds -> src/calc.py? [y/N]: y
--- src/calc.py ---
def add(a, b):
    return a + b




def sub(a, b):
    return a - b
[x] 1. Fix add() in src/calc.py so it adds -> src/calc.py (0.1s) passed
```

## See your earlier sessions

`/sessions` lists the saved sessions, newest first, with the id, the time, and
the last request. The turn and cost columns show `-`: the session file does not
store them yet.

```text
ract> /sessions
Sessions
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ Id                   ┃ Updated          ┃ Turns ┃ Cost ┃ Last request        ┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ repl-20261023-090000 │ 1970-01-12 05:48 │ -     │ -    │ rename the greeting │
│                      │                  │       │      │ helper and update   │
│                      │                  │       │      │ its tests           │
│ repl-20261022-110000 │ 1970-01-12 05:47 │ -     │ -    │ fix the parser so   │
│                      │                  │       │      │ it stops on empty   │
│                      │                  │       │      │ input               │
│ repl-20261022-100000 │ 1970-01-12 05:46 │ -     │ -    │ add a docstring to  │
│                      │                  │       │      │ hello.py            │
└──────────────────────┴──────────────────┴───────┴──────┴─────────────────────┘
```

`/resume` switches to one of them, by id, or to the newest with `latest`:

```text
✓  resumed repl-20261023-090000, last request: rename the greeting helper and up
```

## Check what the model has been sent

`/context` says what the last model request used, as the server reported it, and
what RACT does not know. It sends no request. The window is shown as unknown
unless a server reported one, and the turn count is not stored yet.

```text
ract> /context
last request used 167 tokens in, 55 out (reported by 127.0.0.1)
window: unknown (run ract doctor --check-providers to measure it)
turns: not stored in the session file
```

## A question that completes

This capture uses the fake server's `j1_no_tools` scenario. Its reply is the same
JSON envelope for every message, so the answer below is not an answer to the
question. The run completes, and it shows two things a user would notice:
`/ask` prints a plan first, and it prints the reply as raw JSON.

```text
ract> /ask what does add() do in src/calc.py?
Plan: 1 step, confidence 1.00
  assumes: The user asked a question; the answer is shown and no file is
    written.
  1. what does add() do in src/calc.py?
[step 1] what does add() do in src/calc.py?
{"final":"Hello. I answer in the JSON format you asked for."}
[step 1] done (0.3s)
  Done: 1 step ran; no tests were run.
  changed: nothing
  verified: RACT ran no tests this turn
  1 model request, 2.1 s, 167 tokens in / 15 out
```

## Mode, cost and undo

`/mode` shows how RACT applies changes. `/cost` shows the requests this session
sent off the machine. `/undo` reverses the last turn's file changes, and says so
when there is none.

```text
ract> /mode
default: RACT asks before each step that changes a file
ract> /cost
no requests left this machine
ledger: C:\Users\rootl\AppData\Local\ract\egress.jsonl (ract doctor --egress for history)
ract> /undo
nothing to undo: no turn RACT can reverse is recorded here
```

## Ask a question

`/ask` answers a question about the code, with no plan and no file written. The
capture below is a failed run: the fake server returned an empty reply.

```text
ract> /ask what does add() do in src/calc.py?
Plan: 1 step, confidence 1.00
  assumes: The user asked a question; the answer is shown and no file is written.
  1. what does add() do in src/calc.py?
[step 1] what does add() do in src/calc.py?
[step 1] failed (0.1s)
error: Step 1 returned an empty answer. The model returned an empty response instead of a answer.
hint: the model sent an empty reply for that step; run it again, or set a stronger model for this provider in ract.yaml
no files were changed
  The turn failed.
  changed: nothing
  verified: RACT ran no tests this turn
  1 model request, 1.0 s, 167 tokens in / 10 out
```

## Known issues

- At 60 columns, some lines are wider than the terminal. The checklist and the
  approval prompts are not yet folded to the width. Tracked as B-041c.
- `/ask` prints a plan and runs a step. `/help` says `/ask` makes no plan, so
  one of the two is wrong. Reported as a FOUND for the BUILDER.
- The `/ask` error says "returned an empty answer instead of a answer". The
  article is wrong. Reported as a FOUND.
- Whether the empty reply is a scenario mismatch or a defect is not checked.
  The capture does not show it.
- At 80 columns, the `/resume` summary line can wrap in the middle of a word
  (the capture above shows `up` and `pdate` on two lines). Reported as a
  FOUND for the BUILDER; the guide does not hide it.

## Not covered yet

This guide will grow to cover the full `/help` table and a successful question.
Neither has a capture yet, so neither is described here.
