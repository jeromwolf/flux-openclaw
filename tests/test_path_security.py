"""경로 보안 테스트"""
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch


class TestReadTextFileSecurity:
    """read_text_file 경로 보안 테스트"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_workspace, monkeypatch):
        """워크스페이스를 현재 디렉토리로 설정"""
        monkeypatch.chdir(temp_workspace)
        # tools 모듈 경로 추가
        tools_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
        if tools_path not in sys.path:
            sys.path.insert(0, tools_path)

    def _read(self, path):
        from tools.read_text_file import main
        return main(path)

    def test_read_normal_file(self):
        """정상 파일 읽기"""
        result = self._read("test.txt")
        assert result == "hello world"

    def test_read_nested_file(self):
        """중첩 파일 읽기"""
        result = self._read("sub/nested.txt")
        assert result == "nested content"

    def test_block_path_traversal_dotdot(self):
        """../ 경로 탈출 차단"""
        result = self._read("../../../etc/passwd")
        assert "Error" in result

    def test_block_absolute_path(self):
        """절대 경로 차단"""
        result = self._read("/etc/passwd")
        assert "Error" in result

    def test_block_env_file(self):
        """`.env` 파일 읽기 차단"""
        Path(".env").write_text("SECRET=value")
        result = self._read(".env")
        assert "Error" in result

    def test_block_env_local(self):
        """.env.local 읽기 차단"""
        Path(".env.local").write_text("SECRET=value")
        result = self._read(".env.local")
        assert "Error" in result

    def test_block_history_dir(self):
        """history/ 디렉토리 읽기 차단"""
        Path("history").mkdir(exist_ok=True)
        Path("history/chat.json").write_text("{}")
        result = self._read("history/chat.json")
        assert "Error" in result

    def test_block_log_file(self):
        """log.md 읽기 차단"""
        Path("log.md").write_text("log data")
        result = self._read("log.md")
        assert "Error" in result

    def test_masks_api_keys(self):
        """API 키 마스킹"""
        Path("config.txt").write_text("key=sk-ant-api03-abc123def456_xyz")
        result = self._read("config.txt")
        assert "sk-ant-" not in result
        assert "REDACTED" in result

    def test_nonexistent_file(self):
        """존재하지 않는 파일"""
        result = self._read("nonexistent.txt")
        assert "Error" in result


class TestSaveTextFileSecurity:
    """save_text_file 경로 보안 테스트"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_workspace, monkeypatch):
        monkeypatch.chdir(temp_workspace)
        tools_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
        if tools_path not in sys.path:
            sys.path.insert(0, tools_path)

    def _save(self, path, content):
        from tools.save_text_file import main
        return main(path, content)

    def test_save_normal_file(self):
        """정상 파일 저장"""
        result = self._save("new.txt", "content")
        assert "저장 완료" in result
        assert Path("new.txt").read_text() == "content"

    def test_block_path_traversal(self):
        """경로 탈출 차단"""
        result = self._save("../../evil.txt", "hack")
        assert "Error" in result

    def test_block_env_write(self):
        """.env 파일 쓰기 차단"""
        result = self._save(".env", "STOLEN=yes")
        assert "Error" in result

    def test_block_main_py_write(self):
        """main.py 쓰기 차단"""
        result = self._save("main.py", "hacked")
        assert "Error" in result

    def test_block_tools_dir_write(self):
        """tools/ 디렉토리 쓰기 차단"""
        Path("tools").mkdir(exist_ok=True)
        result = self._save("tools/evil.py", "import os")
        assert "Error" in result

    def test_block_large_content(self):
        """1MB 초과 콘텐츠 차단"""
        large_content = "x" * (1024 * 1024 + 1)
        result = self._save("large.txt", large_content)
        assert "Error" in result

    def test_block_absolute_path_write(self):
        """절대 경로 쓰기 차단"""
        result = self._save("/tmp/evil.txt", "hack")
        assert "Error" in result

    def test_creates_parent_dirs(self):
        """부모 디렉토리 자동 생성"""
        result = self._save("newdir/file.txt", "content")
        assert "저장 완료" in result
        assert Path("newdir/file.txt").read_text() == "content"
