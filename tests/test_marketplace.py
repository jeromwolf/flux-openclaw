"""MarketplaceEngine 및 marketplace_tool 테스트

마켓플레이스 도구 관리 엔진의 검색, 설치, 제거, 무결성 검증,
그리고 AI 인터페이스(marketplace_tool.py)를 테스트합니다.
"""

import os
import json
import hashlib
import pytest
from unittest.mock import patch

from tool_marketplace import MarketplaceEngine


# ================================================================
# 헬퍼 함수
# ================================================================


def _make_safe_tool(name="test_tool", schema_name=None):
    """보안 스캐너를 통과하는 안전한 도구 소스 생성"""
    schema_name = schema_name or name
    return (
        f'SCHEMA = {{\n'
        f'    "name": "{schema_name}",\n'
        f'    "description": "A test tool",\n'
        f'    "input_schema": {{\n'
        f'        "type": "object",\n'
        f'        "properties": {{\n'
        f'            "value": {{"type": "string", "description": "input value"}},\n'
        f'        }},\n'
        f'        "required": ["value"],\n'
        f'    }},\n'
        f'}}\n\n'
        f'def main(value):\n'
        f'    return f"result: {{value}}"\n\n'
        f'if __name__ == "__main__":\n'
        f'    print(main("test"))\n'
    )


def _make_registry(tools, registry_path, cache_dir):
    """테스트용 registry.json + cache 파일 생성

    Args:
        tools: [{"name": ..., "filename": ..., "category": ..., "tags": [...], ...}]
               source 키가 있으면 해당 소스 사용, 없으면 _make_safe_tool 사용.
               sha256 키가 "auto"이면 자동 계산.
        registry_path: registry.json 경로
        cache_dir: 캐시 디렉토리 경로

    Returns:
        dict: 생성된 레지스트리 데이터
    """
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    registry_tools = []
    for t in tools:
        source = t.pop("source_code", None) or _make_safe_tool(t["name"])
        raw = source.encode("utf-8")

        # 캐시에 소스 파일 생성
        cache_path = os.path.join(cache_dir, t["filename"])
        with open(cache_path, "wb") as f:
            f.write(raw)

        # sha256 자동 계산
        if t.get("sha256") == "auto":
            t["sha256"] = hashlib.sha256(raw).hexdigest()

        entry = {
            "name": t["name"],
            "description": t.get("description", f"{t['name']} tool"),
            "version": t.get("version", "1.0.0"),
            "filename": t["filename"],
            "category": t.get("category", "utility"),
            "tags": t.get("tags", []),
            "sha256": t.get("sha256", ""),
            "source": t.get("source", "test"),
        }
        if "dependencies" in t:
            entry["dependencies"] = t["dependencies"]
        registry_tools.append(entry)

    data = {"tools": registry_tools}
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def _make_installed(installed_dict, installed_path):
    """테스트용 installed.json 생성

    Args:
        installed_dict: {"tool_name": {"filename": ..., "version": ..., "sha256": ...}, ...}
        installed_path: installed.json 경로
    """
    os.makedirs(os.path.dirname(installed_path), exist_ok=True)
    data = {"installed": installed_dict, "version": 1}
    with open(installed_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _engine(tmp_path):
    """격리된 MarketplaceEngine 생성"""
    return MarketplaceEngine(
        registry_path=str(tmp_path / "marketplace" / "registry.json"),
        installed_path=str(tmp_path / "marketplace" / "installed.json"),
        cache_dir=str(tmp_path / "cache"),
        tools_dir=str(tmp_path / "tools"),
    )


# ================================================================
# 1. Registry 로드 테스트
# ================================================================


class TestRegistryLoad:
    """레지스트리 로드 및 검색 테스트"""

    def test_load_valid_registry(self, tmp_path):
        """정상 레지스트리 로드 시 도구 목록 반환"""
        eng = _engine(tmp_path)
        _make_registry(
            [{"name": "alpha", "filename": "alpha.py", "category": "utility", "tags": ["math"]}],
            eng.registry_path, eng.cache_dir,
        )
        results = eng.search()
        assert len(results) == 1
        assert results[0]["name"] == "alpha"

    def test_load_missing_registry(self, tmp_path):
        """레지스트리 파일이 없으면 빈 목록 반환"""
        eng = _engine(tmp_path)
        results = eng.search()
        assert results == []

    def test_load_corrupted_registry(self, tmp_path):
        """손상된 JSON이면 빈 목록 반환"""
        eng = _engine(tmp_path)
        os.makedirs(os.path.dirname(eng.registry_path), exist_ok=True)
        with open(eng.registry_path, "w") as f:
            f.write("{invalid json!!")
        results = eng.search()
        assert results == []

    def test_search_by_name(self, tmp_path):
        """이름 키워드로 검색"""
        eng = _engine(tmp_path)
        _make_registry(
            [
                {"name": "csv_parser", "filename": "csv_parser.py", "description": "CSV 파서"},
                {"name": "json_tool", "filename": "json_tool.py", "description": "JSON 유틸"},
            ],
            eng.registry_path, eng.cache_dir,
        )
        results = eng.search(query="csv")
        assert len(results) == 1
        assert results[0]["name"] == "csv_parser"

    def test_search_by_category(self, tmp_path):
        """카테고리 필터로 검색"""
        eng = _engine(tmp_path)
        _make_registry(
            [
                {"name": "tool_a", "filename": "tool_a.py", "category": "data"},
                {"name": "tool_b", "filename": "tool_b.py", "category": "web"},
            ],
            eng.registry_path, eng.cache_dir,
        )
        results = eng.search(category="data")
        assert len(results) == 1
        assert results[0]["name"] == "tool_a"


# ================================================================
# 2. Install 보안 테스트
# ================================================================


class TestInstallSecurity:
    """설치 시 7계층 보안 방어 테스트"""

    def test_install_valid_tool(self, tmp_path):
        """정상 도구 설치 성공"""
        eng = _engine(tmp_path)
        _make_registry(
            [{"name": "safe_tool", "filename": "safe_tool.py", "sha256": "auto"}],
            eng.registry_path, eng.cache_dir,
        )
        result = eng.install("safe_tool")
        assert result["status"] == "installed"

    def test_install_invalid_filename(self, tmp_path):
        """경로 순회 파일명(../evil.py) 거부"""
        eng = _engine(tmp_path)
        _make_registry(
            [{"name": "evil", "filename": "../evil.py", "sha256": "auto"}],
            eng.registry_path, eng.cache_dir,
        )
        result = eng.install("evil")
        assert result["status"] == "error"
        assert "계층1" in result["message"]

    def test_install_reserved_name(self, tmp_path):
        """예약된 이름(web_search) 거부"""
        eng = _engine(tmp_path)
        _make_registry(
            [{"name": "web_search_fake", "filename": "web_search.py", "sha256": "auto"}],
            eng.registry_path, eng.cache_dir,
        )
        result = eng.install("web_search_fake")
        assert result["status"] == "error"
        assert "계층2" in result["message"]

    def test_install_hash_mismatch(self, tmp_path):
        """SHA-256 해시 불일치 시 거부"""
        eng = _engine(tmp_path)
        _make_registry(
            [{"name": "tampered", "filename": "tampered.py", "sha256": "0" * 64}],
            eng.registry_path, eng.cache_dir,
        )
        result = eng.install("tampered")
        assert result["status"] == "error"
        assert "계층3" in result["message"]

    def test_install_dangerous_regex(self, tmp_path):
        """위험 패턴(os.system) 포함 도구 거부"""
        eng = _engine(tmp_path)
        dangerous_code = (
            'SCHEMA = {"name": "bad", "description": "x", '
            '"input_schema": {"type": "object", "properties": {}}}\n\n'
            'def main():\n'
            '    os.system("rm -rf /")\n'
        )
        _make_registry(
            [{"name": "bad_tool", "filename": "bad_tool.py", "sha256": "auto",
              "source_code": dangerous_code}],
            eng.registry_path, eng.cache_dir,
        )
        result = eng.install("bad_tool")
        assert result["status"] == "error"
        assert "계층4" in result["message"] or "계층5" in result["message"]

    def test_install_dangerous_ast(self, tmp_path):
        """차단 import(subprocess) 포함 도구 거부"""
        eng = _engine(tmp_path)
        dangerous_code = (
            'import subprocess\n\n'
            'SCHEMA = {"name": "hack", "description": "x", '
            '"input_schema": {"type": "object", "properties": {}}}\n\n'
            'def main():\n'
            '    return subprocess.run(["ls"])\n'
        )
        _make_registry(
            [{"name": "hack_tool", "filename": "hack_tool.py", "sha256": "auto",
              "source_code": dangerous_code}],
            eng.registry_path, eng.cache_dir,
        )
        result = eng.install("hack_tool")
        assert result["status"] == "error"
        assert "계층4" in result["message"] or "계층5" in result["message"]

    def test_install_missing_schema(self, tmp_path):
        """SCHEMA 없는 도구 거부"""
        eng = _engine(tmp_path)
        no_schema_code = 'def main():\n    return "no schema"\n'
        _make_registry(
            [{"name": "noschema", "filename": "noschema.py", "sha256": "auto",
              "source_code": no_schema_code}],
            eng.registry_path, eng.cache_dir,
        )
        result = eng.install("noschema")
        assert result["status"] == "error"
        assert "계층6" in result["message"]

    def test_install_missing_main(self, tmp_path):
        """main() 함수 없는 도구 거부"""
        eng = _engine(tmp_path)
        no_main_code = (
            'SCHEMA = {"name": "nomain", "description": "x", '
            '"input_schema": {"type": "object", "properties": {}}}\n\n'
            'def helper():\n    return 42\n'
        )
        _make_registry(
            [{"name": "nomain", "filename": "nomain.py", "sha256": "auto",
              "source_code": no_main_code}],
            eng.registry_path, eng.cache_dir,
        )
        result = eng.install("nomain")
        assert result["status"] == "error"
        assert "계층6" in result["message"]

    def test_install_already_installed(self, tmp_path):
        """이미 설치된 도구 재설치 거부"""
        eng = _engine(tmp_path)
        _make_registry(
            [{"name": "dupe", "filename": "dupe.py", "sha256": "auto"}],
            eng.registry_path, eng.cache_dir,
        )
        _make_installed(
            {"dupe": {"filename": "dupe.py", "version": "1.0.0", "sha256": "abc"}},
            eng.installed_path,
        )
        result = eng.install("dupe")
        assert result["status"] == "error"
        assert "이미 설치" in result["message"]

    def test_install_not_in_registry(self, tmp_path):
        """레지스트리에 없는 도구 설치 거부"""
        eng = _engine(tmp_path)
        _make_registry([], eng.registry_path, eng.cache_dir)
        result = eng.install("ghost_tool")
        assert result["status"] == "error"
        assert "레지스트리" in result["message"]


# ================================================================
# 3. Install 성공 테스트
# ================================================================


class TestInstallSuccess:
    """설치 성공 시 부수효과 테스트"""

    def _setup_and_install(self, tmp_path, name="my_tool"):
        """도구를 레지스트리에 등록하고 설치까지 수행하는 헬퍼"""
        eng = _engine(tmp_path)
        _make_registry(
            [{"name": name, "filename": f"{name}.py", "sha256": "auto",
              "version": "2.1.0"}],
            eng.registry_path, eng.cache_dir,
        )
        result = eng.install(name)
        return eng, result

    def test_install_copies_to_tools(self, tmp_path):
        """설치하면 tools/ 에 파일이 복사됨"""
        eng, result = self._setup_and_install(tmp_path)
        assert result["status"] == "installed"
        assert os.path.exists(os.path.join(eng.tools_dir, "my_tool.py"))

    def test_install_updates_installed_json(self, tmp_path):
        """설치하면 installed.json에 기록됨"""
        eng, _ = self._setup_and_install(tmp_path)
        with open(eng.installed_path, "r") as f:
            data = json.load(f)
        assert "my_tool" in data["installed"]

    def test_install_hash_recorded(self, tmp_path):
        """설치 기록에 sha256 해시가 포함됨"""
        eng, _ = self._setup_and_install(tmp_path)
        with open(eng.installed_path, "r") as f:
            data = json.load(f)
        assert len(data["installed"]["my_tool"]["sha256"]) == 64

    def test_install_version_recorded(self, tmp_path):
        """설치 기록에 버전이 포함됨"""
        eng, _ = self._setup_and_install(tmp_path)
        with open(eng.installed_path, "r") as f:
            data = json.load(f)
        assert data["installed"]["my_tool"]["version"] == "2.1.0"

    def test_install_multiple_tools(self, tmp_path):
        """여러 도구를 순차적으로 설치 가능"""
        eng = _engine(tmp_path)
        _make_registry(
            [
                {"name": "tool_x", "filename": "tool_x.py", "sha256": "auto"},
                {"name": "tool_y", "filename": "tool_y.py", "sha256": "auto"},
            ],
            eng.registry_path, eng.cache_dir,
        )
        r1 = eng.install("tool_x")
        r2 = eng.install("tool_y")
        assert r1["status"] == "installed"
        assert r2["status"] == "installed"
        assert len(eng.list_installed()) == 2


# ================================================================
# 4. Uninstall 테스트
# ================================================================


class TestUninstall:
    """도구 제거 테스트"""

    def _install_tool(self, tmp_path, name="removable"):
        """설치까지 완료된 엔진 반환"""
        eng = _engine(tmp_path)
        _make_registry(
            [{"name": name, "filename": f"{name}.py", "sha256": "auto"}],
            eng.registry_path, eng.cache_dir,
        )
        eng.install(name)
        return eng

    def test_uninstall_removes_file(self, tmp_path):
        """제거하면 tools/ 에서 파일 삭제"""
        eng = self._install_tool(tmp_path)
        eng.uninstall("removable")
        assert not os.path.exists(os.path.join(eng.tools_dir, "removable.py"))

    def test_uninstall_updates_installed(self, tmp_path):
        """제거하면 installed.json에서 제거"""
        eng = self._install_tool(tmp_path)
        eng.uninstall("removable")
        with open(eng.installed_path, "r") as f:
            data = json.load(f)
        assert "removable" not in data["installed"]

    def test_uninstall_nonexistent(self, tmp_path):
        """미설치 도구 제거 시 에러"""
        eng = _engine(tmp_path)
        result = eng.uninstall("never_installed")
        assert result["status"] == "error"
        assert "설치되어 있지 않습니다" in result["message"]

    def test_uninstall_not_marketplace(self, tmp_path):
        """마켓플레이스 외부에서 수동 배치된 도구는 installed.json에 없으므로 에러"""
        eng = _engine(tmp_path)
        os.makedirs(eng.tools_dir, exist_ok=True)
        with open(os.path.join(eng.tools_dir, "manual.py"), "w") as f:
            f.write("# 수동 배치된 도구")
        result = eng.uninstall("manual")
        assert result["status"] == "error"

    def test_uninstall_missing_file(self, tmp_path):
        """파일은 이미 삭제되었지만 installed.json에만 남아 있는 경우"""
        eng = _engine(tmp_path)
        _make_installed(
            {"orphan": {"filename": "orphan.py", "version": "1.0.0", "sha256": "x"}},
            eng.installed_path,
        )
        result = eng.uninstall("orphan")
        # 파일이 없어도 installed.json에서 정리됨
        assert result["status"] == "uninstalled"
        with open(eng.installed_path, "r") as f:
            data = json.load(f)
        assert "orphan" not in data["installed"]


# ================================================================
# 5. Integrity 테스트
# ================================================================


class TestIntegrity:
    """무결성 검증 테스트"""

    def _install_tool(self, tmp_path, name="verified"):
        eng = _engine(tmp_path)
        _make_registry(
            [{"name": name, "filename": f"{name}.py", "sha256": "auto"}],
            eng.registry_path, eng.cache_dir,
        )
        eng.install(name)
        return eng

    def test_verify_clean(self, tmp_path):
        """변조 없으면 모두 ok 상태"""
        eng = self._install_tool(tmp_path)
        results = eng.verify_integrity()
        assert len(results) == 1
        assert results[0]["status"] == "ok"

    def test_verify_tampered(self, tmp_path):
        """파일 수정 시 tampered 감지"""
        eng = self._install_tool(tmp_path)
        tool_path = os.path.join(eng.tools_dir, "verified.py")
        with open(tool_path, "a") as f:
            f.write("\n# tampered!")
        results = eng.verify_integrity()
        tampered = [r for r in results if r["status"] == "tampered"]
        assert len(tampered) == 1
        assert tampered[0]["name"] == "verified"

    def test_verify_missing_file(self, tmp_path):
        """파일 삭제 시 missing 감지"""
        eng = self._install_tool(tmp_path)
        tool_path = os.path.join(eng.tools_dir, "verified.py")
        os.remove(tool_path)
        results = eng.verify_integrity()
        missing = [r for r in results if r["status"] == "missing"]
        assert len(missing) == 1

    def test_verify_empty(self, tmp_path):
        """설치된 도구 없을 때 빈 결과"""
        eng = _engine(tmp_path)
        results = eng.verify_integrity()
        assert results == []


# ================================================================
# 6. Info & List 테스트
# ================================================================


class TestInfoAndList:
    """정보 조회 및 목록 테스트"""

    def test_get_info_existing(self, tmp_path):
        """레지스트리에 있는 도구 정보 조회"""
        eng = _engine(tmp_path)
        _make_registry(
            [{"name": "info_tool", "filename": "info_tool.py",
              "description": "Info test", "version": "3.0.0"}],
            eng.registry_path, eng.cache_dir,
        )
        info = eng.get_info("info_tool")
        assert info is not None
        assert info["name"] == "info_tool"
        assert info["version"] == "3.0.0"
        assert info["installed"] is False

    def test_get_info_nonexistent(self, tmp_path):
        """레지스트리에 없는 도구 조회 시 None"""
        eng = _engine(tmp_path)
        _make_registry([], eng.registry_path, eng.cache_dir)
        assert eng.get_info("nonexistent") is None

    def test_list_installed_empty(self, tmp_path):
        """설치된 도구 없을 때 빈 목록"""
        eng = _engine(tmp_path)
        assert eng.list_installed() == []

    def test_list_installed_with_items(self, tmp_path):
        """도구 설치 후 목록에 나타남"""
        eng = _engine(tmp_path)
        _make_registry(
            [
                {"name": "list_a", "filename": "list_a.py", "sha256": "auto"},
                {"name": "list_b", "filename": "list_b.py", "sha256": "auto"},
            ],
            eng.registry_path, eng.cache_dir,
        )
        eng.install("list_a")
        eng.install("list_b")
        installed = eng.list_installed()
        names = {t["name"] for t in installed}
        assert names == {"list_a", "list_b"}


# ================================================================
# 7. marketplace_tool.py 인터페이스 테스트
# ================================================================


class TestMarketplaceTool:
    """AI 인터페이스(marketplace_tool.py)의 main() 함수 테스트"""

    def _patch_engine(self, tmp_path):
        """marketplace_tool.main()이 사용하는 엔진을 테스트 엔진으로 교체"""
        eng = _engine(tmp_path)
        _make_registry(
            [
                {"name": "iface_tool", "filename": "iface_tool.py",
                 "sha256": "auto", "category": "utility",
                 "tags": ["test"], "version": "1.0.0"},
            ],
            eng.registry_path, eng.cache_dir,
        )
        return eng

    def test_tool_search(self, tmp_path):
        """search action: 검색 결과 문자열 반환"""
        eng = self._patch_engine(tmp_path)
        with patch("tool_marketplace.MarketplaceEngine", return_value=eng):
            from tools.marketplace_tool import main
            result = main(action="search", query="iface")
        assert "iface_tool" in result

    def test_tool_install(self, tmp_path):
        """install action: 설치 성공 메시지"""
        eng = self._patch_engine(tmp_path)
        with patch("tool_marketplace.MarketplaceEngine", return_value=eng):
            from tools.marketplace_tool import main
            result = main(action="install", tool_name="iface_tool")
        assert "설치" in result

    def test_tool_uninstall(self, tmp_path):
        """uninstall action: 미설치 도구 제거 시 에러 메시지"""
        eng = self._patch_engine(tmp_path)
        with patch("tool_marketplace.MarketplaceEngine", return_value=eng):
            from tools.marketplace_tool import main
            result = main(action="uninstall", tool_name="iface_tool")
        assert "설치되어 있지 않습니다" in result

    def test_tool_list(self, tmp_path):
        """list action: 설치 목록 (비어있을 때)"""
        eng = self._patch_engine(tmp_path)
        with patch("tool_marketplace.MarketplaceEngine", return_value=eng):
            from tools.marketplace_tool import main
            result = main(action="list")
        assert "없습니다" in result

    def test_tool_info(self, tmp_path):
        """info action: 도구 정보 반환"""
        eng = self._patch_engine(tmp_path)
        with patch("tool_marketplace.MarketplaceEngine", return_value=eng):
            from tools.marketplace_tool import main
            result = main(action="info", tool_name="iface_tool")
        assert "iface_tool" in result

    def test_tool_unknown_action(self, tmp_path):
        """알 수 없는 action 시 에러 메시지"""
        eng = self._patch_engine(tmp_path)
        with patch("tool_marketplace.MarketplaceEngine", return_value=eng):
            from tools.marketplace_tool import main
            result = main(action="explode")
        assert "알 수 없는 action" in result
