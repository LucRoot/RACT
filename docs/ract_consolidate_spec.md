# ract consolidate design specification

## Overview
The `ract consolidate` subcommand transforms RACT's static duplication detection into an interactive cleanup workflow. It identifies near‑duplicate modules, groups them by similarity, presents a unified diff preview, queues merge proposals for operator approval, and applies approved merges using existing RACT infrastructure.

## 1. Detection of near‑duplicate modules
- **SymbolGraph** is loaded to represent the module dependency graph.
- **CompressionNoveltyDetector** computes a similarity score for each pair of modules based on byte‑level compression of their source files.
- Modules whose similarity exceeds a configurable threshold are marked as candidates for consolidation.

## 2. Grouping candidates by similarity
- Candidates are clustered using a simple agglomerative algorithm:
  1. Start with each candidate in its own group.
  2. Iteratively merge the two groups with the highest average similarity until no pair exceeds a secondary merge threshold.
- The resulting groups represent sets of modules that can be safely merged into a single representative module.

## 3. Unified‑diff merge preview
- For each group, a **unified diff** is generated that compares the current state of all members against the target merged module.
- The diff is rendered in the standard RACT format and displayed to the operator, highlighting added, removed, and modified code.
- The preview includes a summary of total lines changed and a list of affected files.

## 4. Queuing merge proposals in HandshakeRegistry
- Each diff preview is packaged into a **MergeProposal** object containing:
  - The target module name.
  - The list of source modules to be merged.
  - The unified diff.
- The proposal is enqueued in the **HandshakeRegistry** with a unique identifier and a status of `PENDING`.
- Operators can review proposals using the `ract propose` command and approve or reject them via `ract approve <proposal-id>`.

## 5. Applying approved merges
- When a proposal is approved, the merge is executed by either:
  - **DiffApplier**, which writes the diff directly to the filesystem, or
  - **SymbolRenamer**, which updates all references to the merged modules in the SymbolGraph and rewrites import statements.
- After a successful merge, the involved modules are removed from the graph, and the SymbolGraph is updated to reflect the new structure.
- The HandshakeRegistry entry is marked as `COMPLETED`, and a confirmation message is emitted.

## Integration points
- **src/ract/symbol_graph.py** – provides the graph representation and utilities for adding/removing nodes.
- **src/ract/compression_novelty_detector.py** – supplies the similarity scoring function.
- **src/ract/dead_code_auction.py** – can be reused for the clustering logic if desired.
- **src/ract/diff_applier.py** – handles the actual file writes for approved merges.
- **src/ract/handshake_registry.py** – manages the queue of merge proposals and their lifecycle.
- **src/ract/symbol_renamer.py** – performs reference updates when a merge involves name changes.
- **src/ract/cli.py** – will be extended with a new `consolidate` subcommand that orchestrates the above steps.

## Implementation notes
- All thresholds (similarity, merge, and approval) should be configurable via command‑line flags.
- The spec assumes that the existing RACT environment already has a populated SymbolGraph and that the novelty detector can be instantiated without additional dependencies.
- Error handling should propagate failures from DiffApplier or SymbolRenamer back to the operator with clear messages.

## Risk mitigations

### 1. Merge safety validation
Before any proposal is enqueued, the candidate group must pass a **merge-safety check**:
- **Import reachability**: for every source module in the group, verify that all public symbols it exports are either (a) also present in the target module after merge, or (b) re-exported via an alias, so external callers remain resolvable.
- **Circular-dependency check**: compute the strongly connected components (SCCs) of `SymbolGraph` before and after the simulated merge; if a new SCC is created or an existing one grows, flag the proposal for manual review.
- **Test gate**: run the affected modules' tests (or the full suite if the affected surface is small) in **dry-run/validate mode** using `pytest --collect-only` plus a lightweight import check; only groups whose imports resolve cleanly are queued.
- **Staged apply**: approved merges are applied to a temporary copy of the source tree first; `pytest -q` must pass on the copy before the changes are promoted to the working tree.

### 2. Name collisions and module identity
- **Canonical target selection**: the target module for a group is the module with the highest cumulative inbound reference count in `SymbolGraph`. Ties are broken by shortest absolute path, then lexicographically.
- **Collision check**: before finalizing the target name, query `SymbolGraph` for any existing module with the same canonical id; if one exists outside the group, the proposal is rejected with a `NAME_COLLISION` reason.
- **Identity preservation**: each merged source module is replaced by a shim that re-exports the target's public API for one release cycle, unless `--no-shims` is passed. The shim carries a deprecation marker and is added to the next dead-code auction.
- **Import rewriting**: `SymbolRenamer` produces a deterministic rewrite plan; the plan is previewed in the diff and executed only on approval.

### 3. Error propagation and rollback
- **Atomic proposal**: each `MergeProposal` stores the original file contents (or git object ids) of every touched module before any write.
- **Failure handling**: if `DiffApplier` or `SymbolRenamer` raises, the operation halts, the proposal status moves to `FAILED`, and all touched files are restored from the stored originals.
- **Graph consistency**: `SymbolGraph` is rebuilt from disk after a successful merge; if rebuild fails, the file-system rollback is triggered automatically.
- **Operator notification**: failures are emitted with the proposal id, the failing module, the exception type/message, and the path to the preserved backup directory.

### 4. Clustering algorithm (concrete)
Input: matrix `M` where `M[a][b]` is the compression similarity between modules `a` and `b`.
1. Initialize each module as its own cluster.
2. Repeat:
   - For every pair of clusters `(C_i, C_j)`, compute average linkage: `avg(i,j) = (1 / |C_i||C_j|) * sum(M[a][b] for a in C_i for b in C_j)`.
   - Find the pair with maximum `avg`. Ties are broken by (a) smaller total line count, (b) lexicographically earliest canonical target id.
   - If `avg` < `--merge-threshold`, stop.
   - Merge `C_i` and `C_j`.
3. Discard any cluster of size 1.
4. For each remaining cluster, generate one `MergeProposal`.
Complexity is `O(n^2 log n)` for `n` candidates and is acceptable for repositories up to several hundred modules.

### 5. CLI flags and defaults
`ract consolidate [OPTIONS]`
- `--similarity-threshold` (float, default `0.80`, range `[0.5, 1.0]`): minimum similarity for a pair to be considered a candidate.
- `--merge-threshold` (float, default `0.75`, range `[0.5, 1.0]`): minimum average linkage required to merge two clusters.
- `--max-modules` (int, default `50`, min `1`): cap the number of modules scanned, to bound runtime on large repos.
- `--no-shims` (flag): skip the generation of backward-compatible re-export shims.
- `--dry-run` (flag): compute proposals and print previews without enqueueing them.
- `--auto-approve` (flag, dangerous): apply proposals immediately without handshake review. Requires `--yes`.
- `--paths` (multiple, default `.`): restrict scanning to specific directories or modules.

Validation: thresholds outside the allowed range raise `click.BadParameter`; `--auto-approve` without `--yes` raises a usage error.

---
This specification is concrete enough to be implemented in the next development loop, providing a clear roadmap for code, tests, and CLI integration.
<!-- RACT 0.1.1 - Trust and Tooling -->
