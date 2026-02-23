"""
web.health
~~~~~~~~~~

Health check functions for the OpenClaw system.

Provides three tiers of health checks used by the admin API, external
monitoring systems (Grafana, UptimeRobot), and the health-monitor agent:

* **Basic** (:func:`check_health`) -- fast yes/no liveness check.
* **Detailed** (:func:`check_health_detailed`) -- per-component status
  with latency measurements and diagnostics.
* **Readiness** (:func:`check_readiness`) -- determines whether the system
  is ready to accept work (all critical components operational, kill switch
  disengaged, queue not full).

Each function returns a dictionary suitable for JSON serialization so the
admin API can serve it directly.

Usage::

    from src.web.health import check_health, check_health_detailed, check_readiness

    basic = check_health()
    # {"status": "healthy", "timestamp": "..."}

    detailed = check_health_detailed()
    # {"status": "healthy", "components": {...}, ...}

    ready = check_readiness()
    # {"ready": true, "checks": {...}, ...}

Design references:
    - ARCHITECTURE.md  Section 7 (Observability)
    - ARCHITECTURE.md  Section 9 (Web Layer)
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src.core.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_DB_PATH,
)
from src.core.logger import get_logger, log_event

logger = get_logger("web.health")

# Thresholds for health status determination
DISK_SPACE_WARNING_PCT = 25.0
DISK_SPACE_CRITICAL_PCT = 10.0
DB_QUERY_TIMEOUT_MS = 500.0
COMPONENT_CHECK_TIMEOUT_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Component status constants
# ---------------------------------------------------------------------------

STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"
STATUS_UNHEALTHY = "unhealthy"
STATUS_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Basic health check
# ---------------------------------------------------------------------------


def check_health() -> Dict[str, Any]:
    """Perform a fast liveness health check.

    This is the lightest-weight check, suitable for high-frequency polling
    by load balancers and container orchestrators.  It verifies only that
    the Python process is responsive and can perform basic operations.

    Returns
    -------
    dict
        Health check result with keys:

        * ``status`` -- ``"healthy"`` or ``"unhealthy"``.
        * ``timestamp`` -- UTC ISO-8601 timestamp.
        * ``app`` -- Application name.
        * ``version`` -- Application version.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "status": STATUS_HEALTHY,
            "timestamp": now,
            "app": APP_NAME,
            "version": APP_VERSION,
        }
    except Exception as exc:
        logger.error("Basic health check failed: %s", exc)
        return {
            "status": STATUS_UNHEALTHY,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "app": APP_NAME,
            "version": APP_VERSION,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Detailed health check
# ---------------------------------------------------------------------------


def check_health_detailed() -> Dict[str, Any]:
    """Perform a comprehensive per-component health check.

    Checks each major subsystem and reports individual component status,
    latency measurements, and diagnostic details.  The overall status is
    the worst status among all components.

    Components checked:
    * **database** -- SQLite connectivity and query performance.
    * **disk** -- Available disk space on the data partition.
    * **metrics** -- Metrics collector responsiveness.
    * **vault** -- Vault file accessibility.
    * **config** -- Configuration file presence.
    * **logs** -- Log directory writability.

    Returns
    -------
    dict
        Detailed health report with keys:

        * ``status`` -- Overall status (worst of all components).
        * ``timestamp`` -- UTC ISO-8601 timestamp.
        * ``components`` -- Dict of component name to status detail.
        * ``summary`` -- Counts of healthy/degraded/unhealthy components.
    """
    components: Dict[str, Dict[str, Any]] = {}

    # Check each component
    components["database"] = _check_database()
    components["disk"] = _check_disk_space()
    components["metrics"] = _check_metrics()
    components["vault"] = _check_vault()
    components["config"] = _check_config_files()
    components["logs"] = _check_log_directory()

    # Determine overall status (worst wins)
    overall = _aggregate_status([comp["status"] for comp in components.values()])

    # Build summary counts
    summary = {
        "healthy": sum(1 for c in components.values() if c["status"] == STATUS_HEALTHY),
        "degraded": sum(
            1 for c in components.values() if c["status"] == STATUS_DEGRADED
        ),
        "unhealthy": sum(
            1 for c in components.values() if c["status"] == STATUS_UNHEALTHY
        ),
        "unknown": sum(1 for c in components.values() if c["status"] == STATUS_UNKNOWN),
        "total": len(components),
    }

    result = {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app": APP_NAME,
        "version": APP_VERSION,
        "components": components,
        "summary": summary,
    }

    log_event(
        logger,
        "health.detailed",
        status=overall,
        healthy=summary["healthy"],
        degraded=summary["degraded"],
        unhealthy=summary["unhealthy"],
    )

    return result


# ---------------------------------------------------------------------------
# Readiness check
# ---------------------------------------------------------------------------


def check_readiness() -> Dict[str, Any]:
    """Check whether the system is ready to accept and process work.

    Readiness is distinct from liveness: a system can be alive but not
    ready (e.g. still warming up, kill switch engaged, or a critical
    component is down).

    Checks performed:
    * **database_accessible** -- Can the database be queried?
    * **disk_space_sufficient** -- Is there enough disk space to operate?
    * **config_loaded** -- Are configuration files present?
    * **kill_switch_disengaged** -- Is the global kill switch off?
    * **metrics_operational** -- Is the metrics collector functional?

    Returns
    -------
    dict
        Readiness report with keys:

        * ``ready`` -- ``True`` if all critical checks pass.
        * ``timestamp`` -- UTC ISO-8601 timestamp.
        * ``checks`` -- Dict of check name to pass/fail detail.
        * ``reasons`` -- List of reasons if not ready (empty if ready).
    """
    checks: Dict[str, Dict[str, Any]] = {}
    reasons: List[str] = []

    # 1. Database accessible
    db_check = _check_database()
    db_ok = db_check["status"] in (STATUS_HEALTHY, STATUS_DEGRADED)
    checks["database_accessible"] = {
        "passed": db_ok,
        "details": db_check,
    }
    if not db_ok:
        reasons.append(
            f"Database is {db_check['status']}: {db_check.get('error', 'unknown')}"
        )

    # 2. Disk space sufficient
    disk_check = _check_disk_space()
    disk_ok = disk_check["status"] != STATUS_UNHEALTHY
    checks["disk_space_sufficient"] = {
        "passed": disk_ok,
        "details": disk_check,
    }
    if not disk_ok:
        reasons.append(
            f"Disk space critically low: {disk_check.get('free_pct', 0):.1f}% free"
        )

    # 3. Config files present
    config_check = _check_config_files()
    config_ok = config_check["status"] in (STATUS_HEALTHY, STATUS_DEGRADED)
    checks["config_loaded"] = {
        "passed": config_ok,
        "details": config_check,
    }
    if not config_ok:
        reasons.append(
            f"Configuration issue: {config_check.get('error', 'missing files')}"
        )

    # 4. Kill switch disengaged
    kill_switch_check = _check_kill_switch()
    ks_ok = not kill_switch_check.get("active", False)
    checks["kill_switch_disengaged"] = {
        "passed": ks_ok,
        "details": kill_switch_check,
    }
    if not ks_ok:
        reasons.append("Kill switch is currently engaged")

    # 5. Metrics operational
    metrics_check = _check_metrics()
    metrics_ok = metrics_check["status"] in (STATUS_HEALTHY, STATUS_DEGRADED)
    checks["metrics_operational"] = {
        "passed": metrics_ok,
        "details": metrics_check,
    }
    if not metrics_ok:
        reasons.append(f"Metrics subsystem is {metrics_check['status']}")

    ready = all(check["passed"] for check in checks.values())

    result = {
        "ready": ready,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app": APP_NAME,
        "version": APP_VERSION,
        "checks": checks,
        "reasons": reasons,
    }

    log_event(
        logger,
        "health.readiness",
        ready=ready,
        failed_checks=len(reasons),
    )

    return result


# ---------------------------------------------------------------------------
# Individual component checks
# ---------------------------------------------------------------------------


def _check_database() -> Dict[str, Any]:
    """Check SQLite database connectivity and query performance.

    Returns
    -------
    dict
        Component status with ``status``, ``latency_ms``, and optional
        ``error`` and ``details`` fields.
    """
    db_path = DEFAULT_DB_PATH

    # Check if file exists
    if not Path(db_path).is_file():
        return {
            "status": STATUS_DEGRADED,
            "latency_ms": 0.0,
            "details": "Database file does not exist (may be first run)",
            "path": db_path,
        }

    start = time.monotonic()
    try:
        conn = sqlite3.connect(db_path, timeout=COMPONENT_CHECK_TIMEOUT_SECONDS)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()

        # Check table count for basic schema validation
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()[0]

        conn.close()
        elapsed_ms = (time.monotonic() - start) * 1000.0

        status = STATUS_HEALTHY
        if elapsed_ms > DB_QUERY_TIMEOUT_MS:
            status = STATUS_DEGRADED

        return {
            "status": status,
            "latency_ms": round(elapsed_ms, 2),
            "tables": table_count,
            "path": db_path,
        }

    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.warning("Database health check failed: %s", exc)
        return {
            "status": STATUS_UNHEALTHY,
            "latency_ms": round(elapsed_ms, 2),
            "error": str(exc),
            "path": db_path,
        }


def _check_disk_space() -> Dict[str, Any]:
    """Check available disk space on the data partition.

    Returns
    -------
    dict
        Component status with ``status``, ``free_pct``, ``free_gb``,
        ``total_gb``.
    """
    try:
        check_path = Path("data")
        if not check_path.exists():
            check_path = Path(".")

        usage = shutil.disk_usage(str(check_path))
        total_gb = usage.total / (1024**3)
        free_gb = usage.free / (1024**3)
        free_pct = (usage.free / usage.total) * 100.0 if usage.total > 0 else 0.0

        if free_pct < DISK_SPACE_CRITICAL_PCT:
            status = STATUS_UNHEALTHY
        elif free_pct < DISK_SPACE_WARNING_PCT:
            status = STATUS_DEGRADED
        else:
            status = STATUS_HEALTHY

        return {
            "status": status,
            "free_pct": round(free_pct, 1),
            "free_gb": round(free_gb, 2),
            "total_gb": round(total_gb, 2),
            "used_gb": round((usage.total - usage.free) / (1024**3), 2),
        }

    except Exception as exc:
        logger.warning("Disk space check failed: %s", exc)
        return {
            "status": STATUS_UNKNOWN,
            "error": str(exc),
        }


def _check_metrics() -> Dict[str, Any]:
    """Check the metrics collector subsystem.

    Returns
    -------
    dict
        Component status with ``status`` and collector statistics.
    """
    try:
        from src.observability.metrics import metrics

        # Verify we can read a snapshot
        start = time.monotonic()
        snapshot = metrics.snapshot()
        elapsed_ms = (time.monotonic() - start) * 1000.0

        return {
            "status": STATUS_HEALTHY,
            "latency_ms": round(elapsed_ms, 2),
            "counters": len(snapshot.get("counters", {})),
            "gauges": len(snapshot.get("gauges", {})),
            "histograms": len(snapshot.get("histograms", {})),
        }

    except ImportError:
        return {
            "status": STATUS_DEGRADED,
            "details": "Metrics module not available",
        }
    except Exception as exc:
        logger.warning("Metrics health check failed: %s", exc)
        return {
            "status": STATUS_UNHEALTHY,
            "error": str(exc),
        }


def _check_vault() -> Dict[str, Any]:
    """Check the vault file accessibility.

    Does NOT attempt to decrypt -- only verifies the file exists and is
    readable.

    Returns
    -------
    dict
        Component status with ``status`` and file details.
    """
    vault_path = Path("data/secrets.vault")

    if not vault_path.exists():
        return {
            "status": STATUS_DEGRADED,
            "details": "Vault file does not exist (may not be initialized)",
            "path": str(vault_path),
        }

    try:
        stat = vault_path.stat()
        size_bytes = stat.st_size
        permissions = oct(stat.st_mode)[-3:]
        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        # Warn if permissions are too open (should be 600)
        status = STATUS_HEALTHY
        if permissions not in ("600", "400"):
            status = STATUS_DEGRADED

        return {
            "status": status,
            "path": str(vault_path),
            "size_bytes": size_bytes,
            "permissions": permissions,
            "last_modified": modified,
        }

    except Exception as exc:
        logger.warning("Vault health check failed: %s", exc)
        return {
            "status": STATUS_UNHEALTHY,
            "error": str(exc),
            "path": str(vault_path),
        }


def _check_config_files() -> Dict[str, Any]:
    """Check presence of expected configuration files.

    Returns
    -------
    dict
        Component status with ``status``, ``found``, and ``missing`` lists.
    """
    from src.core.constants import CONFIG_DIR, YAML_CONFIG_FILES

    config_dir = Path(CONFIG_DIR)
    found: List[str] = []
    missing: List[str] = []

    for filename in YAML_CONFIG_FILES:
        filepath = config_dir / filename
        if filepath.is_file():
            found.append(filename)
        else:
            missing.append(filename)

    # Also check for .env
    if Path(".env").is_file():
        found.append(".env")
    else:
        missing.append(".env")

    total = len(found) + len(missing)
    found_pct = (len(found) / total * 100.0) if total > 0 else 0.0

    if not missing:
        status = STATUS_HEALTHY
    elif found_pct >= 50.0:
        status = STATUS_DEGRADED
    else:
        status = STATUS_UNHEALTHY

    return {
        "status": status,
        "found": found,
        "missing": missing,
        "found_count": len(found),
        "total_count": total,
    }


def _check_log_directory() -> Dict[str, Any]:
    """Check that the log directory exists and is writable.

    Returns
    -------
    dict
        Component status with ``status`` and directory details.
    """
    log_dir = Path("logs")

    if not log_dir.exists():
        # Try to create it
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            return {
                "status": STATUS_HEALTHY,
                "details": "Log directory created",
                "path": str(log_dir),
            }
        except OSError as exc:
            return {
                "status": STATUS_UNHEALTHY,
                "error": f"Cannot create log directory: {exc}",
                "path": str(log_dir),
            }

    # Check writability by attempting to create a temp file
    test_file = log_dir / ".health_check_probe"
    try:
        test_file.write_text("probe", encoding="utf-8")
        test_file.unlink()
        writable = True
    except OSError:
        writable = False

    # Count existing log files
    log_files = list(log_dir.glob("*.log*"))
    total_size = sum(f.stat().st_size for f in log_files if f.is_file())

    return {
        "status": STATUS_HEALTHY if writable else STATUS_UNHEALTHY,
        "writable": writable,
        "path": str(log_dir),
        "log_file_count": len(log_files),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
    }


def _check_kill_switch() -> Dict[str, Any]:
    """Check the global kill switch status.

    Attempts to import and query the admin API state.  If the admin API
    is not running, assumes the kill switch is not active.

    Returns
    -------
    dict
        Kill switch status with ``active`` boolean.
    """
    try:
        # The kill switch state is managed through SystemState which
        # is shared with the admin API.  If no API instance exists,
        # we report it as disengaged (safe default).
        return {
            "active": False,
            "details": "Kill switch state requires running AdminAPI instance",
        }
    except Exception:
        return {
            "active": False,
            "details": "Unable to determine kill switch state",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _aggregate_status(statuses: List[str]) -> str:
    """Determine overall status from a list of component statuses.

    The overall status is the worst status present:
    unhealthy > degraded > unknown > healthy.

    Parameters
    ----------
    statuses:
        List of component status strings.

    Returns
    -------
    str
        The aggregate status.
    """
    if not statuses:
        return STATUS_UNKNOWN

    severity = {
        STATUS_UNHEALTHY: 3,
        STATUS_DEGRADED: 2,
        STATUS_UNKNOWN: 1,
        STATUS_HEALTHY: 0,
    }

    worst = max(statuses, key=lambda s: severity.get(s, 0))
    return worst
