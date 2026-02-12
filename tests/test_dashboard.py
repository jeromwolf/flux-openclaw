"""
dashboard.py 테스트

DashboardHandler의 인증, JSON 응답, 정적 파일 서빙, API 라우팅,
엔드포인트 핸들러, 요청 본문 처리를 단위 테스트한다.
ThreadingHTTPServer를 실제로 기동하지 않고, mock을 활용하여
핸들러 메서드를 직접 호출한다.
"""
import pytest
import os
import sys
import json
import time
from unittest.mock import patch, MagicMock
from io import BytesIO
from http.client import HTTPMessage
from email.message import Message

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openclaw.dashboard_server as dashboard_module
from openclaw.dashboard_server import DashboardHandler, _MAX_BODY_SIZE


# ============================================================
# Fixture
# ============================================================

@pytest.fixture
def handler():
    """mock DashboardHandler 인스턴스 (실제 소켓 연결 없음)"""
    with patch.object(DashboardHandler, "__init__", lambda self, *args, **kwargs: None):
        h = DashboardHandler()

    # BaseHTTPRequestHandler가 기대하는 속성 설정
    h.headers = Message()
    h.rfile = BytesIO()
    h.wfile = BytesIO()
    h.requestline = ""
    h.request_version = "HTTP/1.1"
    h.client_address = ("127.0.0.1", 12345)
    h.server = MagicMock()

    # 응답 메서드 mock
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()

    return h


@pytest.fixture
def authed_handler(handler, monkeypatch):
    """유효한 Bearer 토큰이 설정된 핸들러"""
    monkeypatch.setenv("DASHBOARD_TOKEN", "test-secret-token")
    handler.headers["Authorization"] = "Bearer test-secret-token"
    return handler


# ============================================================
# 1. 인증 (Authentication) 테스트
# ============================================================

class TestAuth:
    """Bearer 토큰 인증 검증"""

    def test_auth_valid_token(self, handler, monkeypatch):
        """올바른 Bearer 토큰으로 인증 성공"""
        monkeypatch.setenv("DASHBOARD_TOKEN", "my-secret")
        handler.headers["Authorization"] = "Bearer my-secret"
        assert handler._check_auth() is True

    def test_auth_invalid_token(self, handler, monkeypatch):
        """잘못된 Bearer 토큰으로 인증 실패"""
        monkeypatch.setenv("DASHBOARD_TOKEN", "correct-token")
        handler.headers["Authorization"] = "Bearer wrong-token"
        assert handler._check_auth() is False

    def test_auth_missing_header(self, handler, monkeypatch):
        """Authorization 헤더 없을 때 인증 실패"""
        monkeypatch.setenv("DASHBOARD_TOKEN", "my-secret")
        # headers에 Authorization 없음
        assert handler._check_auth() is False

    def test_auth_no_bearer_prefix(self, handler, monkeypatch):
        """'Bearer ' 접두사 없이 토큰만 보내면 인증 실패"""
        monkeypatch.setenv("DASHBOARD_TOKEN", "my-secret")
        handler.headers["Authorization"] = "my-secret"
        assert handler._check_auth() is False

    def test_auth_no_env_token(self, handler, monkeypatch):
        """DASHBOARD_TOKEN 환경변수 미설정 시 인증 실패"""
        monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
        handler.headers["Authorization"] = "Bearer some-token"
        assert handler._check_auth() is False


# ============================================================
# 2. JSON 응답 헬퍼 테스트
# ============================================================

class TestSendJson:
    """_send_json 헬퍼 메서드 검증"""

    def test_send_json_200(self, handler):
        """200 상태로 올바른 JSON 응답 전송"""
        data = {"status": "ok", "count": 42}
        handler._send_json(data, 200)

        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call(
            "Content-Type", "application/json; charset=utf-8"
        )
        handler.end_headers.assert_called_once()

        # wfile에 기록된 JSON 파싱
        written = handler.wfile.getvalue()
        parsed = json.loads(written.decode("utf-8"))
        assert parsed == data

    def test_send_json_401(self, handler):
        """401 상태로 에러 JSON 응답 전송"""
        data = {"error": "인증 실패"}
        handler._send_json(data, 401)

        handler.send_response.assert_called_once_with(401)
        written = handler.wfile.getvalue()
        parsed = json.loads(written.decode("utf-8"))
        assert parsed["error"] == "인증 실패"

    def test_send_json_404(self, handler):
        """404 상태로 에러 JSON 응답 전송"""
        data = {"error": "알 수 없는 엔드포인트", "path": "/api/unknown"}
        handler._send_json(data, 404)

        handler.send_response.assert_called_once_with(404)
        written = handler.wfile.getvalue()
        parsed = json.loads(written.decode("utf-8"))
        assert parsed["error"] == "알 수 없는 엔드포인트"
        assert parsed["path"] == "/api/unknown"


# ============================================================
# 3. 정적 파일 서빙 테스트
# ============================================================

class TestStaticServing:
    """정적 파일 서빙 및 경로 보안 검증"""

    def _patch_dashboard_file(self, tmp_path):
        """dashboard 모듈의 __file__을 tmp_path 내부로 임시 변경하는 컨텍스트매니저"""
        return patch.object(
            dashboard_module, "__file__", str(tmp_path / "dashboard.py")
        )

    def test_serve_root_redirects(self, handler, tmp_path):
        """GET / 요청 시 dashboard/index.html 서빙"""
        dashboard_dir = tmp_path / "dashboard"
        dashboard_dir.mkdir()
        index_file = dashboard_dir / "index.html"
        index_file.write_text("<html><body>Dashboard</body></html>", encoding="utf-8")

        handler.path = "/"

        with self._patch_dashboard_file(tmp_path):
            handler._serve_static()

        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call("Content-Type", "text/html; charset=utf-8")
        written = handler.wfile.getvalue()
        assert b"Dashboard" in written

    def test_serve_html_file(self, handler, tmp_path):
        """HTML 파일 서빙 시 text/html Content-Type"""
        dashboard_dir = tmp_path / "dashboard"
        dashboard_dir.mkdir()
        page = dashboard_dir / "page.html"
        page.write_text("<h1>Page</h1>", encoding="utf-8")

        handler.path = "/dashboard/page.html"

        with self._patch_dashboard_file(tmp_path):
            handler._serve_static()

        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call("Content-Type", "text/html; charset=utf-8")

    def test_serve_css_file(self, handler, tmp_path):
        """CSS 파일 서빙 시 text/css Content-Type"""
        dashboard_dir = tmp_path / "dashboard"
        dashboard_dir.mkdir()
        css = dashboard_dir / "style.css"
        css.write_text("body { color: red; }", encoding="utf-8")

        handler.path = "/dashboard/style.css"

        with self._patch_dashboard_file(tmp_path):
            handler._serve_static()

        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call("Content-Type", "text/css; charset=utf-8")

    def test_serve_js_file(self, handler, tmp_path):
        """JS 파일 서빙 시 application/javascript Content-Type"""
        dashboard_dir = tmp_path / "dashboard"
        dashboard_dir.mkdir()
        js = dashboard_dir / "app.js"
        js.write_text("console.log('hello');", encoding="utf-8")

        handler.path = "/dashboard/app.js"

        with self._patch_dashboard_file(tmp_path):
            handler._serve_static()

        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call(
            "Content-Type", "application/javascript; charset=utf-8"
        )

    def test_serve_path_traversal_blocked(self, handler, tmp_path):
        """경로 탐색 공격(../)이 403 또는 404로 차단됨"""
        dashboard_dir = tmp_path / "dashboard"
        dashboard_dir.mkdir()

        handler.path = "/dashboard/../../../etc/passwd"

        with self._patch_dashboard_file(tmp_path):
            handler._serve_static()

        # 403(접근 거부) 또는 404(파일 없음) 중 하나가 반환되어야 함
        response_code = handler.send_response.call_args[0][0]
        assert response_code in (403, 404)


# ============================================================
# 4. API 라우팅 테스트
# ============================================================

class TestAPIRouting:
    """GET/POST API 라우팅 검증"""

    def test_get_routes_status(self, authed_handler):
        """GET /api/status가 올바르게 라우팅됨"""
        authed_handler.path = "/api/status"
        with patch.object(authed_handler, "_handle_status") as mock_handler:
            authed_handler._route_api_get()
            mock_handler.assert_called_once()

    def test_get_routes_tools(self, authed_handler):
        """GET /api/tools가 올바르게 라우팅됨"""
        authed_handler.path = "/api/tools"
        with patch.object(authed_handler, "_handle_tools_list") as mock_handler:
            authed_handler._route_api_get()
            mock_handler.assert_called_once()

    def test_post_routes_knowledge(self, authed_handler):
        """POST /api/knowledge/search가 올바르게 라우팅됨"""
        authed_handler.path = "/api/knowledge/search"
        with patch.object(authed_handler, "_handle_knowledge_search") as mock_handler:
            authed_handler._route_api_post()
            mock_handler.assert_called_once()

    def test_unknown_route_404(self, authed_handler):
        """알 수 없는 API 경로는 404 반환"""
        authed_handler.path = "/api/nonexistent"
        authed_handler._route_api_get()

        # wfile에 JSON이 기록되었는지 확인
        written = authed_handler.wfile.getvalue()
        parsed = json.loads(written.decode("utf-8"))
        assert parsed["error"] == "알 수 없는 엔드포인트"
        authed_handler.send_response.assert_called_once_with(404)


# ============================================================
# 5. API 엔드포인트 테스트
# ============================================================

class TestAPIEndpoints:
    """개별 API 엔드포인트 핸들러 검증"""

    def test_api_status(self, authed_handler):
        """GET /api/status가 예상 키를 포함하는 dict 반환"""
        with patch("openclaw.dashboard_server._get_tool_manager", return_value=None), \
             patch("openclaw.dashboard_server._get_memory_store", return_value=None), \
             patch("openclaw.dashboard_server._get_scheduler", return_value=None), \
             patch("openclaw.dashboard_server._get_knowledge_base", return_value=None), \
             patch("openclaw.dashboard_server._get_marketplace", return_value=None):

            authed_handler._handle_status()

        written = authed_handler.wfile.getvalue()
        parsed = json.loads(written.decode("utf-8"))
        assert parsed["status"] == "running"
        assert "uptime_seconds" in parsed
        assert "uptime_hours" in parsed
        assert "server_start" in parsed
        assert "current_time" in parsed
        assert "tools_loaded" in parsed
        assert "services" in parsed
        assert "memory_stats" in parsed

    def test_api_usage(self, authed_handler, tmp_path):
        """GET /api/usage가 usage_data.json의 내용을 반환"""
        usage_data = {
            "date": "2026-02-11",
            "calls": 100,
            "input_tokens": 5000,
            "output_tokens": 3000,
        }
        usage_file = tmp_path / "usage_data.json"
        usage_file.write_text(json.dumps(usage_data), encoding="utf-8")

        with patch("openclaw.dashboard_server.os.path.exists", return_value=True), \
             patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__ = lambda s: BytesIO(
                json.dumps(usage_data).encode("utf-8")
            )
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            authed_handler._handle_usage()

        written = authed_handler.wfile.getvalue()
        parsed = json.loads(written.decode("utf-8"))
        assert parsed["date"] == "2026-02-11"
        assert parsed["calls"] == 100

    def test_api_tools(self, authed_handler):
        """GET /api/tools가 도구 목록 반환"""
        mock_mgr = MagicMock()
        mock_mgr.schemas = [
            {"name": "test_tool", "description": "테스트 도구", "input_schema": {}},
            {"name": "another_tool", "description": "다른 도구", "input_schema": {}},
        ]

        with patch("openclaw.dashboard_server._get_tool_manager", return_value=mock_mgr):
            authed_handler._handle_tools_list()

        written = authed_handler.wfile.getvalue()
        parsed = json.loads(written.decode("utf-8"))
        assert parsed["count"] == 2
        assert len(parsed["tools"]) == 2
        assert parsed["tools"][0]["name"] == "test_tool"

    def test_api_memory_list(self, authed_handler):
        """GET /api/memory가 메모리 목록 반환"""
        mock_store = MagicMock()
        mock_store._load.return_value = [
            {"id": "m1", "category": "notes", "key": "k1", "value": "v1"},
            {"id": "m2", "category": "facts", "key": "k2", "value": "v2"},
        ]

        with patch("openclaw.dashboard_server._get_memory_store", return_value=mock_store):
            authed_handler._handle_memory_list()

        written = authed_handler.wfile.getvalue()
        parsed = json.loads(written.decode("utf-8"))
        assert parsed["count"] == 2
        assert len(parsed["memories"]) == 2

    def test_api_knowledge_stats(self, authed_handler):
        """GET /api/knowledge가 지식 베이스 통계 반환"""
        mock_kb = MagicMock()
        mock_kb.get_stats.return_value = {"total_documents": 10}
        mock_kb.list_documents.return_value = [{"title": "doc1"}, {"title": "doc2"}]

        with patch("openclaw.dashboard_server._get_knowledge_base", return_value=mock_kb):
            authed_handler._handle_knowledge_stats()

        written = authed_handler.wfile.getvalue()
        parsed = json.loads(written.decode("utf-8"))
        assert parsed["available"] is True
        assert parsed["stats"]["total_documents"] == 10
        assert len(parsed["documents"]) == 2

    def test_api_knowledge_search(self, authed_handler):
        """POST /api/knowledge/search가 검색 결과 반환"""
        mock_kb = MagicMock()
        mock_kb.search.return_value = [
            {"title": "result1", "score": 0.9},
            {"title": "result2", "score": 0.7},
        ]

        # 요청 본문 설정
        body = json.dumps({"query": "테스트 검색"}).encode("utf-8")
        authed_handler.rfile = BytesIO(body)
        authed_handler.headers["Content-Length"] = str(len(body))

        with patch("openclaw.dashboard_server._get_knowledge_base", return_value=mock_kb):
            authed_handler._handle_knowledge_search()

        written = authed_handler.wfile.getvalue()
        parsed = json.loads(written.decode("utf-8"))
        assert parsed["query"] == "테스트 검색"
        assert len(parsed["results"]) == 2
        mock_kb.search.assert_called_once_with("테스트 검색")


# ============================================================
# 6. 요청 본문 처리 테스트
# ============================================================

class TestRequestBody:
    """_read_body 메서드 검증"""

    def test_read_body(self, handler):
        """올바른 JSON 본문을 정상적으로 파싱"""
        payload = {"query": "hello", "limit": 10}
        body = json.dumps(payload).encode("utf-8")
        handler.rfile = BytesIO(body)
        handler.headers["Content-Length"] = str(len(body))

        result = handler._read_body()
        assert result == payload

    def test_body_size_limit(self, handler):
        """1MB 초과 본문은 413 에러로 거부"""
        handler.headers["Content-Length"] = str(_MAX_BODY_SIZE + 1)

        result = handler._read_body()
        assert result is None

        # 413 상태 코드로 응답했는지 확인
        handler.send_response.assert_called_once_with(413)
        written = handler.wfile.getvalue()
        parsed = json.loads(written.decode("utf-8"))
        assert "error" in parsed
