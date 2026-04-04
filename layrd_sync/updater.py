"""Self-updater — checks GitHub Releases for new versions and applies updates.

Flow:
1. GET https://api.github.com/repos/{owner}/{repo}/releases/latest
2. Parse version tag, compare to current
3. Download the LayrdSync.zip asset from the release
4. Verify SHA-256 if provided in release body
5. On Windows: write a batch script that waits for this process to exit,
   replaces the app folder, and relaunches. Then exit.
"""

import logging
import hashlib
import re
import sys
import os
import tempfile
import subprocess
import zipfile
from pathlib import Path

import httpx

from . import __version__

logger = logging.getLogger(__name__)

GITHUB_REPO = "layrd-health/sync-agent"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_NAME = "LayrdSync.zip"


def _version_tuple(v: str) -> tuple[int, ...]:
    clean = v.lstrip("vV").strip()
    return tuple(int(x) for x in clean.split("."))


def _extract_sha256(body: str | None, asset_name: str) -> str | None:
    """Try to extract a SHA-256 hash from the release body for a given asset."""
    if not body:
        return None
    for line in body.splitlines():
        if asset_name in line:
            match = re.search(r"[a-f0-9]{64}", line, re.IGNORECASE)
            if match:
                return match.group(0).lower()
    match = re.search(r"sha256[:\s]+([a-f0-9]{64})", body, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return None


class Updater:
    def __init__(self, update_url: str | None = None):
        self._update_url = update_url
        self._client = httpx.Client(
            timeout=120,
            headers={"Accept": "application/vnd.github+json"},
            follow_redirects=True,
        )

    def check_for_update(self) -> dict | None:
        """Check GitHub Releases for a newer version. Returns info dict or None."""
        try:
            resp = self._client.get(GITHUB_API)
            resp.raise_for_status()
            release = resp.json()

            tag = release.get("tag_name", "v0.0.0")
            remote_version = _version_tuple(tag)
            current_version = _version_tuple(__version__)

            if remote_version <= current_version:
                logger.debug("Up to date (current=%s, latest=%s)", __version__, tag)
                return None

            assets = release.get("assets", [])
            download_url = None
            for asset in assets:
                if asset.get("name") == ASSET_NAME:
                    download_url = asset.get("browser_download_url")
                    break

            if not download_url:
                # Fallback: check for .exe (old format)
                for asset in assets:
                    if asset.get("name") == "LayrdSync.exe":
                        download_url = asset.get("browser_download_url")
                        break

            if not download_url:
                logger.warning("Release %s has no %s asset", tag, ASSET_NAME)
                return None

            expected_hash = _extract_sha256(release.get("body"), ASSET_NAME)

            logger.info("Update available: %s -> %s", __version__, tag)
            return {
                "version": tag.lstrip("vV"),
                "download_url": download_url,
                "sha256": expected_hash,
                "release_url": release.get("html_url"),
            }

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
            tmp_path = tmp_dir / ASSET_NAME

            logger.info("Downloading update v%s from %s", new_version, download_url)
            with self._client.stream("GET", download_url) as resp:
                resp.raise_for_status()
                h = hashlib.sha256()
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_bytes(8192):
                        f.write(chunk)
                        h.update(chunk)

            actual_hash = h.hexdigest()
            if expected_hash and actual_hash != expected_hash:
                logger.error("Hash mismatch! Expected %s, got %s", expected_hash, actual_hash)
                tmp_path.unlink()
                return False

            logger.info("Download complete (%s), applying update", actual_hash[:12])

            if sys.platform == "win32" and getattr(sys, "frozen", False):
                return self._apply_windows_update(tmp_path, tmp_dir)
            else:
                logger.info("Non-frozen or non-Windows: update at %s (manual replacement)", tmp_path)
                return True

        except Exception as e:
            logger.exception("Failed to download/apply update: %s", e)
            return False

    def _apply_windows_update(self, downloaded_path: Path, tmp_dir: Path) -> bool:
        """Windows: extract zip, write a batch script to swap the app folder and relaunch."""
        current_exe = Path(sys.executable)
        app_dir = current_exe.parent
        pid = os.getpid()

        # Extract zip to a staging directory
        staging_dir = tmp_dir / "staging"
        if downloaded_path.suffix == ".zip":
            logger.info("Extracting update zip to %s", staging_dir)
            with zipfile.ZipFile(downloaded_path, "r") as zf:
                zf.extractall(staging_dir)
            source_dir = staging_dir
        else:
            # Fallback for old single-exe format
            staging_dir.mkdir(parents=True, exist_ok=True)
            source_dir = staging_dir
            downloaded_path.rename(staging_dir / current_exe.name)

        bat_path = tmp_dir / "layrd_update.bat"
        bat_content = f"""@echo off
echo Waiting for LayrdSync (PID {pid}) to exit...
:wait
tasklist /FI "PID eq {pid}" /NH 2>NUL | findstr /B /C:"{pid} " >NUL 2>NUL
if %errorlevel%==0 (
    timeout /t 1 /nobreak >NUL
    goto wait
)
echo Process exited. Waiting for file locks to release...
timeout /t 3 /nobreak >NUL

echo Cleaning old files...
rmdir /S /Q "{app_dir}\\_internal" >NUL 2>NUL

echo Replacing app folder contents...
set RETRIES=0
:copy_retry
xcopy /E /Y /Q "{source_dir}\\*" "{app_dir}\\" >NUL 2>NUL
if errorlevel 1 (
    set /a RETRIES+=1
    if %RETRIES% GEQ 10 (
        echo Update failed after 10 retries
        exit /b 1
    )
    timeout /t 1 /nobreak >NUL
    goto copy_retry
)
echo Relaunching LayrdSync...
start "" /D "{app_dir}" "{current_exe}"
timeout /t 3 /nobreak >NUL
rmdir /S /Q "{tmp_dir}" >NUL 2>NUL
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
