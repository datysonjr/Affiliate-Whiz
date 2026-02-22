# Secrets Directory

This directory stores encrypted secrets for the OpenClaw system.

## Rules

1. **NEVER** commit unencrypted secrets to version control
2. All secrets are stored encrypted via the vault system (`src/security/vault.py`)
3. The vault master key is set via environment variable, never stored in files
4. Access to this directory should be restricted to the service account

## Files

- `vault.enc` - Encrypted vault file (created at runtime)
- This `README.md` - Documentation only

## Key Rotation

See `src/security/key_rotation.py` for automated key rotation.
Manual rotation: `python src/cli.py rotate-keys --all`
