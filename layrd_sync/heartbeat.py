"""Heartbeat client — reports status and processes remote commands.

Replaces the separate remote logging flush. The heartbeat POST sends agent
status + buffered log records every cycle, and receives pending commands
in the response.
"""

import logging
import platform
import threading
import traceback
from datetime import datetime, timezone

import httpx

from . import __version__
from .database import Database
from .remote_logging import _get_agent_id

logger = logging.getLogger(__name__)


class HeartbeatClient:
    """Sends periodic heartbeats and executes commands from the server."""

    def __init__(
        self,
        db: Database,
        api_url: str,
        api_key: str | None = None,
    ):
        self.db = db
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.agent_id = _get_agent_id(db.db_path.parent)
        self.hostname = platform.node()
        self.os_info = f"{platform.system()} {platform.release()}"

        self._log_buffer: list[dict] = []
        self._log_lock = threading.Lock()
        self._client = httpx.Client(timeout=15)

        # Wired up by main.py after engine is created
        self.get_status: callable = lambda: {}
        self.on_command: callable = lambda cmd, params: None

    def buffer_log(self, record: logging.LogRecord):
        """Add a log record to the buffer for the next heartbeat."""
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "exc": "".join(traceback.format_exception(*record.exc_info)) if record.exc_info and record.exc_info[0] else None,
        }
        with self._log_lock:
            self._log_buffer.append(entry)
            # Cap buffer to prevent memory growth if heartbeats are failing
            if len(self._log_buffer) > 500:
                self._log_buffer = self._log_buffer[-200:]

    def send_heartbeat(self):
        """POST status + logs, process commands from response."""
        # Drain log buffer
        with self._log_lock:
            logs = self._log_buffer[:]
            self._log_buffer.clear()

        status_data = self.get_status()

        payload = {
            "agent_id": self.agent_id,
            "agent_version": __version__,
            "hostname": self.hostname,
            "os_info": self.os_info,
            "status": status_data.get("sync_status", "active"),
            "status_data": status_data,
            "logs": logs,
        }

        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            resp = self._client.post(
                f"{self.api_url}/api/sync-agent/heartbeat",
                json=payload,
                headers=headers,
            )

            if resp.status_code == 200:
                data = resp.json()
                for cmd in data.get("commands", []):
                    command = cmd.get("command")
                    params = cmd.get("params")
                    logger.info("Remote command received: %s %s", command, params or "")
                    try:
                        self.on_command(command, params)
                    except Exception:
                        logger.exception("Error executing command: %s", command)
            elif resp.status_code == 401:
                logger.warning("Heartbeat auth failed (401) — check API key")
            else:
                logger.debug("Heartbeat response: HTTP %s", resp.status_code)

        except httpx.ConnectError:
            logger.debug("Heartbeat: server unreachable")
        except Exception:
            logger.debug("Heartbeat error", exc_info=True)

    def close(self):
        self._client.close()


class HeartbeatLogHandler(logging.Handler):
    """Logging handler that buffers records for the heartbeat client."""

    def __init__(self, heartbeat: HeartbeatClient):
        super().__init__(level=logging.INFO)
        self.heartbeat = heartbeat

    def emit(self, record: logging.LogRecord):
        try:
            self.heartbeat.buffer_log(record)
        except Exception:
            self.handleError(record)
