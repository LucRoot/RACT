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

## Known issues

- At 60 columns, some lines are wider than the terminal. The checklist and the
  approval prompts are not yet folded to the width. Tracked as B-041c.

## Not covered yet

This guide will grow to cover `/sessions`, `/resume`, `/cost`, `/undo`, `/help`
and the mode line. None of these has a capture yet, so none is described here.
