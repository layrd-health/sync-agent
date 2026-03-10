"""SQLite database for config, watched folders, and file upload state."""

import sqlite3
import hashlib
import time
from pathlib import Path
from dataclasses import dataclass
from platformdirs import user_data_dir

APP_NAME = "LayrdSync"
DB_NAME = "layrd_sync.db"


@dataclass
class WatchedFolder:
    id: int
    path: str
    label: str  # e.g. "fax", "scan"
    enabled: bool
    poll_interval_seconds: int


@dataclass
class UploadedFile:
    id: int
    folder_id: int
    file_path: str
    file_hash: str
    file_size: int
    modified_at: float
    uploaded_at: float
    upload_status: str  # "uploaded", "failed", "pending"
    remote_id: str | None  # ID returned by the server after upload


def _get_db_path() -> Path:
    data_dir = Path(user_data_dir(APP_NAME))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / DB_NAME


def hash_file(path: Path, chunk_size: int = 8192) -> str:
    """SHA-256 hash of file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


class Database:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or _get_db_path()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS watched_folders (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                path                  TEXT NOT NULL UNIQUE,
                label                 TEXT NOT NULL DEFAULT 'fax',
                enabled               INTEGER NOT NULL DEFAULT 1,
                poll_interval_seconds INTEGER NOT NULL DEFAULT 30
            );

            CREATE TABLE IF NOT EXISTS uploaded_files (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id     INTEGER NOT NULL REFERENCES watched_folders(id),
                file_path     TEXT NOT NULL,
                file_hash     TEXT NOT NULL,
                file_size     INTEGER NOT NULL,
                modified_at   REAL NOT NULL,
                uploaded_at   REAL NOT NULL,
                upload_status TEXT NOT NULL DEFAULT 'pending',
                remote_id     TEXT,
                UNIQUE(folder_id, file_path)
            );

            CREATE INDEX IF NOT EXISTS idx_uploaded_files_hash
                ON uploaded_files(file_hash);
            CREATE INDEX IF NOT EXISTS idx_uploaded_files_status
                ON uploaded_files(upload_status);
        """)
        self.conn.commit()

    # ── Config ──────────────────────────────────────────────────────

    def get_config(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_config(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    # ── Watched Folders ─────────────────────────────────────────────

    def add_folder(
        self, path: str, label: str = "fax", poll_interval: int = 30
    ) -> WatchedFolder:
        cur = self.conn.execute(
            "INSERT INTO watched_folders (path, label, poll_interval_seconds) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET label=excluded.label, "
            "poll_interval_seconds=excluded.poll_interval_seconds",
            (path, label, poll_interval),
        )
        self.conn.commit()
        return self.get_folder(cur.lastrowid or self._folder_id_by_path(path))

    def get_folder(self, folder_id: int) -> WatchedFolder:
        row = self.conn.execute(
            "SELECT * FROM watched_folders WHERE id = ?", (folder_id,)
        ).fetchone()
        return self._row_to_folder(row)

    def get_folders(self, enabled_only: bool = True) -> list[WatchedFolder]:
        query = "SELECT * FROM watched_folders"
        if enabled_only:
            query += " WHERE enabled = 1"
        rows = self.conn.execute(query).fetchall()
        return [self._row_to_folder(r) for r in rows]

    def remove_folder(self, folder_id: int):
        self.conn.execute("DELETE FROM uploaded_files WHERE folder_id = ?", (folder_id,))
        self.conn.execute("DELETE FROM watched_folders WHERE id = ?", (folder_id,))
        self.conn.commit()

    def set_folder_enabled(self, folder_id: int, enabled: bool):
        self.conn.execute(
            "UPDATE watched_folders SET enabled = ? WHERE id = ?",
            (int(enabled), folder_id),
        )
        self.conn.commit()

    def _folder_id_by_path(self, path: str) -> int:
        row = self.conn.execute(
            "SELECT id FROM watched_folders WHERE path = ?", (path,)
        ).fetchone()
        return row["id"]

    @staticmethod
    def _row_to_folder(row: sqlite3.Row) -> WatchedFolder:
        return WatchedFolder(
            id=row["id"],
            path=row["path"],
            label=row["label"],
            enabled=bool(row["enabled"]),
            poll_interval_seconds=row["poll_interval_seconds"],
        )

    # ── Uploaded Files (State Tracking) ─────────────────────────────

    def is_file_uploaded(self, folder_id: int, file_path: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM uploaded_files "
            "WHERE folder_id = ? AND file_path = ? AND upload_status = 'uploaded'",
            (folder_id, file_path),
        ).fetchone()
        return row is not None

    def has_file_changed(self, folder_id: int, file_path: str, current_hash: str) -> bool:
        """Check if a previously uploaded file has been modified."""
        row = self.conn.execute(
            "SELECT file_hash FROM uploaded_files "
            "WHERE folder_id = ? AND file_path = ?",
            (folder_id, file_path),
        ).fetchone()
        if row is None:
            return True
        return row["file_hash"] != current_hash

    def record_upload(
        self,
        folder_id: int,
        file_path: str,
        file_hash: str,
        file_size: int,
        modified_at: float,
        upload_status: str = "uploaded",
        remote_id: str | None = None,
    ):
        self.conn.execute(
            "INSERT INTO uploaded_files "
            "(folder_id, file_path, file_hash, file_size, modified_at, uploaded_at, upload_status, remote_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(folder_id, file_path) DO UPDATE SET "
            "file_hash=excluded.file_hash, file_size=excluded.file_size, "
            "modified_at=excluded.modified_at, uploaded_at=excluded.uploaded_at, "
            "upload_status=excluded.upload_status, remote_id=excluded.remote_id",
            (folder_id, file_path, file_hash, file_size, modified_at, time.time(), upload_status, remote_id),
        )
        self.conn.commit()

    def get_pending_files(self, folder_id: int | None = None) -> list[UploadedFile]:
        query = "SELECT * FROM uploaded_files WHERE upload_status = 'pending'"
        params: list = []
        if folder_id is not None:
            query += " AND folder_id = ?"
            params.append(folder_id)
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_file(r) for r in rows]

    def get_failed_files(self, folder_id: int | None = None) -> list[UploadedFile]:
        query = "SELECT * FROM uploaded_files WHERE upload_status = 'failed'"
        params: list = []
        if folder_id is not None:
            query += " AND folder_id = ?"
            params.append(folder_id)
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_file(r) for r in rows]

    def reset_failed_files(self, folder_id: int | None = None) -> int:
        """Delete failed file records so they get re-discovered on next scan.
        Returns the number of records removed."""
        query = "DELETE FROM uploaded_files WHERE upload_status = 'failed'"
        params: list = []
        if folder_id is not None:
            query += " AND folder_id = ?"
            params.append(folder_id)
        cur = self.conn.execute(query, params)
        self.conn.commit()
        return cur.rowcount

    def get_uploaded_files(self) -> list[UploadedFile]:
        """Return all files with upload_status='uploaded' (candidates for cleanup)."""
        rows = self.conn.execute(
            "SELECT * FROM uploaded_files WHERE upload_status = 'uploaded'"
        ).fetchall()
        return [self._row_to_file(r) for r in rows]

    def mark_file_cleaned(self, file_id: int):
        self.conn.execute(
            "UPDATE uploaded_files SET upload_status = 'cleaned' WHERE id = ?",
            (file_id,),
        )
        self.conn.commit()

    def get_upload_stats(self, folder_id: int | None = None) -> dict[str, int]:
        where = ""
        params: list = []
        if folder_id is not None:
            where = "WHERE folder_id = ?"
            params.append(folder_id)
        rows = self.conn.execute(
            f"SELECT upload_status, COUNT(*) as cnt FROM uploaded_files {where} GROUP BY upload_status",
            params,
        ).fetchall()
        return {row["upload_status"]: row["cnt"] for row in rows}

    @staticmethod
    def _row_to_file(row: sqlite3.Row) -> UploadedFile:
        return UploadedFile(
            id=row["id"],
            folder_id=row["folder_id"],
            file_path=row["file_path"],
            file_hash=row["file_hash"],
            file_size=row["file_size"],
            modified_at=row["modified_at"],
            uploaded_at=row["uploaded_at"],
            upload_status=row["upload_status"],
            remote_id=row["remote_id"],
        )

    def close(self):
        self.conn.close()
