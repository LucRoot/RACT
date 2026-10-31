# R-001 rehearsal: the history repair on throwaway clones (B-153)

Status: rehearsed on 2026-10-31 by the BUILDER. Nothing was run on the real
repository's history or on any remote. Nothing was pushed or tagged.

R-001 rewrites the author identities and commit messages of the whole history
with `git filter-repo`, so that private names and one wrong identity leave the
published history. The file contents are not changed (option A). This page
records what the repair does when run on a throwaway clone of the history as
it is today, and how to undo it.

## How it was run

`tools/r001_rehearsal.py` repeats every check below. It takes the source
repository, the repair kit (`mailmap.txt` and `msg_cb.py`, the message
callback), a work folder and a terms file:

```
python tools/r001_rehearsal.py <repository> <kit dir> <work dir> <terms file>
```

The terms file lists the private terms, one per line: the ones the kit was
written for, and every term of the closed-IP wordlist in
`tests/test_release_surface.py`. It stays outside the tracked tree, so this
page and the script name none of them.

The script clones the repository with `git clone --no-local` (the source is
only read), makes a local branch of every branch, removes the remote, and
records the state. Then it runs the repair and records the state again. On a
second clone, standing in for the real repository, it adopts the rewritten
refs and then undoes that from a mirror backup. The work folder was deleted
afterwards.

## What was found

The rehearsal ran twice, with two kits.

**The kit as tested at T-021** (`BOARD/r001/`) does what it was written for:
its own terms leave every message, and the wrong identity leaves every commit.
But it fails the closed-IP wordlist. Commit messages on the published refs
(`main` and the tags) still name ten wordlist terms: reviewer-dispatcher
names, an operator path and the private workspace name, 31 hits in all. The
feature branch carries some of the same. The T-021 kit did not list these
terms.

**The extended kit** adds one rule per remaining wordlist term to `msg_cb.py`.
Each rule changes the term to neutral wording ("second-pass reviewer",
"provider dispatcher", "workspace"). It also adds one `mailmap.txt` line for
a misspelled form of the operator's own name. That form appears only on local
review branches. The extended kit passes every check:

| Check | Before | After |
|---|---|---|
| Commits | 1340 | 1340 |
| Branches and tags | 189 and 15 | 189 and 15, same names |
| Tree of every branch and tag | | unchanged on all 204 refs |
| Tracked files at the feature tip (2328) | | byte for byte identical |
| Messages naming a private term (29 terms, all refs) | up to 37 per term | 0 for every term |
| Identities on the refs to push (`main`, tags, feature) | 3, one of them wrong | 2, both the operator |
| Time for the rewrite itself | | 6.3 s (the whole script about 3 minutes) |
| Undo: adopt the rewritten refs, then restore from the mirror | | every ref back to its original commit |

Each check's "before" number is from the same clone just before the rewrite.
The trees are unchanged, so the source digest, the golden hashes and every
test stay as they are. Commit ids change on 203 of the 204 refs, because the
earliest commits' messages change.

## Findings that become cards

1. **The kit needs the extended rules** before the operator runs it. Without
   them, the repair push would publish the wordlist terms again. The extended
   `msg_cb.py` and `mailmap.txt` are in the BUILDER's log entry for the
   MANAGER to put in `BOARD/r001/`. The board is not committed.
2. **Two `rootact/step/<id>` branches are in the real repository.** They were
   left by a RACT run on 2026-10-27 and carry test identities (`example.invalid`,
   `ract@localhost`). They are local only, and the push of `main`, the tags and
   the feature branch does not include them. They should be deleted by the
   operator, or never pushed. A step branch left in the operator's repository
   is also a product question, with B-146.
3. **Two forms of the operator's name** are on the published history:
   "Dr. Lucas Root, Ph.D." and "Lucas Root" (140 commits on `main`). Both use
   the operator's address, so the check accepts both. One more mailmap line
   would make them one. This is the operator's call. It costs nothing extra,
   since every commit id changes anyway.

## How the operator runs it, and how to undo it

The repair never changes the repository it reads. It writes a new clone
(`<repository>` is the operator's checkout, `<release copy>` a new folder):

```
bash <kit dir>/run_r001.sh <repository> <release copy>
```

**To undo the rewrite itself,** delete that folder. The original repository was
never changed:

```
rm -rf <release copy>
```

**If the rewritten refs are later brought back into the original repository,**
first make a mirror backup, so that the step can be undone:

```
git clone --mirror --no-local <repository> <backup>.git
```

The one-line undo then restores every branch and tag from it:

```
git -C <repository> fetch --force --prune <backup>.git "refs/heads/*:refs/heads/*" "refs/tags/*:refs/tags/*"
```

The rehearsal tried this on its stand-in clone. Every ref came back to its
original commit.

**Not tried:** the real repository has worktrees, and git refuses to move a
branch that a worktree has checked out. Bringing the rewritten refs back into
the real repository would need every worktree's branch released first. The
simpler path is to push from `<release copy>` and keep the original as it is.
The exact commands are B-155's (`RELEASE_COMMANDS.md`).
