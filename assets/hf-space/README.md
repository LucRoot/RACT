# RACT Hugging Face Space

This directory contains a static HTML landing page for RACT's Hugging Face Space.

## Deployment

1. Create a new Hugging Face Space with the **Static** template.
2. Copy `index.html` (and optionally this `README.md`) into the Space repository root.
3. Push. Hugging Face will serve `index.html` at the Space URL.

## Keeping the page in sync

The page mirrors the README's headline, quick start, and feature list. When those change, update `assets/hf-space/index.html` and re-copy to the Space repository. A future loop pass may generate this page from a canonical project manifest instead of maintaining it by hand.
