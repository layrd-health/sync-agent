"""Core sync engine — ties together watcher, uploader, and state tracking."""

import logging
import threading
from pathlib import Path

from .database import Database
from .watcher import FolderWatcher, NewFile
from .uploader import Uploader, UploadResult

logger = logging.getLogger(__name__)


class SyncEngine:
    """Runs the scan → upload → record cycle. Thread-safe for use with scheduler."""

    def __init__(self, db: Database, uploader: Uploader):
        self.db = db
        self.watcher = FolderWatcher(db)
        self.uploader = uploader
        self._lock = threading.Lock()
        self._running = False

        self.on_file_uploaded: list[callable] = []
        self.on_file_failed: list[callable] = []
        self.on_scan_complete: list[callable] = []

    def run_sync_cycle(self):
        """One full scan-and-upload cycle across all enabled folders."""
        if not self._lock.acquire(blocking=False):
            logger.debug("Sync cycle already running, skipping")
            return

        try:
            self._running = True
            new_files = self.watcher.scan_all()

            uploaded_count = 0
            failed_count = 0

            for nf in new_files:
                result = self._upload_file(nf)
                if result.success:
                    uploaded_count += 1
                else:
                    failed_count += 1

            for cb in self.on_scan_complete:
                try:
                    cb(uploaded_count, failed_count)
                except Exception:
                    logger.exception("Error in on_scan_complete callback")

        finally:
            self._running = False
            self._lock.release()

    def _upload_file(self, nf: NewFile) -> UploadResult:
        rel_path = str(nf.path.relative_to(Path(nf.folder.path)))

        self.db.record_upload(
            folder_id=nf.folder.id,
            file_path=rel_path,
            file_hash=nf.file_hash,
            file_size=nf.file_size,
            modified_at=nf.modified_at,
            upload_status="pending",
        )

        result = self.uploader.upload(nf)

        if result.success:
            self.db.record_upload(
                folder_id=nf.folder.id,
                file_path=rel_path,
                file_hash=nf.file_hash,
                file_size=nf.file_size,
                modified_at=nf.modified_at,
                upload_status="uploaded",
                remote_id=result.remote_id,
            )
            logger.info("Uploaded: %s/%s → %s", nf.folder.label, rel_path, result.remote_id)
            for cb in self.on_file_uploaded:
                try:
                    cb(nf, result)
                except Exception:
                    logger.exception("Error in on_file_uploaded callback")
        else:
            self.db.record_upload(
                folder_id=nf.folder.id,
                file_path=rel_path,
                file_hash=nf.file_hash,
                file_size=nf.file_size,
                modified_at=nf.modified_at,
                upload_status="failed",
            )
            logger.warning("Upload failed: %s/%s — %s", nf.folder.label, rel_path, result.error)
            for cb in self.on_file_failed:
                try:
                    cb(nf, result)
                except Exception:
                    logger.exception("Error in on_file_failed callback")

        return result

    def retry_failed(self) -> int:
        """Reset all failed uploads and re-run a sync cycle.
        Returns the number of failed files queued for retry."""
        count = self.db.reset_failed_files()
        if count > 0:
            logger.info("Reset %d failed file(s) for retry", count)
            self.run_sync_cycle()
        else:
            logger.info("No failed files to retry")
        return count

    @property
    def is_running(self) -> bool:
        return self._running
