# Setup walks (B-160), on the feature tip 1a7d33d, fake servers, throwaway HOME

Three walks, real pseudo-terminal, `ract setup` in an empty temporary folder with a throwaway HOME. The
transcripts are verbatim (escape sequences removed by the driver).

- `local_server_80.txt`, `local_server_60.txt`: case 2 (a local server by address). The probe finds the
  server named in `RACT_BASE_URL` (a fake server); the flow asks `Use the server at ...? [Y/n]`, writes
  `ract.yaml`, makes one tiny request (`ok: the model answered`), and offers `git init`.
- `hosted_key_unset_80.txt`: case 1 (a hosted endpoint, key variable not set). The walk declines the local
  server, picks a provider from the list, and the flow writes `ract.yaml` and skips the health check
  with the line that names the variable.

Not walked: case 1 with the key set. A preset names a real provider address, so the health check would
send a request to that provider. That is outside a fake-server walk, and it needs a base-url override for
presets before it can run on fake servers (a proposed card, B-160d).

## Findings for the BUILDER (the file and the line of each transcript)

1. `hosted_key_unset_80.txt`: the provider list shows local presets with an empty variable: `  3) llamacpp  (key in )`,
   `4) lmstudio  (key in )`, `5) ollama  (key in )`, `8) vllm  (key in )`. A local server has no key
   variable, so the line should say `(no key needed)` or name nothing at all, not an empty `(key in )`.
2. The same transcript: `Which one? [1] 1` shows the chosen digit echoed after the prompt. Harmless, noted.
3. Width is NOT established by these records. The 60-column record has lines of 91 to 124 characters
   (for example the `Next:` line), so the driver stored the output unwrapped. The check that every line fits
   at 60 columns needs a wrapped capture, which this walk did not make.
4. The `Run git init here now? [y/N]` question is asked after the config is written, so a user who says `n`
   is still told the config works. Read as intended; no change asked.

## Second round (wrong key and unreachable address), 80 columns, fake servers, throwaway HOME

- `wrong_key_doctor_80.txt`: `ract doctor --check-providers` with `ract.yaml` naming a fake server (a 401 that echoes the key it was sent, masked by RACT as `********`), the key in `ZZ_WALK_KEY` (throwaway value), and `RACT_KEY_HOSTS` pairing that variable with the fake server's host and port. The key value appears in no record. The 401 text reads `chat: failed (HTTP 401: ...)`, and the advice line says the key and host pair and the tiny request failed.
- A first attempt had no `RACT_KEY_HOSTS` pairing; RACT then refused to send the key to the unpaired address and printed `the key in ZZ_WALK_KEY is not paired with 127.0.0.1:<port>, so RACT does not send it there`. That is a designed refusal and it is recorded in the run log, not here.
- `unreachable_setup_80.txt`: `ract setup` with `RACT_BASE_URL` naming a closed port. The flow says `nothing answered`, asks `L/c`, asks memory and model questions for a local model, writes `ract.yaml` for Ollama's default address (11434) after the user presses Enter with nothing answering, then the check reports `connection refused` and the hint `start your model server, or fix the provider url in ract.yaml`.

Findings for the BUILDER (wording, not claims about the product beyond the transcripts):
1. Setup writes a config for an address nothing answered, before the health check, and the check then fails. The B-160a address prompt would have let the user type the address they run. This is the same gap as B-160a.
2. The memory and model sizing questions appear for a user who chose a local model with no server running; the sizing text is long at 80 columns. A walk at 60 columns is still not wrapped (see the README's first round).
3. The wrong-key text is reached only when the key is paired with the host (`RACT_KEY_HOSTS`). Setup does not say that pairing is needed. Setup's own check reads the key variable only when a preset with a key is chosen, and that path is not walked (it needs B-160d). Until it is walked, the wrong-key text in the setup flow is unknown; the text above is from `ract doctor --check-providers`.
