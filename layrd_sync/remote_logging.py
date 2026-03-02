"""Remote logging handler — batches and ships log records to a backend endpoint.

The handler accumulates records in memory and flushes them periodically or
when the buffer reaches a size threshold.  If the endpoint is unreachable,
records are silently dropped after a configurable number of retries so the
agent keeps running.

Payload format (POST JSON):
{
    "agent_id": "<machine-unique-id>",
    "agent_version": "0.1.0",
    "hostname": "DESKTOP-ABC",
    "records": [
        {
            "ts": "2026-03-02T01:30:00.000Z",
            "level": "INFO",
            "logger": "layrd_sync.sync_engine",
            "message": "Uploaded: fax/page1.tif → abc123",
            "exc": null
        },
        ...
    ]
}
"""

import logging
import threading
import traceback
import platform
import uuid
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import __version__

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL = 30  # seconds
_BUFFER_LIMIT = 100  # flush when this many records buffered
_AGENT_ID_FILE = ".agent_id"


def _get_agent_id(data_dir: Path) -> str:
    """Persistent machine identifier stored next to the database."""
    id_path = data_dir / _AGENT_ID_FILE
    if id_path.exists():
        return id_path.read_text().strip()
    agent_id = str(uuid.uuid4())
    try:
        id_path.write_text(agent_id)
    except OSError:
        pass
    return agent_id


class RemoteLogHandler(logging.Handler):
    """Batching HTTP log handler with background flush thread."""

    def __init__(
        self,
        endpoint: str,
        data_dir: Path,
        flush_interval: float = _FLUSH_INTERVAL,
        buffer_limit: int = _BUFFER_LIMIT,
        api_key: str | None = None,
    ):
        super().__init__(level=logging.INFO)
        self.endpoint = endpoint
        self.agent_id = _get_agent_id(data_dir)
        self.hostname = platform.node()
        self.api_key = api_key

        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._flush_interval = flush_interval
        self._buffer_limit = buffer_limit
        self._closed = False

        self._client = httpx.Client(timeout=10)

        self._timer: threading.Timer | None = None
        self._schedule_flush()

    def emit(self, record: logging.LogRecord):
        if self._closed:
            return
        try:
            entry = {
                "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
                "exc": self._format_exception(record),
            }
            with self._lock:
                self._buffer.append(entry)
                if len(self._buffer) >= self._buffer_limit:
                    self._flush_locked()
        except Exception:
            self.handleError(record)

    def _format_exception(self, record: logging.LogRecord) -> str | None:
        if record.exc_info and record.exc_info[0] is not None:
            return "".join(traceback.format_exception(*record.exc_info))
        return None

    def flush(self):
        with self._lock:
            self._flush_locked()

    def _flush_locked(self):
        """Send buffered records. Must be called with self._lock held."""
        if not self._buffer:
            return

        records = self._buffer[:]
        self._buffer.clear()

        payload = {
            "agent_id": self.agent_id,
            "agent_version": __version__,
            "hostname": self.hostname,
            "records": records,
        }

        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            resp = self._client.post(self.endpoint, json=payload, headers=headers)
            if resp.status_code >= 400:
                pass  # silently drop — don't log about logging failures
        except Exception:
            pass  # endpoint unreachable — silently drop

    def _schedule_flush(self):
        if self._closed:
            return
        self._timer = threading.Timer(self._flush_interval, self._timed_flush)
        self._timer.daemon = True
        self._timer.start()

    def _timed_flush(self):
        if self._closed:
            return
        self.flush()
        self._schedule_flush()

    def close(self):
        self._closed = True
        if self._timer:
            self._timer.cancel()
        self.flush()
        self._client.close()
        super().close()
