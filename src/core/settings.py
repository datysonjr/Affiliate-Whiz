"""
core.settings
~~~~~~~~~~~~~

Centralized configuration management for the OpenClaw system.

Loads settings from multiple sources in priority order:

1. Environment variables (highest priority -- overrides everything)
2. ``.env`` file in the project root
3. YAML files under ``config/`` (agents.yaml, pipelines.yaml, etc.)
4. Built-in defaults from :mod:`core.constants`

The :class:`Settings` singleton validates that all required fields are
present at startup and provides typed accessors so the rest of the
codebase never touches raw dicts or ``os.environ`` directly.

Usage::

    from src.core.settings import settings

    db_path = settings.get_str("database.path")
    max_retries = settings.get_int("retry.max_retries", default=3)
    agent_cfg = settings.agent_config("research")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, TypeVar

from src.core.constants import (
    CONFIG_DIR,
    DEFAULT_DB_PATH,
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT,
    ENV_FILE,
    YAML_CONFIG_FILES,
)
from src.core.errors import ConfigError

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Optional dependency: PyYAML
# ---------------------------------------------------------------------------
try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Optional dependency: python-dotenv
# ---------------------------------------------------------------------------
try:
    from dotenv import dotenv_values  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    dotenv_values = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Required environment variables (will raise ConfigError if missing)
# ---------------------------------------------------------------------------
REQUIRED_ENV_VARS: list[str] = [
    # None strictly required for startup -- add as integrations land.
    # Example: "OPENAI_API_KEY", "WORDPRESS_APP_PASSWORD"
]


def _find_project_root(start: Path | None = None) -> Path:
    """Walk upward from *start* until we find a directory containing ``config/``.

    Falls back to the current working directory if nothing matches.

    Parameters
    ----------
    start:
        Starting directory.  Defaults to the parent of this file.

    Returns
    -------
    Path
        Absolute path to the project root.
    """
    cursor = (start or Path(__file__)).resolve()
    for parent in [cursor] + list(cursor.parents):
        if (parent / CONFIG_DIR).is_dir():
            return parent
    return Path.cwd()


class Settings:
    """Unified, read-only configuration store for the OpenClaw system.

    :class:`Settings` merges data from ``.env``, YAML config files, and
    environment variables into a single nested dict, then exposes typed
    accessor methods for safe lookups.

    Parameters
    ----------
    project_root:
        Absolute path to the project root.  If ``None``, the class
        auto-detects the root by walking upward from this source file.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, project_root: Path | str | None = None) -> None:
        self._root = Path(project_root) if project_root else _find_project_root()
        self._env: Dict[str, str] = {}
        self._yaml: Dict[str, Any] = {}
        self._merged: Dict[str, Any] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> "Settings":
        """Load all configuration sources and validate required fields.

        Calling ``load()`` multiple times re-reads from disk (useful for
        the ``reload-config`` CLI command).

        Raises
        ------
        ConfigError
            If a required environment variable is missing or a YAML file
            cannot be parsed.
        """
        self._load_dotenv()
        self._load_yaml_configs()
        self._merge()
        self._validate()
        self._loaded = True
        return self

    def _load_dotenv(self) -> None:
        """Read the ``.env`` file if it exists and ``python-dotenv`` is available."""
        env_path = self._root / ENV_FILE
        if dotenv_values is not None and env_path.is_file():
            raw = dotenv_values(env_path)
            self._env = {k: v for k, v in raw.items() if v is not None}
        else:
            self._env = {}

    def _load_yaml_configs(self) -> None:
        """Read every YAML file listed in :data:`YAML_CONFIG_FILES`."""
        if yaml is None:
            return

        config_dir = self._root / CONFIG_DIR
        if not config_dir.is_dir():
            return

        for filename in YAML_CONFIG_FILES:
            filepath = config_dir / filename
            if not filepath.is_file():
                continue
            try:
                with filepath.open("r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if isinstance(data, dict):
                    # Key = filename without extension (e.g. "agents")
                    key = filepath.stem
                    self._yaml[key] = data
            except yaml.YAMLError as exc:
                raise ConfigError(
                    f"Failed to parse {filepath}",
                    details={"file": str(filepath)},
                    cause=exc,
                ) from exc

    def _merge(self) -> None:
        """Build the final merged dict: defaults < yaml < .env < os.environ."""
        merged: Dict[str, Any] = {}

        # Layer 1: built-in defaults
        merged["database"] = {"path": DEFAULT_DB_PATH}
        merged["log"] = {
            "level": DEFAULT_LOG_LEVEL,
            "file": DEFAULT_LOG_FILE,
        }
        merged["retry"] = {"max_retries": DEFAULT_MAX_RETRIES}
        merged["http"] = {"timeout": DEFAULT_REQUEST_TIMEOUT}

        # Layer 2: YAML configs
        merged.update(self._yaml)

        # Layer 3: .env values
        merged["env"] = {**self._env}

        # Layer 4: live environment variables (highest priority)
        merged["env"].update(
            {k: v for k, v in os.environ.items() if k.startswith("OPENCLAW_")}
        )

        self._merged = merged

    def _validate(self) -> None:
        """Ensure all required environment variables are set.

        Raises
        ------
        ConfigError
            Lists every missing variable in a single error.
        """
        missing: list[str] = []
        for var in REQUIRED_ENV_VARS:
            if var not in self._env and var not in os.environ:
                missing.append(var)
        if missing:
            raise ConfigError(
                f"Missing required environment variables: {', '.join(missing)}",
                details={"missing_vars": missing},
            )

    # ------------------------------------------------------------------
    # Typed accessors
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Retrieve a value using a dot-separated key path.

        Parameters
        ----------
        dotted_key:
            Key path like ``"agents.research.frequency_seconds"``.
        default:
            Returned when the key is not found.

        Returns
        -------
        Any
            The configuration value, or *default*.

        Examples
        --------
        >>> settings.get("agents.research.enabled")
        True
        >>> settings.get("nonexistent.key", 42)
        42
        """
        self._ensure_loaded()
        parts = dotted_key.split(".")
        node: Any = self._merged
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def get_str(self, dotted_key: str, default: str = "") -> str:
        """Return a string value (empty string if missing)."""
        value = self.get(dotted_key, default)
        return str(value) if value is not None else default

    def get_int(self, dotted_key: str, default: int = 0) -> int:
        """Return an integer value.

        Raises
        ------
        ConfigError
            If the raw value cannot be converted to ``int``.
        """
        value = self.get(dotted_key, default)
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"Config key {dotted_key!r} is not a valid integer: {value!r}",
                details={"key": dotted_key, "raw_value": value},
                cause=exc,
            ) from exc

    def get_float(self, dotted_key: str, default: float = 0.0) -> float:
        """Return a float value.

        Raises
        ------
        ConfigError
            If the raw value cannot be converted to ``float``.
        """
        value = self.get(dotted_key, default)
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"Config key {dotted_key!r} is not a valid float: {value!r}",
                details={"key": dotted_key, "raw_value": value},
                cause=exc,
            ) from exc

    def get_bool(self, dotted_key: str, default: bool = False) -> bool:
        """Return a boolean value.

        Truthy strings: ``"true"``, ``"1"``, ``"yes"``, ``"on"`` (case-insensitive).
        """
        value = self.get(dotted_key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "on")
        return bool(value)

    def get_list(self, dotted_key: str, default: Optional[List[Any]] = None) -> List[Any]:
        """Return a list value (empty list if missing)."""
        value = self.get(dotted_key, default)
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    # ------------------------------------------------------------------
    # Convenience accessors for common config sections
    # ------------------------------------------------------------------

    def agent_config(self, agent_name: str) -> Dict[str, Any]:
        """Return the full config dict for a specific agent.

        Parameters
        ----------
        agent_name:
            Agent identifier matching a top-level key in ``config/agents.yaml``.

        Raises
        ------
        ConfigError
            If the agent is not defined in configuration.
        """
        agents = self.get("agents", {})
        if not isinstance(agents, dict):
            raise ConfigError("'agents' config section is not a dict")
        if agent_name not in agents:
            raise ConfigError(
                f"No configuration found for agent {agent_name!r}",
                details={"known_agents": list(agents.keys())},
            )
        return dict(agents[agent_name])

    def pipeline_config(self, pipeline_name: str) -> Dict[str, Any]:
        """Return the full config dict for a specific pipeline."""
        pipelines = self.get("pipelines", {})
        if not isinstance(pipelines, dict):
            raise ConfigError("'pipelines' config section is not a dict")
        if pipeline_name not in pipelines:
            raise ConfigError(
                f"No configuration found for pipeline {pipeline_name!r}",
                details={"known_pipelines": list(pipelines.keys())},
            )
        return dict(pipelines[pipeline_name])

    def env_var(self, name: str, default: str = "") -> str:
        """Return an environment variable from .env or ``os.environ``.

        Priority: ``os.environ`` > ``.env`` file > *default*.

        Parameters
        ----------
        name:
            Variable name (e.g. ``"OPENAI_API_KEY"``).
        default:
            Fallback value.
        """
        self._ensure_loaded()
        return os.environ.get(name, self._env.get(name, default))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def project_root(self) -> Path:
        """Return the resolved project root path."""
        return self._root

    @property
    def is_loaded(self) -> bool:
        """Return ``True`` if :meth:`load` has been called successfully."""
        return self._loaded

    def as_dict(self) -> Dict[str, Any]:
        """Return a *copy* of the full merged configuration.

        Useful for debugging.  Secrets in the ``env`` sub-dict are masked.
        """
        self._ensure_loaded()
        import copy

        snapshot = copy.deepcopy(self._merged)
        # Mask secrets in the env section
        if "env" in snapshot and isinstance(snapshot["env"], dict):
            for key in snapshot["env"]:
                upper = key.upper()
                if any(
                    secret_word in upper
                    for secret_word in ("KEY", "SECRET", "PASSWORD", "TOKEN", "CREDENTIAL")
                ):
                    snapshot["env"][key] = "***MASKED***"
        return snapshot

    def __repr__(self) -> str:
        return (
            f"Settings(root={self._root}, loaded={self._loaded}, "
            f"yaml_sections={list(self._yaml.keys())})"
        )


# ---------------------------------------------------------------------------
# Module-level singleton -- import ``settings`` and call ``settings.load()``
# once during startup.
# ---------------------------------------------------------------------------
settings = Settings()
