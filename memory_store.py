"""
flux-openclaw 구조화된 장기 메모리 엔진

JSON 기반 메모리 저장소. memory/memory.md를 대체합니다.
저장 경로: memory/memories.json

사용처:
- core.py의 load_system_prompt()에서 get_summary()로 시스템 프롬프트에 메모리 포함
- tools/memory_manage.py (AI 도구)에서 동일 파일 포맷 사용 (인라인 구현)
"""

import json
import uuid
import fcntl
import os
from datetime import datetime


class MemoryStore:
    """구조화된 장기 메모리 저장소"""

    MEMORY_FILE = "memory/memories.json"
    MAX_MEMORIES = 200
    CATEGORY_LIMITS = {
        "user_info": 20,
        "preferences": 30,
        "facts": 50,
        "notes": 80,
        "reminders": 20,
    }
    VALID_CATEGORIES = set(CATEGORY_LIMITS.keys())

    def __init__(self, memory_file=None):
        self.memory_file = memory_file or self.MEMORY_FILE
        self._ensure_dir()

    def _ensure_dir(self):
        """메모리 파일의 상위 디렉토리 생성"""
        dirpath = os.path.dirname(self.memory_file)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)

    def _load(self, user_id=None):
        """메모리 파일 로드 (파일 잠금 사용). 만료된 항목 자동 정리.

        Args:
            user_id: 필터링할 사용자 ID (None이면 전체, "default"는 user_id 없는 항목 포함)
        """
        if not os.path.exists(self.memory_file):
            return []
        try:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    memories = json.load(f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except (json.JSONDecodeError, ValueError, OSError):
            return []
        if not isinstance(memories, list):
            return []
        # 만료된 항목 자동 정리
        now = datetime.now().isoformat()
        before = len(memories)
        memories = [
            m for m in memories
            if not m.get("expires_at") or m["expires_at"] > now
        ]
        if len(memories) < before:
            self._save(memories)
        # user_id 필터링 (기존 항목에 user_id가 없으면 "default"로 취급)
        if user_id is not None:
            memories = [
                m for m in memories
                if m.get("user_id", "default") == user_id
            ]
        return memories

    def _save(self, memories):
        """메모리 파일 저장 (배타적 파일 잠금)"""
        self._ensure_dir()
        try:
            with open(self.memory_file, "a+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    f.truncate()
                    json.dump(memories, f, ensure_ascii=False, indent=2)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except OSError as e:
            print(f" [메모리] 저장 실패: {e}")

    # ---- CRUD ----

    def add(self, category, key, value, importance=3, expires_at=None, source="user", user_id="default"):
        """메모리 항목 추가. 동일 category+key(+user_id)가 있으면 업데이트.

        Args:
            category: 메모리 카테고리
            key: 메모리 키
            value: 메모리 값
            importance: 중요도 (1-5)
            expires_at: 만료 일시 (ISO 형식)
            source: 출처
            user_id: 사용자 ID (기본값: "default")
        """
        if category not in self.VALID_CATEGORIES:
            raise ValueError(f"유효하지 않은 카테고리: {category}. "
                             f"가능한 값: {', '.join(sorted(self.VALID_CATEGORIES))}")
        importance = max(1, min(5, int(importance)))
        now = datetime.now().isoformat()

        memories = self._load()

        # 동일 category+key+user_id 존재 시 업데이트
        for m in memories:
            if m["category"] == category and m["key"] == key and m.get("user_id", "default") == user_id:
                m["value"] = value
                m["importance"] = importance
                m["updated_at"] = now
                if expires_at is not None:
                    m["expires_at"] = expires_at
                m["source"] = source
                m["user_id"] = user_id
                self._save(memories)
                return m

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
            "source": source,
            "user_id": user_id,
        }
        memories.append(entry)

        # 용량 관리
        self._enforce_limits_internal(memories)
        self._save(memories)
        return entry

    def get(self, memory_id):
        """ID로 메모리 항목 조회"""
        memories = self._load()
        for m in memories:
            if m["id"] == memory_id:
                return m
        return None

    def update(self, memory_id, **kwargs):
        """메모리 항목 부분 업데이트"""
        allowed_fields = {"key", "value", "category", "importance", "expires_at", "source"}
        memories = self._load()
        for m in memories:
            if m["id"] == memory_id:
                for k, v in kwargs.items():
                    if k in allowed_fields:
                        if k == "category" and v not in self.VALID_CATEGORIES:
                            raise ValueError(f"유효하지 않은 카테고리: {v}")
                        if k == "importance":
                            v = max(1, min(5, int(v)))
                        m[k] = v
                m["updated_at"] = datetime.now().isoformat()
                self._save(memories)
                return m
        return None

    def delete(self, memory_id):
        """메모리 항목 삭제"""
        memories = self._load()
        before = len(memories)
        memories = [m for m in memories if m["id"] != memory_id]
        if len(memories) < before:
            self._save(memories)
            return True
        return False

    # ---- 검색 ----

    def search(self, query, category=None, user_id=None):
        """키워드로 메모리 검색 (key, value에서 대소문자 무시 매칭)

        Args:
            query: 검색 키워드
            category: 필터링할 카테고리 (None이면 전체)
            user_id: 필터링할 사용자 ID (None이면 전체)
        """
        memories = self._load(user_id=user_id)
        query_lower = query.lower()
        results = []
        for m in memories:
            if category and m["category"] != category:
                continue
            if (query_lower in m.get("key", "").lower()
                    or query_lower in str(m.get("value", "")).lower()):
                results.append(m)
        # importance 높은 순, updated_at 최신 순
        results.sort(key=lambda x: (-x.get("importance", 3), x.get("updated_at", "")),
                     reverse=False)
        results.sort(key=lambda x: -x.get("importance", 3))
        return results

    def get_by_category(self, category):
        """카테고리별 메모리 목록 조회"""
        memories = self._load()
        results = [m for m in memories if m["category"] == category]
        results.sort(key=lambda x: (-x.get("importance", 3), x.get("updated_at", "")))
        return results

    def get_by_key(self, key):
        """키로 메모리 검색 (정확 매칭)"""
        memories = self._load()
        return [m for m in memories if m["key"] == key]

    # ---- 정리 ----

    def cleanup_expired(self):
        """만료된 항목 삭제. 삭제된 항목 수 반환."""
        memories = self._load()  # _load()가 이미 만료 정리를 수행
        # _load() 내부에서 처리되므로, 변경분은 거기서 저장됨
        # 별도로 확인 후 추가 정리
        now = datetime.now().isoformat()
        before = len(memories)
        memories = [
            m for m in memories
            if not m.get("expires_at") or m["expires_at"] > now
        ]
        removed = before - len(memories)
        if removed > 0:
            self._save(memories)
        return removed

    def _enforce_limits_internal(self, memories):
        """내부용: 메모리 리스트에 직접 용량 제한 적용 (in-place 수정)"""
        # 카테고리별 제한
        for cat, limit in self.CATEGORY_LIMITS.items():
            cat_items = [m for m in memories if m["category"] == cat]
            if len(cat_items) > limit:
                # importance 낮은 순 -> created_at 오래된 순으로 정렬하여 초과분 삭제
                cat_items.sort(key=lambda x: (x.get("importance", 3), x.get("created_at", "")))
                to_remove = len(cat_items) - limit
                remove_ids = {cat_items[i]["id"] for i in range(to_remove)}
                memories[:] = [m for m in memories if m["id"] not in remove_ids]

        # 전체 제한
        if len(memories) > self.MAX_MEMORIES:
            memories.sort(key=lambda x: (x.get("importance", 3), x.get("created_at", "")))
            to_remove = len(memories) - self.MAX_MEMORIES
            remove_ids = {memories[i]["id"] for i in range(to_remove)}
            all_sorted = list(memories)
            memories[:] = [m for m in all_sorted if m["id"] not in remove_ids]

    def enforce_limits(self):
        """용량 초과 시 낮은 importance부터 삭제"""
        memories = self._load()
        before = len(memories)
        self._enforce_limits_internal(memories)
        if len(memories) < before:
            self._save(memories)

    # ---- 시스템 프롬프트용 요약 ----

    def get_summary(self, max_chars=1500, user_id=None):
        """시스템 프롬프트에 포함할 메모리 요약 생성

        Args:
            max_chars: 최대 문자 수
            user_id: 필터링할 사용자 ID (None이면 전체)

        형식:
        ## 사용자 정보
        - 이름: 켈리

        ## 선호
        - 좋아하는 언어: Python

        ## 사실
        - 프로젝트 마감일: 3월 1일

        ## 메모 (최근 5개)
        - 2026-02-11: 어떤 메모

        ## 리마인더
        - [2026-03-01] 마감일 알림
        """
        memories = self._load(user_id=user_id)
        if not memories:
            return ""

        category_labels = {
            "user_info": "사용자 정보",
            "preferences": "선호",
            "facts": "사실",
            "notes": "메모",
            "reminders": "리마인더",
        }

        sections = []
        for cat in ["user_info", "preferences", "facts", "notes", "reminders"]:
            items = [m for m in memories if m["category"] == cat]
            if not items:
                continue
            # importance 높은 순
            items.sort(key=lambda x: -x.get("importance", 3))

            label = category_labels.get(cat, cat)
            if cat == "notes":
                # 메모는 최근 5개만
                items = items[:5]
                header = f"## {label} (최근 {len(items)}개)"
            else:
                header = f"## {label}"

            lines = [header]
            for m in items:
                if cat == "notes":
                    date_str = m.get("created_at", "")[:10]
                    lines.append(f"- {date_str}: {m['value']}")
                elif cat == "reminders":
                    exp = m.get("expires_at", "")[:10] if m.get("expires_at") else "영구"
                    lines.append(f"- [{exp}] {m['key']}: {m['value']}")
                else:
                    lines.append(f"- {m['key']}: {m['value']}")
            sections.append("\n".join(lines))

        result = "\n\n".join(sections)
        if len(result) > max_chars:
            result = result[:max_chars]
        return result

    # ---- 마이그레이션 ----

    @staticmethod
    def migrate_from_markdown(md_path="memory/memory.md"):
        """기존 memory.md를 파싱하여 메모리 항목 리스트로 변환

        파싱 규칙:
        - '## 사용자 정보' 섹션 -> category='user_info'
        - '## 선호' 또는 '## 선호도' 섹션 -> category='preferences'
        - '## 사실' 섹션 -> category='facts'
        - '## 메모' 섹션 -> category='notes'
        - '- key: value' 형식의 항목을 파싱
        """
        if not os.path.exists(md_path):
            return []

        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        section_map = {
            "사용자 정보": "user_info",
            "선호": "preferences",
            "선호도": "preferences",
            "사실": "facts",
            "메모": "notes",
            "리마인더": "reminders",
        }

        entries = []
        current_category = "notes"  # 기본값
        now = datetime.now().isoformat()

        for line in content.splitlines():
            line = line.strip()
            # 섹션 헤더 감지
            if line.startswith("## "):
                section_name = line[3:].strip()
                # 매핑 테이블에서 찾기
                matched = False
                for label, cat in section_map.items():
                    if label in section_name:
                        current_category = cat
                        matched = True
                        break
                if not matched:
                    current_category = "notes"
                continue

            # '# 기억' 같은 최상위 헤더는 무시
            if line.startswith("#"):
                continue

            # '- key: value' 형식 파싱
            if line.startswith("- "):
                item_text = line[2:].strip()
                if not item_text:
                    continue
                if ": " in item_text:
                    key, value = item_text.split(": ", 1)
                else:
                    key = item_text
                    value = ""
                entries.append({
                    "id": str(uuid.uuid4()),
                    "category": current_category,
                    "key": key.strip(),
                    "value": value.strip(),
                    "created_at": now,
                    "updated_at": now,
                    "expires_at": None,
                    "importance": 4,  # 기존 데이터는 중요도 높게
                    "source": "migration",
                })

        return entries
