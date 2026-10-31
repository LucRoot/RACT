# Setup: getting a model (draft chapter for the user guide, B-143 sibling)

Status: draft. Every line in quotation marks is what `ract setup` prints today on the feature tip,
taken from the walk records in this folder. Where a capture is missing the line says `capture pending`.
Nothing here is a claim about a provider's service; RACT ships no model.

## Before you start

`ract setup` looks for a model server on this machine (the default ports only) and asks where your
model comes from. It does not download anything, and it never reads or stores your key. You put the key
in an environment variable in your shell; the config refers to the variable by name.

## Case 1: a hosted endpoint with a key

1. Answer `c` at `No server chosen. Use a local model or a cloud provider? [L/c]`.
2. Pick a provider from the list, one line each, `n) name  (key in VARIABLE)`.
3. Set the variable in your shell. The flow writes `ract.yaml` and says whether the variable is set.
4. If it is not set: `Skipped the health check: the key variable is not set yet. Then run: ract doctor --check-providers`.

Capture: `hosted_key_unset_80.txt` (the variable not set). With the variable set: `capture pending` (the
check that sends one request needs the preset override, walk script `walk_cases.py`, not yet run).

## Case 2: a local server by address

1. Setup finds a server on a default port, or on the address in `RACT_BASE_URL` or `OPENAI_BASE_URL`.
2. `Use the server at <address>? [Y/n]`. Enter takes the default.
3. The flow writes `ract.yaml` and makes one tiny request: `ok: the model answered`.

Captures: `local_server_80.txt` and `local_server_60.txt` (the 60-column one is not wrapped; see the README).

## Case 2b: nothing answers at the default addresses

Today the flow writes a config for Ollama's default address and the check then fails:
`failed: Request failed: nothing is answering at http://127.0.0.1:11434/v1 (connection refused).`
Capture: `unreachable_setup_80.txt`. The address prompt (B-160a) is not yet built; this chapter will
show it when it lands.

## Case 3: a preset

A preset is a provider with a known address and key variable. The preset's address is printed when it
is chosen (B-160b, not yet built). The variable is the same as in case 1.
Capture: `capture pending`.

## Case 4: a second endpoint added later

Run `ract setup --reconfigure`; it writes `ract.draft.yaml` and shows the differences, then asks you to
replace `ract.yaml` with it or delete it. A path that adds a second provider without this step is
B-160c, not yet built.
Capture: `capture pending`.

## Wrong key and unreachable address

- A wrong key shows as `HTTP 401` with the key masked as `********` in `ract doctor --check-providers`
  (capture: `wrong_key_doctor_80.txt`). The key is sent only to a host you paired with it in
  `RACT_KEY_HOSTS`.
- Setup's own check for a keyed preset is not walked yet.
