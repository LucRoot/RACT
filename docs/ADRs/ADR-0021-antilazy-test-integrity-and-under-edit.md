# ADR-0021 — Sandbox-enforced test integrity and symbol-graph under-edit as pre-commit gates

## Status

Accepted (v0.4.0-rc1, ALM module_03).

## Context

Substrate module_03 (ADR-0012) landed the capability manifest and the
OS sandbox. ALM modules 01 and 02 (ADR-0019, ADR-0020) added the
held-out predicate suite, mutation-kill, patch differentiation, and
coverage delta gates. Two failure modes those gates still admit:

1. **Test-suite tampering.** A patch that passes the visible suite
   because the model deleted assertions, inserted ``pytest.skip``,
   monkey-patched the grader, or edited the conftest that shapes the
   suite. METR named this the "chess-hacking" family: any reward
   channel writable from inside the sandbox is a channel the model
   can trivially maximize without solving the intent.
2. **Under-editing.** A patch that renames a symbol, moves a method,
   or changes a signature without updating every downstream caller.
   The visible suite may still pass because the touched call sites
   were not exercised, but the workspace is inconsistent and the
   next step lands on a stale reference.

ALM spec §3.5 (Gate G5) and §3.6 (Gate G6) close both by adding two
pre-commit checks that attach at the ``WorktreeManager`` merge site
— the write literally does not commit if either gate fires.

Reference sources:

- ALM spec §3.5 (Gate G5), §3.6 (Gate G6); §13 signals 5 and 6.
- Python ``ast`` module (public standard-library documentation).
- METR reward-hacking findings (chess-hacking, monkey-patched
  graders). Public report.
- ``git`` ``.gitattributes`` ``linguist-generated=true`` idiom.
- SUBSTRATE spec §4 (capability manifest) — the ``test_integrity``
  section grows here.

## Decision

Accept both gates as pre-commit enforcement on top of the substrate
transaction.

1. **Test integrity (G5).** ``analyze_diff(parent_snapshot,
   child_snapshot, config)`` walks the diff between parent and child
   workspace snapshots. Any hit against ``config.denied_ast_patterns``
   (``pytest.skip``, ``pytest.xfail``, ``pytest.mark.skip*``),
   ``config.denied_assertion_transforms`` (``assertion_removal``,
   ``assert_true_to_pass``), ``config.denied_file_edits``
   (``tests/**/*grader*.py``, ``tests/**/conftest.py``), or
   ``config.monkey_patch_watchlist`` (``sys.modules['<grader>']``,
   ``builtins.__import__``, ``sys.settrace``) is a hard-block
   violation. ``enforce_g5`` rolls the transaction back and emits
   ``laziness.violated`` with ``kind="test_hack_denied"``.

2. **Symbol graph and under-edit closure (G6).** ``build_graph
   (workspace)`` produces a ``SymbolGraph`` of the Python surface
   using the stdlib ``ast`` module. ``compute_closure(graph,
   edited_symbols, edited_files, passing_tests_touched,
   declared_unaffected)`` returns the set of downstream callers,
   partitioned into covered-by-edit, covered-by-test, covered-by-
   declaration, and uncovered. Non-empty ``uncovered`` rolls the
   transaction back with ``kind="under_edit_uncovered_callers"``.

3. **CapabilityManifest ``test_integrity`` section.** The manifest
   grows a strict-mode ``TestIntegrityConfig`` populated with the
   ALM §3.5 defaults. ``ManifestValidator.validate`` refuses a
   manifest whose ``denied_ast_patterns`` or ``denied_file_edits``
   is empty (``code="test_integrity_section_narrowed"`` /
   ``code="test_integrity_denied_files_missing"``); narrowing
   requires a signed operator handshake (parallel to the tier-3
   compile-time hard-off pattern from ADR-0012).

4. **Metaprogramming-escape detector (Second Pass Q1).** The AST
   analyzer surfaces ``getattr(pytest, 'skip')()``,
   ``pytest.__dict__['skip']()``, and ``exec("pytest.skip()")``
   shapes under the pattern
   ``test_integrity_metaprogramming_escape`` so a model that
   reaches for reflection to bypass the literal-attribute denial
   still surfaces to the trace.

5. **Symbol-graph cache (lateral chain branch B).** The graph
   persists to ``${WORKSPACE_META}/symgraph.db`` (SQLite) with
   ``symbols``, ``call_edges``, and ``import_edges`` tables plus a
   ``meta`` table holding the snapshot digest. ``build_graph``
   loads from the cache when the workspace digest matches; a
   digest mismatch triggers a rebuild.

6. **Generated-file exclusion (lateral chain branch C + Second
   Pass Q4).** The closure reads ``.gitattributes`` for
   ``linguist-generated=true`` annotations plus a per-language
   heuristic default (``*_pb2.py``, ``*_pb2_grpc.py``,
   ``**/generated/**``, ``**/gen/**``) so workspaces without
   explicit annotations do not surface false-positive under-edit
   violations on generated code.

7. **Platform-skip exemption (lateral chain branch A).** A
   ``pytest.skip(reason=...)`` call whose reason string matches
   one of ``allowed_skip_reason_substrings`` (``"only on
   windows"``, ``"requires linux"``, ``"platform-specific"``, ...)
   or whose call arguments contain a ``sys.platform`` reference is
   exempt from the denial. ``@pytest.mark.skipif(sys.platform ==
   ...)`` decorators are exempt on the same basis. Portability
   skips do not train the operator to disable the gate.

8. **Unsupported-language advisory (lateral chain branch D).**
   Test files in TypeScript, Go, or Rust surface a
   ``test_integrity_unsupported_language`` violation with
   ``severity="advisory"``; the gate does not roll back but the
   trace records the coverage gap so a reviewer can see what the
   analyzer actually consulted. v0.5 tree-sitter work owns the
   language expansion.

## Rejected alternatives

- **Lint-level check only.** A ``ruff``/``flake8`` rule
  forbidding ``pytest.skip`` can be disabled at the same layer.
  G5 needs sandbox-layer enforcement so the model cannot silently
  turn off its own reward-channel gate. Merge-site enforcement is
  the only shape that survives a hostile diff.

- **Test integrity at CI time only.** By the time CI runs, the
  diff has already merged into the parent snapshot. A CI-only
  check catches the pattern but does not prevent the state
  corruption. The pre-commit worktree gate is the only layer where
  a rollback is meaningful.

- **Symbol graph via LSP only.** LSP is optional; some workspaces
  do not have a language server running. ``tree-sitter`` is
  always installable and its Python grammar is stable — but we
  ship stdlib ``ast`` for v0.4.0-rc1 because Python-only coverage
  is what the DoD requires and the extra runtime dep would be
  premature. Tree-sitter migration is a v0.5 ADR when the
  language-expansion pipeline needs the wider grammar surface.

- **Coverage-of-caller as a proxy for graph closure.** A caller
  that is never covered by any test at all would produce a
  false-negative on this proxy; the whole point of G6 is to catch
  the case where the caller is not covered. The symbol graph is
  the only signal that catches under-editing independent of the
  test suite's shape.

- **Tree-sitter as the parser now.** Attractive for the eventual
  multi-language expansion, but stdlib ``ast`` already covers
  every Python shape G6 needs and does not add a runtime
  dependency. Deferring the switch keeps the module scope
  honest: Python-only coverage plus a documented extension
  surface, not a false promise of TypeScript / Go / Rust support
  the module has not implemented.

## Consequences

- Every ``StepTransaction`` in the ALM-enabled loop now pays two
  additional pre-commit checks: an AST diff of touched test files
  (linear in the size of the diff) and a symbol-graph closure
  over edited symbols (linear in the graph size, memoized on
  workspace digest).
- The trace vocabulary gains no new event kind. G5 emits
  ``laziness.violated`` with ``kind="test_hack_denied"``; G6
  emits ``laziness.violated`` with
  ``kind="under_edit_uncovered_callers"``. Both share
  vocabulary with the earlier G1-G4 landings.
- A future ADR will replace stdlib ``ast`` with tree-sitter when
  v0.5 opens TypeScript / Go / Rust coverage. The extension
  points are declared in ``testintegrity.py`` and ``symgraph.py``
  today; the switch is a parser change, not an API change.
- Handshake-approved denials do not carry a per-run cap (Second
  Pass Q3, deferred to Flagged gaps). Cluster analysis to catch
  habitual handshake-approval patterns lands in a v0.5 hardening
  pipeline; the trace is the current safety net.

## References

- ``src/ract/antilazy/testintegrity.py`` — G5 AST diff analyzer.
- ``src/ract/antilazy/symgraph.py`` — G6 symbol graph, closure,
  SQLite cache.
- ``src/ract/antilazy/pre_commit.py`` — ``enforce_g5`` and
  ``enforce_g6`` helpers.
- ``src/ract/executor/worktree.py`` — ``_check_test_integrity``
  and ``_check_under_edit`` pre-commit hooks.
- ``src/ract/security/manifest.py`` — ``TestIntegrityConfig``
  section; ``ManifestValidator`` narrowing refusal.
- ``tests/test_antilazy_g5_g6.py`` — the 13-test DoD floor plus
  the Second Pass adversarial-question guards.
- ``evals/antilazy/G5-G6/`` — three fixture tasks:
  ``pytest_skip_net_new``, ``grader_edit``,
  ``symbol_rename_uncovered``.
- ``docs/RACT_v0.4.0_ANTILAZY_SPEC.md`` §3.5, §3.6, §13 signals
  5 and 6.
