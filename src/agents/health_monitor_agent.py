"""
agents.health_monitor_agent
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The HealthMonitorAgent monitors system health across the two-node Mac Mini
cluster.  It checks node uptime, disk usage, task queue depths, error rates,
and service availability.  When thresholds are breached it emits alerts and
records health snapshots for trend analysis.

Design references:
    - ARCHITECTURE.md  Section 2 (Agent Architecture)
    - config/agents.yaml   (health_monitor settings)
    - config/cluster.yaml  (node addresses, SSH credentials)
    - config/thresholds.yaml (health check thresholds)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent
from src.core.constants import AgentName, NodeRole
from src.core.logger import log_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@unique
class HealthStatus(str, Enum):
    """Overall health verdict for a single check."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class NodeHealth:
    """Health snapshot for a single cluster node.

    Attributes:
        node_id:          Unique node identifier (e.g. ``oc-core-01``).
        role:             Node role in the cluster.
        reachable:        Whether the node responded to a health ping.
        uptime_seconds:   Node uptime in seconds.
        cpu_percent:      Current CPU usage as a percentage.
        memory_percent:   Current memory usage as a percentage.
        load_average:     1-min load average.
        status:           Overall node health verdict.
        checked_at:       When the check was performed.
    """

    node_id: str
    role: NodeRole = NodeRole.CORE
    reachable: bool = False
    uptime_seconds: float = 0.0
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    load_average: float = 0.0
    status: HealthStatus = HealthStatus.UNKNOWN
    checked_at: Optional[datetime] = None


@dataclass
class DiskHealth:
    """Disk usage snapshot for a mount point.

    Attributes:
        node_id:      Node this disk belongs to.
        mount_point:  Filesystem mount point (e.g. ``/``).
        total_gb:     Total disk space in GB.
        used_gb:      Used disk space in GB.
        free_gb:      Free disk space in GB.
        usage_percent: Percentage of disk used.
        status:       Health verdict for this disk.
    """

    node_id: str
    mount_point: str = "/"
    total_gb: float = 0.0
    used_gb: float = 0.0
    free_gb: float = 0.0
    usage_percent: float = 0.0
    status: HealthStatus = HealthStatus.UNKNOWN


@dataclass
class QueueHealth:
    """Health snapshot for a task or message queue.

    Attributes:
        queue_name:    Name of the queue.
        depth:         Number of items currently in the queue.
        oldest_age_s:  Age of the oldest item in seconds.
        consumers:     Number of active consumers.
        status:        Health verdict for this queue.
    """

    queue_name: str
    depth: int = 0
    oldest_age_s: float = 0.0
    consumers: int = 0
    status: HealthStatus = HealthStatus.UNKNOWN


@dataclass
class HealthPlan:
    """Output of the planning phase -- which checks to run this cycle.

    Attributes:
        nodes:         Node IDs to check.
        check_disk:    Whether to run disk checks.
        check_queues:  Whether to inspect task queues.
        check_errors:  Whether to scan error logs.
        plan_time:     When the plan was generated.
    """

    nodes: List[str] = field(default_factory=list)
    check_disk: bool = True
    check_queues: bool = True
    check_errors: bool = True
    plan_time: Optional[datetime] = None


@dataclass
class HealthExecutionResult:
    """Aggregated results from all health checks.

    Attributes:
        node_health:   Per-node health snapshots.
        disk_health:   Per-mount disk usage snapshots.
        queue_health:  Per-queue depth snapshots.
        error_counts:  Error counts by category.
        alerts:        Alert messages generated during checks.
        overall_status: Worst-case status across all checks.
        errors:        Errors encountered while running the checks themselves.
    """

    node_health: Dict[str, NodeHealth] = field(default_factory=dict)
    disk_health: List[DiskHealth] = field(default_factory=list)
    queue_health: List[QueueHealth] = field(default_factory=list)
    error_counts: Dict[str, int] = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)
    overall_status: HealthStatus = HealthStatus.UNKNOWN
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------


class HealthMonitorAgent(BaseAgent):
    """Monitors system health across the cluster and sends alerts on degradation.

    The health monitor runs at a high frequency (every few minutes) and
    performs lightweight checks: node reachability, disk usage, queue depth,
    and error rate scanning.  When any metric crosses a configured threshold
    the agent emits an alert that the error recovery agent or an operator
    can act upon.

    Configuration keys (from ``config/agents.yaml`` under ``health_monitor``):
        enabled:              bool  -- whether this agent is active.
        nodes:                list  -- node identifiers to monitor.
        disk_warning_pct:     float -- disk usage % to trigger a warning.
        disk_critical_pct:    float -- disk usage % to trigger a critical alert.
        queue_depth_warning:  int   -- queue depth to trigger a warning.
        queue_depth_critical: int   -- queue depth to trigger a critical alert.
        error_rate_threshold: int   -- errors/hour to trigger an alert.
        alert_webhook_url:    str   -- webhook URL for alert delivery.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(name=str(AgentName.HEALTH_MONITOR), config=config)
        self._nodes: List[str] = config.get("nodes", ["oc-core-01", "oc-pub-01"])
        self._disk_warning_pct: float = config.get("disk_warning_pct", 80.0)
        self._disk_critical_pct: float = config.get("disk_critical_pct", 95.0)
        self._queue_depth_warning: int = config.get("queue_depth_warning", 100)
        self._queue_depth_critical: int = config.get("queue_depth_critical", 500)
        self._error_rate_threshold: int = config.get("error_rate_threshold", 50)
        self._alert_webhook_url: str = config.get("alert_webhook_url", "")
        self._queue_names: List[str] = config.get(
            "queue_names",
            [
                "content_pipeline",
                "publish_queue",
                "analytics_queue",
            ],
        )

    # ------------------------------------------------------------------
    # BaseAgent lifecycle
    # ------------------------------------------------------------------

    def plan(self) -> HealthPlan:
        """Define the set of health checks to execute this cycle.

        Returns:
            A :class:`HealthPlan` listing nodes and check types to run.
        """
        log_event(
            self.logger,
            "health_monitor.plan.start",
            nodes=len(self._nodes),
        )

        plan = HealthPlan(
            nodes=list(self._nodes),
            check_disk=True,
            check_queues=bool(self._queue_names),
            check_errors=True,
            plan_time=datetime.now(timezone.utc),
        )

        log_event(
            self.logger,
            "health_monitor.plan.complete",
            node_count=len(plan.nodes),
            check_disk=plan.check_disk,
            check_queues=plan.check_queues,
        )
        return plan

    def execute(self, plan: HealthPlan) -> HealthExecutionResult:
        """Run all scheduled health checks.

        Executes in order: node checks, disk checks, queue checks, error
        log scanning.  Alerts are accumulated and the overall status is
        set to the worst-case finding.

        Parameters:
            plan: The :class:`HealthPlan` from planning.

        Returns:
            A :class:`HealthExecutionResult` with all findings.
        """
        result = HealthExecutionResult()
        statuses: List[HealthStatus] = []

        # --- Node checks ---
        for node_id in plan.nodes:
            try:
                node_health = self._check_node(node_id)
                result.node_health[node_id] = node_health
                statuses.append(node_health.status)

                if node_health.status != HealthStatus.HEALTHY:
                    alert_msg = (
                        f"Node '{node_id}' status is {node_health.status.value} "
                        f"(cpu={node_health.cpu_percent:.1f}%, "
                        f"mem={node_health.memory_percent:.1f}%)"
                    )
                    result.alerts.append(alert_msg)
                    self.logger.warning(alert_msg)

            except Exception as exc:
                result.errors.append(f"Node check for '{node_id}': {exc}")
                self.logger.error("Node check failed for '%s': %s", node_id, exc)

        # --- Disk checks ---
        if plan.check_disk:
            for node_id in plan.nodes:
                try:
                    disk_snapshots = self._check_disk(node_id)
                    result.disk_health.extend(disk_snapshots)

                    for disk in disk_snapshots:
                        statuses.append(disk.status)
                        if disk.status != HealthStatus.HEALTHY:
                            alert_msg = (
                                f"Disk '{disk.mount_point}' on '{node_id}' "
                                f"at {disk.usage_percent:.1f}% ({disk.status.value})"
                            )
                            result.alerts.append(alert_msg)
                            self.logger.warning(alert_msg)

                except Exception as exc:
                    result.errors.append(f"Disk check for '{node_id}': {exc}")
                    self.logger.error("Disk check failed for '%s': %s", node_id, exc)

        # --- Queue checks ---
        if plan.check_queues:
            for queue_name in self._queue_names:
                try:
                    queue_health = self._check_queues(queue_name)
                    result.queue_health.append(queue_health)
                    statuses.append(queue_health.status)

                    if queue_health.status != HealthStatus.HEALTHY:
                        alert_msg = (
                            f"Queue '{queue_name}' depth={queue_health.depth} "
                            f"({queue_health.status.value})"
                        )
                        result.alerts.append(alert_msg)
                        self.logger.warning(alert_msg)

                except Exception as exc:
                    result.errors.append(f"Queue check for '{queue_name}': {exc}")
                    self.logger.error(
                        "Queue check failed for '%s': %s", queue_name, exc
                    )

        # --- Error log scanning ---
        if plan.check_errors:
            result.error_counts = self._scan_error_logs()
            total_errors = sum(result.error_counts.values())
            if total_errors > self._error_rate_threshold:
                alert_msg = (
                    f"Error rate {total_errors}/period exceeds "
                    f"threshold {self._error_rate_threshold}"
                )
                result.alerts.append(alert_msg)
                statuses.append(HealthStatus.DEGRADED)
                self.logger.warning(alert_msg)

        # --- Determine overall status ---
        if HealthStatus.CRITICAL in statuses:
            result.overall_status = HealthStatus.CRITICAL
        elif HealthStatus.DEGRADED in statuses:
            result.overall_status = HealthStatus.DEGRADED
        elif statuses:
            result.overall_status = HealthStatus.HEALTHY
        else:
            result.overall_status = HealthStatus.UNKNOWN

        return result

    def report(self, plan: HealthPlan, result: HealthExecutionResult) -> Dict[str, Any]:
        """Send alerts and return a structured health summary.

        If alerts have been generated and a webhook URL is configured,
        the report phase dispatches them.

        Parameters:
            plan:   The health plan.
            result: The execution result.

        Returns:
            A summary dict for the orchestrator's audit log.
        """
        report_data: Dict[str, Any] = {
            "overall_status": result.overall_status.value,
            "nodes_checked": len(result.node_health),
            "disks_checked": len(result.disk_health),
            "queues_checked": len(result.queue_health),
            "alerts_generated": len(result.alerts),
            "alerts": result.alerts,
            "error_counts": result.error_counts,
            "per_node": {
                nid: {
                    "status": nh.status.value,
                    "reachable": nh.reachable,
                    "cpu_percent": nh.cpu_percent,
                    "memory_percent": nh.memory_percent,
                }
                for nid, nh in result.node_health.items()
            },
            "errors": result.errors,
        }

        self._log_metric("health.overall_status", result.overall_status.value)
        self._log_metric("health.alerts", len(result.alerts))
        self._log_metric(
            "health.nodes_healthy",
            sum(
                1
                for nh in result.node_health.values()
                if nh.status == HealthStatus.HEALTHY
            ),
        )

        # Dispatch alerts if webhook is configured
        if result.alerts and self._alert_webhook_url:
            self._send_alerts(result.alerts)

        log_event(
            self.logger,
            "health_monitor.report.complete",
            overall=result.overall_status.value,
            alerts=len(result.alerts),
        )
        return report_data

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_node(self, node_id: str) -> NodeHealth:
        """Check the health of a single cluster node.

        In production this SSHs to the node (or calls its local health
        endpoint) and collects CPU, memory, uptime, and load metrics.

        Parameters:
            node_id: The node identifier to check.

        Returns:
            A :class:`NodeHealth` snapshot.
        """
        if self._check_dry_run(f"node health check for '{node_id}'"):
            return NodeHealth(
                node_id=node_id,
                reachable=True,
                status=HealthStatus.HEALTHY,
                checked_at=datetime.now(timezone.utc),
            )

        self.logger.debug("Checking node health for '%s'.", node_id)

        # Determine node role from config or naming convention
        role = NodeRole.PUBLISHER if "pub" in node_id else NodeRole.CORE

        # Placeholder: real implementation performs actual system checks
        return NodeHealth(
            node_id=node_id,
            role=role,
            reachable=True,
            uptime_seconds=0.0,
            cpu_percent=0.0,
            memory_percent=0.0,
            load_average=0.0,
            status=HealthStatus.HEALTHY,
            checked_at=datetime.now(timezone.utc),
        )

    def _check_disk(self, node_id: str) -> List[DiskHealth]:
        """Check disk usage on a cluster node.

        Examines key mount points and classifies usage against warning
        and critical thresholds.

        Parameters:
            node_id: The node identifier.

        Returns:
            A list of :class:`DiskHealth` snapshots (one per mount point).
        """
        if self._check_dry_run(f"disk check for node '{node_id}'"):
            return [DiskHealth(node_id=node_id, status=HealthStatus.HEALTHY)]

        self.logger.debug("Checking disk usage for node '%s'.", node_id)

        mount_points = self.config.get("disk_mount_points", ["/", "/data"])
        snapshots: List[DiskHealth] = []

        for mount in mount_points:
            # Placeholder: real implementation calls shutil.disk_usage or SSH
            usage_pct = 0.0  # would be populated from actual check

            if usage_pct >= self._disk_critical_pct:
                status = HealthStatus.CRITICAL
            elif usage_pct >= self._disk_warning_pct:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.HEALTHY

            snapshots.append(
                DiskHealth(
                    node_id=node_id,
                    mount_point=mount,
                    usage_percent=usage_pct,
                    status=status,
                )
            )

        return snapshots

    def _check_queues(self, queue_name: str) -> QueueHealth:
        """Check the depth and health of a task queue.

        Parameters:
            queue_name: The name of the queue to inspect.

        Returns:
            A :class:`QueueHealth` snapshot.
        """
        if self._check_dry_run(f"queue check for '{queue_name}'"):
            return QueueHealth(queue_name=queue_name, status=HealthStatus.HEALTHY)

        self.logger.debug("Checking queue health for '%s'.", queue_name)

        # Placeholder: real implementation inspects the actual queue backend
        depth = 0  # would be populated from queue inspection

        if depth >= self._queue_depth_critical:
            status = HealthStatus.CRITICAL
        elif depth >= self._queue_depth_warning:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.HEALTHY

        return QueueHealth(
            queue_name=queue_name,
            depth=depth,
            oldest_age_s=0.0,
            consumers=0,
            status=status,
        )

    def _scan_error_logs(self) -> Dict[str, int]:
        """Scan recent error logs and categorise error counts.

        Returns:
            A dict mapping error category names to occurrence counts.
        """
        if self._check_dry_run("error log scanning"):
            return {}

        self.logger.debug("Scanning error logs for recent errors.")

        # Placeholder: real implementation parses structured log files or
        # queries the logging backend (e.g. Elasticsearch / Loki)
        return {
            "agent_failures": 0,
            "pipeline_errors": 0,
            "http_errors": 0,
            "db_errors": 0,
        }

    def _send_alerts(self, alerts: List[str]) -> None:
        """Dispatch alert messages to the configured webhook.

        Parameters:
            alerts: List of alert message strings.
        """
        if self._check_dry_run(f"send {len(alerts)} alert(s) to webhook"):
            return

        self.logger.info(
            "Sending %d alert(s) to webhook %s.",
            len(alerts),
            self._alert_webhook_url,
        )

        # Placeholder: real implementation calls requests.post(...)
        for alert in alerts:
            self.logger.debug("Alert dispatched: %s", alert)
