# Message audit: the tool layer (B-144)

A reader of a refusal, an error or a hint should be able to answer three questions: what happened,
why, and what to do next. This audit reads the printed messages of the tool layer
(`src/ract/tools/`, the tool registry, the loop's refusal path) on the feature tip `b48f815` and
checks each against those three questions. It proposes a rewording where one is missing. The BUILDER
decides and lands; nothing here changes code.

Scope: the messages a user reads in a session or a headless run. Log lines for a developer
(`print(f"[module] ...")`) are not audited here.

## The three questions

- **What happened**: the call did not run, or it ran and did not do what was asked.
- **Why**: the rule, the file or the argument that decided it, named.
- **What next**: one action the user or the model can take.

## Findings

| # | Where | Message as printed | What happened | Why | What next | Proposal |
|---|-------|--------------------|---------------|-----|-----------|----------|
| 1 | `tools/__init__.py:129` | `no tool named 'x'; the tools are: ...` | yes | yes (the name) | yes (hint: call a listed tool) | keep; the list is long for 80 columns, so it folds. Fine. |
| 2 | `tools/__init__.py:144` | `<tool> arguments refused: <problems>` | yes | yes | yes (hint names the declared arguments) | keep |
| 3 | `tools/__init__.py:178` | `<tool> refused: <exc>` | yes | depends on `exc` | depends on `exc.hint` | make every `ToolRefused` carry a reason; see 9 |
| 4 | `tools/command.py:452` | `the rule's cwd leaves the step worktree` | yes | yes | yes (hint: fix the rule's cwd in `.ract/policy.yaml`) | keep |
| 5 | `tools/command.py:504` | `the executable changed after it was resolved; nothing ran` | yes | yes | hint: `<exe> was replaced or rewritten; ask again` | keep; the hint repeats the cause and gives the action. Good. |
| 6 | `tools/write.py:272` | `an empty body is refused` | yes | not said | yes (`write the file's full content`) | **why is missing**: propose `an empty body would erase <rel>; nothing was written`. |
| 7 | `tools/write.py:277` | `<rel> exists; create refuses it` | yes | yes | yes (`pass expected_digest to replace it`) | keep |
| 8 | `tools/write.py:331` | `<dest> exists; move_file refuses it` | yes | yes | yes (`choose a new destination`) | keep |
| 9 | `tools/read.py:111` | `the path is refused` (default when the resolver gave no error) | yes | **not said** | not said | propose: `the path is outside the project or is a RACT control file; nothing was read`, and make the default name the reason it had. |
| 10 | `tools/read.py:406,408` | `the pattern was refused: <ripgrep first line>` | yes | yes (ripgrep's line) | yes (`fix the regular expression`) | keep; the ripgrep line may be long: fold it, it already is |
| 11 | `tools/read.py:498` | `the pattern was refused: <reply error>` | yes | yes | yes | keep |
| 12 | `tools/tests_tool.py:137` | `refused: <matcher reason>` | yes | yes (the matcher's reason) | yes (`name tests inside the project`) | keep; the leading `refused:` repeats the `refused` of the call line: propose dropping it so the reason reads first. |
| 13 | `tools/loop.py:217,258` | a refused call, status `refused`, error `rooted.error or "refused"` | yes | **not said** when `error` is empty | hint may be empty | propose: never print a bare `refused`; the default is `the tool did not say why; nothing ran`. |

## Rewordings proposed (for the BUILDER)

1. `tools/write.py:272`: `an empty body is refused` becomes `an empty body would erase <rel>; nothing was written` (hint unchanged).
2. `tools/read.py:111`: when the resolver gives no error, print `the path is outside the project or is a RACT control file; nothing was read`.
3. `tools/loop.py:258` and the refusal status: replace the bare default `"refused"` with `the tool did not say why; nothing ran`.
4. `tools/tests_tool.py:137`: drop the leading `refused: ` so the matcher's reason reads first: `the rule does not allow this test selector` (the reason text stays the matcher's).
5. `tools/__init__.py:178`: every `ToolRefused` must carry a `reason` (the "why") and a `hint` (the "what next"); a `ToolRefused` built without a reason is a test failure, not a message.

## What is good

Most refusals name the file, the argument or the rule that decided them, and give one next action
(items 1, 2, 4, 5, 7, 8, 10 and 11 above). The message that says a path changed, and the one that
says the executable was replaced, are the best in the layer: they say what did not run and why.

## How to check the rewordings

Each proposal is one line change in a message; the test that pins the old wording (where there is one)
is changed with the reason, as the card asks. The B-145 conformance harness renders the screens; these
messages are not screens, so they need the unit tests of their modules, not a fixture.
