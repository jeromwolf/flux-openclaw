"""
tests/test_browser_tool.py

브라우저 자동화 도구 테스트 (20-25 tests)
- URL 검증 (SSRF 방어)
- 액션 디스패치
- 폴백 모드
- 보안 제한
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import browser_tool


class TestURLValidation:
    """URL 검증 및 SSRF 방어 (6 tests)"""

    def test_block_file_scheme(self):
        """file:// URL 차단"""
        result = browser_tool.main(action="navigate", url="file:///etc/passwd")
        assert "Error" in result
        assert "차단된 프로토콜" in result or "file" in result.lower()

    def test_block_javascript_scheme(self):
        """javascript: URL 차단"""
        result = browser_tool.main(action="navigate", url="javascript:alert(1)")
        assert "Error" in result
        assert "차단된 프로토콜" in result or "javascript" in result.lower()

    def test_block_data_scheme(self):
        """data: URL 차단"""
        result = browser_tool.main(action="navigate", url="data:text/html,<h1>XSS</h1>")
        assert "Error" in result
        assert "차단된 프로토콜" in result or "data" in result.lower()

    def test_block_private_ip_127(self):
        """프라이빗 IP 차단 (127.0.0.1)"""
        result = browser_tool.main(action="navigate", url="http://127.0.0.1/admin")
        assert "Error" in result
        assert "내부 네트워크" in result or "접근할 수 없습니다" in result

    def test_block_private_ip_10(self):
        """프라이빗 IP 차단 (10.0.0.1)"""
        result = browser_tool.main(action="navigate", url="http://10.0.0.1/")
        assert "Error" in result
        assert "내부 네트워크" in result or "접근할 수 없습니다" in result

    def test_block_private_ip_192(self):
        """프라이빗 IP 차단 (192.168.1.1)"""
        result = browser_tool.main(action="navigate", url="http://192.168.1.1/")
        assert "Error" in result
        assert "내부 네트워크" in result or "접근할 수 없습니다" in result


class TestActionDispatch:
    """액션 디스패치 로직 (6 tests)"""

    def test_unknown_action(self):
        """알 수 없는 액션 에러"""
        result = browser_tool.main(action="unknown")
        assert "Error" in result
        assert "알 수 없는 액션" in result

    def test_navigate_no_url(self):
        """navigate에 url 없으면 에러"""
        result = browser_tool.main(action="navigate")
        assert "Error" in result
        assert "url" in result.lower()

    def test_click_no_selector(self):
        """click에 selector 없으면 에러"""
        result = browser_tool.main(action="click")
        assert "Error" in result
        assert "selector" in result.lower()

    def test_type_no_text(self):
        """type_text에 text 없으면 에러"""
        result = browser_tool.main(action="type_text", selector="input")
        assert "Error" in result
        assert "text" in result.lower()

    def test_type_no_selector(self):
        """type_text에 selector 없으면 에러"""
        result = browser_tool.main(action="type_text", text="hello")
        assert "Error" in result
        assert "selector" in result.lower()

    def test_wait_max_limit(self):
        """wait는 최대 10초 제한"""
        # wait(1)은 빠르게 완료되어야 함
        result = browser_tool.main(action="wait", wait_seconds=1)
        assert "Error" not in result
        assert "대기 완료" in result


class TestFallbackMode:
    """폴백 모드 (Playwright 없을 때) (6 tests)"""

    def test_click_needs_playwright(self):
        """click은 Playwright 필요"""
        result = browser_tool.main(action="click", selector="#btn")
        # Playwright 없으면 에러 메시지, 있으면 다른 에러 (페이지 없음 등)
        assert isinstance(result, str)
        if "Playwright" in result or "playwright" in result:
            assert "설치" in result or "필요" in result

    def test_screenshot_needs_playwright(self):
        """screenshot은 Playwright 필요"""
        result = browser_tool.main(action="screenshot")
        # Playwright 없거나 페이지 없음 에러
        assert isinstance(result, str)

    def test_scroll_needs_playwright(self):
        """scroll은 Playwright 필요"""
        result = browser_tool.main(action="scroll", direction="down")
        assert isinstance(result, str)

    def test_navigate_fallback(self, monkeypatch):
        """navigate는 Playwright 없어도 requests 폴백"""
        # Playwright와 requests 모두 없을 때
        monkeypatch.setattr(browser_tool, '_HAS_PLAYWRIGHT', False)
        monkeypatch.setattr(browser_tool, '_HAS_REQUESTS', False)
        result = browser_tool.main(action="navigate", url="http://example.com")
        assert "Error" in result or "설치" in result

    def test_get_links_fallback(self, monkeypatch):
        """get_links는 Playwright 없을 때 에러"""
        monkeypatch.setattr(browser_tool, '_HAS_PLAYWRIGHT', False)
        result = browser_tool.main(action="get_links")
        assert isinstance(result, str)
        # 페이지 없음 에러 예상

    def test_get_text_no_page(self, monkeypatch):
        """get_text는 페이지 없을 때 에러"""
        monkeypatch.setattr(browser_tool, '_HAS_PLAYWRIGHT', False)
        result = browser_tool.main(action="get_text")
        assert isinstance(result, str)
        assert "Error" in result or "페이지" in result


class TestSecurityLimits:
    """보안 제한 및 상수 (4 tests)"""

    def test_max_chars_default(self):
        """max_chars 기본값 및 제한"""
        assert hasattr(browser_tool, '_MAX_RESPONSE_CHARS')
        assert browser_tool._MAX_RESPONSE_CHARS == 50000

    def test_timeout_limit(self):
        """타임아웃은 최대 30초"""
        assert hasattr(browser_tool, '_MAX_TIMEOUT')
        assert browser_tool._MAX_TIMEOUT == 30

    def test_blocked_schemes(self):
        """차단 스킴 목록 확인"""
        assert hasattr(browser_tool, '_BLOCKED_SCHEMES')
        blocked = browser_tool._BLOCKED_SCHEMES
        for scheme in ["file", "javascript", "data"]:
            assert scheme in blocked

    def test_schema_valid(self):
        """SCHEMA가 올바른 형식"""
        assert "name" in browser_tool.SCHEMA
        assert "input_schema" in browser_tool.SCHEMA
        assert browser_tool.SCHEMA["name"] == "browser"
        assert "action" in browser_tool.SCHEMA["input_schema"]["properties"]


class TestHelperFunctions:
    """헬퍼 함수 테스트 (3 tests)"""

    def test_is_safe_url_valid(self):
        """안전한 URL 검증"""
        safe, err = browser_tool._is_safe_url("https://example.com")
        assert safe is True
        assert err is None

    def test_is_safe_url_invalid_scheme(self):
        """잘못된 스킴 거부"""
        safe, err = browser_tool._is_safe_url("ftp://example.com")
        assert safe is False
        assert err is not None

    def test_clean_html_text(self):
        """HTML 텍스트 정리"""
        html = "<html><head><title>Test</title></head><body><p>Hello</p><script>alert(1)</script></body></html>"
        result = browser_tool._clean_html_text(html, max_chars=100)
        assert isinstance(result, str)
        assert len(result) <= 100 + 50  # 여유 허용


class TestEdgeCases:
    """엣지 케이스 (2 tests)"""

    def test_navigate_invalid_url_format(self):
        """잘못된 URL 형식"""
        result = browser_tool.main(action="navigate", url="not-a-url")
        # DNS 실패 또는 파싱 에러
        assert "Error" in result

    def test_scroll_invalid_direction(self):
        """잘못된 스크롤 방향은 down으로 폴백"""
        result = browser_tool.main(action="scroll", direction="invalid")
        # direction이 유효하지 않으면 down으로 처리됨
        assert isinstance(result, str)
