# B-028: confining commands on Windows (design note, before code)

Status: proposal for the MANAGER and the operator. Nothing here is built yet.
Slice (e)'s Linux path (B-114) runs a tier-3 command inside bubblewrap only
after a self-test proves the confinement; Windows has no such path. This note
says how B-028 would add one without weakening what the grant and the prompt
promise.

## What is on this machine

A read-only check is the first step of the card, and it waits for the B-046
slot to end (it starts `wsl.exe`). What the lane reported for B-046: WSL 2 with
Ubuntu-24.04, stopped. Docker Desktop's data lives on F:. Neither is installed
or changed by B-028.

## The WSL2 backend

The command runs as `wsl.exe -d <distro> -- bwrap ... <argv>` with the step
worktree mounted at `/workspace` from its `/mnt/<drive>/...` path, and the
same self-test as B-114 run inside WSL first.

Three questions decide whether it is honest:

1. **Which program runs.** The matcher resolves and hashes a Windows
   executable (G-214 M3, G-215 C3). Inside WSL the program is a Linux one
   found on WSL's PATH. The grant's rule then names a different file than the
   one the operator approved. Proposal: a grant rule may say
   `backend: wsl2`, and for such a rule the matcher resolves the name inside
   WSL (`wsl.exe -- command -v <name>`), hashes that file through
   `\\wsl$\...`, and the prompt shows the Linux path. A rule without it never
   runs in WSL.
2. **bubblewrap inside WSL.** It is a system package (`apt install
   bubblewrap`), outside D1's scope (no apt, no sudo). If it is missing, the
   self-test fails and the result is `best_effort`, as now. Installing it is
   the operator's decision.
3. **Files through /mnt.** The worktree is on NTFS through WSL's 9P mount.
   bubblewrap can bind it, but a Windows process outside WSL can still change
   it during the run. That is the same as the Linux case for the worktree
   (it is the command's workspace); the confinement claim covers what the
   command can reach, not what the host can.

## The container backend

Behind the same interface: `docker run --rm --network none --read-only
-v <worktree>:/workspace -w /workspace <image> <argv>` with the image named
in the grant rule (`backend: container`, `image: <name>@sha256:<digest>`).
The image must already be present (`docker image inspect`); B-028 pulls
nothing. The self-test runs in the same image. Docker Desktop's VM is the
boundary; a rule whose image is not pinned by digest is refused at load.

## The low-integrity experiment

A one-off experiment, not a backend: run a probe at low integrity
(`icacls`-style mandatory label on a copy of the worktree, process started
with a low-IL token) and record what it could and could not write, read and
reach. The result is a report under `docs/`, whatever it shows; it does not
change `sandbox_confines_commands()` unless a later card says so.

## What stays the same

Where no backend proves itself, the result, the prompt and `ract doctor
--sandbox` say `best_effort` and a grant that says `enforced` does not hold.
Tier 3 stays off by default, and `--yolo` never runs it.

## Questions for the operator

- May a grant rule name `backend: wsl2` (the program then comes from WSL)?
- Install bubblewrap inside WSL (outside D1), or leave the WSL backend
  `best_effort` until he does?
- Is a container backend wanted at all on this machine, and with which
  pinned image?

## Code so far (D-142, 2026-10-30)

- A grant rule may say `backend: wsl2` or `backend: container` with `image: <name>@sha256:<digest>`; a container rule without a digest-pinned image is refused at load.
- Such a rule is refused at run, with the reason, until its backend is wired: nothing runs on the host in its place (`tests_tool.run_under_rule`).
- `ract.security.other_backends`: `resolve_in_wsl` finds the program on WSL's PATH and hashes it through `\\wsl$`; `ContainerBackend` renders `docker run` (network none, read-only root, no new privileges, the worktree at `/workspace`, `--pull=never`) and checks the image is present. Both run through an injectable runner; the tests start no WSL and no Docker.
- `ract doctor --tier3` lists both backends and why they do not run yet.
- Not done: the WSL self-test and the run path (bubblewrap in WSL is the operator's row D4), and any image (nothing is pulled).
