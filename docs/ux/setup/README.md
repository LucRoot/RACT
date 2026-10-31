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
