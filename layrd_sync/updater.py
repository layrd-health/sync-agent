"""Self-updater — checks for new versions and applies updates.

Flow:
1. GET /api/sync-agent/version → { "version": "0.2.0", "download_url": "...", "sha256": "..." }
2. If newer than current, download to temp dir
3. Verify SHA-256
4. Launch installer/new binary and exit current process
"""

import logging
import hashlib
import sys
import os
import tempfile
import subprocess
from pathlib import Path

import httpx

from . import __version__

logger = logging.getLogger(__name__)


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.strip().split("."))


class Updater:
    def __init__(self, update_url: str):
        self.update_url = update_url.rstrip("/")
        self._client = httpx.Client(timeout=30)

    def check_for_update(self) -> dict | None:
        """Returns update info dict if a newer version is available, else None."""
        try:
            resp = self._client.get(f"{self.update_url}/api/sync-agent/version")
            resp.raise_for_status()
            info = resp.json()

            remote_version = info.get("version", "0.0.0")
            if _version_tuple(remote_version) > _version_tuple(__version__):
                logger.info("Update available: %s → %s", __version__, remote_version)
                return info
            else:
                logger.debug("Up to date (current=%s, remote=%s)", __version__, remote_version)
                return None

        except Exception as e:
            logger.warning("Update check failed: %s", e)
            return None

    def download_and_apply(self, update_info: dict) -> bool:
        """Download the update, verify it, and launch the installer."""
        download_url = update_info.get("download_url")
        expected_hash = update_info.get("sha256")

        if not download_url:
            logger.error("No download URL in update info")
            return False

        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="layrd_update_"))
            filename = download_url.split("/")[-1] or "layrd_sync_update.exe"
            tmp_path = tmp_dir / filename

            logger.info("Downloading update from %s", download_url)
            with self._client.stream("GET", download_url) as resp:
                resp.raise_for_status()
                h = hashlib.sha256()
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_bytes(8192):
                        f.write(chunk)
                        h.update(chunk)

            if expected_hash and h.hexdigest() != expected_hash:
                logger.error("Hash mismatch! Expected %s, got %s", expected_hash, h.hexdigest())
                tmp_path.unlink()
                return False

            logger.info("Update downloaded to %s, launching installer", tmp_path)
            if sys.platform == "win32":
                os.startfile(str(tmp_path))
            else:
                subprocess.Popen([str(tmp_path)], start_new_session=True)

            return True

        except Exception as e:
            logger.exception("Failed to download/apply update: %s", e)
            return False

    def close(self):
        self._client.close()
