"""Upload client — sends files to the Layrd backend via the sync upload endpoint."""

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from .watcher import NewFile

logger = logging.getLogger(__name__)

UPLOAD_TIMEOUT_SECONDS = 120


@dataclass
class UploadResult:
    success: bool
    remote_id: str | None = None
    error: str | None = None


class Uploader:
    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(timeout=UPLOAD_TIMEOUT_SECONDS)

    def upload(self, new_file: NewFile) -> UploadResult:
        """Upload a single file to the Layrd backend."""
        try:
            headers: dict[str, str] = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            with open(new_file.path, "rb") as f:
                response = self._client.post(
                    f"{self.base_url}/api/sync/upload",
                    headers=headers,
                    files={"file": (new_file.path.name, f)},
                    data={
                        "source_label": new_file.folder.label,
                        "source_path": str(new_file.path),
                        "file_hash": new_file.file_hash,
                        "file_modified_at": str(new_file.modified_at),
                    },
                )

            if response.status_code == 200:
                body = response.json()
                return UploadResult(success=True, remote_id=body.get("id"))
            else:
                return UploadResult(
                    success=False,
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

        except httpx.TimeoutException:
            return UploadResult(success=False, error="Upload timed out")
        except httpx.ConnectError as e:
            return UploadResult(success=False, error=f"Connection failed: {e}")
        except Exception as e:
            logger.exception("Unexpected upload error for %s", new_file.path)
            return UploadResult(success=False, error=str(e))

    def check_cleanup(self, file_hashes: list[str]) -> list[str]:
        """Ask the backend which uploaded files are ready for local cleanup."""
        if not file_hashes:
            return []
        try:
            headers: dict[str, str] = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            response = self._client.post(
                f"{self.base_url}/api/sync/cleanup-ready",
                headers=headers,
                json={"file_hashes": file_hashes},
            )
            if response.status_code == 200:
                return response.json().get("ready", [])
            else:
                logger.warning("Cleanup check failed: HTTP %s", response.status_code)
                return []
        except Exception as e:
            logger.warning("Cleanup check error: %s", e)
            return []

    def close(self):
        self._client.close()
