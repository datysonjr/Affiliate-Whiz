"""
security.vault
~~~~~~~~~~~~~~

File-based encrypted secret storage for the OpenClaw system.

Provides a :class:`Vault` that stores API keys, credentials, and other
sensitive values in an encrypted JSON file on disk.  Secrets are encrypted
using Fernet symmetric encryption (from the ``cryptography`` library if
available) or a basic XOR-based fallback for environments without the
dependency.

The vault supports lock/unlock semantics: the master key must be provided
to decrypt secrets, and the vault can be explicitly locked to prevent
accidental access during non-operational periods.

Usage::

    from src.security.vault import Vault

    vault = Vault("data/secrets.vault")
    vault.unlock(master_key="my-secret-master-key")
    vault.store_secret("OPENAI_API_KEY", "sk-abc123...")
    api_key = vault.get_secret("OPENAI_API_KEY")
    vault.lock()

Design references:
    - ARCHITECTURE.md  Section 8 (Security)
    - AI_RULES.md  Ethical Guidelines (credential management)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional

from src.core.errors import SecurityError, CredentialMissingError
from src.core.logger import get_logger, log_event

logger = get_logger("security.vault")

# Default vault file location
DEFAULT_VAULT_PATH = "data/secrets.vault"

# ---------------------------------------------------------------------------
# Optional dependency: cryptography (Fernet)
# ---------------------------------------------------------------------------
try:
    from cryptography.fernet import Fernet  # type: ignore[import-untyped]

    _HAS_FERNET = True
except ImportError:  # pragma: no cover
    _HAS_FERNET = False


def _derive_fernet_key(master_key: str) -> bytes:
    """Derive a 32-byte Fernet-compatible key from an arbitrary master key.

    Uses PBKDF2 with SHA-256 and a fixed salt (acceptable for a local
    single-user vault; production should use a random salt stored alongside).

    Parameters
    ----------
    master_key:
        The user-provided master password or key.

    Returns
    -------
    bytes
        URL-safe base64-encoded 32-byte key suitable for Fernet.
    """
    salt = b"openclaw-vault-salt-v1"
    dk = hashlib.pbkdf2_hmac("sha256", master_key.encode("utf-8"), salt, 100_000)
    return base64.urlsafe_b64encode(dk)


def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    """Simple XOR cipher for environments without ``cryptography``.

    This is NOT cryptographically secure -- it exists only as a minimal
    obfuscation fallback.  Install ``cryptography`` for real encryption.

    Parameters
    ----------
    data:
        Plaintext bytes to encrypt.
    key:
        Key bytes (will be cycled if shorter than data).

    Returns
    -------
    bytes
        XOR-encrypted bytes.
    """
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


# XOR decrypt is the same operation as encrypt
_xor_decrypt = _xor_encrypt


class Vault:
    """File-based encrypted secret storage.

    Secrets are stored as a JSON dictionary encrypted with either Fernet
    (preferred) or XOR fallback.  The vault must be ``unlock()``-ed with a
    master key before secrets can be read or written.

    Parameters
    ----------
    vault_path:
        Filesystem path to the encrypted vault file.
    """

    def __init__(self, vault_path: str = DEFAULT_VAULT_PATH) -> None:
        self._vault_path = vault_path
        self._lock = threading.RLock()
        self._secrets: Dict[str, str] = {}
        self._master_key: Optional[str] = None
        self._is_locked = True
        self._modified = False

    # ------------------------------------------------------------------
    # Lock / Unlock
    # ------------------------------------------------------------------

    def unlock(self, master_key: str) -> None:
        """Unlock the vault and load secrets from disk.

        If the vault file does not exist, an empty vault is initialised.

        Parameters
        ----------
        master_key:
            The master encryption key or passphrase.

        Raises
        ------
        SecurityError
            If the vault file exists but cannot be decrypted (wrong key
            or corrupt data).
        """
        with self._lock:
            self._master_key = master_key
            vault_file = Path(self._vault_path)

            if vault_file.is_file():
                self._load_from_disk()
            else:
                self._secrets = {}

            self._is_locked = False
            self._modified = False
            log_event(logger, "vault.unlocked", path=self._vault_path)

    def lock(self) -> None:
        """Lock the vault, persisting any changes and clearing secrets from memory.

        After locking, all secret access requires another ``unlock()`` call.
        """
        with self._lock:
            if self._modified and not self._is_locked:
                self._save_to_disk()

            self._secrets.clear()
            self._master_key = None
            self._is_locked = True
            self._modified = False
            log_event(logger, "vault.locked", path=self._vault_path)

    @property
    def is_locked(self) -> bool:
        """Return ``True`` if the vault is locked."""
        return self._is_locked

    def _ensure_unlocked(self) -> None:
        """Raise if the vault is locked."""
        if self._is_locked:
            raise SecurityError(
                "Vault is locked. Call unlock() with the master key first."
            )

    # ------------------------------------------------------------------
    # Secret operations
    # ------------------------------------------------------------------

    def store_secret(self, key: str, value: str) -> None:
        """Store a secret value under the given key.

        Overwrites any existing value for the same key.  Changes are
        persisted to disk immediately.

        Parameters
        ----------
        key:
            Secret identifier (e.g. ``"OPENAI_API_KEY"``).
        value:
            The secret value to store.

        Raises
        ------
        SecurityError
            If the vault is locked.
        """
        with self._lock:
            self._ensure_unlocked()
            self._secrets[key] = value
            self._modified = True
            self._save_to_disk()
            log_event(logger, "vault.secret_stored", key=key)

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve a secret by key.

        Parameters
        ----------
        key:
            Secret identifier.
        default:
            Value to return if the key is not found.  If ``None`` and the
            key is missing, raises ``CredentialMissingError``.

        Returns
        -------
        str or None
            The secret value.

        Raises
        ------
        SecurityError
            If the vault is locked.
        CredentialMissingError
            If the key is not found and no default is provided.
        """
        with self._lock:
            self._ensure_unlocked()
            if key in self._secrets:
                return self._secrets[key]
            if default is not None:
                return default
            raise CredentialMissingError(
                f"Secret {key!r} not found in vault",
                details={"key": key, "available_keys": list(self._secrets.keys())},
            )

    def delete_secret(self, key: str) -> bool:
        """Remove a secret from the vault.

        Parameters
        ----------
        key:
            Secret identifier to remove.

        Returns
        -------
        bool
            ``True`` if the secret existed and was removed.

        Raises
        ------
        SecurityError
            If the vault is locked.
        """
        with self._lock:
            self._ensure_unlocked()
            if key not in self._secrets:
                return False
            del self._secrets[key]
            self._modified = True
            self._save_to_disk()
            log_event(logger, "vault.secret_deleted", key=key)
            return True

    def list_keys(self) -> List[str]:
        """Return a list of all stored secret keys.

        The values themselves are not exposed -- only the key names.

        Returns
        -------
        list[str]
            Secret key identifiers.

        Raises
        ------
        SecurityError
            If the vault is locked.
        """
        with self._lock:
            self._ensure_unlocked()
            return list(self._secrets.keys())

    def has_secret(self, key: str) -> bool:
        """Check whether a secret exists without retrieving its value.

        Parameters
        ----------
        key:
            Secret identifier to check.

        Returns
        -------
        bool
            ``True`` if the secret exists.
        """
        with self._lock:
            self._ensure_unlocked()
            return key in self._secrets

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt plaintext using the current master key."""
        assert self._master_key is not None

        if _HAS_FERNET:
            fernet_key = _derive_fernet_key(self._master_key)
            f = Fernet(fernet_key)
            return f.encrypt(plaintext)
        else:
            # XOR fallback (not cryptographically secure)
            key_bytes = hashlib.sha256(self._master_key.encode("utf-8")).digest()
            encrypted = _xor_encrypt(plaintext, key_bytes)
            return base64.b64encode(encrypted)

    def _decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt ciphertext using the current master key."""
        assert self._master_key is not None

        if _HAS_FERNET:
            fernet_key = _derive_fernet_key(self._master_key)
            f = Fernet(fernet_key)
            try:
                return f.decrypt(ciphertext)
            except Exception as exc:
                raise SecurityError(
                    "Failed to decrypt vault (wrong master key or corrupt data)",
                    cause=exc,
                ) from exc
        else:
            key_bytes = hashlib.sha256(self._master_key.encode("utf-8")).digest()
            try:
                raw = base64.b64decode(ciphertext)
                return _xor_decrypt(raw, key_bytes)
            except Exception as exc:
                raise SecurityError(
                    "Failed to decrypt vault (wrong master key or corrupt data)",
                    cause=exc,
                ) from exc

    def _save_to_disk(self) -> None:
        """Encrypt and write all secrets to the vault file."""
        plaintext = json.dumps(self._secrets, indent=2).encode("utf-8")
        ciphertext = self._encrypt(plaintext)

        path = Path(self._vault_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write atomically via temp file
        tmp_path = path.with_suffix(".tmp")
        try:
            tmp_path.write_bytes(ciphertext)
            tmp_path.replace(path)
            # Restrict file permissions (owner read/write only)
            os.chmod(str(path), 0o600)
        except OSError as exc:
            raise SecurityError(
                f"Failed to write vault file: {self._vault_path}",
                cause=exc,
            ) from exc

        self._modified = False
        log_event(logger, "vault.saved", path=self._vault_path, keys=len(self._secrets))

    def _load_from_disk(self) -> None:
        """Read and decrypt secrets from the vault file."""
        path = Path(self._vault_path)
        ciphertext = path.read_bytes()
        plaintext = self._decrypt(ciphertext)

        try:
            self._secrets = json.loads(plaintext.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SecurityError(
                "Vault data is corrupt or was encrypted with a different key",
                cause=exc,
            ) from exc

        log_event(
            logger, "vault.loaded", path=self._vault_path, keys=len(self._secrets)
        )

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Vault(path={self._vault_path!r}, "
            f"locked={self._is_locked}, "
            f"keys={len(self._secrets) if not self._is_locked else '?'})"
        )

    def __del__(self) -> None:
        """Ensure secrets are cleared from memory on garbage collection."""
        self._secrets.clear()
        self._master_key = None
