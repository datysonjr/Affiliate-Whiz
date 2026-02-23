"""
web.admin_api
~~~~~~~~~~~~~

Simple HTTP API for administrative control of the OpenClaw system.

Built on Python's ``http.server`` module (no external dependencies), this
API provides endpoints for monitoring system status, managing agents,
engaging/disengaging the kill switch, updating configuration, and querying
metrics.

Endpoints
---------
::

    GET  /status       -- System status summary
    GET  /agents       -- List registered agents and their states
    POST /kill-switch  -- Engage or disengage the global kill switch
    GET  /config       -- View current configuration (secrets masked)
    POST /config       -- Reload configuration from disk
    GET  /metrics      -- Current metrics snapshot

Usage::

    from src.web.admin_api import AdminAPI

    api = AdminAPI(host="127.0.0.1", port=8080)
    api.start()   # runs in a background thread
    # ...
    api.stop()

Design references:
    - ARCHITECTURE.md  Section 9 (Web Layer)
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from src.core.constants import APP_NAME, APP_VERSION
from src.core.logger import get_logger, log_event

logger = get_logger("web.admin_api")

# Default bind address
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


class SystemState:
    """Shared mutable state for the admin API.

    Provides a thread-safe container that the API handlers read from and
    external components (orchestrator, scheduler) write to.  This avoids
    tight coupling between the HTTP layer and the core system.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._kill_switch: bool = False
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._config: Dict[str, Any] = {}
        self._metrics_provider: Optional[Callable[[], Dict[str, Any]]] = None
        self._start_time: float = time.monotonic()
        self._start_wall: str = datetime.now(timezone.utc).isoformat()

    # Kill switch
    @property
    def kill_switch_active(self) -> bool:
        with self._lock:
            return self._kill_switch

    def set_kill_switch(self, active: bool) -> None:
        with self._lock:
            self._kill_switch = active

    # Agents
    def register_agent(self, name: str, info: Dict[str, Any]) -> None:
        with self._lock:
            self._agents[name] = {
                **info,
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }

    def update_agent(self, name: str, updates: Dict[str, Any]) -> None:
        with self._lock:
            if name in self._agents:
                self._agents[name].update(updates)

    def get_agents(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._agents)

    # Config
    def set_config(self, config: Dict[str, Any]) -> None:
        with self._lock:
            self._config = config

    def get_config(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._config)

    # Metrics
    def set_metrics_provider(self, provider: Callable[[], Dict[str, Any]]) -> None:
        self._metrics_provider = provider

    def get_metrics(self) -> Dict[str, Any]:
        if self._metrics_provider is not None:
            try:
                return self._metrics_provider()
            except Exception as exc:
                logger.warning("Metrics provider failed: %s", exc)
        return {}

    # Uptime
    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def started_at(self) -> str:
        return self._start_wall


class AdminRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for admin API endpoints.

    Routes requests to the appropriate handler method based on the URL path.
    All responses are JSON-encoded.
    """

    # Reference to the shared SystemState (set by AdminAPI)
    state: SystemState

    def log_message(self, format: str, *args: Any) -> None:
        """Override to use OpenClaw logger instead of stderr."""
        logger.debug("HTTP %s", format % args)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def do_GET(self) -> None:
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        parse_qs(parsed.query)

        routes: Dict[str, Callable[[], Tuple[int, Dict[str, Any]]]] = {
            "/status": self._handle_status,
            "/agents": self._handle_agents_get,
            "/config": self._handle_config_get,
            "/metrics": self._handle_metrics,
            "/kill-switch": self._handle_kill_switch_get,
        }

        handler = routes.get(path)
        if handler is not None:
            status_code, body = handler()
            self._send_json(status_code, body)
        else:
            self._send_json(
                404,
                {
                    "error": "not_found",
                    "message": f"Unknown endpoint: {path}",
                    "available_endpoints": list(routes.keys()),
                },
            )

    def do_POST(self) -> None:
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        routes: Dict[str, Callable[[], Tuple[int, Dict[str, Any]]]] = {
            "/kill-switch": self._handle_kill_switch_post,
            "/config": self._handle_config_post,
        }

        handler = routes.get(path)
        if handler is not None:
            status_code, body = handler()
            self._send_json(status_code, body)
        else:
            self._send_json(
                404,
                {
                    "error": "not_found",
                    "message": f"Unknown endpoint: {path}",
                },
            )

    # ------------------------------------------------------------------
    # Endpoint handlers
    # ------------------------------------------------------------------

    def _handle_status(self) -> Tuple[int, Dict[str, Any]]:
        """GET /status -- System status summary."""
        agents = self.state.get_agents()
        uptime = self.state.uptime_seconds

        return 200, {
            "status": "degraded" if self.state.kill_switch_active else "operational",
            "app": APP_NAME,
            "version": APP_VERSION,
            "uptime_seconds": round(uptime, 1),
            "uptime_human": _format_uptime(uptime),
            "started_at": self.state.started_at,
            "kill_switch": self.state.kill_switch_active,
            "agents_registered": len(agents),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _handle_agents_get(self) -> Tuple[int, Dict[str, Any]]:
        """GET /agents -- List all registered agents."""
        agents = self.state.get_agents()
        return 200, {
            "agents": agents,
            "count": len(agents),
        }

    def _handle_kill_switch_get(self) -> Tuple[int, Dict[str, Any]]:
        """GET /kill-switch -- Current kill switch status."""
        return 200, {
            "active": self.state.kill_switch_active,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _handle_kill_switch_post(self) -> Tuple[int, Dict[str, Any]]:
        """POST /kill-switch -- Engage or disengage the kill switch.

        Request body: ``{"active": true/false, "reason": "optional reason"}``
        """
        body = self._read_json_body()
        if body is None:
            return 400, {
                "error": "invalid_json",
                "message": "Request body must be valid JSON",
            }

        active = body.get("active")
        if active is None:
            return 400, {
                "error": "missing_field",
                "message": "Request must include 'active' (true/false)",
            }

        reason = body.get("reason", "admin_api")
        previous = self.state.kill_switch_active
        self.state.set_kill_switch(bool(active))

        action = "engaged" if active else "disengaged"
        log_event(
            logger,
            f"killswitch.{action}",
            reason=reason,
            previous=previous,
        )

        return 200, {
            "active": self.state.kill_switch_active,
            "action": action,
            "reason": reason,
            "previous": previous,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _handle_config_get(self) -> Tuple[int, Dict[str, Any]]:
        """GET /config -- View current configuration (secrets masked)."""
        config = self.state.get_config()
        return 200, {
            "config": config,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _handle_config_post(self) -> Tuple[int, Dict[str, Any]]:
        """POST /config -- Trigger configuration reload.

        This signals the settings module to re-read from disk.
        """
        try:
            from src.core.settings import settings

            settings.load()
            self.state.set_config(settings.as_dict())
            log_event(logger, "config.reloaded")
            return 200, {
                "message": "Configuration reloaded successfully",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.error("Config reload failed: %s", exc)
            return 500, {
                "error": "reload_failed",
                "message": str(exc),
            }

    def _handle_metrics(self) -> Tuple[int, Dict[str, Any]]:
        """GET /metrics -- Current metrics snapshot."""
        metrics = self.state.get_metrics()
        return 200, {
            "metrics": metrics,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _send_json(self, status_code: int, body: Dict[str, Any]) -> None:
        """Send a JSON response."""
        payload = json.dumps(body, indent=2, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-App", f"{APP_NAME}/{APP_VERSION}")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> Optional[Dict[str, Any]]:
        """Read and parse a JSON request body."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}

        try:
            raw = self.rfile.read(content_length)
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None


class AdminAPI:
    """Admin HTTP API server running in a background thread.

    Parameters
    ----------
    host:
        IP address to bind to.  Use ``"0.0.0.0"`` for all interfaces.
    port:
        TCP port to listen on.
    state:
        Shared :class:`SystemState` instance.  If ``None``, a new one
        is created.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        state: Optional[SystemState] = None,
    ) -> None:
        self._host = host
        self._port = port
        self.state = state or SystemState()
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        """Start the API server in a background daemon thread.

        The server will accept connections until :meth:`stop` is called.
        """
        if self._running:
            logger.warning("Admin API is already running")
            return

        # Inject state into the handler class
        handler_class = type(
            "BoundAdminHandler",
            (AdminRequestHandler,),
            {"state": self.state},
        )

        self._server = HTTPServer((self._host, self._port), handler_class)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="admin-api",
            daemon=True,
        )
        self._thread.start()
        self._running = True

        log_event(
            logger,
            "admin_api.started",
            host=self._host,
            port=self._port,
        )

    def stop(self) -> None:
        """Stop the API server and wait for the thread to exit."""
        if not self._running or self._server is None:
            return

        self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

        self._running = False
        log_event(logger, "admin_api.stopped")

    @property
    def is_running(self) -> bool:
        """Return ``True`` if the server is currently running."""
        return self._running

    @property
    def url(self) -> str:
        """Return the base URL of the running server."""
        return f"http://{self._host}:{self._port}"

    def __repr__(self) -> str:
        return f"AdminAPI(url={self.url!r}, running={self._running})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_uptime(seconds: float) -> str:
    """Format uptime seconds into a human-readable string.

    Parameters
    ----------
    seconds:
        Total uptime in seconds.

    Returns
    -------
    str
        Formatted string like ``"2d 5h 30m 15s"``.
    """
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    parts: List[str] = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0 or days > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")

    return " ".join(parts)
