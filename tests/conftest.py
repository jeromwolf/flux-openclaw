import os
import sys
import json
import tempfile
import shutil
import pytest

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def temp_tools_dir(tmp_path):
    """임시 도구 디렉토리"""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    return str(tools_dir)


@pytest.fixture
def safe_tool_file(temp_tools_dir):
    """안전한 도구 파일 생성"""
    code = '''
SCHEMA = {
    "name": "test_add",
    "description": "두 수를 더합니다",
    "input_schema": {
        "type": "object",
        "properties": {
            "a": {"type": "integer", "description": "첫번째 숫자"},
            "b": {"type": "integer", "description": "두번째 숫자"},
        },
        "required": ["a", "b"],
    },
}

def main(a, b):
    return a + b

if __name__ == "__main__":
    print(main(1, 2))
'''
    path = os.path.join(temp_tools_dir, "test_add.py")
    with open(path, "w") as f:
        f.write(code)
    return path


@pytest.fixture
def temp_workspace(tmp_path):
    """임시 워크스페이스 (파일 도구 테스트용)"""
    ws = tmp_path / "workspace"
    ws.mkdir()
    # 테스트 파일 생성
    (ws / "test.txt").write_text("hello world")
    (ws / "sub").mkdir()
    (ws / "sub" / "nested.txt").write_text("nested content")
    return ws


@pytest.fixture
def usage_file(tmp_path):
    """임시 usage_data.json"""
    path = tmp_path / "usage_data.json"
    return str(path)
