"""
agents.error_recovery_agent
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ErrorRecoveryAgent identifies failed operations across the system and
attempts automated recovery through retries, rollbacks, or quarantining.
It classifies errors by severity and recoverability, applies the appropriate
strategy, and logs outcomes for audit and trend analysis.

Design references:
    - ARCHITECTURE.md  Section 2 (Agent Architecture)
    - config/agents.yaml      (error_recovery settings)
    - config/thresholds.yaml  (retry limits, quarantine rules)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent
from src.core.constants import (
    AgentName,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_RETRY_EXPONENTIAL_BASE,
    DEFAULT_RETRY_MAX_DELAY,
)
from src.core.logger import log_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@unique
class ErrorSeverity(str, Enum):
    """How severe the error is."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@unique
class ErrorCategory(str, Enum):
    """High-level classification of the error cause."""

    TRANSIENT = "transient"  # Network timeout, rate limit, temporary outage
    DATA = "data"  # Invalid data, missing fields, parse errors
    CONFIGURATION = "config"  # Bad config, missing credentials
    INFRASTRUCTURE = "infra"  # Disk full, OOM, service down
    LOGIC = "logic"  # Application bug, unexpected state
    UNKNOWN = "unknown"


@unique
class RecoveryStrategy(str, Enum):
    """The strategy applied to recover from an error."""

    RETRY = "retry"
    ROLLBACK = "rollback"
    QUARANTINE = "quarantine"
    ESCALATE = "escalate"
    SKIP = "skip"


@dataclass
class FailedOperation:
    """A single failed operation discovered in the system.

    Attributes:
        operation_id:  Unique identifier (task_id, run_id, etc.).
        agent_name:    Agent that produced the failure.
        pipeline_name: Pipeline where the failure occurred (if applicable).
        error_message: The original error message or traceback excerpt.
        failed_at:     When the failure occurred.
        retry_count:   How many times this operation has already been retried.
        severity:      Classified severity of the error.
        category:      Classified error category.
        context:       Additional context for diagnosis (free-form dict).
    """

    operation_id: str
    agent_name: str = ""
    pipeline_name: str = ""
    error_message: str = ""
    failed_at: Optional[datetime] = None
    retry_count: int = 0
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    category: ErrorCategory = ErrorCategory.UNKNOWN
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryOutcome:
    """Outcome of attempting to recover a single failed operation.

    Attributes:
        operation_id:  ID of the operation that was recovered.
        strategy:      The recovery strategy that was applied.
        success:       Whether recovery was successful.
        attempts:      Number of retry attempts made.
        error:         Error message if recovery itself failed.
        recovered_at:  Timestamp of successful recovery (None if failed).
    """

    operation_id: str
    strategy: RecoveryStrategy = RecoveryStrategy.SKIP
    success: bool = False
    attempts: int = 0
    error: str = ""
    recovered_at: Optional[datetime] = None


@dataclass
class RecoveryPlan:
    """Output of the planning phase -- failed operations and their strategies.

    Attributes:
        operations:    Failed operations identified for recovery.
        strategies:    Mapping of operation_id to chosen strategy.
        plan_time:     When the plan was generated.
    """

    operations: List[FailedOperation] = field(default_factory=list)
    strategies: Dict[str, RecoveryStrategy] = field(default_factory=dict)
    plan_time: Optional[datetime] = None


@dataclass
class RecoveryExecutionResult:
    """Aggregated results from recovery attempts.

    Attributes:
        outcomes:   Per-operation recovery outcomes.
        recovered:  Count of successfully recovered operations.
        quarantined: Count of operations moved to quarantine.
        escalated:  Count of operations escalated for manual review.
        errors:     Errors encountered during recovery itself.
    """

    outcomes: Dict[str, RecoveryOutcome] = field(default_factory=dict)
    recovered: int = 0
    quarantined: int = 0
    escalated: int = 0
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------


class ErrorRecoveryAgent(BaseAgent):
    """Identifies failed operations and attempts automated recovery.

    The error recovery agent runs frequently and scans for failed tasks,
    pipeline errors, and agent run failures.  For each failure it classifies
    the error, selects a recovery strategy, and attempts recovery.  Operations
    that exceed the retry limit are quarantined for manual review.

    Configuration keys (from ``config/agents.yaml`` under ``error_recovery``):
        enabled:            bool  -- whether this agent is active.
        max_retries:        int   -- maximum retry attempts per operation.
        retry_base_delay:   float -- initial backoff delay in seconds.
        retry_max_delay:    float -- maximum backoff delay in seconds.
        quarantine_after:   int   -- move to quarantine after N failed retries.
        escalation_severity: str  -- minimum severity to auto-escalate.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(name=str(AgentName.ERROR_RECOVERY), config=config)
        self._max_retries: int = config.get("max_retries", DEFAULT_MAX_RETRIES)
        self._retry_base_delay: float = config.get(
            "retry_base_delay", DEFAULT_RETRY_BASE_DELAY
        )
        self._retry_max_delay: float = config.get(
            "retry_max_delay", DEFAULT_RETRY_MAX_DELAY
        )
        self._retry_exp_base: float = config.get(
            "retry_exponential_base", DEFAULT_RETRY_EXPONENTIAL_BASE
        )
        self._quarantine_after: int = config.get(
            "quarantine_after", DEFAULT_MAX_RETRIES
        )
        self._escalation_severity: ErrorSeverity = ErrorSeverity(
            config.get("escalation_severity", "critical")
        )
        self._quarantine_store: List[FailedOperation] = []

    # ------------------------------------------------------------------
    # BaseAgent lifecycle
    # ------------------------------------------------------------------

    def plan(self) -> RecoveryPlan:
        """Identify failed operations and assign recovery strategies.

        Scans the task store for operations in a failed state, classifies
        each error, and selects an appropriate recovery strategy.

        Returns:
            A :class:`RecoveryPlan` with operations and their strategies.
        """
        log_event(self.logger, "error_recovery.plan.start")

        # In production this queries the DB / task store for failed operations.
        # Placeholder: return empty list until integration is wired up.
        failed_ops: List[FailedOperation] = self._scan_for_failures()

        # Classify each error and assign a strategy
        strategies: Dict[str, RecoveryStrategy] = {}
        for op in failed_ops:
            op.category = self._classify_error(op)
            op.severity = self._assess_severity(op)
            strategies[op.operation_id] = self._select_strategy(op)

        plan = RecoveryPlan(
            operations=failed_ops,
            strategies=strategies,
            plan_time=datetime.now(timezone.utc),
        )

        log_event(
            self.logger,
            "error_recovery.plan.complete",
            operations=len(plan.operations),
            strategies={
                s.value: list(strategies.values()).count(s) for s in RecoveryStrategy
            },
        )
        return plan

    def execute(self, plan: RecoveryPlan) -> RecoveryExecutionResult:
        """Execute recovery strategies: retry, rollback, quarantine, or escalate.

        Parameters:
            plan: The :class:`RecoveryPlan` from planning.

        Returns:
            A :class:`RecoveryExecutionResult` with per-operation outcomes.
        """
        result = RecoveryExecutionResult()

        for op in plan.operations:
            strategy = plan.strategies.get(op.operation_id, RecoveryStrategy.SKIP)
            log_event(
                self.logger,
                "error_recovery.attempt.start",
                operation_id=op.operation_id,
                strategy=strategy.value,
                severity=op.severity.value,
            )

            try:
                outcome = self._execute_strategy(op, strategy)
                result.outcomes[op.operation_id] = outcome

                if outcome.success:
                    result.recovered += 1
                elif outcome.strategy == RecoveryStrategy.QUARANTINE:
                    result.quarantined += 1
                    self._quarantine_store.append(op)
                elif outcome.strategy == RecoveryStrategy.ESCALATE:
                    result.escalated += 1

            except Exception as exc:
                outcome = RecoveryOutcome(
                    operation_id=op.operation_id,
                    strategy=strategy,
                    success=False,
                    error=str(exc),
                )
                result.outcomes[op.operation_id] = outcome
                result.errors.append(f"Recovery failed for '{op.operation_id}': {exc}")
                self.logger.error(
                    "Recovery failed for operation '%s': %s",
                    op.operation_id,
                    exc,
                )

        return result

    def report(
        self, plan: RecoveryPlan, result: RecoveryExecutionResult
    ) -> Dict[str, Any]:
        """Log recovery outcomes and return a structured summary.

        Parameters:
            plan:   The recovery plan.
            result: The execution result.

        Returns:
            A summary dict for the orchestrator's audit log.
        """
        report_data: Dict[str, Any] = {
            "operations_identified": len(plan.operations),
            "recovered": result.recovered,
            "quarantined": result.quarantined,
            "escalated": result.escalated,
            "still_failing": (
                len(plan.operations)
                - result.recovered
                - result.quarantined
                - result.escalated
            ),
            "quarantine_size": len(self._quarantine_store),
            "per_operation": {
                oid: {
                    "strategy": oc.strategy.value,
                    "success": oc.success,
                    "attempts": oc.attempts,
                    "error": oc.error,
                }
                for oid, oc in result.outcomes.items()
            },
            "errors": result.errors,
        }

        self._log_metric("recovery.identified", len(plan.operations))
        self._log_metric("recovery.recovered", result.recovered)
        self._log_metric("recovery.quarantined", result.quarantined)
        self._log_metric("recovery.escalated", result.escalated)
        self._log_metric("recovery.errors", len(result.errors))

        log_event(
            self.logger,
            "error_recovery.report.complete",
            recovered=result.recovered,
            quarantined=result.quarantined,
            escalated=result.escalated,
        )
        return report_data

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _classify_error(self, op: FailedOperation) -> ErrorCategory:
        """Classify a failed operation into an error category.

        Inspects the error message and context to determine whether the
        failure is transient, data-related, infrastructure-related, etc.

        Parameters:
            op: The failed operation to classify.

        Returns:
            An :class:`ErrorCategory` classification.
        """
        msg = op.error_message.lower()

        # Transient: network issues, rate limits, timeouts
        transient_signals = [
            "timeout",
            "timed out",
            "rate limit",
            "429",
            "503",
            "connection refused",
            "connection reset",
            "retry",
        ]
        if any(signal in msg for signal in transient_signals):
            return ErrorCategory.TRANSIENT

        # Infrastructure: disk, memory, service availability
        infra_signals = [
            "disk full",
            "no space",
            "out of memory",
            "oom",
            "service unavailable",
            "connection pool",
        ]
        if any(signal in msg for signal in infra_signals):
            return ErrorCategory.INFRASTRUCTURE

        # Data: validation, parsing, missing fields
        data_signals = [
            "validation",
            "parse error",
            "missing field",
            "invalid",
            "json",
            "decode",
            "encoding",
        ]
        if any(signal in msg for signal in data_signals):
            return ErrorCategory.DATA

        # Configuration: credentials, config, environment
        config_signals = [
            "credential",
            "api key",
            "auth",
            "permission",
            "config",
            "not configured",
            "missing env",
        ]
        if any(signal in msg for signal in config_signals):
            return ErrorCategory.CONFIGURATION

        return ErrorCategory.UNKNOWN

    def _assess_severity(self, op: FailedOperation) -> ErrorSeverity:
        """Assess the severity of a failed operation.

        Parameters:
            op: The failed operation.

        Returns:
            An :class:`ErrorSeverity` assessment.
        """
        # Infrastructure errors are high severity
        if op.category == ErrorCategory.INFRASTRUCTURE:
            return ErrorSeverity.HIGH

        # Operations that have been retried many times are higher severity
        if op.retry_count >= self._max_retries:
            return ErrorSeverity.HIGH

        # Transient errors are generally low severity
        if op.category == ErrorCategory.TRANSIENT and op.retry_count < 2:
            return ErrorSeverity.LOW

        return ErrorSeverity.MEDIUM

    def _select_strategy(self, op: FailedOperation) -> RecoveryStrategy:
        """Select a recovery strategy based on error classification.

        Parameters:
            op: The classified failed operation.

        Returns:
            A :class:`RecoveryStrategy` to apply.
        """
        # Critical severity: escalate immediately
        if op.severity == ErrorSeverity.CRITICAL:
            return RecoveryStrategy.ESCALATE

        # Exceeded retry limit: quarantine
        if op.retry_count >= self._quarantine_after:
            return RecoveryStrategy.QUARANTINE

        # Transient errors: retry with backoff
        if op.category == ErrorCategory.TRANSIENT:
            return RecoveryStrategy.RETRY

        # Data errors with low retry count: retry once then quarantine
        if op.category == ErrorCategory.DATA:
            return (
                RecoveryStrategy.RETRY
                if op.retry_count == 0
                else RecoveryStrategy.QUARANTINE
            )

        # Configuration errors: escalate (need human intervention)
        if op.category == ErrorCategory.CONFIGURATION:
            return RecoveryStrategy.ESCALATE

        # Infrastructure errors: attempt retry then escalate
        if op.category == ErrorCategory.INFRASTRUCTURE:
            return (
                RecoveryStrategy.RETRY
                if op.retry_count < 2
                else RecoveryStrategy.ESCALATE
            )

        return RecoveryStrategy.RETRY

    def _execute_strategy(
        self, op: FailedOperation, strategy: RecoveryStrategy
    ) -> RecoveryOutcome:
        """Execute the chosen recovery strategy for a single operation.

        Parameters:
            op:       The failed operation.
            strategy: The recovery strategy to apply.

        Returns:
            A :class:`RecoveryOutcome` describing the result.
        """
        if strategy == RecoveryStrategy.RETRY:
            return self._attempt_retry(op)

        if strategy == RecoveryStrategy.ROLLBACK:
            return self._attempt_rollback(op)

        if strategy == RecoveryStrategy.QUARANTINE:
            self.logger.info(
                "Quarantining operation '%s' after %d retries.",
                op.operation_id,
                op.retry_count,
            )
            return RecoveryOutcome(
                operation_id=op.operation_id,
                strategy=RecoveryStrategy.QUARANTINE,
                success=False,
                error="Moved to quarantine for manual review.",
            )

        if strategy == RecoveryStrategy.ESCALATE:
            self.logger.warning(
                "Escalating operation '%s' (severity=%s, category=%s).",
                op.operation_id,
                op.severity.value,
                op.category.value,
            )
            return RecoveryOutcome(
                operation_id=op.operation_id,
                strategy=RecoveryStrategy.ESCALATE,
                success=False,
                error="Escalated for manual intervention.",
            )

        # SKIP
        return RecoveryOutcome(
            operation_id=op.operation_id,
            strategy=RecoveryStrategy.SKIP,
            success=False,
            error="Operation skipped -- no applicable strategy.",
        )

    def _attempt_retry(self, op: FailedOperation) -> RecoveryOutcome:
        """Retry a failed operation with exponential backoff.

        Computes the backoff delay based on the current retry count, waits,
        and then re-invokes the original operation.  In production this would
        call back into the orchestrator to re-queue the task.

        Parameters:
            op: The failed operation to retry.

        Returns:
            A :class:`RecoveryOutcome` indicating retry success or failure.
        """
        if self._check_dry_run(f"retry operation '{op.operation_id}'"):
            return RecoveryOutcome(
                operation_id=op.operation_id,
                strategy=RecoveryStrategy.RETRY,
                success=True,
                attempts=1,
                recovered_at=datetime.now(timezone.utc),
            )

        delay = min(
            self._retry_base_delay * (self._retry_exp_base**op.retry_count),
            self._retry_max_delay,
        )
        self.logger.info(
            "Retrying operation '%s' (attempt %d/%d, delay=%.1fs).",
            op.operation_id,
            op.retry_count + 1,
            self._max_retries,
            delay,
        )

        # In production: sleep then re-queue the operation via orchestrator.
        # Placeholder: record the attempt without actually sleeping or retrying.
        op.retry_count += 1

        return RecoveryOutcome(
            operation_id=op.operation_id,
            strategy=RecoveryStrategy.RETRY,
            success=False,
            attempts=op.retry_count,
            error="Retry queued (placeholder -- orchestrator integration pending).",
        )

    def _attempt_rollback(self, op: FailedOperation) -> RecoveryOutcome:
        """Attempt to roll back a failed operation to a safe state.

        Parameters:
            op: The failed operation to roll back.

        Returns:
            A :class:`RecoveryOutcome` indicating rollback success or failure.
        """
        if self._check_dry_run(f"rollback operation '{op.operation_id}'"):
            return RecoveryOutcome(
                operation_id=op.operation_id,
                strategy=RecoveryStrategy.ROLLBACK,
                success=True,
                recovered_at=datetime.now(timezone.utc),
            )

        self.logger.info("Rolling back operation '%s'.", op.operation_id)

        # Placeholder: real implementation reverses side effects
        return RecoveryOutcome(
            operation_id=op.operation_id,
            strategy=RecoveryStrategy.ROLLBACK,
            success=False,
            error="Rollback not yet implemented.",
        )

    def _scan_for_failures(self) -> List[FailedOperation]:
        """Scan the task store for recently failed operations.

        In production this queries the database for tasks with status
        FAILED that have not been quarantined or resolved.

        Returns:
            A list of :class:`FailedOperation` instances.
        """
        if self._check_dry_run("scan for failed operations"):
            return []

        self.logger.debug("Scanning for failed operations.")

        # Placeholder: real implementation queries the task/run store
        return []
