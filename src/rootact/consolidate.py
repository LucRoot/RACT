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

from rootact.ast_normalizer import normalize_python, structural_similarity_normalized
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

            # Package __init__.py is not a sensible merge target: it carries
            # package-level exports and would absorb unrelated modules.
            if target.endswith("__init__.py"):
                continue

            # Scripts live outside the package and should not be folded into src/.
            if any(s.startswith("scripts/") for s in sources) and target.startswith(
                "src/"
            ):
                continue

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
        """Return similarity scores in (0,1) for each unordered pair of modules.

        Combines compression-based similarity with AST-normalized structural
        similarity so that renamed clones are caught even when byte-level
        compression fails to see them.
        """
        # Normalize each module once; structural normalization is expensive on
        # large files and this cache avoids redundant work across pairs.
        normalized: dict[int, str] = {}
        for i, (_rel, _path, content) in enumerate(modules):
            try:
                normalized[i] = normalize_python(content)
            except ValueError:
                normalized[i] = ""

        sim: dict[tuple[int, int], float] = {}
        for i in range(len(modules)):
            for j in range(i + 1, len(modules)):
                # Compression signal: lower ratio -> more similar. Fast first filter.
                ratio_ij = self.detector._conditional_ratio(
                    modules[i][2], modules[j][1]
                )
                ratio_ji = self.detector._conditional_ratio(
                    modules[j][2], modules[i][1]
                )
                ratios = [r for r in (ratio_ij, ratio_ji) if r is not None]
                compression_sim = (
                    max(0.0, min(1.0, 1.0 - min(ratios))) if ratios else 0.0
                )

                # Structural signal is expensive: only run it when compression suggests
                # the pair might be a renamed clone. Very low compression similarity
                # means the modules differ too much in size or content to be copies.
                structural_sim = 0.0
                if compression_sim >= 0.3:
                    norm_a = normalized.get(i, "")
                    norm_b = normalized.get(j, "")
                    if norm_a and norm_b:
                        # Use the cached normalization; the helper itself still
                        # applies the large-input and size-ratio heuristics.
                        try:
                            structural_sim = structural_similarity_normalized(
                                norm_a, norm_b
                            )
                        except Exception:  # noqa: BLE001
                            structural_sim = 0.0

                # Either signal can push a pair over the threshold.
                sim[(i, j)] = max(compression_sim, structural_sim)
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
                f"Proposal: merge into {proposal.target}\n"
                f"Sources: {', '.join(proposal.sources)}\n"
                f"Reason: {proposal.reason}"
            )
            acceptance = (
                f"Run tests after applying. Source modules should be removed or "
                f"replaced with re-export shims pointing to {proposal.target}."
            )
            metadata = {
                "target": proposal.target,
                "sources": list(proposal.sources),
                "diff": proposal.diff,
                "reason": proposal.reason,
                "safe": proposal.safe,
                "safety_notes": list(proposal.safety_notes),
            }
            reg.add(milestone_id, description, acceptance, metadata=metadata)
            ids.append(milestone_id)
        return ids


@dataclass(frozen=True)
class ApplyResult:
    """Result of applying a merge proposal."""

    proposal_id: str
    applied: bool
    deleted: tuple[str, ...]
    shims: tuple[str, ...]
    backup_dir: str | None
    error: str | None = None


class ConsolidationApplier:
    """Apply approved merge proposals with backup and rollback support."""

    def __init__(self, project_dir: Path | str) -> None:
        self.project_dir = Path(project_dir)
        self.backup_root = self.project_dir / ".rootact" / "consolidate_backups"

    def _backup_dir(self, proposal_id: str) -> Path:
        return self.backup_root / proposal_id

    def _backup_path(self, proposal_id: str, rel: str) -> Path:
        return self._backup_dir(proposal_id) / rel.replace("/", "__")

    def apply(
        self,
        proposal: MergeProposal,
        proposal_id: str,
        registry: HandshakeRegistry | None = None,
        dry_run: bool = False,
    ) -> ApplyResult:
        """Apply *proposal* and return an ``ApplyResult``.

        Backs up the target and all source files before making changes. On
        failure, restores everything from the backup directory.
        """
        if not proposal.safe:
            return ApplyResult(
                proposal_id=proposal_id,
                applied=False,
                deleted=(),
                shims=(),
                backup_dir=None,
                error="proposal failed safety checks",
            )

        backup_dir = self._backup_dir(proposal_id)
        files_to_backup = [proposal.target, *proposal.sources]
        backed_up: dict[str, Path] = {}

        try:
            if not dry_run:
                backup_dir.mkdir(parents=True, exist_ok=True)
                for rel in files_to_backup:
                    src = self.project_dir / rel
                    if src.is_file():
                        dst = self._backup_path(proposal_id, rel)
                        dst.write_bytes(src.read_bytes())
                        backed_up[rel] = dst

            deleted: list[str] = []
            shims: list[str] = []
            for source in proposal.sources:
                # Overwrite the source file with a deprecation shim. The original
                # content is already in the backup directory, so rollback can
                # restore it if the shim write fails.
                if not dry_run:
                    self._write_shim(source, proposal.target)
                deleted.append(source)
                shims.append(source)

            if not dry_run and registry is not None:
                try:
                    registry.update_status(proposal_id, "approved")
                except KeyError:
                    pass

            return ApplyResult(
                proposal_id=proposal_id,
                applied=not dry_run,
                deleted=tuple(deleted),
                shims=tuple(shims),
                backup_dir=str(backup_dir.relative_to(self.project_dir)).replace(
                    "\\", "/"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self._restore_from_backup(backed_up)
            return ApplyResult(
                proposal_id=proposal_id,
                applied=False,
                deleted=tuple(deleted),
                shims=tuple(shims),
                backup_dir=str(backup_dir.relative_to(self.project_dir)).replace(
                    "\\", "/"
                ),
                error=f"apply failed: {exc}",
            )

    def _write_shim(self, source_rel: str, target_rel: str) -> Path:
        """Write a backward-compatible shim over the source file.

        LR:: Shims keep external callers working while the canonical module
        absorbs the source. They are intentionally marked deprecated so the
        next dead-code auction can remove them. The original source content
        must already be backed up before calling this method.
        """
        source_path = self.project_dir / source_rel
        target_module = self._module_id_from_rel(target_rel)
        shim_text = (
            "# Rooted by Dr. Lucas Root, Ph.D.\n"
            "# DEPRECATED: This module has been consolidated into "
            f"{target_module}.\n"
            "from __future__ import annotations\n\n"
            f"from {target_module} import *  # noqa: F401,F403\n"
        )
        source_path.write_text(shim_text, encoding="utf-8")
        return source_path

    def _module_id_from_rel(self, rel: str) -> str:
        """Return a best-effort importable module name for a relative path."""
        path = self.project_dir / rel
        if not path.suffix == ".py":
            raise ValueError(f"not a Python file: {rel}")
        # If a SymbolGraph is cheap to build, use it; otherwise fall back to path.
        try:
            graph = SymbolGraph(self.project_dir).build()
            return graph.module_id_for_path(path)
        except Exception:  # noqa: BLE001
            parts = Path(rel).with_suffix("").parts
            return ".".join(parts)

    def _restore_from_backup(self, backed_up: dict[str, Path]) -> None:
        """Restore files from their backup paths."""
        for rel, backup_path in backed_up.items():
            target = self.project_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(backup_path.read_bytes())

    def rollback(self, proposal_id: str) -> ApplyResult:
        """Restore all files from a previous apply's backup directory."""
        backup_dir = self._backup_dir(proposal_id)
        if not backup_dir.is_dir():
            return ApplyResult(
                proposal_id=proposal_id,
                applied=False,
                deleted=(),
                shims=(),
                backup_dir=str(backup_dir.relative_to(self.project_dir)).replace(
                    "\\", "/"
                ),
                error="backup directory not found",
            )

        restored: list[str] = []
        for backup_path in backup_dir.iterdir():
            rel = backup_path.name.replace("__", "/")
            target = self.project_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(backup_path.read_bytes())
            restored.append(rel)
        return ApplyResult(
            proposal_id=proposal_id,
            applied=False,
            deleted=(),
            shims=(),
            backup_dir=str(backup_dir.relative_to(self.project_dir)).replace("\\", "/"),
        )


def render_html_report(plan: ConsolidationResult) -> str:
    """Return a self-contained HTML summary of a consolidation plan."""
    lines: list[str] = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'><title>Consolidation Report</title></head>",
        "<body><h1>Consolidation Report</h1>",
    ]
    metrics = plan.metrics or {}
    lines.append(
        f"<p>Candidates: {metrics.get('candidates', 0)} | Proposals: {len(plan.proposals)}</p>"
    )
    if plan.proposals:
        lines.append("<ul>")
        for proposal in plan.proposals:
            reduction = metrics.get("predicted_line_reduction", 0)
            lines.append(
                f"<li><strong>{proposal.target}</strong> ← {', '.join(proposal.sources)} "
                f"(predicted reduction: {reduction} lines)</li>"
            )
        lines.append("</ul>")
    else:
        lines.append("<p>No consolidation proposals.</p>")
    if plan.skipped:
        lines.append("<h2>Warnings</h2><ul>")
        for _cluster, reason in plan.skipped:
            lines.append(f"<li>{reason}</li>")
        lines.append("</ul>")
    lines.append("</body></html>")
    return "\n".join(lines)


# RACT 0.1.1 - Trust and Tooling
