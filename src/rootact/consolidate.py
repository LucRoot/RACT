# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Consolidation scanner for near-duplicate modules.

RACT's anti-rot arsenal detects duplication; ``ract consolidate`` turns that
detection into a cleanup workflow. It clusters similar modules, previews the
merge as a unified diff, and queues proposals in the operator handshake queue.
"""

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rootact.compression_novelty_detector import CompressionNoveltyDetector
from rootact.handshake_registry import HandshakeRegistry
from rootact.symbol_graph import SymbolGraph


@dataclass(frozen=True)
class MergeProposal:
    """A proposal to merge a cluster of modules into one canonical module."""

    target: str
    sources: tuple[str, ...]
    diff: str
    reason: str
    safe: bool = True
    safety_notes: tuple[str, ...] = ()


@dataclass
class ConsolidationResult:
    """Output of a consolidation scan."""

    proposals: list[MergeProposal] = field(default_factory=list)
    skipped: list[tuple[list[str], str]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class ConsolidationScanner:
    """Find near-duplicate modules and propose merges."""

    DEFAULT_SIMILARITY = 0.80
    DEFAULT_MERGE = 0.75
    DEFAULT_MAX_MODULES = 50

    def __init__(
        self,
        project_dir: Path | str,
        detector: CompressionNoveltyDetector | None = None,
        graph: SymbolGraph | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.detector = detector or CompressionNoveltyDetector(self.project_dir)
        self.graph = graph or SymbolGraph(self.project_dir).build()

    def scan(
        self,
        similarity_threshold: float = DEFAULT_SIMILARITY,
        merge_threshold: float = DEFAULT_MERGE,
        max_modules: int = DEFAULT_MAX_MODULES,
        paths: list[str] | None = None,
    ) -> ConsolidationResult:
        """Scan for consolidation candidates and return merge proposals."""
        modules = self._collect_modules(paths, max_modules)
        if len(modules) < 2:
            return ConsolidationResult(
                metrics={
                    "candidates": len(modules),
                    "proposals": 0,
                    "similarity_threshold": similarity_threshold,
                    "merge_threshold": merge_threshold,
                }
            )

        sim = self._pairwise_similarity(modules)
        clusters = self._cluster(modules, sim, similarity_threshold, merge_threshold)

        result = ConsolidationResult(
            metrics={
                "candidates": len(modules),
                "pairs_considered": len(sim),
                "clusters_found": len(clusters),
                "similarity_threshold": similarity_threshold,
                "merge_threshold": merge_threshold,
            }
        )

        for cluster in clusters:
            if len(cluster) < 2:
                continue
            rels = [modules[i][0] for i in cluster]
            target = self._pick_target(rels)
            sources = tuple(sorted(s for s in rels if s != target))
            safe, notes = self._safety_check(target, sources)
            diff = self._diff_preview(target, sources)
            reason = (
                f"Merge {len(sources)} module(s) into {target}; "
                f"estimated structural similarity is high."
            )
            result.proposals.append(
                MergeProposal(
                    target=target,
                    sources=sources,
                    diff=diff,
                    reason=reason,
                    safe=safe,
                    safety_notes=tuple(notes),
                )
            )

        return result

    def _collect_modules(
        self, paths: list[str] | None, max_modules: int
    ) -> list[tuple[str, Path, str]]:
        """Return up to *max_modules* Python source modules as (rel, path, content)."""
        roots = [self.project_dir / p for p in (paths or ["."])]
        collected: list[tuple[str, Path, str]] = []
        seen: set[str] = set()
        ignore = CompressionNoveltyDetector.IGNORE_DIRS | {"tests", "test"}
        for root in roots:
            if not root.exists():
                continue
            if root.is_file() and root.suffix == ".py":
                rel = str(root.relative_to(self.project_dir)).replace("\\", "/")
                if rel not in seen:
                    seen.add(rel)
                    collected.append((rel, root, root.read_text(encoding="utf-8")))
                continue
            for path in sorted(root.rglob("*.py")):
                if any(part in ignore for part in path.parts):
                    continue
                if path.name.startswith("test_"):
                    continue
                try:
                    rel = str(path.relative_to(self.project_dir)).replace("\\", "/")
                except ValueError:
                    continue
                if rel in seen:
                    continue
                seen.add(rel)
                collected.append((rel, path, path.read_text(encoding="utf-8")))
        collected.sort(key=lambda x: x[0])
        return collected[:max_modules]

    def _pairwise_similarity(
        self, modules: list[tuple[str, Path, str]]
    ) -> dict[tuple[int, int], float]:
        """Return similarity scores in (0,1) for each unordered pair of modules."""
        sim: dict[tuple[int, int], float] = {}
        for i in range(len(modules)):
            for j in range(i + 1, len(modules)):
                ratio_ij = self.detector._conditional_ratio(
                    modules[i][2], modules[j][1]
                )
                ratio_ji = self.detector._conditional_ratio(
                    modules[j][2], modules[i][1]
                )
                ratios = [r for r in (ratio_ij, ratio_ji) if r is not None]
                if not ratios:
                    sim[(i, j)] = 0.0
                    continue
                best = min(ratios)
                # Clamp and invert so 1.0 means identical, 0.0 means unrelated.
                sim[(i, j)] = max(0.0, min(1.0, 1.0 - best))
        return sim

    def _cluster(
        self,
        modules: list[tuple[str, Path, str]],
        sim: dict[tuple[int, int], float],
        similarity_threshold: float,
        merge_threshold: float,
    ) -> list[set[int]]:
        """Agglomerative average-linkage clustering."""
        n = len(modules)
        clusters: list[set[int]] = [{i} for i in range(n)]

        def avg_linkage(a: set[int], b: set[int]) -> float:
            total = 0.0
            count = 0
            for i in a:
                for j in b:
                    key = (min(i, j), max(i, j))
                    total += sim.get(key, 0.0)
                    count += 1
            return total / count if count else 0.0

        def cluster_target_id(cluster: set[int]) -> str:
            # Deterministic tie-breaker: smallest canonical path in cluster.
            return min(modules[i][0] for i in cluster)

        while True:
            best_score = -1.0
            best_pair: tuple[int, int] | None = None
            for idx_a in range(len(clusters)):
                for idx_b in range(idx_a + 1, len(clusters)):
                    score = avg_linkage(clusters[idx_a], clusters[idx_b])
                    if score < similarity_threshold:
                        continue
                    # Tie-break: prefer merging smaller clusters, then lex target.
                    if score > best_score or (
                        score == best_score
                        and best_pair is not None
                        and (
                            len(clusters[idx_a]) + len(clusters[idx_b])
                            < len(clusters[best_pair[0]]) + len(clusters[best_pair[1]])
                            or cluster_target_id(clusters[idx_a])
                            < cluster_target_id(clusters[best_pair[0]])
                        )
                    ):
                        best_score = score
                        best_pair = (idx_a, idx_b)
            if best_pair is None or best_score < merge_threshold:
                break
            a_idx, b_idx = best_pair
            merged = clusters[a_idx] | clusters[b_idx]
            # Remove higher index first to keep indices valid.
            clusters.pop(b_idx)
            clusters.pop(a_idx)
            clusters.append(merged)

        return clusters

    def _pick_target(self, rels: list[str]) -> str:
        """Choose the canonical target module from a list of relative paths."""
        graph = self.graph

        def inbound_count(rel: str) -> int:
            module = self._module_for_rel(rel)
            module_id = f"{module}:<module>"
            node = graph.nodes.get(module_id)
            return len(node.incoming) if node else 0

        def sort_key(rel: str) -> tuple[int, int, str]:
            return (-inbound_count(rel), len(rel), rel)

        return sorted(rels, key=sort_key)[0]

    def _module_for_rel(self, rel: str) -> str:
        """Return the graph module id for a relative file path."""
        path = self.project_dir / rel
        return self.graph.module_id_for_path(path)

    def _safety_check(
        self, target: str, sources: tuple[str, ...]
    ) -> tuple[bool, list[str]]:
        """Validate that merging *sources* into *target* is safe."""
        notes: list[str] = []
        safe = True

        # Name collision: no other module may share the target's canonical id.
        target_module = self._module_for_rel(target)
        for rel, _path, _content in self._all_modules():
            if rel == target:
                continue
            if self._module_for_rel(rel) == target_module:
                safe = False
                notes.append(f"name collision: {rel} resolves to {target_module}")

        # Parse check: every source module must be readable AST.
        for source in sources:
            source_path = self.project_dir / source
            if self.graph._parse(source_path) is None:
                safe = False
                notes.append(f"cannot parse {source}")

        # Circular dependency guard: merge must not create new SCCs.
        if not self._merge_preserves_scc(target, sources):
            safe = False
            notes.append("merge would create or enlarge a circular dependency")

        return safe, notes

    def _all_modules(self) -> list[tuple[str, Path, str]]:
        """Return all Python modules under the project directory."""
        return self._collect_modules(None, 10_000)

    def _merge_preserves_scc(self, target: str, sources: tuple[str, ...]) -> bool:
        """Return True if merging sources into target does not introduce new cycles.

        For v0 we simulate the merge by checking whether any source module depends
        on the target (folding it into target would make target depend on itself)
        or whether the target already depends on a source (also a cycle after fold).
        We inspect both symbol-graph edges and import bindings because imports that
        are not used do not create edges but still matter for merge safety.
        """
        graph = self.graph
        target_module = self._module_for_rel(target)
        target_id = f"{target_module}:<module>"
        target_node = graph.nodes.get(target_id)
        if target_node is None:
            return False

        def imports_module(module: str, other: str) -> bool:
            bindings = graph._imports.get(module, {})
            for binding in bindings.values():
                if not binding.is_project:
                    continue
                resolved = graph._resolve_imported_module(binding.target_module)
                if resolved == other:
                    return True
            return False

        for source in sources:
            source_module = self._module_for_rel(source)
            source_id = f"{source_module}:<module>"
            source_node = graph.nodes.get(source_id)

            # Target already depends on source -> folding source into target cycles.
            if source_id in target_node.outgoing:
                return False
            for outgoing in target_node.outgoing:
                if outgoing.startswith(f"{source_module}."):
                    return False
            if imports_module(target_module, source_module):
                return False

            if source_node is None:
                continue

            # Source depends on target -> after fold, target depends on itself.
            if target_id in source_node.outgoing:
                return False
            for outgoing in source_node.outgoing:
                if outgoing.startswith(f"{target_module}."):
                    return False
            if imports_module(source_module, target_module):
                return False

        return True

    def _diff_preview(self, target: str, sources: tuple[str, ...]) -> str:
        """Build a unified diff preview for merging *sources* into *target*."""
        target_path = self.project_dir / target
        target_lines = target_path.read_text(encoding="utf-8").splitlines()
        chunks: list[str] = []
        for source in sources:
            source_path = self.project_dir / source
            source_lines = source_path.read_text(encoding="utf-8").splitlines()
            diff = difflib.unified_diff(
                source_lines,
                target_lines,
                fromfile=source,
                tofile=target,
                lineterm="",
            )
            chunks.append("\n".join(diff))
        return "\n\n".join(chunks)

    def enqueue_proposals(
        self, result: ConsolidationResult, registry: HandshakeRegistry | None = None
    ) -> list[str]:
        """Queue proposals in the handshake registry and return their ids."""
        reg = registry or HandshakeRegistry(self.project_dir)
        ids: list[str] = []
        for idx, proposal in enumerate(result.proposals):
            if not proposal.safe:
                continue
            milestone_id = f"consolidate-{idx:04d}"
            description = (
                f"Merge {len(proposal.sources)} module(s) into {proposal.target}\n"
                f"Reason: {proposal.reason}\n"
                f"Sources: {', '.join(proposal.sources)}"
            )
            acceptance = (
                f"Run tests after applying. Source modules should be removed or "
                f"replaced with re-export shims pointing to {proposal.target}."
            )
            reg.add(milestone_id, description, acceptance)
            ids.append(milestone_id)
        return ids


# RACT 0.1.0 - Initial Public Release
