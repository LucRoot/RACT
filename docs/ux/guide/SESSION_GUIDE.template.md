# Session guide

This page shows what a session looks like. Every sample is copied from a
capture in `docs/ux/guide/`. The captures use a fake model server with a
scripted scenario, so they show RACT's output, not a real model's answers.
The header of each capture says how it was made.

## Start a session

Run `ract` with no arguments in the project folder. The session keeps its
settings and the context of each turn until you exit.

(The start screen is not captured in this batch; the first lines of the checklist capture show it.)

{{sample checklist_three_steps.txt 6 8}}

## Ask for a change and read the plan

Type what you want changed. RACT plans first. With two or more steps, the plan
prints as a checklist. Each step's line changes as the step starts and ends:
`[ ]` pending, `[>]` running, `[x]` passed, `[!]` failed or refused, `[-]`
skipped. The final block at the end of the turn shows the state of every step.

{{sample checklist_three_steps.txt 8 26}}

Read the checklist top to bottom. A step marked `[x]` passed its check. The
duration and the file are on the same line.

## Approve each step

In the default mode RACT asks before each step writes a file. Answer `y` to
run the step, or anything else to decline it.

## Plain output for a screen reader or a log

Start RACT with `--plain`, or set `TERM=dumb`. Plain mode turns off color and
box drawing, and labels the lines you type with `you:`. The same three-step
change, in plain mode:

{{sample plain_three_steps.txt 6 26}}

## See your earlier sessions

`/sessions` lists the saved sessions, newest first, with the id, the time, and
the last request. The turn and cost columns show `-`: the session file does not
store them yet.

{{sample sessions_help_resume.txt 53 66}}

`/resume` switches to one of them, by id, or to the newest with `latest`:

{{sample sessions_help_resume.txt 68 68}}

## Check what the model has been sent

`/context` says what the last model request used, as the server reported it, and
what RACT does not know. It sends no request. The window is shown as unknown
unless a server reported one, and the turn count is not stored yet.

{{sample context.txt 8 11}}

## A question that completes

This capture uses the fake server's `ask_read_calc` scenario (`docs/ux/guide/ask_read_calc.txt`).
The model reads `src/calc.py` through the read-only loop before it answers. The answer is the
scenario's scripted text: the fake server wrote it, and no model answered the question.

The `read_file` line shows the read. The answer names the file and the line it read, and the
`citations` line shows that RACT checked that reference against the file.

{{sample ask_read_calc.txt 7 22}}

## Mode, cost and undo

`/mode` shows how RACT applies changes. `/cost` shows the requests this session
sent off the machine. `/undo` reverses the last turn's file changes, and says so
when there is none.
`/review` goes through the last turn's changes hunk by hunk: accept, reject
(the turn's saved copy of that hunk comes back), edit or skip each one.

{{sample ask_cost_undo.txt 8 14}}

## Review a change, then undo it

After a turn that changes files, `/review` walks each hunk. `a` accepts it, `r` rejects it, `e` edits it
(type the new lines, then a line holding only a dot), `s` skips it, `A` accepts the rest of the file and
`R` rejects the rest. `/undo` puts back the version from before the turn for the files the turn kept.
The capture below is a real run: one turn that changed three files, then the review and `/undo`.

{{sample review_three_files.txt 78 117}}

## Ask a question

`/ask` answers a question about the code, with no plan and no file written. The
capture below is a failed run: the fake server returned an empty reply.

{{sample ask_cost_undo.txt 15 27}}

## Known issues

{{known_issues}}

## Not covered yet

This guide will grow to cover the full `/help` table and a successful question.
Neither has a capture yet, so neither is described here.
