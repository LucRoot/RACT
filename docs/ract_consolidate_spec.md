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
- **src/rootact/symbol_graph.py** – provides the graph representation and utilities for adding/removing nodes.
- **src/rootact/compression_novelty_detector.py** – supplies the similarity scoring function.
- **src/rootact/dead_code_auction.py** – can be reused for the clustering logic if desired.
- **src/rootact/diff_applier.py** – handles the actual file writes for approved merges.
- **src/rootact/handshake_registry.py** – manages the queue of merge proposals and their lifecycle.
- **src/rootact/symbol_renamer.py** – performs reference updates when a merge involves name changes.
- **src/rootact/cli.py** – will be extended with a new `consolidate` subcommand that orchestrates the above steps.

## Implementation notes
- All thresholds (similarity, merge, and approval) should be configurable via command‑line flags.
- The spec assumes that the existing RACT environment already has a populated SymbolGraph and that the novelty detector can be instantiated without additional dependencies.
- Error handling should propagate failures from DiffApplier or SymbolRenamer back to the operator with clear messages.

---
This specification is concrete enough to be implemented in the next development loop, providing a clear roadmap for code, tests, and CLI integration.