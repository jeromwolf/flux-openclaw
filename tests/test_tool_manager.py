"""ToolManager 보안 기능 테스트"""
import os
import json
import pytest
from unittest.mock import patch
from core import ToolManager


class TestCheckDangerous:
    """위험 패턴 regex 탐지 테스트"""

    def test_detects_os_system(self):
        mgr = ToolManager.__new__(ToolManager)
        assert mgr._check_dangerous("os.system('rm -rf /')")

    def test_detects_subprocess(self):
        mgr = ToolManager.__new__(ToolManager)
        assert mgr._check_dangerous("import subprocess")

    def test_detects_eval(self):
        mgr = ToolManager.__new__(ToolManager)
        assert mgr._check_dangerous("eval(user_input)")

    def test_detects_exec(self):
        mgr = ToolManager.__new__(ToolManager)
        assert mgr._check_dangerous("exec(code)")

    def test_detects_import_trick(self):
        mgr = ToolManager.__new__(ToolManager)
        assert mgr._check_dangerous("__import__('os')")

    def test_detects_pickle(self):
        mgr = ToolManager.__new__(ToolManager)
        assert mgr._check_dangerous("import pickle")

    def test_detects_open(self):
        mgr = ToolManager.__new__(ToolManager)
        assert mgr._check_dangerous("f = open('/etc/passwd')")

    def test_safe_code_passes(self):
        mgr = ToolManager.__new__(ToolManager)
        safe_code = """
def main(a, b):
    return a + b
"""
        assert not mgr._check_dangerous(safe_code)

    def test_detects_builtins_access(self):
        mgr = ToolManager.__new__(ToolManager)
        assert mgr._check_dangerous("__builtins__['eval']")

    def test_detects_subclasses(self):
        mgr = ToolManager.__new__(ToolManager)
        assert mgr._check_dangerous("().__class__.__subclasses__()")


class TestCheckDangerousAST:
    """AST 기반 위험 코드 탐지 테스트"""

    def test_blocks_subprocess_import(self):
        mgr = ToolManager.__new__(ToolManager)
        findings = mgr._check_dangerous_ast("import subprocess")
        assert any("subprocess" in f for f in findings)

    def test_blocks_from_import(self):
        mgr = ToolManager.__new__(ToolManager)
        findings = mgr._check_dangerous_ast("from subprocess import run")
        assert any("subprocess" in f for f in findings)

    def test_blocks_ctypes(self):
        mgr = ToolManager.__new__(ToolManager)
        findings = mgr._check_dangerous_ast("import ctypes")
        assert any("ctypes" in f for f in findings)

    def test_blocks_os_remove(self):
        mgr = ToolManager.__new__(ToolManager)
        findings = mgr._check_dangerous_ast("os.remove('/tmp/file')")
        assert any("os.remove" in f for f in findings)

    def test_blocks_eval_builtin(self):
        mgr = ToolManager.__new__(ToolManager)
        findings = mgr._check_dangerous_ast("result = eval('1+1')")
        assert any("eval" in f for f in findings)

    def test_blocks_exec_builtin(self):
        mgr = ToolManager.__new__(ToolManager)
        findings = mgr._check_dangerous_ast("exec('print(1)')")
        assert any("exec" in f for f in findings)

    def test_blocks_dunder_access(self):
        mgr = ToolManager.__new__(ToolManager)
        findings = mgr._check_dangerous_ast("x.__builtins__")
        assert any("__builtins__" in f for f in findings)

    def test_safe_code_passes(self):
        mgr = ToolManager.__new__(ToolManager)
        safe = """
SCHEMA = {"name": "test"}
def main():
    return "hello"
"""
        findings = mgr._check_dangerous_ast(safe)
        assert findings == []

    def test_syntax_error_detected(self):
        mgr = ToolManager.__new__(ToolManager)
        findings = mgr._check_dangerous_ast("def (broken")
        assert "SyntaxError" in findings

    def test_blocks_nested_import(self):
        mgr = ToolManager.__new__(ToolManager)
        findings = mgr._check_dangerous_ast("import http.server")
        assert any("http" in f for f in findings)

    def test_blocks_webbrowser(self):
        mgr = ToolManager.__new__(ToolManager)
        findings = mgr._check_dangerous_ast("import webbrowser")
        assert any("webbrowser" in f for f in findings)

    def test_blocks_multiprocessing(self):
        mgr = ToolManager.__new__(ToolManager)
        findings = mgr._check_dangerous_ast("import multiprocessing")
        assert any("multiprocessing" in f for f in findings)


class TestToolLoading:
    """도구 로딩 테스트"""

    def test_loads_safe_tool(self, temp_tools_dir, safe_tool_file):
        """안전한 도구 파일 로드"""
        # stdin이 tty가 아닌 환경에서는 자동 차단되므로, 해시 승인 파일 미리 생성
        import hashlib
        with open(safe_tool_file, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        approved_path = ".tool_approved.json"
        with open(approved_path, "w") as f:
            json.dump({"test_add.py": file_hash}, f)
        try:
            mgr = ToolManager(tools_dir=temp_tools_dir)
            assert "test_add" in mgr.functions
            assert len(mgr.schemas) == 1
            assert mgr.functions["test_add"](3, 4) == 7
        finally:
            if os.path.exists(approved_path):
                os.remove(approved_path)

    def test_empty_tools_dir(self, temp_tools_dir):
        """빈 도구 디렉토리"""
        # 기존 파일 삭제
        for f in os.listdir(temp_tools_dir):
            os.remove(os.path.join(temp_tools_dir, f))
        mgr = ToolManager(tools_dir=temp_tools_dir)
        assert mgr.functions == {}
        assert mgr.schemas == []

    def test_nonexistent_tools_dir(self, tmp_path):
        """존재하지 않는 디렉토리"""
        mgr = ToolManager(tools_dir=str(tmp_path / "nonexistent"))
        assert mgr.functions == {}

    def test_file_hash_consistency(self):
        """동일 내용은 동일 해시"""
        mgr = ToolManager.__new__(ToolManager)
        data = b"hello world"
        assert mgr._file_hash(data) == mgr._file_hash(data)

    def test_file_hash_changes(self):
        """다른 내용은 다른 해시"""
        mgr = ToolManager.__new__(ToolManager)
        assert mgr._file_hash(b"hello") != mgr._file_hash(b"world")
