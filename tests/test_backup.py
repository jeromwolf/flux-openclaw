"""backup 모듈 테스트"""
import os
import sys
import json
import sqlite3
import tarfile
import pytest
from pathlib import Path
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backup import BackupManager, BackupResult, BackupInfo


class TestBackupManager:
    @pytest.fixture
    def setup(self, tmp_path):
        """테스트 환경 설정"""
        backup_dir = str(tmp_path / "backups")

        # Save original working directory
        orig_dir = os.getcwd()

        # Change to tmp_path for isolated testing
        os.chdir(str(tmp_path))

        # Create test data files
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Create test SQLite databases
        db_path = data_dir / "conversations.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello')")
        conn.commit()
        conn.close()

        auth_db = data_dir / "auth.db"
        conn = sqlite3.connect(str(auth_db))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'admin')")
        conn.commit()
        conn.close()

        # Create test JSON files
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        json_path = memory_dir / "memories.json"
        json_path.write_text(json.dumps([{"key": "test", "value": "data"}]))

        usage_path = tmp_path / "usage_data.json"
        usage_path.write_text(json.dumps({"calls": 5}))

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"setting": "value"}))

        # Create test directory
        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()
        (knowledge_dir / "doc.txt").write_text("knowledge content")

        mgr = BackupManager(backup_dir=backup_dir)

        yield mgr, tmp_path, backup_dir

        # Restore original working directory
        os.chdir(orig_dir)

    def test_create_backup(self, setup):
        """백업 생성"""
        mgr, tmp_path, _ = setup
        result = mgr.create_backup()

        assert result is not None
        assert result.file_path.endswith(".tar.gz")
        assert "flux-backup-" in result.file_path
        assert result.size_bytes > 0
        assert os.path.exists(result.file_path)
        assert isinstance(result.contents, list)
        assert len(result.contents) > 0

    def test_backup_contains_sqlite(self, setup):
        """백업에 SQLite DB 포함 확인"""
        mgr, tmp_path, _ = setup
        result = mgr.create_backup()

        with tarfile.open(result.file_path, "r:gz") as tar:
            names = tar.getnames()
            assert any("conversations.db" in n for n in names)
            assert any("auth.db" in n for n in names)

        assert "data/conversations.db" in result.contents
        assert "data/auth.db" in result.contents

    def test_backup_contains_json(self, setup):
        """백업에 JSON 파일 포함 확인"""
        mgr, tmp_path, _ = setup
        result = mgr.create_backup()

        with tarfile.open(result.file_path, "r:gz") as tar:
            names = tar.getnames()
            assert any("memories.json" in n for n in names)
            assert any("usage_data.json" in n for n in names)

        assert "memory/memories.json" in result.contents
        assert "usage_data.json" in result.contents

    def test_backup_contains_directory(self, setup):
        """백업에 디렉토리 포함 확인"""
        mgr, tmp_path, _ = setup
        result = mgr.create_backup()

        with tarfile.open(result.file_path, "r:gz") as tar:
            names = tar.getnames()
            assert any("knowledge" in n for n in names)

        assert "knowledge" in result.contents

    def test_list_backups(self, setup):
        """백업 목록"""
        mgr, tmp_path, _ = setup
        mgr.create_backup()

        backups = mgr.list_backups()
        assert len(backups) >= 1
        assert backups[0].file_path.endswith(".tar.gz")
        assert backups[0].size_bytes > 0
        assert backups[0].created_at is not None

    def test_list_backups_empty(self, tmp_path):
        """빈 백업 목록"""
        backup_dir = str(tmp_path / "empty_backups")
        mgr = BackupManager(backup_dir=backup_dir)

        backups = mgr.list_backups()
        assert len(backups) == 0

    def test_multiple_backups(self, setup):
        """여러 백업 생성"""
        mgr, _, _ = setup

        mgr.create_backup()
        time.sleep(1)  # Ensure different timestamps
        mgr.create_backup()

        backups = mgr.list_backups()
        assert len(backups) >= 2

        # Check sorting (newest first)
        for i in range(len(backups) - 1):
            assert backups[i].created_at >= backups[i + 1].created_at

    def test_restore_backup(self, setup):
        """백업 복원"""
        mgr, tmp_path, _ = setup
        result = mgr.create_backup()

        # Modify data
        usage_path = tmp_path / "usage_data.json"
        usage_path.write_text(json.dumps({"calls": 999}))

        db_path = tmp_path / "data" / "conversations.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE test SET value = 'modified' WHERE id = 1")
        conn.commit()
        conn.close()

        # Restore
        restore_result = mgr.restore_backup(result.file_path)
        assert restore_result is not None
        assert len(restore_result.contents) > 0

        # Verify restored JSON data
        restored = json.loads(usage_path.read_text())
        assert restored["calls"] == 5  # Original value

        # Verify restored SQLite data
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT value FROM test WHERE id = 1")
        value = cursor.fetchone()[0]
        conn.close()
        assert value == "hello"  # Original value

    def test_restore_nonexistent(self, setup):
        """존재하지 않는 백업 복원"""
        mgr, _, _ = setup

        with pytest.raises(FileNotFoundError):
            mgr.restore_backup("nonexistent.tar.gz")

    def test_restore_invalid_format(self, setup, tmp_path):
        """유효하지 않은 형식의 백업 복원"""
        mgr, _, _ = setup

        # Create a file with wrong extension
        invalid_file = tmp_path / "backups" / "invalid.txt"
        invalid_file.write_text("not a backup")

        with pytest.raises(ValueError):
            mgr.restore_backup(str(invalid_file))

    def test_backup_result_structure(self, setup):
        """BackupResult 구조"""
        mgr, _, _ = setup
        result = mgr.create_backup()

        assert hasattr(result, 'file_path')
        assert hasattr(result, 'size_bytes')
        assert hasattr(result, 'created_at')
        assert hasattr(result, 'contents')
        assert isinstance(result.contents, list)
        assert isinstance(result.size_bytes, int)
        assert isinstance(result.file_path, str)

    def test_backup_dir_creation(self, tmp_path):
        """백업 디렉토리 자동 생성"""
        # Change to tmp_path
        orig_dir = os.getcwd()
        os.chdir(str(tmp_path))

        try:
            new_dir = str(tmp_path / "new_backups")
            assert not os.path.exists(new_dir)

            mgr = BackupManager(backup_dir=new_dir)
            assert os.path.exists(new_dir)
        finally:
            os.chdir(orig_dir)

    def test_backup_skips_missing_files(self, setup):
        """누락 파일 스킵"""
        mgr, tmp_path, _ = setup

        # Remove an optional file that backup would look for
        config_path = tmp_path / "config.json"
        if config_path.exists():
            config_path.unlink()

        tool_approved_path = tmp_path / ".tool_approved.json"
        if tool_approved_path.exists():
            tool_approved_path.unlink()

        # Should still succeed
        result = mgr.create_backup()
        assert result is not None
        assert result.size_bytes > 0

        # But missing files should not be in contents
        assert "config.json" not in result.contents
        assert ".tool_approved.json" not in result.contents

    def test_sqlite_hot_backup(self, setup):
        """SQLite hot backup (백업 중 쓰기 가능)"""
        mgr, tmp_path, _ = setup

        db_path = tmp_path / "data" / "conversations.db"

        # Keep connection open during backup
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO test VALUES (2, 'during_backup')")
        conn.commit()

        # Create backup while connection is open
        result = mgr.create_backup()

        # Close connection
        conn.close()

        # Backup should succeed
        assert result is not None
        assert "data/conversations.db" in result.contents

    def test_restore_creates_directories(self, setup):
        """복원 시 디렉토리 자동 생성"""
        mgr, tmp_path, _ = setup
        result = mgr.create_backup()

        # Remove directories
        import shutil
        data_dir = tmp_path / "data"
        if data_dir.exists():
            shutil.rmtree(data_dir)

        memory_dir = tmp_path / "memory"
        if memory_dir.exists():
            shutil.rmtree(memory_dir)

        # Restore should recreate directories
        restore_result = mgr.restore_backup(result.file_path)

        assert data_dir.exists()
        assert memory_dir.exists()
        assert (data_dir / "conversations.db").exists()
        assert (memory_dir / "memories.json").exists()

    def test_backup_info_structure(self, setup):
        """BackupInfo 구조"""
        mgr, _, _ = setup
        mgr.create_backup()

        backups = mgr.list_backups()
        assert len(backups) > 0

        info = backups[0]
        assert hasattr(info, 'file_path')
        assert hasattr(info, 'size_bytes')
        assert hasattr(info, 'created_at')
        assert isinstance(info.file_path, str)
        assert isinstance(info.size_bytes, int)
        assert isinstance(info.created_at, str)
