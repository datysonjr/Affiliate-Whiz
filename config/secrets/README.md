# Secrets (DO NOT COMMIT)

This folder should never contain real secrets committed to git.

Use:
- environment variables
- a team password manager
- a local secrets file that is gitignored

Rules:
- Never print secrets in logs.
- Use staging credentials for testing.
- Rotate credentials if leaked or team changes.
