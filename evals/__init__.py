"""RACT evals package — module_07 (v0.4.0).

Making ``evals`` importable lets the module_07 runners share types
across ``evals.polyglot`` and ``evals.swe_bench_lite`` without falling
back to the load-by-path pattern the v0.3 refactor-token-usage
benchmark uses. See ``pyproject.toml`` ``[tool.pytest.ini_options]
pythonpath``.
"""

# RACT 0.4.0
