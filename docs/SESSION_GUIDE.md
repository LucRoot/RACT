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

This capture uses the fake server's `ask_read_calc` scenario (`docs/ux/guide/ask_read_calc.txt`).
The model reads `src/calc.py` through the read-only loop before it answers. The answer is the
scenario's scripted text: the fake server wrote it, and no model answered the question.

The `read_file` line shows the read. The answer names the file and the line it read, and the
`citations` line shows that RACT checked that reference against the file.

```text
ract> /ask what does add() do in src/calc.py?
Plan: 1 step, confidence 1.00
  assumes: The user asked a question; the answer is shown and no file is
    written.
  1. what does add() do in src/calc.py?
[step 1] what does add() do in src/calc.py?
  > read_file(limit=20, offset=1, path='src/calc.py')  [T0]
    ok 0.0s  read_file(limit=20, offset=1, path='src/calc.py')
add() in src/calc.py:2 returns a - b, so it subtracts instead of adding.
[step 1] done (0.2s)
  Done: 1 step ran; no tests were run.
  changed: nothing
  verified: RACT ran no tests this turn
  citations: 1 verified, 0 unverified
  2 model requests, 1.2 s, 783 tokens in / 54 out
ract> /exit
```

## Mode, cost and undo

`/mode` shows how RACT applies changes. `/cost` shows the requests this session
sent off the machine. `/undo` reverses the last turn's file changes, and says so
when there is none.
`/review` goes through the last turn's changes hunk by hunk: accept, reject
(the turn's saved copy of that hunk comes back), edit or skip each one.

```text
ract> /mode
default: RACT asks before each step that changes a file
ract> /cost
no requests left this machine
ledger: C:\Users\you\AppData\Local\ract\egress.jsonl (ract doctor --egress for history)
ract> /undo
nothing to undo: no turn RACT can reverse is recorded here
```

## Review a change, then undo it

After a turn that changes files, `/review` walks each hunk. `a` accepts it, `r` rejects it, `e` edits it
(type the new lines, then a line holding only a dot), `s` skips it, `A` accepts the rest of the file and
`R` rejects the rest. `/undo` puts back the version from before the turn for the files the turn kept.
The capture below is a real run: one turn that changed three files, then the review and `/undo`.

```text
Hunk 1 of 1 in src/calc.py:
src/calc.py: lines 1-5 -> 1-5, +1 -1
1   def add(a, b):
2 -     return a - b
2 +     return a + b
3
4
5   def sub(a, b):
a accept, r reject, e edit, s skip, A accept the rest of the file,
R reject the rest of the file
answer:a
Hunk 1 of 1 in tests/test_calc.py:
tests/test_calc.py: lines 7-9 -> 7-13, +4 -0
 7   
 8   def test_sub():
 9       assert sub(5, 3) == 2
10 + 
11 + 
12 + def test_sub_zero():
13 +     assert sub(1, 0) == 1
a accept, r reject, e edit, s skip, A accept the rest of the file,
R reject the rest of the file
answer:e
Type the new lines for this hunk. End with a line holding only a dot (.).       
> def test_sub_zero():
>     assert sub(1, 0) == 1
> .
Hunk 1 of 1 in src/notes.py:
src/notes.py: lines 1-0 -> 1-1, +1 -0
1 + NOTE = "two"
a accept, r reject, e edit, s skip, A accept the rest of the file,
R reject the rest of the file
answer: r
src/calc.py: kept as the turn left it
tests/test_calc.py: 1 edited
src/notes.py: removed again (the turn created it)
ract> /undo
restored src/calc.py to the version before the turn
restored tests/test_calc.py to the version before the turn
ract> /exit
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

- The checklist, the approval prompts, `/help`, `/cost`, `/mode`, `/settings` and
  `/model` fold to the terminal width, down to 40 columns. The 40 and 60 column
  checks are in `docs/ux/ux_bar_check.md`.
- The `/ask` reply prints a `Plan: 1 step` line before the answer, and `/help` says
  `/ask` makes no plan, so one of the two is wrong. Reported as a FOUND for the BUILDER.
- The `/ask` error says "returned an empty answer instead of a answer". The
  article is wrong. Reported as a FOUND.
- Whether the empty reply is a scenario mismatch or a defect is not checked.
  The capture does not show it.
- The `/resume` summary now wraps at word boundaries at 80 columns
  (`docs/ux/c_journeys/resume_80.txt`).

## Not covered yet

This guide will grow to cover the full `/help` table and a successful question.
Neither has a capture yet, so neither is described here.
