"""
memory_store.py 테스트
"""
import pytest
import os
import json
import sys
from datetime import datetime, timedelta

# memory_store.py를 임포트하기 위해 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory_store import MemoryStore


# ============================================================
# Fixture
# ============================================================

@pytest.fixture
def memory_store(tmp_path):
    """임시 디렉토리를 사용하는 MemoryStore 인스턴스"""
    memory_file = tmp_path / "test_memories.json"
    return MemoryStore(memory_file=str(memory_file))


# ============================================================
# CRUD 테스트
# ============================================================

def test_add_memory(memory_store):
    """메모리 추가 및 필드 확인"""
    entry = memory_store.add(
        category="user_info",
        key="이름",
        value="켈리",
        importance=5,
        source="test"
    )

    assert entry["id"] is not None
    assert entry["category"] == "user_info"
    assert entry["key"] == "이름"
    assert entry["value"] == "켈리"
    assert entry["importance"] == 5
    assert entry["source"] == "test"
    assert "created_at" in entry
    assert "updated_at" in entry


def test_add_upsert(memory_store):
    """동일 category+key 추가 시 업데이트"""
    memory_store.add("preferences", "언어", "Python", importance=3)
    entry = memory_store.add("preferences", "언어", "TypeScript", importance=4)

    # 동일 key이므로 업데이트됨
    assert entry["value"] == "TypeScript"
    assert entry["importance"] == 4

    # 전체 항목 수는 1개
    memories = memory_store._load()
    assert len(memories) == 1


def test_get_memory(memory_store):
    """ID로 조회"""
    entry = memory_store.add("facts", "프로젝트", "flux-openclaw")
    memory_id = entry["id"]

    result = memory_store.get(memory_id)
    assert result is not None
    assert result["id"] == memory_id
    assert result["key"] == "프로젝트"
    assert result["value"] == "flux-openclaw"


def test_get_nonexistent(memory_store):
    """없는 ID 조회 시 None"""
    result = memory_store.get("nonexistent-id")
    assert result is None


def test_update_memory(memory_store):
    """부분 업데이트"""
    entry = memory_store.add("notes", "메모1", "내용1", importance=3)
    memory_id = entry["id"]

    updated = memory_store.update(memory_id, value="내용2", importance=5)
    assert updated is not None
    assert updated["value"] == "내용2"
    assert updated["importance"] == 5
    assert updated["key"] == "메모1"  # 변경 안 함


def test_update_invalid_category(memory_store):
    """잘못된 카테고리 업데이트 시 ValueError"""
    entry = memory_store.add("notes", "메모", "내용")
    memory_id = entry["id"]

    with pytest.raises(ValueError, match="유효하지 않은 카테고리"):
        memory_store.update(memory_id, category="invalid_category")


def test_delete_memory(memory_store):
    """삭제 성공"""
    entry = memory_store.add("notes", "삭제될 메모", "내용")
    memory_id = entry["id"]

    assert memory_store.delete(memory_id) is True

    # 조회 시 None
    assert memory_store.get(memory_id) is None


def test_delete_nonexistent(memory_store):
    """없는 ID 삭제 시 False"""
    assert memory_store.delete("nonexistent-id") is False


# ============================================================
# 검색 테스트
# ============================================================

def test_search_by_key(memory_store):
    """key에서 검색"""
    memory_store.add("notes", "Python 메모", "내용1")
    memory_store.add("notes", "Java 메모", "내용2")
    memory_store.add("notes", "Python 튜토리얼", "내용3")

    results = memory_store.search("python")
    assert len(results) == 2
    assert all("Python" in r["key"] or "python" in r["key"] for r in results)


def test_search_by_value(memory_store):
    """value에서 검색"""
    memory_store.add("notes", "메모1", "Python은 좋은 언어")
    memory_store.add("notes", "메모2", "Java도 좋은 언어")
    memory_store.add("notes", "메모3", "Python 튜토리얼")

    results = memory_store.search("python")
    assert len(results) == 2


def test_search_with_category_filter(memory_store):
    """카테고리 필터 검색"""
    memory_store.add("user_info", "이름", "켈리")
    memory_store.add("preferences", "언어", "Python")
    memory_store.add("facts", "좋아하는 언어", "Python")

    results = memory_store.search("python", category="preferences")
    assert len(results) == 1
    assert results[0]["category"] == "preferences"


def test_search_no_results(memory_store):
    """결과 없을 때 빈 리스트"""
    memory_store.add("notes", "메모", "내용")
    results = memory_store.search("존재하지않는검색어")
    assert results == []


def test_get_by_category(memory_store):
    """카테고리별 조회"""
    memory_store.add("user_info", "이름", "켈리")
    memory_store.add("user_info", "나이", "30")
    memory_store.add("preferences", "언어", "Python")

    results = memory_store.get_by_category("user_info")
    assert len(results) == 2
    assert all(r["category"] == "user_info" for r in results)


def test_get_by_key(memory_store):
    """키별 조회 (정확 매칭)"""
    memory_store.add("notes", "메모1", "내용1")
    memory_store.add("notes", "메모2", "내용2")
    memory_store.add("notes", "메모1", "내용3")  # 중복 키 (upsert)

    results = memory_store.get_by_key("메모1")
    assert len(results) == 1
    assert results[0]["key"] == "메모1"
    assert results[0]["value"] == "내용3"


# ============================================================
# 정리 테스트
# ============================================================

def test_cleanup_expired(memory_store):
    """만료된 항목 자동 삭제"""
    past = (datetime.now() - timedelta(hours=1)).isoformat()
    future = (datetime.now() + timedelta(hours=1)).isoformat()

    memory_store.add("reminders", "만료됨", "내용1", expires_at=past)
    memory_store.add("reminders", "유효함", "내용2", expires_at=future)
    memory_store.add("notes", "영구", "내용3")

    # _load()가 이미 만료 항목을 제거하므로, cleanup_expired()는 추가 작업 없음
    removed = memory_store.cleanup_expired()
    # add() 시점에 _load()에서 이미 제거되었으므로 0개
    assert removed == 0

    memories = memory_store._load()
    assert len(memories) == 2


def test_enforce_category_limits(memory_store):
    """카테고리별 용량 제한"""
    # user_info 제한은 20개
    for i in range(25):
        memory_store.add("user_info", f"키{i}", f"값{i}", importance=3)

    memory_store.enforce_limits()

    user_info_items = memory_store.get_by_category("user_info")
    assert len(user_info_items) <= MemoryStore.CATEGORY_LIMITS["user_info"]


def test_enforce_total_limit(memory_store):
    """전체 용량 제한"""
    # 각 카테고리에 항목 추가
    for i in range(60):
        memory_store.add("notes", f"메모{i}", f"내용{i}", importance=3)
    for i in range(60):
        memory_store.add("facts", f"사실{i}", f"내용{i}", importance=3)
    for i in range(60):
        memory_store.add("preferences", f"선호{i}", f"내용{i}", importance=3)

    memory_store.enforce_limits()

    all_memories = memory_store._load()
    assert len(all_memories) <= MemoryStore.MAX_MEMORIES


# ============================================================
# 요약 테스트
# ============================================================

def test_get_summary_empty(memory_store):
    """빈 저장소에서 빈 문자열"""
    summary = memory_store.get_summary()
    assert summary == ""


def test_get_summary_with_data(memory_store):
    """데이터 있을 때 마크다운 형식"""
    memory_store.add("user_info", "이름", "켈리", importance=5)
    memory_store.add("preferences", "언어", "Python", importance=4)
    memory_store.add("facts", "프로젝트", "flux-openclaw", importance=3)
    memory_store.add("notes", "메모1", "내용1", importance=3)

    summary = memory_store.get_summary()

    assert "## 사용자 정보" in summary
    assert "이름: 켈리" in summary
    assert "## 선호" in summary
    assert "언어: Python" in summary
    assert "## 사실" in summary
    assert "프로젝트: flux-openclaw" in summary
    assert "## 메모" in summary


def test_get_summary_max_chars(memory_store):
    """max_chars 초과 시 잘림"""
    for i in range(10):
        memory_store.add("notes", f"메모{i}", "A" * 200, importance=3)

    summary = memory_store.get_summary(max_chars=100)
    assert len(summary) <= 100


# ============================================================
# 마이그레이션 테스트
# ============================================================

def test_migrate_from_markdown(tmp_path):
    """memory.md 파싱"""
    md_content = """# 기억

## 사용자 정보
- 이름: 켈리
- 나이: 30

## 선호
- 언어: Python
- 에디터: VSCode

## 사실
- 프로젝트: flux-openclaw

## 메모
- 2026-02-11: 테스트 메모
"""
    md_path = tmp_path / "memory.md"
    md_path.write_text(md_content, encoding="utf-8")

    entries = MemoryStore.migrate_from_markdown(str(md_path))

    assert len(entries) > 0

    # 카테고리별 확인
    user_info_items = [e for e in entries if e["category"] == "user_info"]
    assert len(user_info_items) == 2
    assert any(e["key"] == "이름" and e["value"] == "켈리" for e in user_info_items)

    preferences_items = [e for e in entries if e["category"] == "preferences"]
    assert len(preferences_items) == 2

    facts_items = [e for e in entries if e["category"] == "facts"]
    assert len(facts_items) == 1

    notes_items = [e for e in entries if e["category"] == "notes"]
    assert len(notes_items) == 1


def test_migrate_empty_file(tmp_path):
    """빈 파일 마이그레이션"""
    md_path = tmp_path / "empty.md"
    md_path.write_text("", encoding="utf-8")

    entries = MemoryStore.migrate_from_markdown(str(md_path))
    assert entries == []
