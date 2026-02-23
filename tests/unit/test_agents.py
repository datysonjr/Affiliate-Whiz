"""Unit tests for agent modules."""

from src.agents.base_agent import BaseAgent, AgentStatus


# ---------------------------------------------------------------------------
# Test agent implementations
# ---------------------------------------------------------------------------

class SuccessAgent(BaseAgent):
    """Agent that always succeeds."""

    def plan(self):
        return {"items": [1, 2, 3]}

    def execute(self, plan):
        return {"processed": len(plan["items"])}

    def report(self, plan, result):
        self._log_metric("items.processed", result["processed"])
        return {"summary": f"Processed {result['processed']} items"}


class FailingAgent(BaseAgent):
    """Agent that raises during execute."""

    def plan(self):
        return {"ok": True}

    def execute(self, plan):
        raise ValueError("Simulated failure in execute()")

    def report(self, plan, result):
        return {"summary": "unreachable"}


class DryRunAgent(BaseAgent):
    """Agent that respects dry-run mode."""

    def plan(self):
        return {"action": "publish"}

    def execute(self, plan):
        if self._check_dry_run("publish to CMS"):
            return {"skipped": True, "dry_run": True}
        return {"published": True}

    def report(self, plan, result):
        return {"dry_run": result.get("dry_run", False)}


# ---------------------------------------------------------------------------
# BaseAgent lifecycle tests
# ---------------------------------------------------------------------------

class TestBaseAgent:
    def test_successful_run(self):
        agent = SuccessAgent(name="success", config={"enabled": True})
        result = agent.run()
        assert result.status == AgentStatus.COMPLETED
        assert result.plan_output == {"items": [1, 2, 3]}
        assert result.exec_output == {"processed": 3}
        assert result.report_output["summary"] == "Processed 3 items"
        assert result.error is None
        assert result.duration_s >= 0

    def test_failed_run_captures_error(self):
        agent = FailingAgent(name="failer", config={"enabled": True})
        result = agent.run()
        assert result.status == AgentStatus.FAILED
        assert "Simulated failure" in result.error
        assert result.plan_output == {"ok": True}

    def test_disabled_agent_returns_disabled(self):
        agent = SuccessAgent(name="disabled", config={"enabled": False})
        result = agent.run()
        assert result.status == AgentStatus.DISABLED
        assert result.plan_output is None

    def test_dry_run_mode(self):
        agent = DryRunAgent(name="dry", config={"enabled": True, "dry_run": True})
        result = agent.run()
        assert result.status == AgentStatus.COMPLETED
        assert result.exec_output["dry_run"] is True

    def test_run_history(self):
        agent = SuccessAgent(name="history", config={"enabled": True})
        agent.run()
        agent.run()
        assert len(agent.run_history) == 2
        assert agent.last_run is not None
        assert agent.last_run.status == AgentStatus.COMPLETED

    def test_get_status(self):
        agent = SuccessAgent(name="status", config={"enabled": True})
        assert agent.get_status() == AgentStatus.IDLE
        agent.run()
        assert agent.get_status() == AgentStatus.COMPLETED

    def test_is_enabled(self):
        agent_on = SuccessAgent(name="on", config={"enabled": True})
        agent_off = SuccessAgent(name="off", config={"enabled": False})
        assert agent_on.is_enabled() is True
        assert agent_off.is_enabled() is False

    def test_risk_level(self):
        agent = SuccessAgent(name="risky", config={"risk_level": "high"})
        assert agent.risk_level == "high"

    def test_default_risk_level(self):
        agent = SuccessAgent(name="safe", config={})
        assert agent.risk_level == "low"

    def test_run_id_is_unique(self):
        agent = SuccessAgent(name="unique", config={"enabled": True})
        r1 = agent.run()
        r2 = agent.run()
        assert r1.run_id != r2.run_id


# ---------------------------------------------------------------------------
# Queue tests
# ---------------------------------------------------------------------------

class TestTaskQueue:
    def test_enqueue_dequeue(self):
        from src.core.queue import InProcessQueue, QueuedTask
        q = InProcessQueue()
        task = QueuedTask(task_id="t1", agent_name="research", priority=1)
        q.enqueue(task)
        assert q.size() == 1
        result = q.dequeue(timeout=0.1)
        assert result is not None
        assert result.task_id == "t1"
        assert q.size() == 0

    def test_priority_ordering(self):
        from src.core.queue import InProcessQueue, QueuedTask
        q = InProcessQueue()
        q.enqueue(QueuedTask(task_id="low", agent_name="a", priority=10))
        q.enqueue(QueuedTask(task_id="high", agent_name="a", priority=1))
        q.enqueue(QueuedTask(task_id="med", agent_name="a", priority=5))
        # Should dequeue in priority order
        assert q.dequeue(timeout=0.1).task_id == "high"
        assert q.dequeue(timeout=0.1).task_id == "med"
        assert q.dequeue(timeout=0.1).task_id == "low"

    def test_dequeue_timeout(self):
        from src.core.queue import InProcessQueue
        q = InProcessQueue()
        result = q.dequeue(timeout=0.01)
        assert result is None

    def test_clear(self):
        from src.core.queue import InProcessQueue, QueuedTask
        q = InProcessQueue()
        for i in range(5):
            q.enqueue(QueuedTask(task_id=f"t{i}", agent_name="a"))
        assert q.size() == 5
        removed = q.clear()
        assert removed == 5
        assert q.size() == 0


# ---------------------------------------------------------------------------
# Database tests
# ---------------------------------------------------------------------------

class TestDatabase:
    def test_connect_and_migrate(self, tmp_path):
        from src.data.db import Database
        db = Database(db_path=str(tmp_path / "test.db"))
        db.connect()
        applied = db.migrate()
        assert applied >= 1
        version = db.get_schema_version()
        assert version >= 1
        db.disconnect()

    def test_insert_and_query(self, tmp_path):
        from src.data.db import Database
        db = Database(db_path=str(tmp_path / "test.db"))
        db.connect()
        db.migrate()
        db.execute(
            "INSERT INTO agent_runs (run_id, agent_name, status) VALUES (?, ?, ?)",
            ("test-run-1", "research", "success"),
        )
        row = db.fetch_one("SELECT * FROM agent_runs WHERE run_id = ?", ("test-run-1",))
        assert row is not None
        assert row["agent_name"] == "research"
        assert row["status"] == "success"
        db.disconnect()

    def test_transaction_rollback(self, tmp_path):
        from src.data.db import Database
        db = Database(db_path=str(tmp_path / "test.db"))
        db.connect()
        db.migrate()
        try:
            with db.transaction() as conn:
                conn.execute(
                    "INSERT INTO agent_runs (run_id, agent_name, status) VALUES (?, ?, ?)",
                    ("tx-1", "test", "success"),
                )
                raise ValueError("force rollback")
        except ValueError:
            pass
        row = db.fetch_one("SELECT * FROM agent_runs WHERE run_id = ?", ("tx-1",))
        assert row is None  # rolled back
        db.disconnect()
