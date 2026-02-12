"""
장기 메모리 관리 도구

AI가 대화 중 사용자 정보, 선호, 메모 등을 저장/검색/삭제합니다.
저장소: memory/memories.json (memory_store.py와 동일 포맷)

보안 참고:
- open(), json 사용으로 보안 경고 발생 -> 사용자 승인 필요 (한번 승인 시 해시 저장)
- save_text_file.py, read_text_file.py와 동일한 패턴
"""

import json
import uuid
import fcntl
import os
from datetime import datetime, timedelta

SCHEMA = {
    "name": "memory_manage",
    "description": "장기 메모리를 관리합니다. 정보 저장, 검색, 삭제가 가능합니다. 사용자의 정보, 선호, 메모 등을 기억합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "수행할 작업: save(저장), search(검색), list(카테고리별 목록), delete(삭제)",
                "enum": ["save", "search", "list", "delete"],
            },
            "category": {
                "type": "string",
                "description": "카테고리: user_info, preferences, facts, notes, reminders",
                "enum": ["user_info", "preferences", "facts", "notes", "reminders"],
            },
            "key": {
                "type": "string",
                "description": "기억의 키 (예: 'name', 'favorite_language')",
            },
            "value": {
                "type": "string",
                "description": "기억의 값 (예: '켈리', 'Python')",
            },
            "importance": {
                "type": "integer",
                "description": "중요도 (1-5, 기본값 3)",
            },
            "expires_days": {
                "type": "integer",
                "description": "만료일 (일 단위, 설정하지 않으면 영구)",
            },
            "query": {
                "type": "string",
                "description": "검색 키워드",
            },
            "memory_id": {
                "type": "string",
                "description": "삭제 시 사용할 메모리 ID",
            },
        },
        "required": ["action"],
    },
}

# ---- 내부 상수 ----

_MEMORY_FILE = "memory/memories.json"
_MAX_MEMORIES = 200
_CATEGORY_LIMITS = {
    "user_info": 20,
    "preferences": 30,
    "facts": 50,
    "notes": 80,
    "reminders": 20,
}
_VALID_CATEGORIES = set(_CATEGORY_LIMITS.keys())


# ---- 내부 파일 I/O (memory_store.py와 동일 포맷) ----

def _ensure_dir():
    dirpath = os.path.dirname(_MEMORY_FILE)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)


def _load_memories():
    """메모리 파일 로드 + 만료 항목 자동 정리"""
    if not os.path.exists(_MEMORY_FILE):
        return []
    try:
        with open(_MEMORY_FILE, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                memories = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except (json.JSONDecodeError, ValueError, OSError):
        return []
    if not isinstance(memories, list):
        return []
    # 만료 정리
    now = datetime.now().isoformat()
    before = len(memories)
    memories = [m for m in memories if not m.get("expires_at") or m["expires_at"] > now]
    if len(memories) < before:
        _save_memories(memories)
    return memories


def _save_memories(memories):
    """메모리 파일 저장 (배타적 잠금)"""
    _ensure_dir()
    try:
        with open(_MEMORY_FILE, "a+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                f.truncate()
                json.dump(memories, f, ensure_ascii=False, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        pass


def _enforce_limits(memories):
    """용량 초과 시 낮은 importance부터 삭제 (in-place)"""
    for cat, limit in _CATEGORY_LIMITS.items():
        cat_items = [m for m in memories if m["category"] == cat]
        if len(cat_items) > limit:
            cat_items.sort(key=lambda x: (x.get("importance", 3), x.get("created_at", "")))
            to_remove = len(cat_items) - limit
            remove_ids = {cat_items[i]["id"] for i in range(to_remove)}
            memories[:] = [m for m in memories if m["id"] not in remove_ids]
    if len(memories) > _MAX_MEMORIES:
        memories.sort(key=lambda x: (x.get("importance", 3), x.get("created_at", "")))
        to_remove = len(memories) - _MAX_MEMORIES
        remove_ids = {memories[i]["id"] for i in range(to_remove)}
        all_sorted = list(memories)
        memories[:] = [m for m in all_sorted if m["id"] not in remove_ids]


# ---- 액션 핸들러 ----

def _action_save(category, key, value, importance=3, expires_days=None):
    """메모리 저장 (동일 category+key 존재 시 업데이트)"""
    if not category:
        return "Error: category가 필요합니다."
    if category not in _VALID_CATEGORIES:
        return f"Error: 유효하지 않은 카테고리입니다. 가능한 값: {', '.join(sorted(_VALID_CATEGORIES))}"
    if not key:
        return "Error: key가 필요합니다."
    if not value:
        return "Error: value가 필요합니다."

    importance = max(1, min(5, int(importance)))
    now = datetime.now().isoformat()
    expires_at = None
    if expires_days and expires_days > 0:
        expires_at = (datetime.now() + timedelta(days=expires_days)).isoformat()

    memories = _load_memories()

    # 동일 category+key 업데이트
    for m in memories:
        if m["category"] == category and m["key"] == key:
            old_value = m["value"]
            m["value"] = value
            m["importance"] = importance
            m["updated_at"] = now
            if expires_at is not None:
                m["expires_at"] = expires_at
            m["source"] = "ai_tool"
            _save_memories(memories)
            return f"업데이트 완료: [{category}] {key} = '{value}' (이전: '{old_value}')"

    # 새 항목 생성
    entry = {
        "id": str(uuid.uuid4()),
        "category": category,
        "key": key,
        "value": value,
        "created_at": now,
        "updated_at": now,
        "expires_at": expires_at,
        "importance": importance,
        "source": "ai_tool",
    }
    memories.append(entry)
    _enforce_limits(memories)
    _save_memories(memories)
    exp_info = f", 만료: {expires_days}일 후" if expires_days else ""
    return f"저장 완료: [{category}] {key} = '{value}' (중요도: {importance}{exp_info})"


def _action_search(query, category=None):
    """키워드로 메모리 검색"""
    if not query:
        return "Error: query가 필요합니다."

    memories = _load_memories()
    query_lower = query.lower()
    results = []
    for m in memories:
        if category and m["category"] != category:
            continue
        if (query_lower in m.get("key", "").lower()
                or query_lower in str(m.get("value", "")).lower()):
            results.append(m)
    results.sort(key=lambda x: -x.get("importance", 3))

    if not results:
        scope = f" (카테고리: {category})" if category else ""
        return f"'{query}' 검색 결과 없음{scope}"

    lines = [f"검색 결과 ({len(results)}건):"]
    for m in results:
        exp = ""
        if m.get("expires_at"):
            exp = f" [만료: {m['expires_at'][:10]}]"
        lines.append(
            f"  - [{m['category']}] {m['key']}: {m['value']} "
            f"(중요도: {m['importance']}{exp}) [ID: {m['id'][:8]}]"
        )
    return "\n".join(lines)


def _action_list(category=None):
    """카테고리별 메모리 목록"""
    memories = _load_memories()

    if category:
        if category not in _VALID_CATEGORIES:
            return f"Error: 유효하지 않은 카테고리입니다. 가능한 값: {', '.join(sorted(_VALID_CATEGORIES))}"
        items = [m for m in memories if m["category"] == category]
        items.sort(key=lambda x: -x.get("importance", 3))
        if not items:
            return f"[{category}] 카테고리에 저장된 기억이 없습니다."
        lines = [f"[{category}] 목록 ({len(items)}건):"]
        for m in items:
            exp = ""
            if m.get("expires_at"):
                exp = f" [만료: {m['expires_at'][:10]}]"
            lines.append(
                f"  - {m['key']}: {m['value']} "
                f"(중요도: {m['importance']}{exp}) [ID: {m['id'][:8]}]"
            )
        return "\n".join(lines)

    # 전체 요약
    if not memories:
        return "저장된 기억이 없습니다."

    category_labels = {
        "user_info": "사용자 정보",
        "preferences": "선호",
        "facts": "사실",
        "notes": "메모",
        "reminders": "리마인더",
    }
    lines = [f"전체 기억 ({len(memories)}건):"]
    for cat in ["user_info", "preferences", "facts", "notes", "reminders"]:
        items = [m for m in memories if m["category"] == cat]
        if items:
            label = category_labels.get(cat, cat)
            limit = _CATEGORY_LIMITS.get(cat, "?")
            lines.append(f"\n  [{label}] ({len(items)}/{limit})")
            items.sort(key=lambda x: -x.get("importance", 3))
            for m in items[:10]:  # 카테고리당 최대 10개 표시
                exp = ""
                if m.get("expires_at"):
                    exp = f" [만료: {m['expires_at'][:10]}]"
                lines.append(
                    f"    - {m['key']}: {m['value']} "
                    f"(중요도: {m['importance']}{exp}) [ID: {m['id'][:8]}]"
                )
            if len(items) > 10:
                lines.append(f"    ... 외 {len(items) - 10}건")
    return "\n".join(lines)


def _action_delete(memory_id):
    """메모리 항목 삭제"""
    if not memory_id:
        return "Error: memory_id가 필요합니다."

    memories = _load_memories()

    # 짧은 ID (8자) 또는 전체 UUID 모두 지원
    target = None
    for m in memories:
        if m["id"] == memory_id or m["id"].startswith(memory_id):
            target = m
            break

    if not target:
        return f"Error: ID '{memory_id}'에 해당하는 기억을 찾을 수 없습니다."

    memories = [m for m in memories if m["id"] != target["id"]]
    _save_memories(memories)
    return f"삭제 완료: [{target['category']}] {target['key']}: {target['value']}"


# ---- 메인 진입점 ----

def main(action, category=None, key=None, value=None,
         importance=3, expires_days=None, query=None, memory_id=None):
    """메모리 관리 도구 메인 함수"""
    try:
        if action == "save":
            return _action_save(category, key, value, importance, expires_days)
        elif action == "search":
            return _action_search(query, category)
        elif action == "list":
            return _action_list(category)
        elif action == "delete":
            return _action_delete(memory_id)
        else:
            return f"Error: 알 수 없는 action입니다: {action}. 가능한 값: save, search, list, delete"
    except Exception as e:
        return f"Error: 메모리 관리 실패 - {e}"


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(SCHEMA, indent=2, ensure_ascii=False))
