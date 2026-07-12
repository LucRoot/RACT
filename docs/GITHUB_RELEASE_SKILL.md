: Rooted by Dr. Lucas Root, Ph.D.
# GitHub Release Skill

The `release` skill lets RACT list and create GitHub releases for a project
configured in `rootact.yaml`.

## Status

Implemented in RACT v0.1.2.

## Configuration

Add a `github` section to `rootact.yaml`:

```yaml
github:
  owner: LucRoot
  repo: rootact
```

The skill reads the `GITHUB_TOKEN` environment variable. The token must have
`repo` scope for private repositories or `public_repo` for public ones. RACT
never prints the token.

## Commands

### List releases

```bash
ract release list
ract release list --config path/to/rootact.yaml
```

Prints a table of existing releases with tag, name, and draft status.

### Create a release

```bash
ract release create \
  --tag v0.1.2 \
  --name "RACT 0.1.2" \
  --body "Release notes here"
```

Optional flags:

- `--asset FILE` — upload an asset (repeatable).
- `--draft` — create as a draft release.
- `--prerelease` — mark as a prerelease.

Example with assets:

```bash
ract release create \
  --tag v0.1.2 \
  --name "RACT 0.1.2" \
  --body "See CHANGELOG.md" \
  --asset dist/rootact-0.1.2-py3-none-any.whl \
  --asset dist/rootact-0.1.2.tar.gz
```

## Error handling

Missing `GITHUB_TOKEN`, missing config, or missing `github.owner`/`github.repo`
produce a clear message and exit code `1`. GitHub API errors are surfaced
through `GitHubReleaseError` without leaking the token.
