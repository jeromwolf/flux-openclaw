"""ConversationStore 테스트 스위트."""
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conversation_store import ConversationRecord, ConversationStore, MessageRecord


@pytest.fixture
def temp_db():
    """임시 DB 경로 생성."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    yield db_path
    # cleanup - WAL 파일들도 정리
    import shutil
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


@pytest.fixture
def store(temp_db):
    """ConversationStore fixture."""
    store = ConversationStore(db_path=temp_db)
    yield store
    store.close()


# =============================================================================
# 초기화 테스트
# =============================================================================


def test_creates_db_directory():
    """디렉토리가 자동 생성되는지 확인."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "subdir", "db.db")

    assert not os.path.exists(os.path.dirname(db_path))

    store = ConversationStore(db_path=db_path)
    assert os.path.exists(os.path.dirname(db_path))
    assert os.path.exists(db_path)

    store.close()


def test_wal_mode_enabled(store):
    """WAL 모드가 활성화되는지 확인."""
    cursor = store._conn.cursor()
    cursor.execute("PRAGMA journal_mode")
    result = cursor.fetchone()
    assert result[0].lower() == "wal"


# =============================================================================
# create_conversation 테스트
# =============================================================================


def test_create_conversation_default(store):
    """기본값으로 대화 생성."""
    conv = store.create_conversation()

    assert conv.id
    assert conv.interface == "cli"
    assert conv.created_at
    assert conv.updated_at
    assert conv.metadata == {}


def test_create_conversation_with_interface(store):
    """인터페이스 지정하여 대화 생성."""
    conv = store.create_conversation(interface="web")
    assert conv.interface == "web"


def test_create_conversation_with_metadata(store):
    """메타데이터 포함하여 대화 생성."""
    metadata = {"user_id": "123", "session_id": "abc"}
    conv = store.create_conversation(metadata=metadata)

    assert conv.metadata == metadata


def test_create_conversation_uuid_format(store):
    """생성된 ID가 UUID 형식인지 확인."""
    conv = store.create_conversation()

    try:
        uuid.UUID(conv.id)
        is_valid = True
    except ValueError:
        is_valid = False

    assert is_valid


# =============================================================================
# add_message / get_messages 테스트
# =============================================================================


def test_add_and_get_messages(store):
    """메시지 추가 및 조회."""
    conv = store.create_conversation()

    msg1 = store.add_message(conv.id, "user", "Hello")
    msg2 = store.add_message(conv.id, "assistant", "Hi there")

    assert msg1.id
    assert msg1.role == "user"
    assert msg1.content == "Hello"

    messages = store.get_messages(conv.id)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Hi there"


def test_message_content_str(store):
    """문자열 content 저장 및 조회."""
    conv = store.create_conversation()
    store.add_message(conv.id, "user", "test message")

    messages = store.get_messages(conv.id)
    assert messages[0]["content"] == "test message"


def test_message_content_dict_list(store):
    """dict/list content 저장 및 조회."""
    conv = store.create_conversation()

    # dict
    dict_content = {"type": "tool_use", "name": "search"}
    store.add_message(conv.id, "assistant", dict_content)

    # list
    list_content = [{"type": "text", "text": "Hello"}]
    store.add_message(conv.id, "user", list_content)

    messages = store.get_messages(conv.id)
    assert messages[0]["content"] == dict_content
    assert messages[1]["content"] == list_content


def test_get_messages_limit(store):
    """limit 파라미터 동작."""
    conv = store.create_conversation()

    for i in range(5):
        store.add_message(conv.id, "user", f"message {i}")

    messages = store.get_messages(conv.id, limit=3)
    assert len(messages) == 3
    assert messages[0]["content"] == "message 0"


def test_get_messages_offset(store):
    """offset 파라미터 동작."""
    conv = store.create_conversation()

    for i in range(5):
        store.add_message(conv.id, "user", f"message {i}")

    messages = store.get_messages(conv.id, offset=2)
    assert len(messages) == 3
    assert messages[0]["content"] == "message 2"


def test_get_messages_empty_conversation(store):
    """메시지가 없는 대화 조회."""
    conv = store.create_conversation()
    messages = store.get_messages(conv.id)
    assert messages == []


# =============================================================================
# list_conversations 테스트
# =============================================================================


def test_list_conversations_all(store):
    """전체 대화 목록 조회."""
    conv1 = store.create_conversation(interface="cli")
    conv2 = store.create_conversation(interface="web")

    conversations = store.list_conversations()
    assert len(conversations) == 2

    # 최신순 정렬 확인 (conv2가 먼저)
    assert conversations[0].id == conv2.id
    assert conversations[1].id == conv1.id


def test_list_conversations_filter_interface(store):
    """인터페이스 필터링."""
    conv1 = store.create_conversation(interface="cli")
    conv2 = store.create_conversation(interface="web")
    conv3 = store.create_conversation(interface="cli")

    cli_conversations = store.list_conversations(interface="cli")
    assert len(cli_conversations) == 2
    assert all(c.interface == "cli" for c in cli_conversations)


def test_list_conversations_ordered_by_updated(store):
    """updated_at 기준 정렬 확인."""
    conv1 = store.create_conversation()
    conv2 = store.create_conversation()

    # conv1에 메시지 추가 (updated_at 갱신)
    store.add_message(conv1.id, "user", "update conv1")

    conversations = store.list_conversations()
    # conv1이 더 최근에 업데이트되었으므로 먼저 나와야 함
    assert conversations[0].id == conv1.id
    assert conversations[1].id == conv2.id


# =============================================================================
# delete_conversation 테스트
# =============================================================================


def test_delete_conversation_cascades(store):
    """대화 삭제 시 메시지도 CASCADE 삭제."""
    conv = store.create_conversation()
    store.add_message(conv.id, "user", "test message")

    # 삭제 전 메시지 확인
    messages_before = store.get_messages(conv.id)
    assert len(messages_before) == 1

    # 삭제
    deleted = store.delete_conversation(conv.id)
    assert deleted is True

    # 대화 조회 불가
    assert store.get_conversation(conv.id) is None

    # 메시지도 삭제됨
    messages_after = store.get_messages(conv.id)
    assert len(messages_after) == 0


def test_delete_nonexistent_returns_false(store):
    """존재하지 않는 대화 삭제 시 False 반환."""
    deleted = store.delete_conversation("nonexistent-id")
    assert deleted is False


# =============================================================================
# get_stats 테스트
# =============================================================================


def test_stats_empty(store):
    """빈 DB의 통계."""
    stats = store.get_stats()

    assert stats["total_conversations"] == 0
    assert stats["total_messages"] == 0
    assert stats["total_tokens"] == 0
    assert stats["conversations_by_interface"] == {}


def test_stats_with_data(store):
    """데이터가 있는 DB의 통계."""
    conv1 = store.create_conversation(interface="cli")
    conv2 = store.create_conversation(interface="web")

    store.add_message(conv1.id, "user", "hello", token_count=10)
    store.add_message(conv1.id, "assistant", "hi", token_count=5)
    store.add_message(conv2.id, "user", "test", token_count=8)

    stats = store.get_stats()

    assert stats["total_conversations"] == 2
    assert stats["total_messages"] == 3
    assert stats["total_tokens"] == 23
    assert stats["conversations_by_interface"] == {"cli": 1, "web": 1}


# =============================================================================
# migrate_from_history_dir 테스트
# =============================================================================


def test_migrate_from_json_files(store, tmp_path):
    """JSON 파일 마이그레이션."""
    history_dir = tmp_path / "history"
    history_dir.mkdir()

    # JSON 파일 생성
    json_data = {
        "timestamp": "2024-01-01T00:00:00",
        "messages": [
            {"role": "user", "content": "hello", "token_count": 5},
            {"role": "assistant", "content": "hi", "token_count": 3}
        ]
    }

    json_file = history_dir / "conv1.json"
    json_file.write_text(json.dumps(json_data, ensure_ascii=False))

    # 마이그레이션 실행
    migrated_count = store.migrate_from_history_dir(str(history_dir))

    assert migrated_count == 1

    # 마이그레이션된 대화 확인
    conversations = store.list_conversations()
    assert len(conversations) == 1

    conv = conversations[0]
    assert conv.interface == "cli"
    assert conv.metadata["source"] == "history_migration"

    # 메시지 확인
    messages = store.get_messages(conv.id)
    assert len(messages) == 2
    assert messages[0]["content"] == "hello"
    assert messages[1]["content"] == "hi"


def test_migrate_skips_if_done_marker_exists(store, tmp_path):
    """마이그레이션 완료 마커가 있으면 스킵."""
    history_dir = tmp_path / "history"
    history_dir.mkdir()

    # 완료 마커 생성
    marker_file = history_dir / ".migration_done"
    marker_file.write_text("done")

    # JSON 파일도 생성
    json_data = {
        "timestamp": "2024-01-01T00:00:00",
        "messages": [{"role": "user", "content": "test"}]
    }
    (history_dir / "conv1.json").write_text(json.dumps(json_data))

    # 마이그레이션 실행
    migrated_count = store.migrate_from_history_dir(str(history_dir))

    assert migrated_count == 0  # 스킵됨

    # 대화가 생성되지 않았는지 확인
    conversations = store.list_conversations()
    assert len(conversations) == 0


def test_migrate_empty_dir(store, tmp_path):
    """빈 디렉토리 마이그레이션."""
    history_dir = tmp_path / "history"
    history_dir.mkdir()

    migrated_count = store.migrate_from_history_dir(str(history_dir))
    assert migrated_count == 0


# =============================================================================
# 기타 테스트
# =============================================================================


def test_get_conversation(store):
    """특정 대화 조회."""
    conv = store.create_conversation(metadata={"test": "value"})

    retrieved = store.get_conversation(conv.id)
    assert retrieved is not None
    assert retrieved.id == conv.id
    assert retrieved.metadata == {"test": "value"}


def test_get_conversation_nonexistent(store):
    """존재하지 않는 대화 조회."""
    retrieved = store.get_conversation("nonexistent-id")
    assert retrieved is None


def test_update_conversation_metadata(store):
    """메타데이터 업데이트."""
    conv = store.create_conversation(metadata={"old": "value"})

    new_metadata = {"new": "data", "key": 123}
    updated = store.update_conversation_metadata(conv.id, new_metadata)
    assert updated is True

    retrieved = store.get_conversation(conv.id)
    assert retrieved.metadata == new_metadata


def test_update_conversation_metadata_nonexistent(store):
    """존재하지 않는 대화 메타데이터 업데이트."""
    updated = store.update_conversation_metadata("nonexistent-id", {"test": "data"})
    assert updated is False
