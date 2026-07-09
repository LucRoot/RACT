# RACT on Hugging Face Spaces

This directory contains a static HTML landing page for RACT, deployed as a Hugging Face Space.

## Deployment

1. Create a new HF Space with SDK **Static**.
2. Push the contents of `assets/hf-space/` to the Space repository root.
3. HF Spaces will serve `index.html` at the Space URL.

## Files

- `index.html` — public landing page with install instructions, feature overview, and comparison table.

## Updating

Edit `assets/hf-space/index.html` in the main RACT repository, then copy it to the HF Space repo and push.
