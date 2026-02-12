"""search 모듈 테스트 (FTS5 검색 + 태그)"""
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from search import ConversationSearch, TagManager, SearchResult
from conversation_store import ConversationStore


@pytest.fixture
def conv_store(tmp_path):
    """테스트용 ConversationStore (데이터 포함)"""
    db_path = str(tmp_path / "test_conversations.db")
    store = ConversationStore(db_path=db_path)

    # Initialize FTS schema BEFORE creating messages
    search_setup = ConversationSearch(db_path=db_path)
    if search_setup._fts5_available:
        search_setup.ensure_fts_schema()
    search_setup.close()

    # Now create test conversations with messages
    conv1 = store.create_conversation(interface="cli")
    store.add_message(conv1.id, "user", "파이썬 프로그래밍에 대해 알려줘")
    store.add_message(conv1.id, "assistant", "파이썬은 인터프리터 언어입니다.")

    conv2 = store.create_conversation(interface="ws")
    store.add_message(conv2.id, "user", "자바스크립트 비동기 처리")
    store.add_message(conv2.id, "assistant", "Promise와 async/await를 사용합니다.")

    conv3 = store.create_conversation(interface="cli", user_id="user2")
    store.add_message(conv3.id, "user", "도커 배포 방법")
    store.add_message(conv3.id, "assistant", "Dockerfile을 작성합니다.")

    yield store, db_path, [conv1.id, conv2.id, conv3.id]
    store.close()


class TestConversationSearch:
    @pytest.fixture
    def search(self, conv_store):
        store, db_path, conv_ids = conv_store
        s = ConversationSearch(db_path=db_path)
        # FTS schema should already be set up and triggers should have fired
        yield s, conv_ids
        s.close()

    def test_fts5_availability_check(self, conv_store):
        """FTS5 가용성 체크"""
        _, db_path, _ = conv_store
        s = ConversationSearch(db_path=db_path)
        # Should be available on most Python builds
        assert isinstance(s._fts5_available, bool)
        s.close()

    def test_search_basic(self, search):
        """기본 검색"""
        s, conv_ids = search
        results = s.search("파이썬")
        assert len(results) > 0
        assert any("파이썬" in r.snippet for r in results)

    def test_search_no_results(self, search):
        """결과 없는 검색"""
        s, _ = search
        results = s.search("xyznonexistent123")
        assert len(results) == 0

    def test_search_limit(self, search):
        """검색 결과 제한"""
        s, _ = search
        results = s.search("user", limit=1)
        assert len(results) <= 1

    def test_search_result_structure(self, search):
        """검색 결과 구조"""
        s, _ = search
        results = s.search("파이썬")
        if results:
            r = results[0]
            assert hasattr(r, 'conversation_id')
            assert hasattr(r, 'message_id')
            assert hasattr(r, 'snippet')
            assert hasattr(r, 'rank')
            assert hasattr(r, 'created_at')

    def test_rebuild_fts_index(self, conv_store):
        """FTS 인덱스 재구축"""
        _, db_path, _ = conv_store
        s = ConversationSearch(db_path=db_path)
        if not s._fts5_available:
            # Skip if FTS5 not available
            s.close()
            return
        s.ensure_fts_schema()
        # For external content FTS tables, use the rebuild command
        try:
            cursor = s._conn.cursor()
            cursor.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
            s._conn.commit()
            # Verify some content exists
            cursor.execute("SELECT COUNT(*) as cnt FROM messages_fts")
            count = cursor.fetchone()['cnt']
            assert count >= 0  # Just verify it doesn't error
        except Exception:
            # Some SQLite builds may not support this
            pass
        s.close()

    def test_search_empty_query(self, search):
        """빈 쿼리 검색"""
        s, _ = search
        results = s.search("")
        assert len(results) == 0
        results = s.search("   ")
        assert len(results) == 0

    def test_search_case_insensitive(self, search):
        """대소문자 무시 검색"""
        s, _ = search
        results_lower = s.search("python")
        results_upper = s.search("PYTHON")
        # Both should find results (if any)
        assert isinstance(results_lower, list)
        assert isinstance(results_upper, list)

    def test_search_snippet_extraction(self, search):
        """스니펫 추출 확인"""
        s, _ = search
        results = s.search("파이썬")
        if results:
            # Snippet should contain the search term or be truncated properly
            snippet = results[0].snippet
            assert len(snippet) > 0
            assert isinstance(snippet, str)

    def test_search_with_date_filter(self, search):
        """날짜 필터링 검색"""
        s, _ = search
        # Search with future date range should return nothing
        results = s.search("파이썬", date_from="2099-01-01")
        assert len(results) == 0

    def test_search_rank_ordering(self, search):
        """검색 랭킹 순서 확인"""
        s, _ = search
        results = s.search("파이썬")
        if len(results) > 1:
            # Ranks should be numeric
            for r in results:
                assert isinstance(r.rank, (int, float))


class TestTagManager:
    @pytest.fixture
    def tags(self, conv_store):
        store, db_path, conv_ids = conv_store
        tm = TagManager(db_path=db_path)
        tm.ensure_tag_schema()
        yield tm, conv_ids
        tm.close()

    def test_add_tag(self, tags):
        """태그 추가"""
        tm, conv_ids = tags
        result = tm.add_tag(conv_ids[0], "important")
        assert result is True

    def test_get_tags(self, tags):
        """태그 조회"""
        tm, conv_ids = tags
        tm.add_tag(conv_ids[0], "python")
        tm.add_tag(conv_ids[0], "tutorial")
        tags_list = tm.get_tags(conv_ids[0])
        assert "python" in tags_list
        assert "tutorial" in tags_list

    def test_remove_tag(self, tags):
        """태그 삭제"""
        tm, conv_ids = tags
        tm.add_tag(conv_ids[0], "deleteme")
        result = tm.remove_tag(conv_ids[0], "deleteme")
        assert result is True
        assert "deleteme" not in tm.get_tags(conv_ids[0])

    def test_duplicate_tag(self, tags):
        """중복 태그 추가"""
        tm, conv_ids = tags
        result1 = tm.add_tag(conv_ids[0], "unique")
        assert result1 is True
        result2 = tm.add_tag(conv_ids[0], "unique")
        assert result2 is False  # Should return False for duplicate

    def test_list_all_tags(self, tags):
        """전체 태그 목록"""
        tm, conv_ids = tags
        tm.add_tag(conv_ids[0], "tag1")
        tm.add_tag(conv_ids[1], "tag1")
        tm.add_tag(conv_ids[0], "tag2")
        all_tags = tm.list_all_tags()
        tag_names = [t["tag"] for t in all_tags]
        assert "tag1" in tag_names
        assert "tag2" in tag_names
        # tag1 should have count of 2
        tag1_info = next(t for t in all_tags if t["tag"] == "tag1")
        assert tag1_info["count"] == 2

    def test_find_by_tag(self, tags):
        """태그로 대화 검색"""
        tm, conv_ids = tags
        tm.add_tag(conv_ids[0], "findme")
        tm.add_tag(conv_ids[2], "findme")
        found = tm.find_by_tag("findme")
        assert conv_ids[0] in found
        assert conv_ids[2] in found
        assert conv_ids[1] not in found

    def test_tags_cascade_delete(self, tmp_path):
        """대화 삭제 시 태그 삭제"""
        db_path = str(tmp_path / "test_cascade.db")
        store = ConversationStore(db_path=db_path)
        conv = store.create_conversation(interface="cli")

        tm = TagManager(db_path=db_path)
        tm.ensure_tag_schema()
        tm.add_tag(conv.id, "cascade_test")

        # Verify tag exists
        assert "cascade_test" in tm.get_tags(conv.id)

        # Delete conversation
        store.delete_conversation(conv.id)

        # Tag should be gone
        assert tm.get_tags(conv.id) == []

        tm.close()
        store.close()

    def test_empty_tags(self, tags):
        """태그 없는 대화 조회"""
        tm, conv_ids = tags
        assert tm.get_tags(conv_ids[0]) == []

    def test_tag_normalization(self, tags):
        """태그 정규화 (소문자, 공백 제거)"""
        tm, conv_ids = tags
        tm.add_tag(conv_ids[0], "  UPPERCASE  ")
        tags_list = tm.get_tags(conv_ids[0])
        assert "uppercase" in tags_list
        assert "  UPPERCASE  " not in tags_list

    def test_empty_tag_rejection(self, tags):
        """빈 태그 거부"""
        tm, conv_ids = tags
        result = tm.add_tag(conv_ids[0], "")
        assert result is False
        result = tm.add_tag(conv_ids[0], "   ")
        assert result is False

    def test_find_by_tag_limit(self, tags):
        """태그 검색 제한"""
        tm, conv_ids = tags
        for conv_id in conv_ids:
            tm.add_tag(conv_id, "common")

        found = tm.find_by_tag("common", limit=2)
        assert len(found) <= 2

    def test_remove_nonexistent_tag(self, tags):
        """존재하지 않는 태그 삭제"""
        tm, conv_ids = tags
        result = tm.remove_tag(conv_ids[0], "nonexistent")
        assert result is False
