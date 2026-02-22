"""
OpenClaw constants, enumerations, and default values.

Centralises magic strings and numeric defaults so the rest of the codebase
can reference them symbolically.  Changing a value here propagates everywhere.
"""

from __future__ import annotations

from enum import Enum, unique


# ---------------------------------------------------------------------------
# Application metadata
# ---------------------------------------------------------------------------

APP_NAME: str = "OpenClaw"
APP_VERSION: str = "0.1.0"
APP_USER_AGENT: str = f"{APP_NAME}/{APP_VERSION}"


# ---------------------------------------------------------------------------
# Agent names  (must match keys in config/agents.yaml)
# ---------------------------------------------------------------------------

@unique
class AgentName(str, Enum):
    """Canonical agent identifiers used for logging, routing, and config lookup."""

    MASTER_SCHEDULER = "master_scheduler"
    RESEARCH = "research"
    CONTENT_GENERATION = "content_generation"
    PUBLISHING = "publishing"
    ANALYTICS = "analytics"
    HEALTH_MONITOR = "health_monitor"
    ERROR_RECOVERY = "error_recovery"
    TRAFFIC_ROUTING = "traffic_routing"

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Pipeline names  (must match keys in config/pipelines.yaml)
# ---------------------------------------------------------------------------

@unique
class PipelineName(str, Enum):
    """Canonical pipeline identifiers."""

    OFFER_DISCOVERY = "offer_discovery"
    CONTENT = "content"
    PUBLISHING = "publishing"
    OPTIMIZATION = "optimization"

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

@unique
class TaskStatus(str, Enum):
    """Status of an orchestrator task (agent run, pipeline invocation)."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"

    def is_terminal(self) -> bool:
        """Return True if the task is in a final state."""
        return self in (
            TaskStatus.SUCCESS,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMED_OUT,
            TaskStatus.SKIPPED,
        )


@unique
class ContentStatus(str, Enum):
    """Lifecycle status of a content piece."""

    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    ARCHIVED = "archived"


@unique
class OfferTier(str, Enum):
    """Quality tier assigned to discovered affiliate offers."""

    A = "A"
    B = "B"
    C = "C"
    REJECTED = "rejected"


@unique
class RiskLevel(str, Enum):
    """Risk classification for agents and actions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@unique
class NodeRole(str, Enum):
    """Node role in the two-node Mac Mini cluster topology."""

    CORE = "core"      # oc-core-01: orchestrator, research, content, db
    PUBLISHER = "pub"  # oc-pub-01: publishing, CMS, DNS, monitoring


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

# Retry / backoff
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BASE_DELAY: float = 1.0       # seconds
DEFAULT_RETRY_MAX_DELAY: float = 60.0       # seconds
DEFAULT_RETRY_EXPONENTIAL_BASE: float = 2.0

# Content
DEFAULT_TARGET_WORD_COUNT: int = 1500
DEFAULT_MIN_WORD_COUNT: int = 1000
DEFAULT_KEYWORD_DENSITY: float = 0.015       # 1.5 %
DEFAULT_MAX_INTERNAL_LINKS: int = 8
DEFAULT_MIN_INTERNAL_LINKS: int = 3
DEFAULT_QUALITY_THRESHOLD: float = 0.7

# Publishing
DEFAULT_POSTING_CADENCE_PER_DAY: int = 1
DEFAULT_MAX_POSTS_PER_DAY: int = 3
DEFAULT_COOLDOWN_MINUTES: int = 30

# Offers
DEFAULT_MIN_OFFER_SCORE: int = 40
OFFER_TIER_THRESHOLDS: dict[str, int] = {"A": 80, "B": 60, "C": 40}

# Scheduling
DEFAULT_HEARTBEAT_INTERVAL_SECONDS: int = 60
DEFAULT_SCHEDULER_INTERVAL_SECONDS: int = 1800  # 30 min

# Logging
DEFAULT_LOG_LEVEL: str = "INFO"
DEFAULT_LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DEFAULT_LOG_FILE: str = "logs/openclaw.log"
DEFAULT_LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
DEFAULT_LOG_BACKUP_COUNT: int = 5

# Database
DEFAULT_DB_PATH: str = "data/openclaw.db"

# Network / HTTP
DEFAULT_REQUEST_TIMEOUT: int = 30  # seconds
DEFAULT_USER_AGENT: str = APP_USER_AGENT

# Config file paths (relative to project root)
CONFIG_DIR: str = "config"
ENV_FILE: str = ".env"
YAML_CONFIG_FILES: list[str] = [
    "agents.yaml",
    "cluster.yaml",
    "niches.yaml",
    "org.yaml",
    "pipelines.yaml",
    "providers.yaml",
    "schedules.yaml",
    "sites.yaml",
    "thresholds.yaml",
]
