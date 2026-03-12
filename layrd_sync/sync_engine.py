"""Core sync engine — ties together watcher, uploader, and state tracking."""

import logging
import shutil
import threading
from pathlib import Path

from .database import Database
from .watcher import FolderWatcher, NewFile
from .uploader import Uploader, UploadResult

RECYCLE_FOLDER_NAME = "layrd_recycle"

logger = logging.getLogger(__name__)


class SyncEngine:
    """Runs the scan → upload → record cycle. Thread-safe for use with scheduler."""

    def __init__(self, db: Database, uploader: Uploader):
        self.db = db
        self.watcher = FolderWatcher(db)
        self.uploader = uploader
        self._lock = threading.Lock()
        self._running = False
        self.last_reconcile: dict | None = None

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

            self._run_reconcile_cycle()
            self._run_cleanup_cycle()

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

    def _run_reconcile_cycle(self):
        """Report current inbox contents to the backend for reconciliation."""
        try:
            inbox_hashes = self.watcher.get_all_inbox_hashes()
            result = self.uploader.reconcile(inbox_hashes)
            if result:
                self.last_reconcile = result
                if result.get("reconciled_count", 0) > 0:
                    logger.info(
                        "Reconcile: %d doc(s) marked externally_handled, "
                        "%d active, %d in inbox",
                        result["reconciled_count"],
                        result["active_count"],
                        result["inbox_count"],
                    )
        except Exception:
            logger.exception("Error in reconcile cycle")

    def _run_cleanup_cycle(self):
        """Check which uploaded files have been fully processed and move them to recycle."""
        uploaded_files = self.db.get_uploaded_files()
        if not uploaded_files:
            return

        hash_to_files: dict[str, list] = {}
        for uf in uploaded_files:
            hash_to_files.setdefault(uf.file_hash, []).append(uf)

        all_hashes = list(hash_to_files.keys())

        # Verify uploads actually exist in the backend; reset phantoms
        existing_hashes = set(self.uploader.check_exists(all_hashes))
        phantom_count = 0
        for file_hash in all_hashes:
            if file_hash not in existing_hashes:
                for uf in hash_to_files.pop(file_hash):
                    self.db.reset_uploaded_file(uf.id)
                    phantom_count += 1
        if phantom_count:
            logger.warning("Reset %d phantom upload(s) for re-upload", phantom_count)

        if not hash_to_files:
            return

        ready_hashes = self.uploader.check_cleanup(list(hash_to_files.keys()))
        if not ready_hashes:
            return

        folders_by_id: dict[int, str] = {}
        for folder in self.db.get_folders(enabled_only=False):
            folders_by_id[folder.id] = folder.path

        cleaned_count = 0
        for file_hash in ready_hashes:
            for uf in hash_to_files.get(file_hash, []):
                folder_path = folders_by_id.get(uf.folder_id)
                if not folder_path:
                    self.db.mark_file_cleaned(uf.id)
                    continue

                src = Path(folder_path) / uf.file_path
                if src.exists():
                    recycle_dir = Path(folder_path) / RECYCLE_FOLDER_NAME
                    recycle_dir.mkdir(exist_ok=True)
                    dest = recycle_dir / src.name
                    if dest.exists():
                        dest = recycle_dir / f"{src.stem}_{uf.id}{src.suffix}"
                    try:
                        shutil.move(str(src), str(dest))
                        logger.info("Cleaned up: %s → %s", src.name, dest)
                    except OSError as e:
                        logger.warning("Failed to move %s to recycle: %s", src, e)
                        continue

                self.db.mark_file_cleaned(uf.id)
                cleaned_count += 1

        if cleaned_count:
            logger.info("Cleanup: moved %d file(s) to recycle", cleaned_count)

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
