"""
flux-openclaw 통합 백업/복원 모듈

SQLite .backup() API + JSON 파일 아카이빙.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class BackupResult:
    file_path: str
    size_bytes: int
    created_at: str
    contents: list[str]  # files included


@dataclass
class BackupInfo:
    file_path: str
    size_bytes: int
    created_at: str  # from filename


class BackupManager:
    """Unified backup/restore for all persistent state"""

    # Files/directories to backup
    SQLITE_DBS = [
        "data/conversations.db",
        "data/auth.db",
        "data/audit.db",
        "data/webhooks.db",
    ]
    JSON_FILES = [
        "memory/memories.json",
        "usage_data.json",
        "config.json",
        ".tool_approved.json",
    ]
    DIRECTORIES = [
        "knowledge",
    ]

    def __init__(self, backup_dir: str = "backups"):
        """초기화.

        Args:
            backup_dir: 백업 파일 저장 디렉토리
        """
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"BackupManager initialized: {self.backup_dir}")

    def create_backup(self) -> BackupResult:
        """백업 생성.

        Returns:
            BackupResult with file path, size, timestamp, and contents
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_name = f"flux-backup-{timestamp}.tar.gz"
        backup_path = self.backup_dir / backup_name

        contents = []

        # Create temporary directory for staging
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Backup SQLite databases
            for db_path in self.SQLITE_DBS:
                if Path(db_path).exists():
                    self._backup_sqlite(db_path, temp_path / db_path)
                    contents.append(db_path)
                    logger.debug(f"Backed up SQLite database: {db_path}")

            # Backup JSON files
            for json_path in self.JSON_FILES:
                if Path(json_path).exists():
                    dest_path = temp_path / json_path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(json_path, dest_path)
                    contents.append(json_path)
                    logger.debug(f"Backed up JSON file: {json_path}")

            # Backup directories
            for dir_path in self.DIRECTORIES:
                if Path(dir_path).exists() and Path(dir_path).is_dir():
                    dest_path = temp_path / dir_path
                    shutil.copytree(dir_path, dest_path)
                    contents.append(dir_path)
                    logger.debug(f"Backed up directory: {dir_path}")

            # Create tar.gz archive
            with tarfile.open(backup_path, "w:gz") as tar:
                for item in temp_path.iterdir():
                    tar.add(item, arcname=item.name)

            logger.info(f"Created backup: {backup_path}")

        # Get file size
        size_bytes = backup_path.stat().st_size

        return BackupResult(
            file_path=str(backup_path),
            size_bytes=size_bytes,
            created_at=datetime.utcnow().isoformat(),
            contents=contents
        )

    def list_backups(self) -> list[BackupInfo]:
        """백업 목록 조회.

        Returns:
            BackupInfo 리스트 (최신순)
        """
        backups = []

        for backup_file in self.backup_dir.glob("flux-backup-*.tar.gz"):
            # Extract timestamp from filename
            # Format: flux-backup-YYYYMMDD-HHMMSS.tar.gz
            try:
                timestamp_str = backup_file.stem.replace("flux-backup-", "")
                # Parse YYYYMMDD-HHMMSS to ISO format
                dt = datetime.strptime(timestamp_str, "%Y%m%d-%H%M%S")
                created_at = dt.isoformat()
            except ValueError:
                # Fallback to file modification time
                created_at = datetime.fromtimestamp(backup_file.stat().st_mtime).isoformat()

            backups.append(BackupInfo(
                file_path=str(backup_file),
                size_bytes=backup_file.stat().st_size,
                created_at=created_at
            ))

        # Sort by created_at descending (newest first)
        backups.sort(key=lambda x: x.created_at, reverse=True)

        return backups

    def restore_backup(self, backup_file: str) -> BackupResult:
        """백업 복원.

        Args:
            backup_file: 백업 파일 경로

        Returns:
            BackupResult with restored contents

        Raises:
            FileNotFoundError: 백업 파일이 존재하지 않음
            ValueError: 유효하지 않은 백업 파일
        """
        backup_path = Path(backup_file)

        # Validate file exists
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_file}")

        # Validate is .tar.gz
        if not (backup_path.suffix == ".gz" and backup_path.stem.endswith(".tar")):
            raise ValueError(f"Invalid backup file (must be .tar.gz): {backup_file}")

        contents = []

        # Extract to temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Extract archive
            with tarfile.open(backup_path, "r:gz") as tar:
                # Security check: validate all members
                safe_members = []
                for member in tar.getmembers():
                    # Prevent path traversal
                    if member.name.startswith("/") or ".." in member.name:
                        raise ValueError(f"Invalid archive member (path traversal): {member.name}")
                    # Block symlinks, hardlinks, and device files
                    if member.issym() or member.islnk():
                        raise ValueError(f"Invalid archive member (symlink/hardlink): {member.name}")
                    if member.isdev() or member.isblk() or member.ischr() or member.isfifo():
                        raise ValueError(f"Invalid archive member (device/special file): {member.name}")
                    safe_members.append(member)

                tar.extractall(temp_path, members=safe_members)

            # Validate structure (at least one known file)
            extracted_files = list(temp_path.rglob("*"))
            if not extracted_files:
                raise ValueError(f"Empty backup archive: {backup_file}")

            # Restore SQLite databases
            for db_path in self.SQLITE_DBS:
                src_path = temp_path / db_path
                if src_path.exists():
                    self._restore_sqlite(src_path, db_path)
                    contents.append(db_path)
                    logger.debug(f"Restored SQLite database: {db_path}")

            # Restore JSON files
            for json_path in self.JSON_FILES:
                src_path = temp_path / json_path
                if src_path.exists():
                    dest_path = Path(json_path)
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dest_path)
                    contents.append(json_path)
                    logger.debug(f"Restored JSON file: {json_path}")

            # Restore directories
            for dir_path in self.DIRECTORIES:
                src_path = temp_path / dir_path
                if src_path.exists() and src_path.is_dir():
                    dest_path = Path(dir_path)

                    # Remove existing directory
                    if dest_path.exists():
                        shutil.rmtree(dest_path)

                    shutil.copytree(src_path, dest_path)
                    contents.append(dir_path)
                    logger.debug(f"Restored directory: {dir_path}")

        logger.info(f"Restored backup: {backup_file} ({len(contents)} items)")

        return BackupResult(
            file_path=backup_file,
            size_bytes=backup_path.stat().st_size,
            created_at=datetime.utcnow().isoformat(),
            contents=contents
        )

    def _backup_sqlite(self, src_path: str, dest_path: Path):
        """SQLite 데이터베이스 백업 (hot snapshot).

        Uses sqlite3.Connection.backup() API for consistent snapshot
        even during writes.

        Args:
            src_path: 원본 데이터베이스 파일 경로
            dest_path: 대상 파일 경로
        """
        # Create destination directory
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Open source connection
        src_conn = sqlite3.connect(src_path)

        # Open destination connection
        dest_conn = sqlite3.connect(str(dest_path))

        try:
            # Use backup() API for hot snapshot
            src_conn.backup(dest_conn)
        finally:
            src_conn.close()
            dest_conn.close()

    def _restore_sqlite(self, src_path: Path, dest_path: str):
        """SQLite 데이터베이스 복원.

        Args:
            src_path: 백업 파일 경로
            dest_path: 복원할 대상 경로
        """
        dest_file = Path(dest_path)

        # Create destination directory
        dest_file.parent.mkdir(parents=True, exist_ok=True)

        # Close any existing connections (caller's responsibility)
        # We just replace the file

        # Remove existing database if present
        if dest_file.exists():
            # Also remove WAL and SHM files if they exist
            for suffix in ["", "-wal", "-shm"]:
                wal_file = Path(str(dest_file) + suffix)
                if wal_file.exists():
                    wal_file.unlink()

        # Copy backup to destination
        shutil.copy2(src_path, dest_file)
