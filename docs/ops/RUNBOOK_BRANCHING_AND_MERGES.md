# RUNBOOK_BRANCHING_AND_MERGES.md

Goal: Keep one clean main branch and safe merges.

## Standard Branch Model

- main: always deployable
- feat/*: feature work
- fix/*: bug fixes
- chore/*: maintenance

## If GitHub Has an Empty Default Branch

1) Decide canonical branch name: main
2) Ensure main exists locally
3) Push main and set it as default in GitHub settings
4) Delete the abandoned empty branch (after confirming nothing needed)

## Merge Rules

- Always PR into main
- CI must pass: ruff + mypy + pytest
- Squash merge recommended for clean history

## Release Tags (Optional)

- v0.1.0 = first working staging publish
- v0.2.0 = first live money publish (after go-live runbook)
