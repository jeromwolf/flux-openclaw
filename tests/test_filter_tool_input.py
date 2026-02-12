"""도구 입력 필터링 테스트"""
import pytest
from core import _filter_tool_input


class TestFilterToolInput:
    """_filter_tool_input 함수 테스트"""

    @pytest.fixture
    def sample_schema(self):
        return {
            "name": "test_tool",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                    "active": {"type": "boolean"},
                    "score": {"type": "number"},
                },
            },
        }

    def test_filters_unknown_keys(self, sample_schema):
        """스키마에 없는 키 제거"""
        result = _filter_tool_input(
            {"name": "test", "evil_key": "malicious"},
            sample_schema
        )
        assert "name" in result
        assert "evil_key" not in result

    def test_keeps_valid_keys(self, sample_schema):
        """유효한 키 유지"""
        result = _filter_tool_input(
            {"name": "test", "age": 25, "active": True},
            sample_schema
        )
        assert result == {"name": "test", "age": 25, "active": True}

    def test_rejects_wrong_type_string(self, sample_schema):
        """문자열 타입 불일치 거부"""
        result = _filter_tool_input(
            {"name": 123},  # should be string
            sample_schema
        )
        assert "name" not in result

    def test_rejects_wrong_type_integer(self, sample_schema):
        """정수 타입 불일치 거부"""
        result = _filter_tool_input(
            {"age": "not a number"},
            sample_schema
        )
        assert "age" not in result

    def test_rejects_wrong_type_boolean(self, sample_schema):
        """불리언 타입 불일치 거부"""
        result = _filter_tool_input(
            {"active": "yes"},
            sample_schema
        )
        assert "active" not in result

    def test_accepts_int_for_number(self, sample_schema):
        """number 타입에 int 허용"""
        result = _filter_tool_input(
            {"score": 100},
            sample_schema
        )
        assert result["score"] == 100

    def test_accepts_float_for_number(self, sample_schema):
        """number 타입에 float 허용"""
        result = _filter_tool_input(
            {"score": 99.5},
            sample_schema
        )
        assert result["score"] == 99.5

    def test_empty_input(self, sample_schema):
        """빈 입력"""
        result = _filter_tool_input({}, sample_schema)
        assert result == {}

    def test_schema_without_properties(self):
        """속성 없는 스키마"""
        schema = {"name": "test", "input_schema": {"type": "object"}}
        result = _filter_tool_input({"anything": "goes"}, schema)
        assert result == {"anything": "goes"}

    def test_injection_via_extra_keys(self, sample_schema):
        """추가 키를 통한 인젝션 시도 방어"""
        result = _filter_tool_input(
            {"name": "test", "__class__": "exploit", "constructor": "bad"},
            sample_schema
        )
        assert "__class__" not in result
        assert "constructor" not in result
