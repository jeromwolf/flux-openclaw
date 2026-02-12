"""
flux-openclaw 도구 마켓플레이스 엔진

커뮤니티 도구의 검색, 설치, 제거, 무결성 검증을 수행합니다.
설치 시 7계층 보안 방어를 적용합니다.

보안 계층:
    1. 파일명 검증 (정규식 패턴)
    2. 예약 이름 충돌 검사
    3. SHA-256 해시 검증
    4. Regex 보안 스캔 (core._DANGEROUS_RE)
    5. AST 보안 스캔 (ToolManager._check_dangerous_ast)
    6. 도구 규약 검증 (SCHEMA + main)
    7. 파일 복사 및 installed.json 업데이트
"""

import os
import re
import ast
import json
import fcntl
import shutil
import hashlib
from datetime import datetime

from core import ToolManager, _DANGEROUS_RE


class MarketplaceEngine:
    """마켓플레이스 도구 관리 엔진

    레지스트리(registry.json)에서 도구를 검색하고,
    캐시(marketplace/cache/)에서 도구를 설치/제거하며,
    설치된 도구(installed.json)의 무결성을 검증합니다.
    """

    REGISTRY_FILE = "marketplace/registry.json"
    INSTALLED_FILE = "marketplace/installed.json"
    CACHE_DIR = "marketplace/cache"
    TOOLS_DIR = "tools"

    # 예약된 도구 이름 (기본 도구와 충돌 방지)
    _RESERVED_NAMES = {
        "web_search", "web_fetch", "weather", "read_text_file", "save_text_file",
        "list_files", "play_audio", "screen_capture", "add_two_numbers",
        "multiply_two_numbers", "memory_manage", "schedule_task",
        "marketplace_tool", "browser_tool", "browser",
    }

    # 허용 파일명 패턴: 영문, 숫자, 밑줄 + .py 확장자만
    _FILENAME_RE = re.compile(r"^[a-zA-Z0-9_]+\.py$")

    def __init__(self, registry_path=None, installed_path=None,
                 cache_dir=None, tools_dir=None):
        """초기화. 경로 커스텀은 주로 테스트용.

        Args:
            registry_path: 레지스트리 JSON 파일 경로
            installed_path: 설치 기록 JSON 파일 경로
            cache_dir: 도구 소스 캐시 디렉토리
            tools_dir: 도구 설치 대상 디렉토리
        """
        self.registry_path = registry_path or self.REGISTRY_FILE
        self.installed_path = installed_path or self.INSTALLED_FILE
        self.cache_dir = cache_dir or self.CACHE_DIR
        self.tools_dir = tools_dir or self.TOOLS_DIR

    # ================================================================
    # 내부: 파일 I/O
    # ================================================================

    def _load_registry(self):
        """레지스트리 로드 (읽기 전용)"""
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f" [마켓플레이스] 레지스트리 로드 실패: {e}")
            return {"tools": []}

    def _load_installed(self):
        """설치 기록 로드 (공유 잠금)"""
        if not os.path.exists(self.installed_path):
            return {"installed": {}, "version": 1}
        try:
            with open(self.installed_path, "r", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                data = json.load(f)
            return data
        except (OSError, json.JSONDecodeError) as e:
            print(f" [마켓플레이스] 설치 기록 로드 실패: {e}")
            return {"installed": {}, "version": 1}

    def _save_installed(self, data):
        """설치 기록 저장 (배타적 잠금, TOCTOU 방지)"""
        try:
            with open(self.installed_path, "a+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.seek(0)
                f.truncate()
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f" [마켓플레이스] 설치 기록 저장 실패: {e}")

    # ================================================================
    # 내부: 보안 검사
    # ================================================================

    def _compute_hash(self, filepath):
        """SHA-256 파일 해시 계산

        Args:
            filepath: 해시를 계산할 파일 경로

        Returns:
            str: 16진수 SHA-256 해시 문자열
        """
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _compute_hash_bytes(self, raw_bytes):
        """바이트 데이터의 SHA-256 해시 계산"""
        return hashlib.sha256(raw_bytes).hexdigest()

    def _security_scan(self, code, filename):
        """보안 검사 (core.py 패턴 재사용)

        계층 4 (Regex) + 계층 5 (AST) 보안 스캔을 수행합니다.
        core.py의 _DANGEROUS_RE와 ToolManager._check_dangerous_ast를 재사용합니다.

        Args:
            code: 검사할 소스 코드 문자열
            filename: 파일명 (로그용)

        Returns:
            list: 발견된 위험 패턴 목록 (빈 리스트면 안전)
        """
        findings = []

        # 계층 4: Regex 보안 스캔
        regex_hits = _DANGEROUS_RE.findall(code)
        if regex_hits:
            findings.extend([f"regex:{h}" for h in regex_hits])

        # 계층 5: AST 보안 스캔
        tm = ToolManager.__new__(ToolManager)
        ast_hits = tm._check_dangerous_ast(code)
        if ast_hits:
            findings.extend([f"ast:{h}" for h in ast_hits])

        return findings

    def _verify_convention(self, code):
        """도구 규약 검증 (계층 6)

        도구 파일이 SCHEMA 딕셔너리와 main() 함수를 갖추고 있는지 확인합니다.

        Args:
            code: 검사할 소스 코드 문자열

        Returns:
            list: 규약 위반 목록 (빈 리스트면 준수)
        """
        errors = []

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return [f"구문 오류: {e}"]

        has_schema = False
        has_main = False

        for node in ast.walk(tree):
            # SCHEMA 변수 할당 확인
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "SCHEMA":
                        has_schema = True
            # main() 함수 정의 확인
            elif isinstance(node, ast.FunctionDef) and node.name == "main":
                has_main = True

        if not has_schema:
            errors.append("SCHEMA 딕셔너리가 없습니다")
        if not has_main:
            errors.append("main() 함수가 없습니다")

        return errors

    # ================================================================
    # 공개 API: 검색
    # ================================================================

    def search(self, query="", category=None, tags=None):
        """레지스트리에서 도구 검색

        Args:
            query: 이름/설명에서 대소문자 무시 검색 (빈 문자열이면 전체)
            category: 카테고리 필터 (utility/data/web/text/math/design/security 등)
            tags: AND 조건 태그 필터 (리스트)

        Returns:
            list[dict]: 매칭된 도구 정보 목록 (각 항목에 "installed" 필드 포함)
        """
        registry = self._load_registry()
        installed_data = self._load_installed()
        installed_names = set(installed_data.get("installed", {}).keys())

        results = []
        query_lower = query.lower()

        for tool in registry.get("tools", []):
            # 쿼리 필터: 이름 또는 설명에 포함
            if query_lower:
                name_match = query_lower in tool.get("name", "").lower()
                desc_match = query_lower in tool.get("description", "").lower()
                if not (name_match or desc_match):
                    continue

            # 카테고리 필터
            if category and tool.get("category") != category:
                continue

            # 태그 필터 (AND 조건)
            if tags:
                tool_tags = set(tool.get("tags", []))
                if not all(t in tool_tags for t in tags):
                    continue

            # 결과에 installed 상태 추가
            tool_copy = dict(tool)
            tool_copy["installed"] = tool["name"] in installed_names
            results.append(tool_copy)

        return results

    def get_info(self, tool_name):
        """특정 도구의 상세 정보 조회

        Args:
            tool_name: 도구 이름

        Returns:
            dict | None: 도구 정보 (installed 필드 포함) 또는 None
        """
        registry = self._load_registry()
        installed_data = self._load_installed()
        installed_names = set(installed_data.get("installed", {}).keys())

        for tool in registry.get("tools", []):
            if tool["name"] == tool_name:
                tool_copy = dict(tool)
                tool_copy["installed"] = tool_name in installed_names

                # 설치 정보가 있으면 추가
                install_info = installed_data.get("installed", {}).get(tool_name)
                if install_info:
                    tool_copy["install_info"] = install_info

                return tool_copy

        return None

    # ================================================================
    # 공개 API: 설치
    # ================================================================

    def install(self, tool_name):
        """도구 설치 (7계층 보안 방어)

        보안 계층:
            1. 파일명 검증
            2. 예약 이름 충돌 검사
            3. SHA-256 해시 검증
            4. Regex 보안 스캔
            5. AST 보안 스캔
            6. 도구 규약 검증 (SCHEMA + main)
            7. 파일 복사 및 installed.json 업데이트

        Args:
            tool_name: 설치할 도구 이름

        Returns:
            dict: {"status": "installed"|"error", "message": "...", "tool": {...}}
        """
        # --- 레지스트리에서 도구 조회 ---
        registry = self._load_registry()
        tool_info = None
        for tool in registry.get("tools", []):
            if tool["name"] == tool_name:
                tool_info = tool
                break

        if tool_info is None:
            return {"status": "error", "message": f"레지스트리에 '{tool_name}' 도구가 없습니다."}

        # 이미 설치 확인
        installed_data = self._load_installed()
        if tool_name in installed_data.get("installed", {}):
            return {"status": "error", "message": f"'{tool_name}'은(는) 이미 설치되어 있습니다."}

        filename = tool_info.get("filename", "")
        source_path = os.path.join(self.cache_dir, filename)

        # --- 계층 1: 파일명 검증 ---
        if not self._FILENAME_RE.match(filename):
            return {
                "status": "error",
                "message": f"[계층1] 유효하지 않은 파일명: {filename}",
            }

        # --- 계층 2: 예약 이름 충돌 검사 ---
        base_name = filename[:-3]  # .py 제거
        if base_name in self._RESERVED_NAMES:
            return {
                "status": "error",
                "message": f"[계층2] 예약된 도구 이름과 충돌: {base_name}",
            }

        # --- 소스 파일 존재 확인 ---
        if not os.path.exists(source_path):
            return {
                "status": "error",
                "message": f"캐시에 소스 파일이 없습니다: {source_path}",
            }

        # 파일 내용을 한 번만 읽기 (TOCTOU 방지)
        try:
            with open(source_path, "rb") as f:
                raw_bytes = f.read()
        except OSError as e:
            return {"status": "error", "message": f"소스 파일 읽기 실패: {e}"}

        code = raw_bytes.decode("utf-8", errors="replace")

        # --- 계층 3: SHA-256 해시 검증 ---
        actual_hash = self._compute_hash_bytes(raw_bytes)
        expected_hash = tool_info.get("sha256", "")

        if not expected_hash:
            return {
                "status": "error",
                "message": f"레지스트리에 SHA-256 해시가 없습니다: {tool_name}"
            }

        if actual_hash != expected_hash:
            return {
                "status": "error",
                "message": (
                    f"[계층3] SHA-256 해시 불일치 — 파일이 변조되었을 수 있습니다.\n"
                    f"  기대: {expected_hash}\n"
                    f"  실제: {actual_hash}"
                ),
            }

        # --- 계층 4 + 5: 보안 스캔 (Regex + AST) ---
        security_findings = self._security_scan(code, filename)
        if security_findings:
            return {
                "status": "error",
                "message": (
                    f"[계층4/5] 보안 검사 실패 — 위험 패턴 발견:\n"
                    f"  {', '.join(security_findings)}"
                ),
            }

        # --- 계층 6: 도구 규약 검증 ---
        convention_errors = self._verify_convention(code)
        if convention_errors:
            return {
                "status": "error",
                "message": (
                    f"[계층6] 도구 규약 위반:\n"
                    f"  {', '.join(convention_errors)}"
                ),
            }

        # --- 계층 7: 파일 복사 및 installed.json 업데이트 ---
        dest_path = os.path.join(self.tools_dir, filename)

        # tools/ 디렉토리가 없으면 생성
        os.makedirs(self.tools_dir, exist_ok=True)

        try:
            # 메모리에 읽은 내용을 직접 쓰기 (TOCTOU 방지)
            with open(dest_path, "wb") as f:
                f.write(raw_bytes)
        except OSError as e:
            return {"status": "error", "message": f"파일 복사 실패: {e}"}

        # installed.json 업데이트 (배타적 잠금)
        installed_data = self._load_installed()
        installed_data.setdefault("installed", {})[tool_name] = {
            "filename": filename,
            "version": tool_info.get("version", "unknown"),
            "sha256": actual_hash,
            "installed_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "source": tool_info.get("source", "unknown"),
        }
        self._save_installed(installed_data)

        print(f" [마켓플레이스] '{tool_name}' 설치 완료 -> {dest_path}")
        return {
            "status": "installed",
            "message": f"'{tool_name}' 도구가 설치되었습니다.",
            "tool": tool_info,
        }

    # ================================================================
    # 공개 API: 제거
    # ================================================================

    def uninstall(self, tool_name):
        """도구 제거

        1. installed.json에서 확인
        2. tools/ 에서 파일 삭제
        3. installed.json에서 제거

        Args:
            tool_name: 제거할 도구 이름

        Returns:
            dict: {"status": "uninstalled"|"error", "message": "..."}
        """
        installed_data = self._load_installed()
        install_info = installed_data.get("installed", {}).get(tool_name)

        if not install_info:
            return {
                "status": "error",
                "message": f"'{tool_name}'은(는) 설치되어 있지 않습니다.",
            }

        filename = install_info.get("filename", "")
        tool_path = os.path.join(self.tools_dir, filename)

        # tools/ 에서 파일 삭제
        if os.path.exists(tool_path):
            try:
                os.remove(tool_path)
            except OSError as e:
                return {"status": "error", "message": f"파일 삭제 실패: {e}"}

        # installed.json에서 제거 (배타적 잠금)
        installed_data = self._load_installed()
        installed_data.get("installed", {}).pop(tool_name, None)
        self._save_installed(installed_data)

        print(f" [마켓플레이스] '{tool_name}' 제거 완료")
        return {
            "status": "uninstalled",
            "message": f"'{tool_name}' 도구가 제거되었습니다.",
        }

    # ================================================================
    # 공개 API: 목록 / 무결성 검증
    # ================================================================

    def list_installed(self):
        """설치된 도구 목록 반환

        Returns:
            list[dict]: 설치된 도구 정보 목록
        """
        installed_data = self._load_installed()
        installed = installed_data.get("installed", {})

        results = []
        for name, info in installed.items():
            entry = dict(info)
            entry["name"] = name
            results.append(entry)

        return results

    def verify_integrity(self):
        """설치된 도구의 SHA-256 해시를 검증하여 변조 여부 확인

        Returns:
            list[dict]: 변조된 파일 목록
                각 항목: {"name", "filename", "expected", "actual", "status"}
                status: "tampered" (변조) | "missing" (파일 없음) | "ok" (정상)
        """
        installed_data = self._load_installed()
        installed = installed_data.get("installed", {})

        results = []
        for name, info in installed.items():
            filename = info.get("filename", "")
            expected_hash = info.get("sha256", "")
            tool_path = os.path.join(self.tools_dir, filename)

            entry = {
                "name": name,
                "filename": filename,
                "expected": expected_hash,
            }

            if not os.path.exists(tool_path):
                entry["actual"] = ""
                entry["status"] = "missing"
                results.append(entry)
                continue

            try:
                actual_hash = self._compute_hash(tool_path)
            except OSError:
                entry["actual"] = ""
                entry["status"] = "missing"
                results.append(entry)
                continue

            entry["actual"] = actual_hash

            if expected_hash and actual_hash != expected_hash:
                entry["status"] = "tampered"
                results.append(entry)
            else:
                entry["status"] = "ok"
                results.append(entry)

        return results

    # ================================================================
    # 공개 API: 레지스트리 유틸리티
    # ================================================================

    def get_categories(self):
        """레지스트리에 등록된 카테고리 목록 반환

        Returns:
            list[str]: 정렬된 고유 카테고리 목록
        """
        registry = self._load_registry()
        categories = set()
        for tool in registry.get("tools", []):
            cat = tool.get("category")
            if cat:
                categories.add(cat)
        return sorted(categories)

    def get_tags(self):
        """레지스트리에 등록된 태그 목록 반환

        Returns:
            list[str]: 정렬된 고유 태그 목록
        """
        registry = self._load_registry()
        tags = set()
        for tool in registry.get("tools", []):
            for tag in tool.get("tags", []):
                tags.add(tag)
        return sorted(tags)

    def get_stats(self):
        """마켓플레이스 통계 반환

        Returns:
            dict: 전체 도구 수, 설치 수, 카테고리 수, 무결성 상태
        """
        registry = self._load_registry()
        installed_data = self._load_installed()
        total = len(registry.get("tools", []))
        installed_count = len(installed_data.get("installed", {}))

        integrity = self.verify_integrity()
        tampered = sum(1 for r in integrity if r["status"] == "tampered")
        missing = sum(1 for r in integrity if r["status"] == "missing")

        return {
            "total_tools": total,
            "installed_count": installed_count,
            "categories": self.get_categories(),
            "integrity": {
                "checked": len(integrity),
                "tampered": tampered,
                "missing": missing,
                "ok": len(integrity) - tampered - missing,
            },
        }


# ================================================================
# CLI 테스트 인터페이스
# ================================================================

if __name__ == "__main__":
    engine = MarketplaceEngine()

    print("=== 마켓플레이스 통계 ===")
    stats = engine.get_stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2))

    print("\n=== 전체 도구 검색 ===")
    all_tools = engine.search()
    for t in all_tools:
        status = "[설치됨]" if t["installed"] else "[미설치]"
        print(f"  {status} {t['name']} - {t['description']}")

    print("\n=== 카테고리 'utility' 검색 ===")
    utility_tools = engine.search(category="utility")
    for t in utility_tools:
        print(f"  {t['name']}: {t['tags']}")

    print("\n=== 'hash' 키워드 검색 ===")
    hash_tools = engine.search(query="hash")
    for t in hash_tools:
        print(f"  {t['name']}: {t['description']}")

    print("\n=== 'unit_converter' 상세 정보 ===")
    info = engine.get_info("unit_converter")
    if info:
        print(json.dumps(info, ensure_ascii=False, indent=2))
