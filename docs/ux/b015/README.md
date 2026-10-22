# First-run walkthroughs (B-015)

Recorded with `python -m tests.ux.run_baseline --out docs/ux/b015 --only S1,S2,S3,S4`:
the real `ract` executable in an 80 by 40 pseudo-terminal (ConPTY on Windows),
an empty directory, and the scripted fake model server. Each journey has a
plain transcript (`S*.txt`), the raw terminal bytes and a timeline.

| Journey | What happens | Questions | Measured |
|---|---|---|---|
| S1 | Empty directory, not a git repository; a server found through `RACT_BASE_URL`; then one question in the session | 3 (set up now, use this server, git init) | setup offer at 2.0 s, working prompt at 4.2 s, first answer at 6.0 s |
| S2 | No server answers: local guidance, then a config for Ollama's default address | 4 (set up now, local or cloud, memory, start or skip) | health check fails with the "nothing is answering" hint; the session opens |
| S3 | A server answers but lists no model | 4, as S2 | the server is shown with "load one in it", not offered |
| S4 | Ctrl-C at the first setup question | 1 | "setup stopped; nothing was written"; no file left |

Time budget for a first run: three minutes (G-056). S1 reaches a working
prompt in 4.2 s on a loaded machine; the rest of a real first run is the
user starting a model server, which setup cannot speed up.

## Findings while recording

- S3, fixed before these recordings: a server that lists no model was
  offered, setup wrote a placeholder model name, and the health check failed
  with a bare "HTTP 404".
- S2, fixed: when nothing answered, the "Looking for a model server" line had
  nothing under it; it now says "nothing answered".
- S1, fixed: after setup, the last line said "run `ract` to open a session"
  while the session was already opening; it now says so.
- Detection took 2.3 s because a refused connection on a closed loopback
  port takes about 2 s on Windows; the probe's connect timeout is now 0.5 s
  (as for providers, B-043).
- Open, not fixed: on Windows, a Ctrl-C pressed within a few milliseconds of
  a prompt appearing, before Python's `input()` starts reading, is held until
  the next Enter. One recording sent Ctrl-C 16 ms after the prompt and setup
  stopped only when the next line arrived. Later recordings, with the
  keystroke a moment after the prompt, stop within 5 ms. This affects every
  `input()` prompt, the session's included.
- The suggested memory share is 60 percent of the memory available at that
  moment. On a busy machine (these recordings: 64 GB total, 8 GB available)
  that suggests a small model; the question shows the number and the user
  can type another.
