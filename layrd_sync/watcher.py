"""Polling-based folder watcher. Reliable on SMB/network shares."""

import logging
import time
from pathlib import Path
from dataclasses import dataclass

from .database import Database, WatchedFolder, hash_file

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".tif", ".tiff", ".png", ".jpg", ".jpeg"}

# Freshly-arriving faxes may still be written to disk. Wait this long after
# the last modification before considering a file "stable" and ready to upload.
STABILITY_WINDOW_SECONDS = 5


@dataclass
class NewFile:
    folder: WatchedFolder
    path: Path
    file_hash: str
    file_size: int
    modified_at: float


class FolderWatcher:
    """Scans watched folders for new/modified files on each poll cycle."""

    def __init__(self, db: Database):
        self.db = db

    def scan_folder(self, folder: WatchedFolder) -> list[NewFile]:
        """Scan a single folder and return files that need uploading."""
        folder_path = Path(folder.path)
        if not folder_path.exists():
            logger.warning("Watched folder does not exist: %s", folder.path)
            return []

        new_files: list[NewFile] = []
        now = time.time()

        for file_path in self._iter_files(folder_path):
            try:
                stat = file_path.stat()

                if now - stat.st_mtime < STABILITY_WINDOW_SECONDS:
                    logger.debug("Skipping (still being written): %s", file_path)
                    continue

                rel_path = str(file_path.relative_to(folder_path))

                if self.db.is_file_uploaded(folder.id, rel_path):
                    continue

                file_hash = hash_file(file_path)

                if not self.db.has_file_changed(folder.id, rel_path, file_hash):
                    continue

                new_files.append(
                    NewFile(
                        folder=folder,
                        path=file_path,
                        file_hash=file_hash,
                        file_size=stat.st_size,
                        modified_at=stat.st_mtime,
                    )
                )
            except OSError as e:
                logger.warning("Error reading %s: %s", file_path, e)
                continue

        logger.info(
            "Scanned %s (%s): %d new file(s)",
            folder.label,
            folder.path,
            len(new_files),
        )
        return new_files

    def scan_all(self) -> list[NewFile]:
        """Scan all enabled watched folders."""
        folders = self.db.get_folders(enabled_only=True)
        all_new: list[NewFile] = []
        for folder in folders:
            all_new.extend(self.scan_folder(folder))
        return all_new

    def get_all_inbox_hashes(self) -> list[str]:
        """Return the SHA-256 hash of every supported file currently on disk.

        Unlike :meth:`scan_all`, this does **not** skip already-uploaded files
        or apply a stability window — it is a raw snapshot of what is in the
        inbox right now, used for backend reconciliation.
        """
        hashes: list[str] = []
        for folder in self.db.get_folders(enabled_only=True):
            folder_path = Path(folder.path)
            if not folder_path.exists():
                continue
            for file_path in self._iter_files(folder_path):
                try:
                    hashes.append(hash_file(file_path))
                except OSError as e:
                    logger.warning("Error hashing %s: %s", file_path, e)
        return hashes

    def _iter_files(self, root: Path):
        """Yield supported files in the top-level directory only (no recursion)."""
        try:
            for entry in root.iterdir():
                if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
                    yield entry
        except PermissionError as e:
            logger.warning("Permission denied: %s", e)
        except OSError as e:
            logger.warning("OS error scanning %s: %s", root, e)
