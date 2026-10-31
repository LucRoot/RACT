# Setup flow: the questions, in the words we want (B-160, draft for the walk)

This is the text the setup flow should show for the four cases of D-151: a hosted endpoint with a
key, a local server by address, a preset, and a second endpoint added later. It is written before the
walk, so the walk is a check against the product: each line below is either printed as written, or
the walk records the difference and the difference becomes a card.

The current wizard (`src/ract/setup/wizard.py`) is the reference for what is printed today. Where the
draft differs, the walk says so.

## Common opening (every case)

1. `Machine:` then one line per fact about this machine (the host probe's lines), then
   `network: not tested; setup contacts only the default model-server addresses on this machine and the provider you choose`.
   The sentence stays: it says what setup touches before the first question.
2. `Looking for a model server on this machine (default ports only):`

## Case 1: a hosted endpoint with a key

- Question: `No server chosen. Use a local model or a cloud provider? [L/c]`. Answer `c`.
- Then the provider list: one line per preset, `  n) name  (key in VARIABLE)`. The name of the
  environment variable is shown; the key is not asked for.
- Question: `Which one? [1]`.
- The key step says, in these words: `Put the key in <VARIABLE> in your shell before running RACT.
  Setup never reads or stores the key.` The flow does not ask for the key. Draft change for the
  BUILDER to consider: a question is not possible without a terminal to type a secret at; the draft
  keeps setup's rule (it never takes a key) and says where the key goes.
- Health check: after the file is written the flow reports whether the variable is set. A missing
  variable prints `Skipped the health check: the key variable is not set yet. Then run: ract doctor --check-providers`.
- Error for a wrong key: not yet known. The walk records the real text the flow prints for a 401 and
  checks that it names the variable and never shows the key. Until then this line is a question, not a claim.

## Case 2: a local server by address

- The probe looks at the default addresses and at `RACT_BASE_URL` and `OPENAI_BASE_URL`.
- Line per server: `<url> answers (<label>); models: <names>`, or `... but lists no model yet; load one in it, then run setup again`.
- Question: `Use the server at <url>? [Y/n]`. Enter takes the default.
- If it reports more than one model: `Which one? [1]`.
- Unreachable address: `nothing answered`, then `No server chosen. Use a local model or a cloud provider? [L/c]`.
- Draft: an address typed by the user is not a question today (the probe reads the environment). The
  draft asks for it once when nothing answers: `Address of your model server (for example http://127.0.0.1:8080/v1), or Enter to skip: `.
  This is a proposed card (B-160a), not a change the walk makes.

## Case 3: a preset

- A preset is a cloud provider with a known address and key variable. The provider list (case 1) is
  the preset list. The walk picks one and records the printed line for it.
- Draft: after the preset is chosen, print the address it will use and the variable it reads, in one line each.

## Case 4: a second endpoint added later

- Setup writes one provider. A second endpoint is added after setup. The draft asks the user to run
  `ract setup --reconfigure` (it writes a draft and shows the differences) and says what changed.
- Draft wording: `Wrote ract.draft.yaml. Differences from ract.yaml:` then the diff, then
  `Review it, then replace ract.yaml with it to use it, or delete it.` (today's text).

## What the walk checks

- Each printed line above, at 80 and 60 columns, against the product's text.
- That no key, address with a secret, or model name is printed where it should not be.
- The error texts for a wrong key and an unreachable address, as the product prints them.

## Cards this draft suggests (not assigned)

- B-160a: an address prompt when no local server answers (case 2), with a test that the typed address
  is probed and never stored as a secret.
- B-160b: a line that names the preset's address and variable (case 3).
- B-160c: a second-endpoint path that does not need `--reconfigure` (case 4), or a documented one.
