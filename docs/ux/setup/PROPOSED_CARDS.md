# Proposed cards from the setup walk (B-160)

Each card has an acceptance line: the check that says it is done. None is assigned. The walk records
(`local_server_80.txt`, `local_server_60.txt`, `hosted_key_unset_80.txt`) are the evidence for the first
three findings; the others come from the question draft (`QUESTIONS_DRAFT.md`) and are not yet walked.

## B-160a: an address prompt when no local server answers (case 2)

- Today: when the probe finds nothing, the flow goes to the cloud list. A user with a server on another
  address has no way to give it.
- Proposal: when nothing answers, ask once: `Address of your model server (for example http://127.0.0.1:8080/v1), or Enter to skip:`.
- Acceptance: a typed address is probed with one tiny request; a refused or silent address prints
  `nothing answered at <address>`; the typed value is written to `ract.yaml` as an address, never to any
  file as a secret; a test with a fake server covers both answers.

## B-160b: a line that names a preset's address and variable (case 3)

- Today: after a preset is chosen the flow names the variable only.
- Proposal: print the address the preset uses and the variable it reads, one line each.
- Acceptance: the walk at 80 and 60 columns (wrapped capture, not the unwrapped driver output) shows both lines; no key value appears.

## B-160c: a second endpoint without `--reconfigure` (case 4)

- Today: a second endpoint means `ract setup --reconfigure`, which writes `ract.draft.yaml` and shows differences.
- Proposal: either a documented path that adds a provider to `ract.yaml`, or the draft text stays and the
  user guide says so.
- Acceptance: after the change, a walk adds a second endpoint and `ract doctor --check-providers` lists both.

## B-160d: a base-URL override for presets (needed to walk the key-set hosted case)

- Today: a preset names a real provider address, so the health check contacts that provider. A fake-server
  walk cannot cover the hosted case with the key set.
- Proposal: an environment override for a preset's base URL, used only by tests and walks, documented as such.
- Acceptance: with the override set to a fake server and the key variable set to a throwaway value in a
  temporary folder, the walk prints `ok: the model answered` and the key value appears in no output and no file.

## B-160e: empty key variable in the provider list (finding from the walk)

- Today: local presets print `(key in )` with nothing after `in`.
- Proposal: print `(no key needed)` for a preset with no key variable.
- Acceptance: the provider list shows `(no key needed)` for llamacpp, lmstudio, ollama and vllm, and the
  existing cloud rows are unchanged.

## Not yet walked (stated, not claimed)

- Wrong-key error text (401) and unreachable-address text: the real text is not known until the walk runs
  with a fake server that returns a 401 and with a closed port.
