# Rooted by Dr. Lucas Root, Ph.D.

# RACT Skill Authoring Guide

Skills are reusable prompt templates that prepend context to an intent. They let you codify recurring styles, constraints, or workflows so every run starts from the same baseline.

## Where skills live

Skills are stored as JSON files under `skills/` inside your project directory (usually `.rootact/skills/` once installed, or `skills/` at the project root). Each JSON file contains a name, a template string, and an optional list of tools.

```
my_project/
  rootact.yaml
  skills/
    terse.json
    pytest_only.json
```

Reference the skill in `rootact.yaml`:

```yaml
skill: terse
```

Now every run prepends the rendered skill template to the intent before planning.

## Skill file format

A skill is a JSON object with three keys:

```json
{
  "name": "terse",
  "description": "Keep generated code terse and explicit.",
  "template": "STYLE GUIDE FOR THIS RUN:\n\n- Keep all generated code under 80 columns.\n- Prefer explicit over implicit.\n- Write one assertion per test case.\n\nIntent: $intent",
  "tools": []
}
```

- `name` — the skill identifier. Must match the filename stem.
- `description` — a one-line summary shown in `rootact skills list` after installation.
- `template` — the prompt fragment. RACT renders it with Python's `string.Template` and prepends the result to the user intent.
- `tools` — optional list of tool names the skill may invoke.

## Template variables

RACT passes these variables to `safe_substitute`:

- `$intent` — the user's original intent.
- `$project_name` — the project name from `rootact.yaml`.
- `$context` — the curated project context block, if any.

Example template that mentions the project name:

```json
{
  "name": "project_aware",
  "template": "You are working on $project_name.\n\nRelevant project context:\n$context\n\nPlease handle this intent: $intent",
  "tools": []
}
```

Unknown `$variables` are left untouched, so a skill template can safely include literal dollar signs that do not match the supported variables.

## Authoring a skill in the RACT voice

A strong RACT skill encodes the author's style, not just a generic instruction. Use the same markers you expect in generated code:

```json
{
  "name": "root_knot_python",
  "description": "Generate Python files that carry the Root Knot and return Rooted results.",
  "template": "RACT PYTHON SKILL\n\nGenerate Python code for this intent: $intent\n\nRequired style:\n- Every non-__init__.py file must carry:\n    __root_author__ = \"Dr. Lucas Root, Ph.D.\"\n    __ract_name__ = \"RACT\"\n    _ROOT_KNOT = object()\n- Functions that depend on unstated assumptions return Rooted[T] with assumption, confidence, and provenance.\n- No bare except blocks. No silent error masks.\n- Include an LR:: comment explaining one non-obvious choice.",
  "tools": []
}
```

## Compose multiple skills

RACT selects one skill per run via the `skill` config key. To combine behaviors, create a composite skill that copies the contents of sub-skills into one template, or write a single skill that bundles the rules you want.

## Install and test a skill

Place the JSON file in `skills/` or install it with:

```bash
rootact skills install my_skill
```

Run a dry-run with the skill active to see how the plan changes:

```bash
rootact "add a new module" --config rootact.yaml --dry-run
```

Iterate on the skill template until the plan reflects the desired style.

## Built-in skills

RACT ships with signed templates in `src/rootact/builtin_skills/`. Inspect them with:

```bash
rootact skills list
```

They are ordinary JSON skill files, so you can copy one into your project `skills/` directory and customize it.

## Best practices

- Keep skills focused. One behavior per skill is easier to reason about than a large composite.
- Name skills after the behavior they encode.
- Version-control skills with your project so teammates get consistent behavior.
- Do not put secrets in skill templates.
- Include a `description` so `rootact skills list` remains useful.

<!-- RACT 0.1.1 - Trust and Tooling -->
