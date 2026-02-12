"""flux-openclaw 대화 검색 + 태그 관리 모듈

SQLite FTS5 전문 검색 (미지원 시 LIKE 폴백).
"""
from __future__ import annotations

import json
import sqlite3
import threading
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
class SearchResult:
    """검색 결과 레코드."""
    conversation_id: str
    message_id: int
    role: str
    snippet: str      # highlighted text or plain text
    rank: float       # BM25 score (0.0 for LIKE fallback)
    created_at: str


class ConversationSearch:
    """FTS5 full-text search on conversation messages."""

    def __init__(self, db_path: str = "data/conversations.db"):
        """초기화.

        Args:
            db_path: 기존 데이터베이스 파일 경로 (ConversationStore와 공유)
        """
        self.db_path = db_path
        self._lock = threading.Lock()

        # 기존 데이터베이스 열기
        db_file = Path(db_path)
        if not db_file.exists():
            logger.warning(f"Database file not found: {db_path}. FTS setup will be deferred.")

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # SQLite 설정
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")

        # FTS5 가용성 확인
        self._fts5_available = self._check_fts5_available()

        # FTS 스키마 초기화 시도
        if self._fts5_available:
            self.ensure_fts_schema()
        else:
            logger.warning("FTS5 not available. Falling back to LIKE-based search.")

        logger.info(f"ConversationSearch initialized: {db_path} (FTS5={self._fts5_available})")

    def _check_fts5_available(self) -> bool:
        """FTS5 지원 여부 확인.

        Returns:
            True if FTS5 available, False otherwise
        """
        try:
            with self._lock:
                cursor = self._conn.cursor()
                cursor.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_check USING fts5(test)")
                cursor.execute("DROP TABLE IF EXISTS _fts5_check")
                self._conn.commit()
            return True
        except sqlite3.OperationalError as e:
            logger.debug(f"FTS5 check failed: {e}")
            return False

    def ensure_fts_schema(self):
        """FTS 스키마 및 트리거 생성 (FTS5 사용 가능할 때만)."""
        if not self._fts5_available:
            return

        with self._lock:
            cursor = self._conn.cursor()

            # FTS5 가상 테이블 생성
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content,
                    content=messages,
                    content_rowid=id
                )
            """)

            # INSERT 트리거
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages
                BEGIN
                    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content_json);
                END
            """)

            # DELETE 트리거
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages
                BEGIN
                    DELETE FROM messages_fts WHERE rowid = old.id;
                END
            """)

            # UPDATE 트리거
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages
                BEGIN
                    DELETE FROM messages_fts WHERE rowid = old.id;
                    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content_json);
                END
            """)

            self._conn.commit()

        logger.info("FTS5 schema and triggers created/verified")

    def rebuild_fts_index(self) -> int:
        """FTS 인덱스 재구축.

        Returns:
            인덱싱된 메시지 수
        """
        if not self._fts5_available:
            logger.warning("Cannot rebuild FTS index: FTS5 not available")
            return 0

        with self._lock:
            cursor = self._conn.cursor()

            # 기존 FTS 데이터 삭제
            cursor.execute("DELETE FROM messages_fts")

            # 전체 메시지 재인덱싱
            cursor.execute("""
                INSERT INTO messages_fts(rowid, content)
                SELECT id, content_json FROM messages
            """)

            count = cursor.rowcount
            self._conn.commit()

        logger.info(f"FTS index rebuilt: {count} messages indexed")
        return count

    def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 20
    ) -> list[SearchResult]:
        """대화 메시지 검색.

        Args:
            query: 검색 쿼리 문자열
            user_id: 사용자 ID 필터
            date_from: 시작 날짜 (ISO 형식)
            date_to: 종료 날짜 (ISO 형식)
            limit: 최대 결과 수

        Returns:
            SearchResult 리스트 (랭킹 순)
        """
        if not query or not query.strip():
            return []

        if self._fts5_available:
            return self._search_fts5(query, user_id, date_from, date_to, limit)
        else:
            return self._search_like(query, user_id, date_from, date_to, limit)

    def _search_fts5(
        self,
        query: str,
        user_id: Optional[str],
        date_from: Optional[str],
        date_to: Optional[str],
        limit: int
    ) -> list[SearchResult]:
        """FTS5 기반 검색."""
        cursor = self._conn.cursor()

        # BM25 랭킹과 함께 검색
        sql = """
            SELECT
                m.conversation_id,
                m.id as message_id,
                m.role,
                m.content_json,
                m.created_at,
                bm25(messages_fts) as rank
            FROM messages_fts
            INNER JOIN messages m ON messages_fts.rowid = m.id
            INNER JOIN conversations c ON m.conversation_id = c.id
            WHERE messages_fts MATCH ?
        """
        params = [query]

        # 날짜 필터
        if date_from:
            sql += " AND m.created_at >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND m.created_at <= ?"
            params.append(date_to)

        # user_id 필터
        if user_id:
            sql += " AND c.user_id = ?"
            params.append(user_id)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            content_json = row['content_json']
            try:
                content = json.loads(content_json)
                snippet = self._extract_snippet(content, query)
            except json.JSONDecodeError:
                snippet = content_json[:200]

            results.append(SearchResult(
                conversation_id=row['conversation_id'],
                message_id=row['message_id'],
                role=row['role'],
                snippet=snippet,
                rank=abs(row['rank']),  # BM25는 음수 점수, 절댓값 사용
                created_at=row['created_at']
            ))

        return results

    def _search_like(
        self,
        query: str,
        user_id: Optional[str],
        date_from: Optional[str],
        date_to: Optional[str],
        limit: int
    ) -> list[SearchResult]:
        """LIKE 기반 폴백 검색."""
        cursor = self._conn.cursor()

        sql = """
            SELECT
                m.conversation_id,
                m.id as message_id,
                m.role,
                m.content_json,
                m.created_at
            FROM messages m
            INNER JOIN conversations c ON m.conversation_id = c.id
            WHERE m.content_json LIKE ?
        """
        params = [f"%{query}%"]

        # 날짜 필터
        if date_from:
            sql += " AND m.created_at >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND m.created_at <= ?"
            params.append(date_to)

        # user_id 필터
        if user_id:
            sql += " AND c.user_id = ?"
            params.append(user_id)

        sql += " ORDER BY m.created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            content_json = row['content_json']
            try:
                content = json.loads(content_json)
                snippet = self._extract_snippet(content, query)
            except json.JSONDecodeError:
                snippet = content_json[:200]

            results.append(SearchResult(
                conversation_id=row['conversation_id'],
                message_id=row['message_id'],
                role=row['role'],
                snippet=snippet,
                rank=0.0,  # LIKE는 랭킹 없음
                created_at=row['created_at']
            ))

        return results

    def _extract_snippet(self, content: any, query: str, context_len: int = 100) -> str:
        """검색어 주변 스니펫 추출.

        Args:
            content: 메시지 content (str, list, dict)
            query: 검색 쿼리
            context_len: 스니펫 길이

        Returns:
            스니펫 문자열
        """
        # content를 문자열로 변환
        if isinstance(content, str):
            text = content
        elif isinstance(content, (list, dict)):
            text = json.dumps(content, ensure_ascii=False)
        else:
            text = str(content)

        # 검색어 위치 찾기 (대소문자 무시)
        lower_text = text.lower()
        lower_query = query.lower()

        pos = lower_text.find(lower_query)
        if pos == -1:
            # 검색어 없으면 앞부분 반환
            return text[:context_len * 2]

        # 검색어 주변 컨텍스트 추출
        start = max(0, pos - context_len)
        end = min(len(text), pos + len(query) + context_len)

        snippet = text[start:end]

        # 앞뒤 ... 추가
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."

        return snippet

    def close(self):
        """커넥션 종료."""
        with self._lock:
            self._conn.close()
        logger.info("ConversationSearch closed")


class TagManager:
    """Conversation tag CRUD."""

    def __init__(self, db_path: str = "data/conversations.db"):
        """초기화.

        Args:
            db_path: 기존 데이터베이스 파일 경로 (ConversationStore와 공유)
        """
        self.db_path = db_path
        self._lock = threading.Lock()

        # 기존 데이터베이스 열기
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # SQLite 설정
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")

        # 태그 스키마 초기화
        self.ensure_tag_schema()

        logger.info(f"TagManager initialized: {db_path}")

    def ensure_tag_schema(self):
        """태그 테이블 및 인덱스 생성."""
        with self._lock:
            cursor = self._conn.cursor()

            # conversation_tags 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                    UNIQUE(conversation_id, tag)
                )
            """)

            # 인덱스
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tags_tag
                ON conversation_tags(tag)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tags_conversation
                ON conversation_tags(conversation_id)
            """)

            self._conn.commit()

        logger.info("Tag schema created/verified")

    def add_tag(self, conversation_id: str, tag: str) -> bool:
        """대화에 태그 추가.

        Args:
            conversation_id: 대화 ID
            tag: 태그 이름

        Returns:
            True if tag added (새 태그), False if already exists
        """
        tag = tag.strip().lower()
        if not tag:
            return False

        now = datetime.utcnow().isoformat()

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO conversation_tags (conversation_id, tag, created_at)
                    VALUES (?, ?, ?)
                """, (conversation_id, tag, now))
                self._conn.commit()
                logger.info(f"Added tag '{tag}' to conversation {conversation_id}")
                return True
            except sqlite3.IntegrityError:
                # 이미 존재하는 태그
                logger.debug(f"Tag '{tag}' already exists on conversation {conversation_id}")
                return False

    def remove_tag(self, conversation_id: str, tag: str) -> bool:
        """대화에서 태그 제거.

        Args:
            conversation_id: 대화 ID
            tag: 태그 이름

        Returns:
            True if tag removed, False if not found
        """
        tag = tag.strip().lower()

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                DELETE FROM conversation_tags
                WHERE conversation_id = ? AND tag = ?
            """, (conversation_id, tag))
            self._conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info(f"Removed tag '{tag}' from conversation {conversation_id}")

        return deleted

    def get_tags(self, conversation_id: str) -> list[str]:
        """대화의 태그 조회.

        Args:
            conversation_id: 대화 ID

        Returns:
            태그 리스트 (알파벳 순)
        """
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT tag FROM conversation_tags
            WHERE conversation_id = ?
            ORDER BY tag ASC
        """, (conversation_id,))

        rows = cursor.fetchall()
        return [row['tag'] for row in rows]

    def list_all_tags(self) -> list[dict]:
        """모든 태그와 사용 횟수 조회.

        Returns:
            [{"tag": "name", "count": N}, ...] (사용 횟수 내림차순)
        """
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT tag, COUNT(*) as count
            FROM conversation_tags
            GROUP BY tag
            ORDER BY count DESC, tag ASC
        """)

        rows = cursor.fetchall()
        return [{"tag": row['tag'], "count": row['count']} for row in rows]

    def find_by_tag(self, tag: str, limit: int = 50) -> list[str]:
        """특정 태그를 가진 대화 ID 조회.

        Args:
            tag: 태그 이름
            limit: 최대 개수

        Returns:
            conversation_id 리스트 (최신순)
        """
        tag = tag.strip().lower()

        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT ct.conversation_id
            FROM conversation_tags ct
            INNER JOIN conversations c ON ct.conversation_id = c.id
            WHERE ct.tag = ?
            ORDER BY c.updated_at DESC
            LIMIT ?
        """, (tag, limit))

        rows = cursor.fetchall()
        return [row['conversation_id'] for row in rows]

    def close(self):
        """커넥션 종료."""
        with self._lock:
            self._conn.close()
        logger.info("TagManager closed")
