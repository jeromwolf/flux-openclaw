"""
flux-openclaw 헬스체크 서버

데몬 프로세스의 liveness probe를 위한 경량 HTTP 서버입니다.

사용법:
    from openclaw.health import HealthServer
    server = HealthServer(port=8766)
    server.start_background()  # 데몬 스레드로 실행
"""

import os
import json
import time
import threading
import logging
import http.server


_start_time = time.time()


class HealthHandler(http.server.BaseHTTPRequestHandler):
    """헬스체크 HTTP 핸들러"""

    def do_GET(self):
        if self.path == "/health":
            self._handle_health()
        elif self.path == "/health/ready":
            self._handle_ready()
        else:
            self._send_json({"error": "Not Found"}, 404)

    def _handle_health(self):
        """기본 헬스체크 — 프로세스 생존 확인"""
        uptime = int(time.time() - _start_time)
        data = {
            "status": "ok",
            "uptime_seconds": uptime,
        }
        self._send_json(data, 200)

    def _handle_ready(self):
        """레디니스 체크 — 서비스 가용성 확인"""
        checks = {}
        ready = True

        # core.py 로드 가능 여부
        try:
            import core
            checks["core"] = "ok"
        except Exception:
            checks["core"] = "fail"
            ready = False

        # tools 디렉토리 존재 여부
        checks["tools_dir"] = "ok" if os.path.isdir("tools") else "fail"

        status_code = 200 if ready else 503
        data = {
            "status": "ready" if ready else "not_ready",
            "checks": checks,
        }
        self._send_json(data, status_code)

    def _send_json(self, data, status_code=200):
        """JSON 응답 전송"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """기본 액세스 로그 억제"""
        pass


class HealthServer:
    """경량 HTTP 헬스체크 서버"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8766):
        self.host = host
        self.port = port
        self._server = None
        self._thread = None

    def start_background(self):
        """백그라운드 데몬 스레드로 서버 시작"""
        try:
            self._server = http.server.HTTPServer(
                (self.host, self.port), HealthHandler
            )
        except OSError:
            logging.getLogger("flux-openclaw.health").warning(
                "Health server failed to bind %s:%d", self.host, self.port
            )
            return  # 포트 사용 중이면 무시
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="health-server",
        )
        self._thread.start()

    def stop(self):
        """서버 종료"""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def start_health_server(host: str = "127.0.0.1", port: int = 8766) -> HealthServer:
    """헬스체크 서버 시작 편의 함수"""
    server = HealthServer(host, port)
    server.start_background()
    return server
