# Tier 3: letting RACT run a command

This page is for a user who wants RACT to run a command, such as your test runner, without a
question each time. It says what tier 3 is, why it is off by default, how to grant it, how to read
the prompts, and how to take the grant back. Every quoted line is text RACT prints.

## What tier 3 is, and why it is off

RACT sorts what a model may do into tiers. Tier 0 reads, tier 1 writes files in the project, tier 2
changes things RACT can reverse or that touch control files, and tier 3 runs a command.

Tier 3 is off until you give a grant. With no grant the status line says:

```text
T3 off (no grant)
```

A grant is a signed file in your project, `.ract/policy.yaml`. RACT checks the signature with your
operator key before it uses the file. A repository you cloned cannot grant itself tier 3: its file
does not verify under your key.

## The guided grant

You need one grant for the project's test runner. The guided flow makes it in one run:

```bash
ract policy init --guided
```

The flow does these steps, in order, and prints each one:

1. It finds the test runner from the files in the project. The line says what it found, for example
   `found the test runner: pytest` and the file it saw the runner in.
2. It proposes the narrowest rule for that runner. The rule allows one command, and each field gets
   one line. For `python -m pytest` the lines say what the rule allows, that network is off, that the
   time limit is 15 minutes, that the command starts in the step's folder, and that its home folder is
   a temporary one.
3. If the sandbox on this machine does not enforce, the network line says so. It reads
   `network: off: declared off; this machine does not enforce it`, and the flow adds
   `it runs with your user's rights on this machine`. A grant that says `sandbox: best_effort` is
   honest about that.
4. It shows the policy file as a diff before anything is written.
5. It asks `sign this rule? [y]es, sign once  [n]o, sign nothing`. Answer `n` and nothing is signed.
6. For `y` it asks for the passphrase of your operator key. The prompt reads
   `passphrase for the operator key (typed here; never read from an environment variable)`.
   Without a terminal it says `no terminal to type a passphrase at: nothing was signed`.
7. The result reads `signed: rule <id> expires <date>`, then `status line now: T3 ask`.

A new user with a test runner should reach the signed result in under two minutes. The walk that
measures this is recorded under `docs/ux/grant_walk/` when it has been run.

## The status line

The status line shows the state of tier 3. These are the states, in the words RACT prints:

| Line | What it means |
|------|---------------|
| `T3 off (no grant)` | No grant is on file. Tier 3 commands are refused. |
| `T3 off (grant expired <date>)` | A grant was on file and its date has passed. Renew it. |
| `T3 ask` | A grant holds. Each tier 3 command asks you first. |
| `T3 allowlist` | A grant holds. A command that matches an allow rule runs without asking. |
| `UNRESTRICTED (signed grant)` | Not reachable from a grant: the signing step refuses `max_mode: unrestricted` on a machine where no sandbox confines commands. |
| `T3 suspended: policy changed` | The policy file or its signature changed during this session. Tier 3 is off until you confirm the change. |

A grant that expires within seven days adds one notice at the start of a session:
`notice: the signed grant expires <when> (<date>); sign it again before then`.

## Reading an approval prompt

Before a tier 3 command runs in `ask` mode, RACT shows the question:

```text
run this command? (tier 3)
argv: python -m pytest tests/
executable: <path>
cwd: <folder>
network: off
sandbox: best effort, not enforced on this machine (<backend>)
```

It then lists the choices: `[o]nce  [s]ession  [a]lways  [d]eny`. The four words are the choices you
type (`o`, `s`, `a` or `d`, or the whole word). What each one keeps is set by ADR-0048 D6: `once`
is for this exact command and this step, `session` for a command prefix until the session ends, and
`always` for an allow rule in the policy file. Check `/permissions` after you choose `always` to see
the rule it made. `deny` refuses the command.

The line that starts with `the model says (model text, not checked):` is the model's reason. Read it
as the model's claim, not as a check.

An allow rule does not answer for every file. A test file, a conftest file or a runner configuration
file that the model wrote in this session, or that changed since you signed the grant, asks again:

```text
this file runs your tests and it changed
file: <path>
why it asks now: written by the model this session
an allow rule does not answer for it
[y]es, once  [n]o
```

### When a proposal follows fetched text

Every tool result reaches the model inside a delimiter that names where it came from (`file`, `command output`, `fetched page`, `search result`) and says it is data, not instructions. When a page RACT fetched was in front of the model before a proposal, the prompt shows one line, `follows fetched page from <host>`, and the proposal always asks: an allow rule or a "for this session" answer does not run it. Your yes clears the line for the proposals after it. (Wording for MASON.)

## The commands

- `/permissions` shows the rules, the deny rules, the largest mode, the expiry, and the sandbox line.
- `/permissions lock` closes the signing key that is unlocked in memory. The key line then reads
  `Signing key: locked; signing asks for the passphrase.`
- `/permissions resume` shows what changed in the policy file after a suspension and asks you to
  confirm it. Until you do, the status line reads `T3 suspended: policy changed`.

Session approvals do not carry over to `/resume`.

## Best effort on this machine

On Windows without WSL2 or a container, RACT cannot confine a command, and the sandbox line says so:
`sandbox: best effort, not enforced on this machine`. A grant for this machine must say
`sandbox: best_effort`, and the interface repeats it at each prompt. Treat a command run under
best effort as a command with your user's rights.

## Revoking and renewing

- To renew before the date, run `ract policy sign` again. It asks for the passphrase before it signs.
- To take a grant back, run `ract policy revoke`. It prints
  `revoked the grant <digest>: its signature is deleted and its digest is listed`.
- A grant that has expired reads `T3 off (grant expired <date>)` on the status line until you sign a
  new one.

## What tier 3 does not do

It does not run headless: a `ract -p` or CI run records tier 3 as off, and a tier-3 tool call with nobody to ask is refused and recorded as a denial, whether or not a rule matches.
It does not let `--yolo` through: `--yolo` never lifts tier 3. A command that needs an answer and
gets none is refused.
