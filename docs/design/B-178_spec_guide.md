# B-178: a guided spec, first slice (design)

Status: proposal by the lane for the MANAGER, 2026-11-01. Where the MANAGER has not decided, this slice builds the proposal below.

## What this is, in one paragraph

Some people start with an idea, not a plan. RACT asks a short list of questions, one at a time, writes the answers into a spec (a short document), and asks the person to approve it section by section. Later runs read the spec, so the plan is built from what the person meant.

## The questions (asked in this order, one at a time)

1. What do you want to exist when it is done? (one sentence)
2. Who uses it, and what do they do with it?
3. What must it do? (list the main things)
4. What must it not do?
5. How will we know it works? (something we can see, count or run)
6. What limits do we have? (time, money, tools, people, the machines we use)

Each answer is kept as written. A blank answer is asked again, once, with an example. Question 6 may be skipped.

## What the spec file looks like

`SPEC.md` at the top of the project, in plain Markdown, with six sections in this order: Goal, Users,
Must do, Must not do, How we will know, Limits. Each section holds the model's draft in short sentences. An acceptance line is one the person can check by looking, running or counting ("the command prints the total"). "It is fast" is not checkable; the harness asks for a number instead.

## Where it is stored, and what is checked

- The spec is `SPEC.md` in the project. It is an ordinary file the person can open, edit and commit.
- The harness also writes `.ract/spec_hash.txt`: the SHA-256 of `SPEC.md` at the moment the person
  approved it. RACT's private folder `.ract` is never sent to a model, so the hash is never read by one.
- Before approval the harness checks that every section exists and each acceptance line is checkable (it names a number, a command, a file, or one of the words "prints", "shows", "exists", "passes", "returns", "counts").

## How approval works

- The person reads one section at a time. The answer is `y` (keep it), `e` (type the replacement, which
  is kept as written), or `n` (the model drafts it again from the same answers).
- Nothing is written to `SPEC.md` until every section is approved. Before that the draft is in
  `.ract/spec_draft.json`.
- An abandoned walk leaves the draft in place. `/spec` on the next visit offers to continue it.

## How it hands off to a plan

- A later run reads `SPEC.md` as context for the planner. It is data the person wrote, not an
  instruction: the planner may cite it, and nothing else in RACT changes.
- The planner's first line names the spec and its hash. If the file changed since approval, the
  planner says so and asks.

## For a weak model

The same questions are asked, and the harness checks every draft. A draft that fails the check is drafted again once, then shown with the reason.

## Screens

Each question is one screen: the question, one example, the prompt. The approval screen shows the section, then `y`, `e` or `n`. Colour, where used (B-179), only marks the question and the section name; every screen reads the same with colour off.

## Decisions the first slice needs

1. Location: `SPEC.md` at the project root (the card's choice). Proposed: keep it.
2. The planner reads the spec: proposed yes, as context only.
3. The six sections above, in that order. Proposed: keep them; the card did not fix a list.
4. An abandoned walk keeps its draft. Proposed: yes, in `.ract/spec_draft.json`.

## Not in the first slice

The roles loader (B-172), any change to the planner, and any check of the spec against tests. Those are later slices.
