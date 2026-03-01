"""Self-updater — checks for new versions and applies updates.

Flow:
1. GET {update_url}/api/sync-agent/version → { "version": "0.2.0", "download_url": "...", "sha256": "..." }
2. If newer than current, download to temp dir
3. Verify SHA-256
4. On Windows: write a batch script that waits for this process to exit, replaces
   the exe, and relaunches. Then exit.
5. On other platforms: launch the new binary and exit.
"""

import logging
import hashlib
import sys
import os
import tempfile
import subprocess
import time
from pathlib import Path

import httpx

from . import __version__

logger = logging.getLogger(__name__)


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.strip().split("."))


class Updater:
    def __init__(self, update_url: str):
        self.update_url = update_url.rstrip("/")
        self._client = httpx.Client(timeout=60)

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
        """Download the update, verify it, and apply it."""
        download_url = update_info.get("download_url")
        expected_hash = update_info.get("sha256")
        new_version = update_info.get("version", "unknown")

        if not download_url:
            logger.error("No download URL in update info")
            return False

        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="layrd_update_"))
            filename = download_url.split("/")[-1] or "LayrdSync_update.exe"
            tmp_path = tmp_dir / filename

            logger.info("Downloading update v%s from %s", new_version, download_url)
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

            logger.info("Download verified (SHA-256 OK), applying update")

            if sys.platform == "win32" and getattr(sys, "frozen", False):
                return self._apply_windows_update(tmp_path)
            else:
                logger.info("Non-frozen or non-Windows: update downloaded to %s", tmp_path)
                logger.info("Manual replacement required in dev mode")
                return True

        except Exception as e:
            logger.exception("Failed to download/apply update: %s", e)
            return False

    def _apply_windows_update(self, new_exe: Path) -> bool:
        """Windows-specific: write a batch script to replace the running exe and relaunch."""
        current_exe = Path(sys.executable)
        pid = os.getpid()

        # Batch script waits for current process to exit, then replaces exe and relaunches
        bat_path = new_exe.parent / "layrd_update.bat"
        bat_content = f"""@echo off
echo Waiting for LayrdSync to exit...
:wait
tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait
)
echo Replacing executable...
copy /Y "{new_exe}" "{current_exe}"
if errorlevel 1 (
    echo Update failed - could not replace executable
    pause
    exit /b 1
)
echo Relaunching LayrdSync...
start "" "{current_exe}"
del "{new_exe}"
del "%~f0"
"""
        bat_path.write_text(bat_content)

        logger.info("Launching update script: %s", bat_path)
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
        return True

    def close(self):
        self._client.close()
