"""
orchestrator.router
~~~~~~~~~~~~~~~~~~~~

Routes tasks to the appropriate agent and cluster node based on the task
type and the node's assigned role.

The OpenClaw cluster consists of two Mac Mini nodes:
    - **oc-core-01** (``NodeRole.CORE``): orchestrator, research, content generation, DB.
    - **oc-pub-01** (``NodeRole.PUBLISHER``): publishing, analytics, health monitor, backup.

The router inspects each incoming task descriptor, determines which agent
should handle it, checks whether the responsible agent lives on the local
node or a remote one, and either returns a local dispatch instruction or
forwards the task over the network.

Design references:
    - ARCHITECTURE.md   Section 3 (Orchestrator), Section 5 (Cluster)
    - config/cluster.yaml
    - config/agents.yaml
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.core.constants import AgentName, NodeRole
from src.core.errors import RoutingError
from src.core.logger import get_logger, log_event


# ---------------------------------------------------------------------------
# Agent-to-node mapping (derived from config/cluster.yaml)
# ---------------------------------------------------------------------------

_DEFAULT_AGENT_NODE_MAP: Dict[str, NodeRole] = {
    AgentName.MASTER_SCHEDULER.value: NodeRole.CORE,
    AgentName.RESEARCH.value: NodeRole.CORE,
    AgentName.CONTENT_GENERATION.value: NodeRole.CORE,
    AgentName.PUBLISHING.value: NodeRole.PUBLISHER,
    AgentName.ANALYTICS.value: NodeRole.PUBLISHER,
    AgentName.HEALTH_MONITOR.value: NodeRole.PUBLISHER,
    AgentName.ERROR_RECOVERY.value: NodeRole.CORE,
    AgentName.TRAFFIC_ROUTING.value: NodeRole.CORE,
}

# Mapping of NodeRole -> node hostname / IP for forwarding.
_DEFAULT_NODE_ADDRESSES: Dict[NodeRole, str] = {
    NodeRole.CORE: "192.168.1.10",
    NodeRole.PUBLISHER: "192.168.1.11",
}


# ---------------------------------------------------------------------------
# Route descriptor
# ---------------------------------------------------------------------------

@dataclass
class RouteDecision:
    """Describes where and how a task should be dispatched.

    Attributes
    ----------
    task_type:
        The original task type string (e.g. ``"research"``, ``"publish"``).
    agent_name:
        The canonical agent name that will handle the task.
    node_role:
        The cluster node role responsible for this agent.
    is_local:
        ``True`` if the agent lives on the current node.
    forward_address:
        IP or hostname of the remote node when ``is_local`` is ``False``.
    metadata:
        Extra context carried along with the routing decision.
    """

    task_type: str
    agent_name: str
    node_role: NodeRole
    is_local: bool = True
    forward_address: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class Router:
    """Route tasks to the correct agent and cluster node.

    Parameters
    ----------
    local_role:
        The :class:`NodeRole` of the node this router is running on.
        Defaults to ``CORE``.
    agent_node_map:
        Override the default agent-to-node mapping if needed (useful for
        testing or non-standard topologies).
    node_addresses:
        Override the default node address map.
    """

    def __init__(
        self,
        *,
        local_role: NodeRole = NodeRole.CORE,
        agent_node_map: Optional[Dict[str, NodeRole]] = None,
        node_addresses: Optional[Dict[NodeRole, str]] = None,
    ) -> None:
        self._logger: logging.Logger = get_logger("orchestrator.router")
        self._local_role: NodeRole = local_role
        self._agent_node_map: Dict[str, NodeRole] = (
            agent_node_map if agent_node_map is not None else dict(_DEFAULT_AGENT_NODE_MAP)
        )
        self._node_addresses: Dict[NodeRole, str] = (
            node_addresses if node_addresses is not None else dict(_DEFAULT_NODE_ADDRESSES)
        )

        log_event(
            self._logger,
            "router.init",
            local_role=str(local_role),
            agents=len(self._agent_node_map),
        )

    # ------------------------------------------------------------------
    # Task-type -> Agent resolution
    # ------------------------------------------------------------------

    # Mapping from generic task types to canonical agent names.  Extend
    # this as new task categories are introduced.
    _TASK_TYPE_TO_AGENT: Dict[str, str] = {
        "research": AgentName.RESEARCH.value,
        "discover_offers": AgentName.RESEARCH.value,
        "generate_content": AgentName.CONTENT_GENERATION.value,
        "content": AgentName.CONTENT_GENERATION.value,
        "publish": AgentName.PUBLISHING.value,
        "publishing": AgentName.PUBLISHING.value,
        "analytics": AgentName.ANALYTICS.value,
        "report": AgentName.ANALYTICS.value,
        "health_check": AgentName.HEALTH_MONITOR.value,
        "monitor": AgentName.HEALTH_MONITOR.value,
        "error_recovery": AgentName.ERROR_RECOVERY.value,
        "recover": AgentName.ERROR_RECOVERY.value,
        "traffic": AgentName.TRAFFIC_ROUTING.value,
        "traffic_routing": AgentName.TRAFFIC_ROUTING.value,
        "schedule": AgentName.MASTER_SCHEDULER.value,
    }

    def get_agent_for_task(self, task_type: str) -> str:
        """Resolve a task type to the canonical agent name.

        Parameters
        ----------
        task_type:
            A human-friendly task type string (e.g. ``"publish"``).

        Returns
        -------
        str
            The agent name that handles this task type.

        Raises
        ------
        RoutingError
            If no agent mapping exists for *task_type*.
        """
        agent = self._TASK_TYPE_TO_AGENT.get(task_type.lower())
        if agent is None:
            raise RoutingError(
                f"No agent mapping for task type '{task_type}'.",
                details={
                    "task_type": task_type,
                    "known_types": list(self._TASK_TYPE_TO_AGENT.keys()),
                },
            )
        return agent

    # ------------------------------------------------------------------
    # Locality check
    # ------------------------------------------------------------------

    def is_local_task(self, agent_name: str) -> bool:
        """Return ``True`` if *agent_name* runs on the local node.

        Parameters
        ----------
        agent_name:
            Canonical agent name.

        Returns
        -------
        bool
            ``True`` when the agent's node role matches ``self._local_role``.
        """
        target_role = self._agent_node_map.get(agent_name)
        if target_role is None:
            self._logger.warning(
                "Agent '%s' has no node-role mapping -- assuming local.", agent_name
            )
            return True
        return target_role == self._local_role

    # ------------------------------------------------------------------
    # Forwarding stub
    # ------------------------------------------------------------------

    def forward_to_node(
        self,
        node_role: NodeRole,
        task_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Forward a task to a remote cluster node for execution.

        In the current scaffold this method logs the forward intent and
        returns a receipt.  The actual network transport (SSH, HTTP, or
        message queue) will be implemented in a future iteration.

        Parameters
        ----------
        node_role:
            The role of the target node.
        task_payload:
            Serialisable dict describing the task.

        Returns
        -------
        dict[str, Any]
            A receipt dict containing the target address and acknowledgement
            status.

        Raises
        ------
        RoutingError
            If the target node address is unknown.
        """
        address = self._node_addresses.get(node_role)
        if address is None:
            raise RoutingError(
                f"No address configured for node role '{node_role}'.",
                details={"node_role": str(node_role)},
            )

        log_event(
            self._logger,
            "router.forward",
            target_role=str(node_role),
            target_address=address,
            task_type=task_payload.get("task_type", "unknown"),
        )

        # TODO(infra): Replace with real network call (SSH / HTTP / MQ).
        return {
            "forwarded": True,
            "target_role": str(node_role),
            "target_address": address,
            "task_payload": task_payload,
        }

    # ------------------------------------------------------------------
    # Top-level routing
    # ------------------------------------------------------------------

    def route_task(self, task_type: str, *, payload: Optional[Dict[str, Any]] = None) -> RouteDecision:
        """Determine routing for a task and optionally forward it.

        This is the primary entry-point called by the orchestrator controller
        on each task dispatch.  It:

        1. Resolves *task_type* to an agent name.
        2. Looks up the agent's node role.
        3. Decides whether the task is local or remote.
        4. If remote, calls :meth:`forward_to_node`.

        Parameters
        ----------
        task_type:
            The type of task to route (e.g. ``"publish"``).
        payload:
            Optional task data forwarded to the remote node if applicable.

        Returns
        -------
        RouteDecision
            Describes the routing decision including locality.

        Raises
        ------
        RoutingError
            If the task type cannot be mapped or the remote node is unreachable.
        """
        agent_name = self.get_agent_for_task(task_type)
        node_role = self._agent_node_map.get(agent_name, self._local_role)
        is_local = node_role == self._local_role

        decision = RouteDecision(
            task_type=task_type,
            agent_name=agent_name,
            node_role=node_role,
            is_local=is_local,
            forward_address=None if is_local else self._node_addresses.get(node_role),
            metadata=payload or {},
        )

        log_event(
            self._logger,
            "router.route_decision",
            task_type=task_type,
            agent=agent_name,
            node_role=str(node_role),
            is_local=is_local,
        )

        # Forward to remote node if not local.
        if not is_local:
            forward_payload = {
                "task_type": task_type,
                "agent_name": agent_name,
                **(payload or {}),
            }
            self.forward_to_node(node_role, forward_payload)

        return decision

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Router(local_role={self._local_role!s}, "
            f"agents={len(self._agent_node_map)})"
        )
