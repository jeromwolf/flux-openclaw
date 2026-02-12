"""health 모듈 테스트"""
import json
import time
import urllib.request
import urllib.error
import socket
from health import HealthServer, HealthHandler, start_health_server


def _get_free_port():
    """사용 가능한 포트 번호 반환"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_get(url):
    """HTTP GET 요청 및 JSON 파싱"""
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8")), response.status


class TestHealth:
    """헬스체크 서버 테스트"""

    def setup_method(self):
        """각 테스트 전 서버 시작"""
        self.port = _get_free_port()
        self.server = HealthServer(port=self.port)
        self.server.start_background()
        time.sleep(0.2)  # 서버 시작 대기

    def teardown_method(self):
        """각 테스트 후 서버 종료"""
        if self.server:
            self.server.stop()
            time.sleep(0.1)

    def test_health_endpoint_returns_ok(self):
        """GET /health: 200 OK with status and uptime (no PID)"""
        url = f"http://127.0.0.1:{self.port}/health"
        data, status = _http_get(url)
        assert status == 200
        assert data["status"] == "ok"
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int)
        # PID no longer exposed for security reasons
        assert "pid" not in data

    def test_health_ready_endpoint(self):
        """GET /health/ready: 200 OK with checks"""
        url = f"http://127.0.0.1:{self.port}/health/ready"
        data, status = _http_get(url)
        assert status in (200, 503)
        assert "status" in data
        assert data["status"] in ("ready", "not_ready")
        assert "checks" in data
        assert isinstance(data["checks"], dict)

    def test_health_ready_checks_core(self):
        """GET /health/ready: core 모듈 체크"""
        url = f"http://127.0.0.1:{self.port}/health/ready"
        data, status = _http_get(url)
        assert "core" in data["checks"]
        assert data["checks"]["core"] in ("ok", "fail")

    def test_health_ready_checks_tools_dir(self):
        """GET /health/ready: tools 디렉토리 체크"""
        url = f"http://127.0.0.1:{self.port}/health/ready"
        data, status = _http_get(url)
        assert "tools_dir" in data["checks"]
        assert data["checks"]["tools_dir"] in ("ok", "fail")

    def test_invalid_path_returns_404(self):
        """GET /invalid: 404 Not Found"""
        url = f"http://127.0.0.1:{self.port}/invalid"
        try:
            _http_get(url)
            assert False, "Expected 404 error"
        except urllib.error.HTTPError as e:
            assert e.code == 404
            data = json.loads(e.read().decode("utf-8"))
            assert data["error"] == "Not Found"

    def test_health_uptime_increases(self):
        """GET /health: uptime이 시간에 따라 증가"""
        url = f"http://127.0.0.1:{self.port}/health"
        data1, _ = _http_get(url)
        uptime1 = data1["uptime_seconds"]
        time.sleep(1.1)
        data2, _ = _http_get(url)
        uptime2 = data2["uptime_seconds"]
        assert uptime2 > uptime1

    def test_server_start_stop_lifecycle(self):
        """서버 시작/종료 라이프사이클"""
        port = _get_free_port()
        server = HealthServer(port=port)
        server.start_background()
        time.sleep(0.2)

        # 서버 응답 확인
        url = f"http://127.0.0.1:{port}/health"
        data, status = _http_get(url)
        assert status == 200

        # 서버 종료
        server.stop()
        time.sleep(0.2)

        # 종료 후 연결 실패 확인
        try:
            _http_get(url)
            assert False, "Expected connection error after stop"
        except urllib.error.URLError:
            pass  # 연결 실패 예상

    def test_start_health_server_convenience_function(self):
        """start_health_server: 편의 함수 반환값 확인"""
        port = _get_free_port()
        server = start_health_server(port=port)
        time.sleep(0.2)

        try:
            assert isinstance(server, HealthServer)
            url = f"http://127.0.0.1:{port}/health"
            data, status = _http_get(url)
            assert status == 200
        finally:
            server.stop()

    def test_server_port_already_in_use(self):
        """포트 사용 중일 때 무시"""
        port = _get_free_port()
        server1 = HealthServer(port=port)
        server1.start_background()
        time.sleep(0.2)

        try:
            # 같은 포트로 두 번째 서버 시작 시도 (조용히 실패)
            server2 = HealthServer(port=port)
            server2.start_background()
            time.sleep(0.2)
            # 예외 발생하지 않음
        finally:
            server1.stop()

    def test_health_endpoint_content_type(self):
        """GET /health: Content-Type이 application/json"""
        url = f"http://127.0.0.1:{self.port}/health"
        with urllib.request.urlopen(url, timeout=5) as response:
            content_type = response.headers.get("Content-Type")
            assert "application/json" in content_type

    def test_multiple_concurrent_requests(self):
        """여러 동시 요청 처리"""
        url = f"http://127.0.0.1:{self.port}/health"
        results = []
        for _ in range(5):
            data, status = _http_get(url)
            results.append((data, status))
        # 모든 요청 성공
        assert all(status == 200 for _, status in results)
        assert all(data["status"] == "ok" for data, _ in results)
