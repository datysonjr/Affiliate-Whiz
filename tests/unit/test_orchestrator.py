"""Unit tests for orchestrator modules."""

import pytest
from datetime import datetime, timezone

from src.orchestrator.state_machine import StateMachine, SystemState
from src.orchestrator.controller import OrchestratorController
from src.agents.base_agent import BaseAgent, AgentStatus
from src.core.errors import (
    InvalidStateTransitionError,
    KillSwitchActiveError,
    AgentNotRegisteredError,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class DummyAgent(BaseAgent):
    """Minimal agent for testing the orchestrator."""

    def plan(self):
        return {"task": "test"}

    def execute(self, plan):
        if self._check_dry_run("execute test action"):
            return {"result": "skipped", "dry_run": True}
        return {"result": "done"}

    def report(self, plan, result):
        return {"summary": "test complete"}


def make_agent(name="test_agent", enabled=True, dry_run=False):
    return DummyAgent(name=name, config={"enabled": enabled, "dry_run": dry_run})


# ---------------------------------------------------------------------------
# StateMachine tests
# ---------------------------------------------------------------------------

class TestStateMachine:
    def test_initial_state_is_idle(self):
        sm = StateMachine()
        assert sm.get_state() == SystemState.IDLE

    def test_transition_idle_to_running(self):
        sm = StateMachine()
        record = sm.transition(SystemState.RUNNING, reason="test")
        assert sm.get_state() == SystemState.RUNNING
        assert record.from_state == SystemState.IDLE
        assert record.to_state == SystemState.RUNNING

    def test_transition_running_to_paused(self):
        sm = StateMachine()
        sm.transition(SystemState.RUNNING)
        sm.transition(SystemState.PAUSED)
        assert sm.get_state() == SystemState.PAUSED

    def test_invalid_transition_raises(self):
        sm = StateMachine()
        # IDLE -> PAUSED is not allowed
        with pytest.raises(InvalidStateTransitionError):
            sm.transition(SystemState.PAUSED)

    def test_can_transition_check(self):
        sm = StateMachine()
        assert sm.can_transition(SystemState.RUNNING) is True
        assert sm.can_transition(SystemState.PAUSED) is False

    def test_history_tracking(self):
        sm = StateMachine()
        sm.transition(SystemState.RUNNING, reason="start")
        sm.transition(SystemState.PAUSED, reason="pause")
        history = sm.get_history()
        assert len(history) == 2
        assert history[0].to_state == SystemState.PAUSED  # most recent first

    def test_forced_reset(self):
        sm = StateMachine()
        sm.transition(SystemState.RUNNING)
        sm.reset(reason="emergency")
        assert sm.get_state() == SystemState.IDLE

    def test_shutdown_is_terminal(self):
        sm = StateMachine()
        sm.transition(SystemState.RUNNING)
        sm.transition(SystemState.SHUTDOWN)
        assert sm.get_state() == SystemState.SHUTDOWN
        # No transitions out of SHUTDOWN
        with pytest.raises(InvalidStateTransitionError):
            sm.transition(SystemState.IDLE)


# ---------------------------------------------------------------------------
# OrchestratorController tests
# ---------------------------------------------------------------------------

class TestController:
    def test_create_controller(self):
        ctrl = OrchestratorController(dry_run=True)
        assert ctrl.is_dry_run() is True

    def test_register_and_run_agent(self):
        ctrl = OrchestratorController(dry_run=True)
        agent = make_agent("research")
        ctrl.register_agent(agent)
        ctrl.start()
        result = ctrl.run_agent("research")
        assert result.status == AgentStatus.COMPLETED
        assert result.agent_name == "research"

    def test_run_unregistered_agent_raises(self):
        ctrl = OrchestratorController(dry_run=True)
        ctrl.start()
        with pytest.raises(AgentNotRegisteredError):
            ctrl.run_agent("nonexistent")

    def test_kill_switch_blocks_execution(self):
        ctrl = OrchestratorController(dry_run=True)
        agent = make_agent("research")
        ctrl.register_agent(agent)
        ctrl.start()
        ctrl.kill_switch_on(reason="test")
        with pytest.raises(KillSwitchActiveError):
            ctrl.run_agent("research")

    def test_kill_switch_off_allows_resume(self):
        ctrl = OrchestratorController(dry_run=True)
        agent = make_agent("research")
        ctrl.register_agent(agent)
        ctrl.start()
        ctrl.kill_switch_on(reason="test")
        ctrl.kill_switch_off(reason="resolved")
        ctrl.start()  # re-start after kill switch off
        result = ctrl.run_agent("research")
        assert result.status == AgentStatus.COMPLETED

    def test_disabled_agent_is_skipped(self):
        ctrl = OrchestratorController(dry_run=True)
        agent = make_agent("research", enabled=False)
        ctrl.register_agent(agent)
        ctrl.start()
        result = ctrl.run_agent("research")
        # Should be skipped by controller or agent
        assert result.status in (AgentStatus.DISABLED, "skipped")

    def test_dry_run_propagates_to_agent(self):
        ctrl = OrchestratorController(dry_run=True)
        agent = make_agent("research")
        ctrl.register_agent(agent)
        ctrl.start()
        result = ctrl.run_agent("research")
        # In dry-run, execute should return dry_run=True
        assert result.exec_output.get("dry_run") is True

    def test_get_status(self):
        ctrl = OrchestratorController(dry_run=True)
        agent = make_agent("research")
        ctrl.register_agent(agent)
        status = ctrl.get_status()
        assert status["dry_run"] is True
        assert status["registered_agents"] == 1
        assert "research" in status["agents"]

    def test_multiple_agents_run_in_sequence(self):
        ctrl = OrchestratorController(dry_run=True)
        agents = [make_agent(f"agent_{i}") for i in range(3)]
        for a in agents:
            ctrl.register_agent(a)
        ctrl.start()
        results = [ctrl.run_agent(f"agent_{i}") for i in range(3)]
        assert all(r.status == AgentStatus.COMPLETED for r in results)

    def test_stop_and_repr(self):
        ctrl = OrchestratorController(dry_run=True)
        ctrl.start()
        ctrl.stop()
        r = repr(ctrl)
        assert "shutdown" in r.lower()


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------

class TestScheduler:
    def test_cron_matches(self):
        from src.orchestrator.scheduler import cron_matches
        # Every minute
        dt = datetime(2025, 6, 15, 10, 30, tzinfo=timezone.utc)
        assert cron_matches("* * * * *", dt) is True
        # Specific minute
        assert cron_matches("30 * * * *", dt) is True
        assert cron_matches("15 * * * *", dt) is False

    def test_cron_step(self):
        from src.orchestrator.scheduler import cron_matches
        dt = datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc)
        assert cron_matches("*/30 * * * *", dt) is True  # 0 % 30 == 0

    def test_schedule_and_cancel_task(self):
        from src.orchestrator.scheduler import Scheduler
        sched = Scheduler()
        task = sched.schedule_task("test_task", "*/5 * * * *")
        assert sched.task_count == 1
        assert task.cron_expr == "*/5 * * * *"

        removed = sched.cancel_task("custom:test_task")
        assert removed is True
        assert sched.task_count == 0
