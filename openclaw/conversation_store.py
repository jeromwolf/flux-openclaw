"""SQLite 기반 대화 영속성 모듈.

stdlib + sqlite3 only, thread-safe implementation.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class ConversationRecord:
    """대화 레코드."""
    id: str
    interface: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


@dataclass
class MessageRecord:
    """메시지 레코드."""
    id: int
    conversation_id: str
    role: str
    content: Any
    token_count: int
    created_at: str


class ConversationStore:
    """SQLite 기반 대화 저장소."""

    def __init__(self, db_path: str = "data/conversations.db"):
        """초기화.

        Args:
            db_path: 데이터베이스 파일 경로 (기본값: data/conversations.db)
        """
        self.db_path = db_path
        self._lock = threading.Lock()

        # 디렉토리 생성
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        # 커넥션 초기화
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # SQLite 설정
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")

        # 스키마 초기화
        self._init_schema()

        logger.info(f"ConversationStore initialized: {db_path}")

    def _init_schema(self):
        """스키마 초기화."""
        with self._lock:
            cursor = self._conn.cursor()

            # conversations 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id              TEXT PRIMARY KEY,
                    interface       TEXT NOT NULL DEFAULT 'cli',
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL,
                    metadata_json   TEXT DEFAULT '{}'
                )
            """)

            # messages 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role            TEXT NOT NULL,
                    content_json    TEXT NOT NULL,
                    token_count     INTEGER DEFAULT 0,
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)

            # 인덱스
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages(conversation_id, created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_interface
                ON conversations(interface, updated_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_updated
                ON conversations(updated_at DESC)
            """)

            # Phase 8: Add user_id column (idempotent migration)
            try:
                self._conn.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT DEFAULT 'default'")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at DESC)")
                self._conn.commit()
            except Exception:
                pass  # Column already exists

            self._conn.commit()

    def create_conversation(
        self,
        interface: str = "cli",
        metadata: Optional[dict[str, Any]] = None,
        user_id: str = "default"
    ) -> ConversationRecord:
        """새 대화 생성.

        Args:
            interface: 인터페이스 타입 (cli, web, api 등)
            metadata: 추가 메타데이터
            user_id: 사용자 ID (기본값: "default")

        Returns:
            생성된 ConversationRecord
        """
        conversation_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        metadata = metadata or {}
        metadata_json = json.dumps(metadata, ensure_ascii=False)

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                INSERT INTO conversations (id, interface, created_at, updated_at, metadata_json, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (conversation_id, interface, now, now, metadata_json, user_id))
            self._conn.commit()

        logger.info(f"Created conversation: {conversation_id} (interface={interface}, user_id={user_id})")

        return ConversationRecord(
            id=conversation_id,
            interface=interface,
            created_at=now,
            updated_at=now,
            metadata=metadata
        )

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: Any,
        token_count: int = 0
    ) -> MessageRecord:
        """대화에 메시지 추가.

        Args:
            conversation_id: 대화 ID
            role: 메시지 역할 (user, assistant 등)
            content: 메시지 내용 (str, list, dict, dataclass)
            token_count: 토큰 수

        Returns:
            생성된 MessageRecord
        """
        now = datetime.utcnow().isoformat()

        # content 직렬화
        content_json = self._serialize_content(content)

        with self._lock:
            cursor = self._conn.cursor()

            # 메시지 삽입
            cursor.execute("""
                INSERT INTO messages (conversation_id, role, content_json, token_count, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (conversation_id, role, content_json, token_count, now))

            message_id = cursor.lastrowid

            # 대화 updated_at 갱신
            cursor.execute("""
                UPDATE conversations SET updated_at = ? WHERE id = ?
            """, (now, conversation_id))

            self._conn.commit()

        logger.debug(f"Added message to conversation {conversation_id}: role={role}, tokens={token_count}")

        return MessageRecord(
            id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            token_count=token_count,
            created_at=now
        )

    def _serialize_content(self, content: Any) -> str:
        """content를 JSON 문자열로 직렬화.

        Args:
            content: 직렬화할 내용 (str, list, dict, dataclass)

        Returns:
            JSON 문자열
        """
        if isinstance(content, str):
            return json.dumps(content, ensure_ascii=False)
        elif isinstance(content, (list, dict)):
            return json.dumps(content, ensure_ascii=False)
        elif hasattr(content, '__dataclass_fields__'):
            # dataclass 처리
            content_dict = dataclasses.asdict(content)
            return json.dumps(content_dict, ensure_ascii=False)
        else:
            # 기타 객체는 str로 변환
            return json.dumps(str(content), ensure_ascii=False)

    def get_messages(
        self,
        conversation_id: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> list[dict[str, Any]]:
        """대화의 메시지 조회 (Anthropic 형식).

        Args:
            conversation_id: 대화 ID
            limit: 최대 메시지 수 (None이면 전체)
            offset: 시작 오프셋

        Returns:
            Anthropic 형식의 메시지 리스트: [{"role": "user", "content": "..."}]
        """
        cursor = self._conn.cursor()

        query = """
            SELECT role, content_json
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
        """
        params = [conversation_id]

        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset > 0:
            query += " LIMIT -1 OFFSET ?"
            params.append(offset)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        messages = []
        for row in rows:
            content = json.loads(row['content_json'])
            messages.append({
                "role": row['role'],
                "content": content
            })

        return messages

    def list_conversations(
        self,
        interface: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None
    ) -> list[ConversationRecord]:
        """대화 목록 조회.

        Args:
            interface: 필터링할 인터페이스 (None이면 전체)
            limit: 최대 개수
            offset: 시작 오프셋
            user_id: 필터링할 사용자 ID (None이면 전체)

        Returns:
            ConversationRecord 리스트 (최신순)
        """
        cursor = self._conn.cursor()

        conditions = []
        params = []

        if interface:
            conditions.append("interface = ?")
            params.append(interface)

        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"""
            SELECT * FROM conversations
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()

        conversations = []
        for row in rows:
            metadata = json.loads(row['metadata_json']) if row['metadata_json'] else {}
            conversations.append(ConversationRecord(
                id=row['id'],
                interface=row['interface'],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                metadata=metadata
            ))

        return conversations

    def delete_conversation(self, conversation_id: str) -> bool:
        """대화 삭제 (CASCADE).

        Args:
            conversation_id: 대화 ID

        Returns:
            삭제 성공 여부
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            self._conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info(f"Deleted conversation: {conversation_id}")

        return deleted

    def get_conversation(self, conversation_id: str) -> Optional[ConversationRecord]:
        """대화 조회.

        Args:
            conversation_id: 대화 ID

        Returns:
            ConversationRecord 또는 None
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        row = cursor.fetchone()

        if not row:
            return None

        metadata = json.loads(row['metadata_json']) if row['metadata_json'] else {}
        return ConversationRecord(
            id=row['id'],
            interface=row['interface'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            metadata=metadata
        )

    def update_conversation_metadata(
        self,
        conversation_id: str,
        metadata: dict[str, Any]
    ) -> bool:
        """대화 메타데이터 업데이트.

        Args:
            conversation_id: 대화 ID
            metadata: 새 메타데이터

        Returns:
            업데이트 성공 여부
        """
        metadata_json = json.dumps(metadata, ensure_ascii=False)
        now = datetime.utcnow().isoformat()

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                UPDATE conversations
                SET metadata_json = ?, updated_at = ?
                WHERE id = ?
            """, (metadata_json, now, conversation_id))
            self._conn.commit()
            updated = cursor.rowcount > 0

        return updated

    def migrate_from_history_dir(self, history_dir: str = "history") -> int:
        """history/ 디렉토리의 JSON 파일을 SQLite로 마이그레이션.

        Args:
            history_dir: history 디렉토리 경로

        Returns:
            마이그레이션된 대화 수
        """
        history_path = Path(history_dir)

        # .migration_done 마커 확인
        marker_file = history_path / ".migration_done"
        if marker_file.exists():
            logger.info(f"Migration already completed (marker exists): {marker_file}")
            return 0

        if not history_path.exists() or not history_path.is_dir():
            logger.warning(f"History directory not found: {history_dir}")
            return 0

        migrated_count = 0

        for json_file in history_path.glob("*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 필드 검증
                if 'timestamp' not in data or 'messages' not in data:
                    logger.warning(f"Skipping invalid file (missing fields): {json_file}")
                    continue

                messages = data['messages']
                if not isinstance(messages, list):
                    logger.warning(f"Skipping invalid file (messages not list): {json_file}")
                    continue

                # 대화 생성
                timestamp_str = data['timestamp']
                metadata = {
                    'source': 'history_migration',
                    'original_file': json_file.name,
                    'original_timestamp': timestamp_str
                }

                conversation = self.create_conversation(interface="cli", metadata=metadata)

                # 메시지 추가
                for msg in messages:
                    if 'role' not in msg or 'content' not in msg:
                        logger.warning(f"Skipping invalid message in {json_file}: {msg}")
                        continue

                    self.add_message(
                        conversation_id=conversation.id,
                        role=msg['role'],
                        content=msg['content'],
                        token_count=msg.get('token_count', 0)
                    )

                migrated_count += 1
                logger.info(f"Migrated conversation from {json_file.name}: {conversation.id}")

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON file {json_file}: {e}")
                continue
            except Exception as e:
                logger.warning(f"Failed to migrate file {json_file}: {e}")
                continue

        # 마이그레이션 완료 마커 생성
        if migrated_count > 0:
            marker_file.write_text(f"Migrated {migrated_count} conversations\n")
            logger.info(f"Migration completed: {migrated_count} conversations")

        return migrated_count

    def get_stats(self) -> dict[str, Any]:
        """통계 반환.

        Returns:
            통계 딕셔너리
        """
        cursor = self._conn.cursor()

        # 대화 수
        cursor.execute("SELECT COUNT(*) as count FROM conversations")
        total_conversations = cursor.fetchone()['count']

        # 메시지 수
        cursor.execute("SELECT COUNT(*) as count FROM messages")
        total_messages = cursor.fetchone()['count']

        # 인터페이스별 대화 수
        cursor.execute("""
            SELECT interface, COUNT(*) as count
            FROM conversations
            GROUP BY interface
        """)
        by_interface = {row['interface']: row['count'] for row in cursor.fetchall()}

        # 총 토큰 수
        cursor.execute("SELECT SUM(token_count) as total FROM messages")
        total_tokens = cursor.fetchone()['total'] or 0

        return {
            'total_conversations': total_conversations,
            'total_messages': total_messages,
            'total_tokens': total_tokens,
            'conversations_by_interface': by_interface,
            'db_path': self.db_path
        }

    def close(self):
        """커넥션 종료."""
        with self._lock:
            self._conn.close()
        logger.info("ConversationStore closed")
