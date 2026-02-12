"""
plugin_sdk.py 테스트 슈트

새 도구 생성, 보안 검사, 테스트, 패키징 기능을 검증합니다.
"""

import pytest
import os
import json
import hashlib
from pathlib import Path

# plugin_sdk 모듈의 함수들 임포트
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from plugin_sdk import validate_name, cmd_new, cmd_check, cmd_test, cmd_package


# ============================================================================
# 픽스처
# ============================================================================

@pytest.fixture
def sample_tool(tmp_path):
    """안전한 샘플 도구 파일 생성"""
    tool_file = tmp_path / "sample_tool.py"
    tool_file.write_text('''
SCHEMA = {
    "name": "sample_tool",
    "description": "테스트용 샘플 도구",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "입력 텍스트"},
        },
        "required": ["text"],
    },
}

def main(text):
    return f"결과: {text}"

if __name__ == "__main__":
    import json
    print(json.dumps(SCHEMA, indent=2))
''')
    return str(tool_file)


@pytest.fixture
def dangerous_tool(tmp_path):
    """위험 패턴이 있는 도구 파일 생성"""
    tool_file = tmp_path / "dangerous_tool.py"
    tool_file.write_text('''
import subprocess

SCHEMA = {
    "name": "dangerous",
    "description": "위험한 도구",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

def main():
    return subprocess.run(["ls"], capture_output=True).stdout
''')
    return str(tool_file)


@pytest.fixture
def missing_schema_tool(tmp_path):
    """SCHEMA가 없는 도구 파일 생성"""
    tool_file = tmp_path / "missing_schema.py"
    tool_file.write_text('''
def main(text):
    return f"결과: {text}"
''')
    return str(tool_file)


@pytest.fixture
def missing_main_tool(tmp_path):
    """main 함수가 없는 도구 파일 생성"""
    tool_file = tmp_path / "missing_main.py"
    tool_file.write_text('''
SCHEMA = {
    "name": "missing_main",
    "description": "main 함수가 없는 도구",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}
''')
    return str(tool_file)


@pytest.fixture
def mismatch_params_tool(tmp_path):
    """SCHEMA와 main() 파라미터가 일치하지 않는 도구"""
    tool_file = tmp_path / "mismatch_params.py"
    tool_file.write_text('''
SCHEMA = {
    "name": "mismatch_params",
    "description": "파라미터 불일치",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "텍스트"},
        },
        "required": ["text"],
    },
}

def main(different_param):
    return f"결과: {different_param}"
''')
    return str(tool_file)


# ============================================================================
# 1. New Command Tests (4 tests)
# ============================================================================

def test_new_creates_file(tmp_path, monkeypatch):
    """새 도구 파일이 정상적으로 생성되는지 검증"""
    monkeypatch.chdir(tmp_path)

    class Args:
        name = "my_tool"
        description = None

    result = cmd_new(Args())
    assert result == 0
    assert (tmp_path / "my_tool.py").exists()

    content = (tmp_path / "my_tool.py").read_text()
    assert "my_tool" in content
    assert "SCHEMA" in content
    assert "def main(" in content


def test_new_with_description(tmp_path, monkeypatch):
    """커스텀 설명이 생성된 파일에 포함되는지 검증"""
    monkeypatch.chdir(tmp_path)

    class Args:
        name = "custom_tool"
        description = "커스텀 설명입니다"

    result = cmd_new(Args())
    assert result == 0

    content = (tmp_path / "custom_tool.py").read_text()
    assert "커스텀 설명입니다" in content


def test_new_invalid_name(tmp_path, monkeypatch):
    """잘못된 이름 형식을 거부하는지 검증"""
    monkeypatch.chdir(tmp_path)

    # 대문자 포함
    class Args1:
        name = "MyTool"
        description = None
    assert cmd_new(Args1()) == 1

    # 특수문자 포함
    class Args2:
        name = "my-tool"
        description = None
    assert cmd_new(Args2()) == 1

    # 너무 짧음
    class Args3:
        name = "a"
        description = None
    assert cmd_new(Args3()) == 1


def test_new_no_overwrite(tmp_path, monkeypatch):
    """기존 파일을 덮어쓰지 않는지 검증"""
    monkeypatch.chdir(tmp_path)

    # 첫 번째 생성
    class Args:
        name = "existing_tool"
        description = None

    result1 = cmd_new(Args())
    assert result1 == 0

    # 두 번째 생성 시도 (실패해야 함)
    result2 = cmd_new(Args())
    assert result2 == 1


# ============================================================================
# 2. Check Command Tests (5 tests)
# ============================================================================

def test_check_clean_file(sample_tool):
    """안전한 도구 파일에서 문제가 없음을 보고하는지 검증"""
    class Args:
        file = sample_tool

    result = cmd_check(Args())
    assert result == 0


def test_check_dangerous_regex(tmp_path):
    """위험한 정규식 패턴을 감지하는지 검증"""
    tool_file = tmp_path / "dangerous_regex.py"
    tool_file.write_text('''
import os

SCHEMA = {
    "name": "dangerous_regex",
    "description": "위험한 도구",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

def main():
    os.system("ls")
    return "done"
''')

    class Args:
        file = str(tool_file)

    result = cmd_check(Args())
    assert result == 1


def test_check_dangerous_ast(dangerous_tool):
    """AST 분석으로 위험한 import를 감지하는지 검증"""
    class Args:
        file = dangerous_tool

    result = cmd_check(Args())
    assert result == 1


def test_check_missing_schema(missing_schema_tool):
    """SCHEMA 누락 시 경고를 발생시키는지 검증"""
    class Args:
        file = missing_schema_tool

    result = cmd_check(Args())
    # WARNING만 있으면 exit code 0 (CRITICAL이 없으므로)
    assert result == 0


def test_check_missing_main(missing_main_tool):
    """main 함수 누락 시 경고를 발생시키는지 검증"""
    class Args:
        file = missing_main_tool

    result = cmd_check(Args())
    # WARNING만 있으면 exit code 0
    assert result == 0


# ============================================================================
# 3. Test Command Tests (3 tests)
# ============================================================================

def test_test_valid_tool(sample_tool):
    """정상적인 도구 파일이 테스트를 통과하는지 검증"""
    class Args:
        file = sample_tool

    result = cmd_test(Args())
    assert result == 0


def test_test_schema_validation(tmp_path):
    """SCHEMA 구조가 검증되는지 확인"""
    # SCHEMA에 필수 필드가 없는 경우
    tool_file = tmp_path / "invalid_schema.py"
    tool_file.write_text('''
SCHEMA = {
    "name": "invalid_schema",
    # description 필드 누락
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

def main():
    return "done"
''')

    class Args:
        file = str(tool_file)

    result = cmd_test(Args())
    assert result == 1


def test_test_parameter_mismatch(mismatch_params_tool, capsys):
    """SCHEMA와 main() 파라미터 불일치를 감지하는지 검증"""
    class Args:
        file = mismatch_params_tool

    result = cmd_test(Args())
    # 경고는 발생하지만 샘플 실행은 실패함
    assert result == 1

    captured = capsys.readouterr()
    # 파라미터 불일치 경고 또는 샘플 실행 실패 메시지가 있어야 함
    assert "경고" in captured.out or "실패" in captured.out


# ============================================================================
# 4. Package Command Tests (3 tests)
# ============================================================================

def test_package_valid_tool(sample_tool, capsys):
    """정상적인 도구가 올바른 registry 엔트리를 생성하는지 검증"""
    class Args:
        file = sample_tool

    result = cmd_package(Args())
    assert result == 0

    captured = capsys.readouterr()
    output = captured.out

    # JSON 출력이 포함되어 있는지 확인
    assert "name" in output
    assert "sample_tool" in output
    assert "sha256" in output


def test_package_includes_hash(sample_tool, capsys):
    """SHA-256 해시가 계산되어 포함되는지 검증"""
    class Args:
        file = sample_tool

    result = cmd_package(Args())
    assert result == 0

    captured = capsys.readouterr()
    output = captured.out

    # 실제 파일의 해시 계산
    with open(sample_tool, "rb") as f:
        expected_hash = hashlib.sha256(f.read()).hexdigest()

    assert expected_hash in output


def test_package_fails_on_dangerous(dangerous_tool):
    """보안 문제가 있는 도구는 패키징이 실패하는지 검증"""
    class Args:
        file = dangerous_tool

    result = cmd_package(Args())
    assert result == 1


# ============================================================================
# 추가 테스트: validate_name 함수 직접 테스트
# ============================================================================

def test_validate_name():
    """validate_name 함수의 정규식 검증 로직 테스트"""
    # 유효한 이름들
    assert validate_name("my_tool") is True
    assert validate_name("tool123") is True
    assert validate_name("a_b_c") is True

    # 무효한 이름들
    assert validate_name("MyTool") is False  # 대문자
    assert validate_name("my-tool") is False  # 하이픈
    assert validate_name("a") is False  # 너무 짧음
    assert validate_name("1tool") is False  # 숫자로 시작
    assert validate_name("tool!") is False  # 특수문자
