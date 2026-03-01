"""Tests for the database module."""

import tempfile
from pathlib import Path

import pytest

from layrd_sync.database import Database, hash_file


@pytest.fixture
def db(tmp_path):
    return Database(db_path=tmp_path / "test.db")


@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "test.pdf"
    f.write_bytes(b"fake pdf content")
    return f


class TestConfig:
    def test_set_and_get(self, db):
        db.set_config("api_url", "http://example.com")
        assert db.get_config("api_url") == "http://example.com"

    def test_get_default(self, db):
        assert db.get_config("missing", "default") == "default"

    def test_upsert(self, db):
        db.set_config("key", "v1")
        db.set_config("key", "v2")
        assert db.get_config("key") == "v2"


class TestWatchedFolders:
    def test_add_and_get(self, db, tmp_path):
        folder = db.add_folder(str(tmp_path / "faxes"), "fax", 30)
        assert folder.label == "fax"
        assert folder.enabled is True

    def test_list_enabled(self, db, tmp_path):
        db.add_folder(str(tmp_path / "faxes"), "fax")
        f2 = db.add_folder(str(tmp_path / "scans"), "scan")
        db.set_folder_enabled(f2.id, False)

        enabled = db.get_folders(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0].label == "fax"

    def test_remove_folder(self, db, tmp_path):
        folder = db.add_folder(str(tmp_path / "faxes"), "fax")
        db.remove_folder(folder.id)
        assert db.get_folders(enabled_only=False) == []

    def test_upsert_folder(self, db, tmp_path):
        path = str(tmp_path / "faxes")
        db.add_folder(path, "fax", 30)
        db.add_folder(path, "fax_updated", 60)
        folders = db.get_folders(enabled_only=False)
        assert len(folders) == 1
        assert folders[0].label == "fax_updated"
        assert folders[0].poll_interval_seconds == 60


class TestUploadedFiles:
    def test_record_and_check(self, db, tmp_path):
        folder = db.add_folder(str(tmp_path), "test")
        assert not db.is_file_uploaded(folder.id, "doc.pdf")

        db.record_upload(
            folder_id=folder.id,
            file_path="doc.pdf",
            file_hash="abc123",
            file_size=1024,
            modified_at=1000.0,
            upload_status="uploaded",
        )
        assert db.is_file_uploaded(folder.id, "doc.pdf")

    def test_has_file_changed(self, db, tmp_path):
        folder = db.add_folder(str(tmp_path), "test")
        db.record_upload(
            folder_id=folder.id,
            file_path="doc.pdf",
            file_hash="abc123",
            file_size=1024,
            modified_at=1000.0,
        )
        assert not db.has_file_changed(folder.id, "doc.pdf", "abc123")
        assert db.has_file_changed(folder.id, "doc.pdf", "different_hash")

    def test_upload_stats(self, db, tmp_path):
        folder = db.add_folder(str(tmp_path), "test")
        db.record_upload(folder.id, "a.pdf", "h1", 100, 1.0, "uploaded")
        db.record_upload(folder.id, "b.pdf", "h2", 200, 2.0, "uploaded")
        db.record_upload(folder.id, "c.pdf", "h3", 300, 3.0, "failed")

        stats = db.get_upload_stats()
        assert stats["uploaded"] == 2
        assert stats["failed"] == 1

    def test_pending_files(self, db, tmp_path):
        folder = db.add_folder(str(tmp_path), "test")
        db.record_upload(folder.id, "a.pdf", "h1", 100, 1.0, "pending")
        db.record_upload(folder.id, "b.pdf", "h2", 200, 2.0, "uploaded")

        pending = db.get_pending_files()
        assert len(pending) == 1
        assert pending[0].file_path == "a.pdf"


class TestHashFile:
    def test_consistent_hash(self, sample_file):
        h1 = hash_file(sample_file)
        h2 = hash_file(sample_file)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_different_content(self, tmp_path):
        f1 = tmp_path / "a.pdf"
        f2 = tmp_path / "b.pdf"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert hash_file(f1) != hash_file(f2)
