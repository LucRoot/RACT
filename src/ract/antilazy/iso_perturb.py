"""ALM optional gate — Isomorphic Perturbation for rule-like intents.

ALM spec §9. When an intent is rule-like (universally quantified: "every
user must have exactly one primary email"; "no function may bypass the
audit logger"; "all monetary values are stored as integer cents"), the
gate restates the intent under three isomorphic transformations and asks
the primary provider to produce a solution for each. A model that
genuinely induced the rule returns the same solution shape under all
three; a model that pattern-matched the surface form diverges. Divergence
emits ``laziness.violated`` with ``kind="isomorphic_divergence"`` and the
loop resumes with the divergence as evidence in the next planning prompt.

Optional gate. The rule-like detector is deliberately over-inclusive but
lateral chain branch A gates the transformation count on the detector's
confidence: high confidence (>= 0.7) runs all three transformations, low
confidence runs one. A non-rule-like intent skips the gate entirely.

Lateral chain branches merged into this module:

- A: confidence-scored detector; ``detect_rule_like_intent`` returns a
  ``RuleLikeDetection`` with ``confidence`` in [0.0, 1.0]. The gate
  runs one transformation below ``config.confidence_threshold_for_full_gate``
  and all three above it.
- B: rename map preserves identifiers that appear in
  ``workspace_symbols``. Only free variables introduced in the intent
  get renamed; existing workspace vocabulary passes through unchanged
  so a rename does not shift the domain semantics.
- C: Python-only AST-normalized comparison. Non-Python solutions fall
  back to string similarity via ``difflib.SequenceMatcher.ratio`` and
  emit an advisory ``laziness.violated`` with
  ``kind="iso_perturb_language_unsupported"``.
- D: iso-perturbation is orthogonal to G1 (held-out suite). G1
  verifies the specific solution passes the held-out suite;
  iso-perturbation verifies the solution's shape is invariant under
  transformation. Both run. See ADR-0024 for the explicit note.

See ADR-0024 for rejected alternatives and ``docs/ARCHITECTURE.md``
"Anti-Lazy Isomorphic Perturbation Gate" for the cross-link into the
substrate architecture.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Mapping, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ract.core.loop import WorkspaceSnapshot


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


TransformationKind = Literal[
    "rename_entities", "swap_syntax", "permute_examples"
]
"""Names of the three isomorphic transformations the gate applies."""


DivergenceReason = Literal[
    "ast_dump_mismatch",
    "parse_failure_original",
    "parse_failure_transformed",
    "parse_failure_both",
    "string_similarity_below_threshold",
    "solution_missing",
]
"""Closed vocabulary for why a transformed solution diverged."""


@dataclass(frozen=True)
class RuleLikeDetection:
    """The output of ``detect_rule_like_intent``.

    - ``is_rule_like`` — True when the intent contains any of the
      universal-quantifier keywords in a subject-verb position.
    - ``confidence`` — [0.0, 1.0]. 1.0 when a universal quantifier
      (``every``, ``all``, ``no``, ``exactly one``) sits at a
      sentence-root position followed by a verb; 0.7 when a modal
      keyword (``must``, ``never``, ``always``, ``cannot``) appears
      alone.
    - ``matched_keywords`` — the keywords that fired; empty when
      ``is_rule_like`` is False.
    """

    is_rule_like: bool
    confidence: float
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class IsomorphicTransformation:
    """One transformed variant of the original intent.

    - ``kind`` — which transformation was applied.
    - ``transformed_intent`` — the transformed intent text.
    - ``renaming_map`` — the map of original-name → transformed-name for
      ``rename_entities``; empty for the other transformations.
    """

    kind: TransformationKind
    transformed_intent: str
    renaming_map: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Divergence:
    """One transformation whose returned solution diverged from the original.

    - ``transformation_kind`` — which transformation the divergence
      applies to.
    - ``reason`` — closed vocabulary for why it diverged.
    - ``similarity`` — [0.0, 1.0] AST-normalized-or-string similarity;
      1.0 means identical after normalization.
    """

    transformation_kind: TransformationKind
    reason: DivergenceReason
    similarity: float


@dataclass(frozen=True)
class PerturbationDivergenceReport:
    """Aggregate result of running the gate on a completion.

    - ``original_intent`` — the intent text the primary was originally
      given.
    - ``transformations`` — the transformed variants produced.
    - ``original_solution_digest`` — the SHA-256 digest of the
      normalized original solution.
    - ``transformed_solution_digests`` — one digest per transformation
      (same index order).
    - ``divergences`` — transformations whose returned solutions
      diverged.
    - ``is_pattern_matching`` — True when at least one transformation
      diverged; the loop reads this to decide whether to block
      COMPLETE.
    """

    original_intent: str
    transformations: tuple[IsomorphicTransformation, ...]
    original_solution_digest: bytes
    transformed_solution_digests: tuple[bytes, ...]
    divergences: tuple[Divergence, ...]
    is_pattern_matching: bool

    def to_canonical(self) -> dict[str, Any]:
        """Return the on-disk canonical form for ``iso_perturb.json``.

        DoD depth-4 leaf (b): the loop writes this to
        ``evals/runs/<run_id>/iso_perturb.json`` after every rule-like
        completion so operators can audit which transformations were
        applied and where they diverged.
        """
        return {
            "original_intent": self.original_intent,
            "transformations": [
                {
                    "kind": t.kind,
                    "transformed_intent": t.transformed_intent,
                    "renaming_map": dict(t.renaming_map),
                }
                for t in self.transformations
            ],
            "original_solution_digest": self.original_solution_digest.hex(),
            "transformed_solution_digests": [
                d.hex() for d in self.transformed_solution_digests
            ],
            "divergences": [
                {
                    "transformation_kind": d.transformation_kind,
                    "reason": d.reason,
                    "similarity": round(d.similarity, 4),
                }
                for d in self.divergences
            ],
            "is_pattern_matching": self.is_pattern_matching,
        }


@runtime_checkable
class SolutionProducer(Protocol):
    """Adapter that dispatches an intent to a provider and returns the solution.

    Kept as a Protocol so tests inject a direct implementation without
    routing through a full ``Provider.send_planned_step_request`` call.
    Production callers wrap the primary provider in an adapter that
    returns the parsed solution text.
    """

    def produce(self, intent: str, workspace: "WorkspaceSnapshot") -> str:
        """Return the solution string for ``intent`` against ``workspace``."""
        ...  # pragma: no cover — protocol


@dataclass(frozen=True)
class IsoPerturbConfig:
    """Tunables for the gate.

    - ``confidence_threshold_for_full_gate`` — the detector's confidence
      cutoff; below this the gate runs one transformation, at-or-above
      runs all three. Lateral chain branch A.
    - ``similarity_threshold`` — AST-normalized (or string) similarity
      below which a transformation is a divergence. Default 0.85 leaves
      room for identifier-rename equivalence after the renaming map is
      applied.
    - ``max_transformations`` — hard ceiling on how many variants to
      generate; 3 in the spec.
    """

    confidence_threshold_for_full_gate: float = 0.7
    similarity_threshold: float = 0.85
    max_transformations: int = 3
    # Second Pass finding (Q1): floor on the rename-map degeneracy
    # ratio (fraction of renameable alpha tokens actually renamed).
    # Below this the rename transformation is effectively a no-op
    # and the module emits an advisory event so the loop can
    # compensate. Default 0.10 is deliberately low; the check
    # exists to catch the "flood workspace_symbols" attack shape,
    # not to reject legitimate high-preservation intents.
    rename_degeneracy_ratio_floor: float = 0.10


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


# High-confidence universal quantifiers — sentence-root subject-verb.
# Word-boundary matched below via ``\b`` regex; substring matches would
# fire on "sm(all)er", "n(o)t", etc.
_HIGH_KEYWORDS: tuple[str, ...] = (
    "every",
    "all",
    "no",
    "exactly one",
)

# Modal-only keywords — the sentence expresses a rule via modality
# alone. Lower confidence because the sentence may be conditional
# rather than universal.
_MODAL_KEYWORDS: tuple[str, ...] = (
    "must",
    "never",
    "always",
    "cannot",
)

# Verb hints that follow a universal quantifier in a rule-like intent.
# The presence lifts confidence toward 1.0.
_RULE_VERB_HINTS: tuple[str, ...] = (
    " must ",
    " has ",
    " have ",
    " is ",
    " are ",
    " shall ",
    " may ",
    " can ",
    " should ",
)


def detect_rule_like_intent(intent: str) -> RuleLikeDetection:
    """Return whether ``intent`` reads as a universally-quantified rule.

    Deliberately over-inclusive per lateral chain branch A: the caller
    reads ``confidence`` and dials the transformation count accordingly.
    False positives cost one extra companion dispatch; false negatives
    lose the gate entirely, which is the more expensive error.
    """
    text = " " + intent.strip().lower() + " "
    matched: list[str] = []
    confidence = 0.0

    # High-confidence universal quantifiers — word-boundary matched
    # so ``all`` does not fire on "smaller" and ``no`` does not fire
    # on "not"/"none".
    for kw in _HIGH_KEYWORDS:
        pattern = rf"\b{re.escape(kw)}\b"
        match = re.search(pattern, text)
        if match:
            matched.append(kw)
            # Lift confidence when a rule-verb hint appears after the
            # quantifier within a short window (60 chars).
            window = text[match.start() : match.start() + 60]
            if any(hint in window for hint in _RULE_VERB_HINTS):
                confidence = max(confidence, 1.0)
            else:
                confidence = max(confidence, 0.8)

    # Modal-only keywords: lower baseline confidence.
    for kw in _MODAL_KEYWORDS:
        # Word-boundary check.
        if re.search(rf"\b{re.escape(kw)}\b", text):
            matched.append(kw)
            confidence = max(confidence, 0.7)

    is_rule_like = bool(matched) and confidence >= 0.7
    # Dedupe while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for kw in matched:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return RuleLikeDetection(
        is_rule_like=is_rule_like,
        confidence=confidence,
        matched_keywords=tuple(unique),
    )


# ---------------------------------------------------------------------------
# Transformations
# ---------------------------------------------------------------------------


# Fixed synonym table — stdlib only, no Faker dependency (module scope
# per the plan's "fixed synonym table approach"). Deterministic so a
# rename is reproducible across runs. Extend cautiously: swapping a
# synonym mid-pipeline shifts every transformed intent's digest.
_ENTITY_SYNONYMS: dict[str, str] = {
    "user": "member",
    "users": "members",
    "email": "address",
    "emails": "addresses",
    "primary": "default",
    "function": "routine",
    "functions": "routines",
    "audit": "ledger",
    "logger": "recorder",
    "value": "amount",
    "values": "amounts",
    "monetary": "currency",
    "payment": "transfer",
    "payments": "transfers",
    "ledger": "book",
    "cent": "penny",
    "cents": "pennies",
    "record": "entry",
    "records": "entries",
    "account": "profile",
    "accounts": "profiles",
    "order": "request",
    "orders": "requests",
    "invoice": "bill",
    "invoices": "bills",
    "customer": "client",
    "customers": "clients",
    "item": "widget",
    "items": "widgets",
    "product": "article",
    "products": "articles",
    "role": "hat",
    "roles": "hats",
    "permission": "grant",
    "permissions": "grants",
}


# Stopwords that must never be renamed (would corrupt the intent).
_RENAME_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "for",
        "with",
        "in",
        "on",
        "to",
        "from",
        "by",
        "at",
        "is",
        "are",
        "be",
        "as",
        "must",
        "no",
        "not",
        "every",
        "all",
        "exactly",
        "one",
        "may",
        "can",
        "should",
        "shall",
        "has",
        "have",
        "each",
    }
)


def transform_intent(
    intent: str,
    *,
    workspace_symbols: frozenset[str] = frozenset(),
) -> tuple[IsomorphicTransformation, ...]:
    """Return three isomorphic variants of ``intent``.

    Lateral chain branch B: identifiers appearing in
    ``workspace_symbols`` pass through unchanged so the rename does
    not shift domain-specific vocabulary. Only free variables
    introduced in the intent get renamed.

    The three variants are always returned in the fixed order
    ``(rename_entities, swap_syntax, permute_examples)`` so downstream
    digests are stable across runs.
    """
    ws_lower = {s.lower() for s in workspace_symbols}
    renamed, rename_map = _apply_rename(intent, ws_lower)
    swapped = _apply_swap_syntax(intent)
    permuted = _apply_permute_examples(intent)
    return (
        IsomorphicTransformation(
            kind="rename_entities",
            transformed_intent=renamed,
            renaming_map=dict(rename_map),
        ),
        IsomorphicTransformation(
            kind="swap_syntax",
            transformed_intent=swapped,
            renaming_map={},
        ),
        IsomorphicTransformation(
            kind="permute_examples",
            transformed_intent=permuted,
            renaming_map={},
        ),
    )


def _apply_rename(
    intent: str, workspace_symbols_lower: set[str]
) -> tuple[str, dict[str, str]]:
    """Substitute entity names against the fixed synonym table.

    Preserves case crudely: title-case tokens map to title-case
    synonyms; everything else is lowercase. Identifiers appearing in
    ``workspace_symbols_lower`` are held out per lateral chain
    branch B.

    Second Pass finding (Additional #2): tokens like ``audit_logger``
    and ``primaryEmail`` are not plain alphabetic; the tokenizer
    splits on underscores and case boundaries so the atomic parts
    (``audit``, ``logger``; ``primary``, ``Email``) become candidates
    for rename.
    """
    # Split on non-alphanumeric AND camelCase boundaries. The regex
    # keeps separators as tokens (the ``()`` group) so reconstruction
    # is exact.
    tokens = _split_intent_tokens(intent)
    out: list[str] = []
    rename_map: dict[str, str] = {}
    for tok in tokens:
        low = tok.lower()
        if not tok.isalpha():
            out.append(tok)
            continue
        if low in _RENAME_STOPWORDS:
            out.append(tok)
            continue
        if low in workspace_symbols_lower:
            # Preserve workspace vocabulary — lateral chain branch B.
            out.append(tok)
            continue
        if low in _ENTITY_SYNONYMS:
            replacement = _ENTITY_SYNONYMS[low]
            if tok[:1].isupper():
                replacement = replacement[:1].upper() + replacement[1:]
            rename_map[tok] = replacement
            out.append(replacement)
            continue
        out.append(tok)
    return "".join(out), rename_map


def _split_intent_tokens(intent: str) -> list[str]:
    """Split ``intent`` into tokens preserving separators for lossless join.

    Second Pass finding (Additional #2): extends the naive
    ``re.split(r"(\\W+)", ...)`` tokenizer to also split on underscores
    (``_``) and case boundaries (``primaryEmail`` → ``primary``,
    ``Email``) so multi-part identifiers become individually
    renameable.
    """
    # First split on non-word plus underscore; then within each
    # alphabetic chunk split on lower->upper transitions.
    parts = re.split(r"([\W_]+)", intent)
    result: list[str] = []
    for part in parts:
        if not part or not part.isalpha():
            result.append(part)
            continue
        # camelCase: split at lower-to-upper boundary. e.g.
        # "primaryEmail" -> ["primary", "Email"].
        chunks = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", part)
        if not chunks:
            result.append(part)
            continue
        # Interleave chunks with the empty-string separator that a
        # join(...) would produce; keeping them as separate items
        # preserves the token boundary for the rename loop's isalpha
        # check.
        for idx, chunk in enumerate(chunks):
            result.append(chunk)
            if idx != len(chunks) - 1:
                # No physical separator existed at this boundary; we
                # append an empty string so ``"".join(result)`` still
                # reconstructs the original text.
                result.append("")
    return result


def rename_map_degeneracy_ratio(
    intent: str, rename_map: Mapping[str, str]
) -> float:
    """Return the fraction of renameable alpha tokens that were renamed.

    Second Pass finding (Q1): a rename transformation whose map is
    nearly empty is a no-op; a primary can force this by naming
    every ordinary noun as a workspace symbol. The ratio is
    ``renamed_alpha_tokens / total_alpha_tokens``; values below a
    threshold surface an advisory so the loop can compensate.

    Zero total alpha tokens returns 1.0 (no rename opportunities,
    nothing to be degenerate about).
    """
    tokens = _split_intent_tokens(intent)
    alpha_tokens = [t for t in tokens if t.isalpha()]
    if not alpha_tokens:
        return 1.0
    return len(rename_map) / len(alpha_tokens)


def _apply_swap_syntax(intent: str) -> str:
    """Reorder clauses via a small syntactic pass.

    Splits the intent on sentence separators (`. `) and internally on
    clause markers (` and `, `, `). Reverses the resulting parts and
    reconstructs. A one-sentence, one-clause intent returns unchanged
    (permutation is a no-op on a single element).
    """
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", intent.strip()) if s]
    swapped_sentences: list[str] = []
    for sentence in sentences:
        # Split on ", " and " and " but preserve the original punctuation.
        parts = re.split(r",\s+|\s+and\s+", sentence)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) <= 1:
            swapped_sentences.append(sentence)
            continue
        # Reverse the clauses; join with a comma so the result is
        # still legible but structurally distinct.
        swapped_sentences.append(", ".join(reversed(parts)))
    return " ".join(swapped_sentences)


def _apply_permute_examples(intent: str) -> str:
    """Permute example lists inside the intent.

    Recognizes three list shapes: dash-prefixed items, numeric-prefixed
    items, and comma-separated quoted items. If none match, the
    original intent is returned unchanged; a divergence there would
    mean the primary is sensitive to something other than list order.
    """
    lines = intent.split("\n")
    dash_items: list[tuple[int, str]] = []
    num_items: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("- "):
            dash_items.append((idx, line))
        elif re.match(r"\d+[.)]\s+", stripped):
            num_items.append((idx, line))

    if len(dash_items) >= 2:
        # Reverse the dash-prefixed items in place.
        indices = [i for i, _ in dash_items]
        rotated = list(reversed([line for _, line in dash_items]))
        for slot, replacement in zip(indices, rotated):
            lines[slot] = replacement
        return "\n".join(lines)

    if len(num_items) >= 2:
        indices = [i for i, _ in num_items]
        # Renumber after rotation so the sequence stays 1, 2, 3.
        raw = [line for _, line in num_items]
        rotated = list(reversed(raw))
        renumbered: list[str] = []
        for i, line in enumerate(rotated, start=1):
            renumbered.append(re.sub(r"^\s*\d+[.)]\s+", f"{i}. ", line))
        for slot, replacement in zip(indices, renumbered):
            lines[slot] = replacement
        return "\n".join(lines)

    # Comma-separated quoted items: "a", "b", "c" → "c", "b", "a".
    #
    # Second Pass finding (Additional #6): the previous placeholder
    # scheme could cross-contaminate on duplicate quoted items. Use
    # a two-pass approach: first replace each source occurrence with
    # a unique per-index sentinel, then rewrite each sentinel to its
    # rotated destination. The sentinel string is chosen so it
    # cannot appear in normal intent text.
    quoted = list(re.finditer(r'"[^"]+"', intent))
    if len(quoted) >= 2:
        rotated_values = list(reversed([m.group(0) for m in quoted]))
        # Walk the intent from the end so index arithmetic stays stable
        # (each replacement changes length; walking end-first avoids
        # shifting later match spans).
        result = intent
        for idx in range(len(quoted) - 1, -1, -1):
            match = quoted[idx]
            sentinel = f"\x00\x01ISO_PERM_{idx}\x00\x02"
            result = result[: match.start()] + sentinel + result[match.end() :]
        for idx, dst in enumerate(rotated_values):
            result = result.replace(f"\x00\x01ISO_PERM_{idx}\x00\x02", dst)
        return result

    return intent


# ---------------------------------------------------------------------------
# AST-normalized comparison
# ---------------------------------------------------------------------------


class _RenameApplier(ast.NodeTransformer):
    """Apply a renaming map to Name / Attribute / arg / FunctionDef nodes.

    The reverse map (transformed-name → original-name) is applied to
    the transformed solution so a semantically-identical solution
    produced under a rename compares equal to the original.
    """

    def __init__(self, reverse_map: Mapping[str, str]) -> None:
        self._reverse = dict(reverse_map)

    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
        if node.id in self._reverse:
            return ast.copy_location(
                ast.Name(id=self._reverse[node.id], ctx=node.ctx), node
            )
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:  # noqa: N802
        self.generic_visit(node)
        if node.attr in self._reverse:
            new = ast.Attribute(
                value=node.value,
                attr=self._reverse[node.attr],
                ctx=node.ctx,
            )
            return ast.copy_location(new, node)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:  # noqa: N802
        if node.arg in self._reverse:
            new = ast.arg(arg=self._reverse[node.arg], annotation=node.annotation)
            return ast.copy_location(new, node)
        return node

    def visit_FunctionDef(  # noqa: N802
        self, node: ast.FunctionDef
    ) -> ast.AST:
        self.generic_visit(node)
        if node.name in self._reverse:
            node.name = self._reverse[node.name]
        return node


def _normalized_ast_dump(
    solution: str, reverse_rename: Mapping[str, str] = {}
) -> str | None:
    """Return an AST-normalized string form of ``solution``.

    ``None`` when ``solution`` does not parse as Python. Callers fall
    back to string similarity in that case (lateral chain branch C).
    """
    try:
        tree = ast.parse(solution)
    except SyntaxError:
        return None
    if reverse_rename:
        tree = _RenameApplier(dict(reverse_rename)).visit(tree)
        ast.fix_missing_locations(tree)
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def _digest_of(text: str) -> bytes:
    """Return the SHA-256 digest of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).digest()


def compare_solutions(
    original: str,
    transformed: str,
    *,
    transformation: IsomorphicTransformation,
    similarity_threshold: float | None = None,
) -> tuple[float, DivergenceReason | None]:
    """Compare ``original`` and ``transformed`` under the transformation.

    Returns ``(similarity, reason)`` where ``reason`` is ``None`` when
    the two are considered equivalent. AST-normalized comparison is
    used when both parse as Python; otherwise ``difflib`` string
    similarity.

    Second Pass finding (Additional #1): the string-similarity
    fallback reason ``string_similarity_below_threshold`` is now
    only set when ``similarity < similarity_threshold``. Callers
    that leave the argument as ``None`` see the reason set whenever
    similarity is below 1.0 (the pre-fix behaviour); callers that
    pass their own threshold see a reason that actually reflects
    the divergence they will act on.
    """
    reverse = {v: k for k, v in transformation.renaming_map.items()}
    original_norm = _normalized_ast_dump(original)
    transformed_norm = _normalized_ast_dump(transformed, reverse)
    if original_norm is None and transformed_norm is None:
        # Both are prose or non-Python; fall back to string similarity.
        similarity = difflib.SequenceMatcher(
            None, original.strip(), transformed.strip()
        ).ratio()
        cutoff = 1.0 if similarity_threshold is None else similarity_threshold
        return similarity, (
            "string_similarity_below_threshold"
            if similarity < cutoff
            else None
        )
    if original_norm is None:
        return 0.0, "parse_failure_original"
    if transformed_norm is None:
        return 0.0, "parse_failure_transformed"
    if original_norm == transformed_norm:
        return 1.0, None
    similarity = difflib.SequenceMatcher(
        None, original_norm, transformed_norm
    ).ratio()
    return similarity, "ast_dump_mismatch"


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------


def run_iso_perturbation(
    *,
    intent: str,
    workspace: "WorkspaceSnapshot",
    original_solution: str,
    primary: SolutionProducer,
    companion: SolutionProducer | None = None,
    workspace_symbols: frozenset[str] = frozenset(),
    config: IsoPerturbConfig | None = None,
) -> PerturbationDivergenceReport:
    """Run the isomorphic perturbation gate.

    - Detects the intent's rule-like confidence to decide the
      transformation count (lateral chain branch A).
    - Generates transformations preserving workspace symbols
      (lateral chain branch B).
    - Dispatches each transformed intent to ``primary`` and compares
      the returned solution to ``original_solution`` under the
      appropriate normalization (lateral chain branch C).
    - Emits ``laziness.violated`` with
      ``kind="isomorphic_divergence"`` on any divergence.

    The gate assumes callers only invoke it when
    ``detect_rule_like_intent(intent).is_rule_like`` is True; a
    non-rule-like intent should not reach this function. Callers
    that mis-route see the report with no divergences and no side
    effects.
    """
    cfg = config or IsoPerturbConfig()
    detection = detect_rule_like_intent(intent)

    variants = transform_intent(intent, workspace_symbols=workspace_symbols)
    if detection.confidence < cfg.confidence_threshold_for_full_gate:
        # Low confidence: run one transformation to save dispatch cost.
        variants = variants[: max(1, min(1, cfg.max_transformations))]
    else:
        variants = variants[: cfg.max_transformations]

    # Second Pass finding (Q1): a rename transformation whose map is
    # degenerate (nearly-empty because the caller flooded workspace_symbols
    # with ordinary nouns) is a no-op. Emit an advisory so the loop can
    # compensate; the divergence check itself still runs.
    for variant in variants:
        if variant.kind != "rename_entities":
            continue
        ratio = rename_map_degeneracy_ratio(intent, variant.renaming_map)
        if ratio < cfg.rename_degeneracy_ratio_floor:
            _emit_rename_degeneracy_advisory(ratio, cfg.rename_degeneracy_ratio_floor)

    original_norm = _normalized_ast_dump(original_solution) or original_solution
    original_digest = _digest_of(original_norm)

    transformed_digests: list[bytes] = []
    divergences: list[Divergence] = []
    for variant in variants:
        try:
            transformed_solution = primary.produce(
                variant.transformed_intent, workspace
            )
        except Exception as exc:  # noqa: BLE001 — differentiated below
            # Second Pass finding (Additional #4): a producer error is
            # not a divergence — it is an infrastructure failure. Emit
            # a distinct advisory event so operators can differentiate
            # provider outages from pattern-matching. The divergence
            # record still lands so the loop blocks COMPLETE (a run
            # with no comparable transformed solution cannot be
            # declared invariant either way).
            _emit_producer_error_advisory(variant.kind, exc)
            transformed_digests.append(_digest_of(""))
            divergences.append(
                Divergence(
                    transformation_kind=variant.kind,
                    reason="solution_missing",
                    similarity=0.0,
                )
            )
            continue
        similarity, reason = compare_solutions(
            original_solution,
            transformed_solution,
            transformation=variant,
            similarity_threshold=cfg.similarity_threshold,
        )
        transformed_norm = (
            _normalized_ast_dump(transformed_solution) or transformed_solution
        )
        transformed_digests.append(_digest_of(transformed_norm))
        # An AST-normalized structural mismatch always counts as a
        # divergence — the AST dumps differ even after applying the
        # reverse rename, so the solution shape is not invariant.
        # For the string-similarity fallback, the threshold decides.
        is_divergent: bool
        if reason is None:
            is_divergent = False
        elif reason == "string_similarity_below_threshold":
            is_divergent = similarity < cfg.similarity_threshold
        else:
            # ast_dump_mismatch / parse_failure_* / solution_missing —
            # structural, not similarity-scaled. Always divergent.
            is_divergent = True
        if is_divergent:
            # ``is_divergent`` is only True when ``reason`` is not
            # None; narrow the type for the dataclass constructor.
            assert reason is not None
            divergences.append(
                Divergence(
                    transformation_kind=variant.kind,
                    reason=reason,
                    similarity=similarity,
                )
            )

    report = PerturbationDivergenceReport(
        original_intent=intent,
        transformations=variants,
        original_solution_digest=original_digest,
        transformed_solution_digests=tuple(transformed_digests),
        divergences=tuple(divergences),
        is_pattern_matching=bool(divergences),
    )
    _emit_iso_perturb_event(report)
    return report


def _emit_rename_degeneracy_advisory(ratio: float, floor: float) -> None:
    """Emit ``laziness.violated`` advisory for a degenerate rename map.

    Second Pass finding (Q1). A rename-map degeneracy ratio below the
    configured floor signals that the rename transformation is a
    no-op (either the intent had no renameable free variables, or a
    caller flooded ``workspace_symbols`` to defeat the rename).
    The advisory carries ``advisory=True`` so operators can
    differentiate it from a hard divergence.
    """
    try:  # local import breaks the trace → antilazy cycle
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": "iso_perturb_rename_degenerate",
                "advisory": True,
                "ratio": round(ratio, 4),
                "floor": round(floor, 4),
            },
        )
    except Exception:  # noqa: BLE001 — never fail on trace error
        pass


def _emit_producer_error_advisory(
    transformation_kind: str, exc: BaseException
) -> None:
    """Emit ``laziness.violated`` advisory when the primary producer errors.

    Second Pass finding (Additional #4). Distinguishing a producer
    outage from a genuine solution divergence unblocks operator
    diagnosis. The advisory carries the exception class name (not
    the message, which may contain sensitive credentials) and the
    transformation the producer was called for.
    """
    try:  # local import breaks the trace → antilazy cycle
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": "iso_perturb_producer_error",
                "advisory": True,
                "transformation_kind": transformation_kind,
                "exception_class": type(exc).__name__,
            },
        )
    except Exception:  # noqa: BLE001 — never fail on trace error
        pass


def _emit_iso_perturb_event(report: PerturbationDivergenceReport) -> None:
    """Best-effort emit of ``laziness.violated`` on divergence."""
    if not report.is_pattern_matching:
        return
    try:  # local import breaks the trace → antilazy cycle
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": "isomorphic_divergence",
                "divergences": [
                    {
                        "transformation_kind": d.transformation_kind,
                        "reason": d.reason,
                        "similarity": round(d.similarity, 4),
                    }
                    for d in report.divergences
                ],
                "transformation_count": len(report.transformations),
                "original_intent_chars": len(report.original_intent),
            },
        )
    except Exception:  # noqa: BLE001 — never fail on trace error
        pass


# ---------------------------------------------------------------------------
# Loop-side bundle + gate outcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IsoPerturbBundle:
    """Everything the loop needs to schedule the gate on completion.

    - ``primary`` — the solution producer (typically wraps the primary
      provider); called per transformation.
    - ``companion`` — optional cross-check producer; currently unused
      by the runner but reserved for a v0.5 diversity check.
    - ``config`` — tunables; defaults are the spec floor.
    - ``workspace_symbols`` — identifiers that must not be renamed
      (lateral chain branch B); typically the union of top-level
      symbol names the symbol-graph exposes.
    - ``report_dir`` — where ``iso_perturb.json`` is written on every
      rule-like completion (DoD depth-4 leaf b).
    """

    primary: SolutionProducer
    companion: SolutionProducer | None = None
    config: IsoPerturbConfig = field(default_factory=IsoPerturbConfig)
    workspace_symbols: frozenset[str] = field(default_factory=frozenset)
    report_dir: Path | None = None


@dataclass(frozen=True)
class IsoPerturbGateOutcome:
    """Outcome of the iso-perturbation gate at a completion attempt.

    - ``blocks_complete`` — True when the loop must NOT terminate
      COMPLETE this iteration.
    - ``resume_prompt`` — the string to inject into the next planning
      turn. Empty when the gate did not block.
    - ``report`` — the ``PerturbationDivergenceReport`` (may be None
      when the intent was not rule-like and the gate was skipped).
    - ``skipped_reason`` — ``"non_rule_like"`` when the detector did
      not fire; ``"no_original_solution"`` when the loop had no
      completed solution to compare against; ``None`` when the gate
      ran.
    """

    blocks_complete: bool
    resume_prompt: str
    report: PerturbationDivergenceReport | None = None
    skipped_reason: str | None = None


def run_iso_perturb_gate(
    *,
    intent: str,
    workspace: "WorkspaceSnapshot",
    original_solution: str | None,
    bundle: IsoPerturbBundle,
    run_id: str | None = None,
) -> IsoPerturbGateOutcome:
    """Loop-side wrapper — decide whether to fire the gate and write the report.

    - The detector runs here; a non-rule-like intent returns an
      outcome with ``skipped_reason="non_rule_like"`` and does not
      call the primary at all (branch A / DoD "gate does not fire on
      non-rule-like intents").
    - When the intent is rule-like but no original solution is
      available, the outcome is ``skipped_reason="no_original_solution"``
      and the loop is not blocked (the substrate loop's own gates
      handle that case).
    - When the gate runs, the report is written to
      ``bundle.report_dir / iso_perturb.json`` (DoD depth-4 leaf b).
    """
    detection = detect_rule_like_intent(intent)
    if not detection.is_rule_like:
        return IsoPerturbGateOutcome(
            blocks_complete=False,
            resume_prompt="",
            report=None,
            skipped_reason="non_rule_like",
        )
    if not original_solution:
        return IsoPerturbGateOutcome(
            blocks_complete=False,
            resume_prompt="",
            report=None,
            skipped_reason="no_original_solution",
        )
    report = run_iso_perturbation(
        intent=intent,
        workspace=workspace,
        original_solution=original_solution,
        primary=bundle.primary,
        companion=bundle.companion,
        workspace_symbols=bundle.workspace_symbols,
        config=bundle.config,
    )
    _write_report(report, bundle.report_dir, run_id)
    if not report.is_pattern_matching:
        return IsoPerturbGateOutcome(
            blocks_complete=False,
            resume_prompt="",
            report=report,
            skipped_reason=None,
        )
    resume = _build_resume_prompt(report)
    return IsoPerturbGateOutcome(
        blocks_complete=True,
        resume_prompt=resume,
        report=report,
        skipped_reason=None,
    )


def _build_resume_prompt(report: PerturbationDivergenceReport) -> str:
    """Return the resume prompt injected into the next planning turn."""
    kinds = ", ".join(sorted({d.transformation_kind for d in report.divergences}))
    sample = report.divergences[0]
    return (
        "[ISOMORPHIC DIVERGENCE] the rule-like intent was restated under "
        f"{len(report.transformations)} isomorphic transformation(s) and "
        f"{len(report.divergences)} produced a divergent solution shape "
        f"(kinds: {kinds}). Sample: transformation "
        f"{sample.transformation_kind} diverged with reason "
        f"{sample.reason} (similarity {sample.similarity:.3f}). "
        "The current solution likely pattern-matches the surface form "
        "rather than inducing the underlying rule; extend the solution "
        "so it survives all three transformations."
    )


def _write_report(
    report: PerturbationDivergenceReport,
    report_dir: Path | None,
    run_id: str | None,
) -> None:
    """Write ``iso_perturb.json`` under ``report_dir`` (best effort).

    The write is best-effort so a filesystem error does not fail the
    gate; the report is still returned in-memory to callers. DoD
    depth-4 leaf (b) says the file exists on every rule-like
    completion — the loop's ``report_dir`` is required for that to
    hold in production.
    """
    if report_dir is None:
        return
    try:
        target_dir = report_dir if run_id is None else report_dir / run_id
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "iso_perturb.json").write_text(
            json.dumps(report.to_canonical(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        # Never fail the gate on a write error; the report is still
        # returned in-memory.
        return


__all__ = [
    "Divergence",
    "DivergenceReason",
    "IsoPerturbBundle",
    "IsoPerturbConfig",
    "IsoPerturbGateOutcome",
    "IsomorphicTransformation",
    "PerturbationDivergenceReport",
    "RuleLikeDetection",
    "SolutionProducer",
    "TransformationKind",
    "compare_solutions",
    "detect_rule_like_intent",
    "rename_map_degeneracy_ratio",
    "run_iso_perturb_gate",
    "run_iso_perturbation",
    "transform_intent",
]


# RACT 0.4.0
