"""
flux-openclaw 웹 대시보드 HTTP API 서버

관리용 웹 대시보드 백엔드. 표준 라이브러리만 사용.
- 시스템 상태, 도구 관리, 메모리, 스케줄, 지식 베이스 REST API
- 정적 파일 서빙 (dashboard/ 디렉토리)
- Bearer 토큰 인증 (DASHBOARD_TOKEN 환경변수)
- 127.0.0.1 바인딩 (로컬 전용)

사용법:
    DASHBOARD_TOKEN=my-secret python3 dashboard.py
"""

import os
import json
import hmac
import time
import http.server
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from typing import Optional

_SERVER_START_TIME = time.time()
_MAX_BODY_SIZE = 1_048_576  # 요청 본문 크기 제한 (1MB)

# CORS 설정 싱글턴
_cors_config = None

# Webhook 싱글턴
_webhook_store = None
_webhook_dispatcher = None

def _get_webhook_store():
    """WebhookStore 싱글턴 반환."""
    global _webhook_store
    if _webhook_store is None:
        try:
            from openclaw.webhook import WebhookStore
            _webhook_store = WebhookStore()
        except ImportError:
            pass
    return _webhook_store

def _get_webhook_dispatcher():
    """WebhookDispatcher 싱글턴 반환."""
    global _webhook_dispatcher
    if _webhook_dispatcher is None:
        store = _get_webhook_store()
        if store:
            try:
                from openclaw.webhook import WebhookDispatcher
                _webhook_dispatcher = WebhookDispatcher(store)
            except ImportError:
                pass
    return _webhook_dispatcher

def _get_cors_config():
    """CORSConfig 싱글턴 반환."""
    global _cors_config
    if _cors_config is None:
        try:
            from openclaw.cors import create_cors_config
            from config import get_config
            cfg = get_config()
            _cors_config = create_cors_config(
                allowed_origins_str=cfg.cors_allowed_origins,
                max_age=cfg.cors_max_age,
            )
        except ImportError:
            return None
    return _cors_config

# 지연 임포트 헬퍼 — 의존성 미설치 시 안전하게 None 반환

def _get_memory_store():
    """MemoryStore 인스턴스 반환 (임포트 실패 시 None)"""
    try:
        from openclaw.memory_store import MemoryStore
        return MemoryStore()
    except ImportError:
        return None

def _get_scheduler():
    """Scheduler 인스턴스 반환 (임포트 실패 시 None)"""
    try:
        from openclaw.scheduler import Scheduler
        return Scheduler()
    except ImportError:
        return None

def _get_knowledge_base():
    """KnowledgeBase 인스턴스 반환 (임포트 실패 시 None)"""
    try:
        from openclaw.knowledge_base import KnowledgeBase
        return KnowledgeBase()
    except ImportError:
        return None

def _get_marketplace():
    """MarketplaceEngine 인스턴스 반환 (임포트 실패 시 None)"""
    try:
        from openclaw.tool_marketplace import MarketplaceEngine
        return MarketplaceEngine()
    except ImportError:
        return None

def _get_tool_manager():
    """ToolManager 인스턴스 반환 (임포트 실패 시 None)"""
    try:
        from core import ToolManager
        return ToolManager()
    except ImportError:
        return None

def _get_conversation_store():
    """ConversationStore 인스턴스 반환 (임포트 실패 시 None)"""
    try:
        from openclaw.conversation_store import ConversationStore
        from config import get_config
        cfg = get_config()
        return ConversationStore(cfg.conversation_db_path)
    except ImportError:
        return None

def _get_user_store():
    """UserStore 인스턴스 반환 (임포트 실패 시 None)"""
    try:
        from openclaw.auth import UserStore
        from config import get_config
        return UserStore(get_config().auth_db_path)
    except ImportError:
        return None

# Rate limiter 싱글턴
_rate_limiter = None

def _get_rate_limiter():
    """HTTPRateLimiter 싱글턴 반환."""
    global _rate_limiter
    if _rate_limiter is None:
        try:
            from openclaw.rate_limiter import HTTPRateLimiter
            from config import get_config
            cfg = get_config()
            _rate_limiter = HTTPRateLimiter(
                max_requests=cfg.api_rate_limit,
                window_seconds=cfg.api_rate_window,
            )
        except ImportError:
            pass
    return _rate_limiter

# ChatAPI 싱글턴
_chat_api = None

def _get_chat_api():
    """ChatAPI 싱글턴. 최초 호출 시 ConversationEngine 부트스트래핑."""
    global _chat_api
    if _chat_api is not None:
        return _chat_api
    try:
        from openclaw.conversation_engine import ConversationEngine
        from core import ToolManager, load_system_prompt
        from openclaw.api_gateway import ChatAPI

        provider = None
        client = None
        try:
            from openclaw.llm_provider import get_provider
            provider = get_provider()
        except (ImportError, Exception):
            pass

        if provider is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                return None
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)

        tool_mgr = ToolManager()
        system_prompt = load_system_prompt()
        engine = ConversationEngine(
            provider=provider,
            client=client,
            tool_mgr=tool_mgr,
            system_prompt=system_prompt,
            restricted_tools={"save_text_file", "screen_capture"},
        )
        conv_store = _get_conversation_store()
        _chat_api = ChatAPI(engine, conv_store)
        return _chat_api
    except Exception:
        return None

def _get_audit_logger():
    """AuditLogger 인스턴스 반환 (임포트 실패 시 None)"""
    try:
        from openclaw.audit import AuditLogger
        from config import get_config
        return AuditLogger(get_config().audit_db_path)
    except ImportError:
        return None

def _get_backup_manager():
    """BackupManager 인스턴스 반환 (임포트 실패 시 None)"""
    try:
        from openclaw.backup import BackupManager
        from config import get_config
        return BackupManager(get_config().backup_dir)
    except ImportError:
        return None

# MIME 타입 매핑
_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """대시보드 HTTP 요청 핸들러 — 정적 파일 + REST API"""

    server_version = "flux-dashboard/1.0"
    sys_version = ""

    # ---- 인증 ----

    def _check_auth(self):
        """Bearer 토큰 인증 확인 (hmac.compare_digest 타이밍 안전 비교)"""
        token = os.environ.get("DASHBOARD_TOKEN", "")
        if not token:
            return False  # 토큰 미설정 시 접근 차단
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth[7:], token)

    # ---- 통합 인증 (Phase 9) ----

    def _authenticate(self):
        """통합 인증 체인 (Phase 9).

        인증 우선순위:
        1. auth_enabled=False → DEFAULT_USER (admin)
        2. JWT Bearer 토큰 → UserContext
        3. API 키 (flux_*) → UserContext via UserStore
        4. DASHBOARD_TOKEN → DEFAULT_USER (admin)
        5. None on failure

        Returns:
            UserContext on success, None on failure.
        """
        try:
            from config import get_config
            cfg = get_config()
        except ImportError:
            return None

        # auth_enabled=False → 모든 요청 허용
        if not cfg.auth_enabled:
            try:
                from openclaw.auth import DEFAULT_USER
                return DEFAULT_USER
            except ImportError:
                return None

        auth_header = self.headers.get("Authorization", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

            # 1. JWT 토큰 시도
            if cfg.jwt_secret:
                try:
                    from openclaw.jwt_auth import JWTManager
                    jwt_mgr = JWTManager(cfg.jwt_secret)
                    payload = jwt_mgr.verify(token)
                    if payload:
                        from openclaw.auth import UserContext
                        return UserContext(
                            user_id=payload["sub"],
                            username=payload.get("username", ""),
                            role=payload.get("role", "user"),
                        )
                except Exception:
                    pass

            # 2. API 키 시도 (flux_* prefix)
            if token.startswith("flux_"):
                store = _get_user_store()
                if store:
                    try:
                        user = store.authenticate_api_key(token)
                        if user:
                            from openclaw.auth import UserContext
                            return UserContext(
                                user_id=user.id,
                                username=user.username,
                                role=user.role,
                                max_daily_calls=user.max_daily_calls,
                            )
                    except Exception:
                        pass

            # 3. DASHBOARD_TOKEN 폴백
            dashboard_token = os.environ.get("DASHBOARD_TOKEN", "")
            if dashboard_token and hmac.compare_digest(token, dashboard_token):
                try:
                    from openclaw.auth import DEFAULT_USER
                    return DEFAULT_USER
                except ImportError:
                    return None

        return None

    # ---- 헬퍼 ----

    def _send_json(self, data, status=200):
        """JSON 응답 전송"""
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        # CORS headers
        cors_cfg = _get_cors_config()
        if cors_cfg is not None:
            try:
                from openclaw.cors import get_cors_headers
                origin = self.headers.get("Origin", "") if hasattr(self, "headers") and self.headers else ""
                cors_headers = get_cors_headers(origin, cors_cfg)
                if "Access-Control-Allow-Origin" in cors_headers:
                    self.send_header("Access-Control-Allow-Origin",
                                     cors_headers["Access-Control-Allow-Origin"])
            except ImportError:
                pass
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        """요청 본문 읽기 (크기 제한 적용). 오류 시 None 반환."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "잘못된 Content-Length"}, 400)
            return None
        if length > _MAX_BODY_SIZE:
            self._send_json({"error": "요청 본문이 너무 큽니다 (최대 1MB)"}, 413)
            return None
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": "잘못된 JSON 형식"}, 400)
            return None

    def log_message(self, format, *args):
        """기본 접근 로그 억제"""
        pass

    # ---- HTTP 메서드 ----

    def do_OPTIONS(self):
        """CORS preflight 처리"""
        cors_cfg = _get_cors_config()
        if cors_cfg is not None:
            try:
                from openclaw.cors import get_cors_headers
                origin = self.headers.get("Origin", "")
                headers = get_cors_headers(origin, cors_cfg)
                self.send_response(204)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            except ImportError:
                pass
        # Fallback if CORS not configured
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        # Phase 9 신규 라우트: 통합 인증
        if path == "/metrics":
            return self._handle_metrics()  # 인증 불필요
        if path.startswith("/api/webhooks"):
            ctx = self._authenticate()
            if not ctx:
                return self._send_json({"error": "인증 실패"}, 401)
            return self._handle_webhook_list(ctx)
        if path.startswith("/api/retention/"):
            ctx = self._authenticate()
            if not ctx:
                return self._send_json({"error": "인증 실패"}, 401)
            return self._handle_retention_stats(ctx)

        # 기존 라우트: DASHBOARD_TOKEN 인증 유지
        if self.path.startswith("/api/"):
            if not self._check_auth():
                self._send_json({"error": "인증 실패"}, 401)
                return
            self._route_api_get()
        else:
            self._serve_static()

    def do_POST(self):
        path = urlparse(self.path).path

        # Phase 9 신규 라우트 (v1 경로 변환 전에 먼저 매칭)
        if path == "/api/v1/chat":
            ctx = self._authenticate()
            if not ctx:
                return self._send_json({"error": "인증 실패"}, 401)
            return self._handle_chat_sync(ctx)
        if path == "/api/v1/chat/stream":
            ctx = self._authenticate()
            if not ctx:
                return self._send_json({"error": "인증 실패"}, 401)
            return self._handle_chat_stream(ctx)
        if path == "/api/auth/token":
            return self._handle_auth_token()
        if path == "/api/auth/refresh":
            return self._handle_auth_refresh()
        if path == "/api/auth/revoke":
            ctx = self._authenticate()
            if not ctx:
                return self._send_json({"error": "인증 실패"}, 401)
            return self._handle_auth_revoke(ctx)
        if path == "/api/webhooks":
            ctx = self._authenticate()
            if not ctx:
                return self._send_json({"error": "인증 실패"}, 401)
            return self._handle_webhook_create(ctx)
        if path == "/api/retention/run":
            ctx = self._authenticate()
            if not ctx:
                return self._send_json({"error": "인증 실패"}, 401)
            return self._handle_retention_run(ctx)

        # 기존 라우트: DASHBOARD_TOKEN 인증 유지
        if not self._check_auth():
            self._send_json({"error": "인증 실패"}, 401)
            return
        self._route_api_post()

    def do_DELETE(self):
        path = urlparse(self.path).path

        # Phase 9 신규 라우트: /api/webhooks/{id}
        m = re.match(r"^/api/webhooks/([a-zA-Z0-9_-]+)$", path)
        if m:
            ctx = self._authenticate()
            if not ctx:
                return self._send_json({"error": "인증 실패"}, 401)
            return self._handle_webhook_delete(ctx, m.group(1))

        # 기존 라우트: DASHBOARD_TOKEN 인증 유지
        if not self._check_auth():
            self._send_json({"error": "인증 실패"}, 401)
            return
        self._route_api_delete()

    # ---- API 라우팅 ----

    def _route_api_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        # API versioning: /api/v1/* -> /api/*
        if path.startswith("/api/v1/"):
            path = "/api/" + path[8:]
        query = parse_qs(parsed.query)
        routes = {
            "/api/status": self._handle_status,
            "/api/usage": self._handle_usage,
            "/api/tools": self._handle_tools_list,
            "/api/tools/marketplace": self._handle_marketplace_info,
            "/api/memory": self._handle_memory_list,
            "/api/schedules": self._handle_schedules_list,
            "/api/knowledge": self._handle_knowledge_stats,
            "/api/conversations": lambda: self._handle_conversations_list(query),
            "/api/users": self._handle_users_list,
            "/api/tags": self._handle_tags_list,
            "/api/audit": self._handle_audit_list,
            "/api/backups": self._handle_backups_list,
        }
        handler = routes.get(path)
        if handler:
            handler()
        elif re.match(r"^/api/conversations/([^/]+)/tags$", path):
            conv_id = re.match(r"^/api/conversations/([^/]+)/tags$", path).group(1)
            self._handle_conversation_tags_get(conv_id)
        elif path.startswith("/api/conversations/"):
            conv_id = path.split("/api/conversations/")[1]
            self._handle_conversation_detail(conv_id)
        else:
            self._send_json({"error": "알 수 없는 엔드포인트", "path": path}, 404)

    def _route_api_post(self):
        path = urlparse(self.path).path
        # API versioning: /api/v1/* -> /api/*
        if path.startswith("/api/v1/"):
            path = "/api/" + path[8:]
        routes = {
            "/api/tools/marketplace/install": self._handle_marketplace_install,
            "/api/tools/marketplace/uninstall": self._handle_marketplace_uninstall,
            "/api/memory": self._handle_memory_add,
            "/api/schedules": self._handle_schedule_add,
            "/api/knowledge/search": self._handle_knowledge_search,
            "/api/knowledge/index": self._handle_knowledge_index,
            "/api/users": self._handle_users_create,
            "/api/conversations/search": self._handle_conversations_search,
            "/api/backup": self._handle_backup_create,
        }
        handler = routes.get(path)
        if handler:
            handler()
        elif re.match(r"^/api/conversations/([^/]+)/tags$", path):
            conv_id = re.match(r"^/api/conversations/([^/]+)/tags$", path).group(1)
            self._handle_conversation_tags_add(conv_id)
        else:
            self._send_json({"error": "알 수 없는 엔드포인트", "path": path}, 404)

    def _route_api_delete(self):
        """DELETE 라우팅 — URL에서 리소스 ID 추출"""
        path = urlparse(self.path).path
        # API versioning: /api/v1/* -> /api/*
        if path.startswith("/api/v1/"):
            path = "/api/" + path[8:]
        # /api/memory/<id>
        m = re.match(r"^/api/memory/([a-zA-Z0-9_-]+)$", path)
        if m:
            return self._handle_memory_delete(m.group(1))
        # /api/schedules/<id>
        m = re.match(r"^/api/schedules/([a-zA-Z0-9_-]+)$", path)
        if m:
            return self._handle_schedule_delete(m.group(1))
        self._send_json({"error": "알 수 없는 엔드포인트", "path": path}, 404)

    # ---- 시스템 ----

    def _handle_status(self):
        """GET /api/status — 업타임, 도구, 서비스 상태, 메모리 통계"""
        uptime = time.time() - _SERVER_START_TIME
        tool_mgr = _get_tool_manager()
        tools_loaded = len(tool_mgr.functions) if tool_mgr else 0
        tool_names = list(tool_mgr.functions.keys()) if tool_mgr else []

        # 서비스 가용 여부
        services = {
            "memory_store": _get_memory_store() is not None,
            "scheduler": _get_scheduler() is not None,
            "knowledge_base": _get_knowledge_base() is not None,
            "marketplace": _get_marketplace() is not None,
        }
        # 메모리 통계
        memory_stats = {}
        store = _get_memory_store()
        if store:
            try:
                memories = store._load()
                cats = {}
                for m in memories:
                    c = m.get("category", "unknown")
                    cats[c] = cats.get(c, 0) + 1
                memory_stats = {"total_memories": len(memories), "categories": cats}
            except Exception:
                memory_stats = {"error": "메모리 통계 조회 실패"}

        self._send_json({
            "status": "running",
            "uptime_seconds": round(uptime, 1),
            "uptime_hours": round(uptime / 3600, 2),
            "server_start": datetime.fromtimestamp(_SERVER_START_TIME).isoformat(),
            "current_time": datetime.now().isoformat(),
            "tools_loaded": tools_loaded,
            "tool_names": tool_names,
            "services": services,
            "memory_stats": memory_stats,
        })

    def _handle_usage(self):
        """GET /api/usage — usage_data.json에서 사용량 통계"""
        usage_file = "usage_data.json"
        if os.path.exists(usage_file):
            try:
                with open(usage_file, "r", encoding="utf-8") as f:
                    self._send_json(json.load(f))
                return
            except (json.JSONDecodeError, OSError):
                pass
        self._send_json({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
        })

    # ---- 도구 ----

    def _handle_tools_list(self):
        """GET /api/tools — 로드된 도구 목록"""
        tool_mgr = _get_tool_manager()
        if not tool_mgr:
            return self._send_json({"error": "ToolManager를 사용할 수 없습니다"}, 503)
        tools = [{
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "parameters": s.get("input_schema", {}),
        } for s in tool_mgr.schemas]
        self._send_json({"count": len(tools), "tools": tools})

    def _handle_marketplace_info(self):
        """GET /api/tools/marketplace — 레지스트리 통계 + 도구 목록"""
        mp = _get_marketplace()
        if not mp:
            return self._send_json({"error": "마켓플레이스 엔진을 사용할 수 없습니다"}, 503)
        try:
            self._send_json({"stats": mp.get_stats(), "tools": mp.search()})
        except Exception as e:
            self._send_json({"error": f"마켓플레이스 조회 실패: {e}"}, 500)

    def _handle_marketplace_install(self):
        """POST /api/tools/marketplace/install — 도구 설치 {"tool_name": "..."}"""
        body = self._read_body()
        if body is None:
            return
        tool_name = body.get("tool_name", "")
        if not tool_name:
            return self._send_json({"error": "tool_name이 필요합니다"}, 400)
        mp = _get_marketplace()
        if not mp:
            return self._send_json({"error": "마켓플레이스 엔진을 사용할 수 없습니다"}, 503)
        try:
            result = mp.install(tool_name)
            self._send_json(result, 200 if result.get("status") == "installed" else 400)
        except Exception as e:
            self._send_json({"error": f"설치 실패: {e}"}, 500)

    def _handle_marketplace_uninstall(self):
        """POST /api/tools/marketplace/uninstall — 도구 제거 {"tool_name": "..."}"""
        body = self._read_body()
        if body is None:
            return
        tool_name = body.get("tool_name", "")
        if not tool_name:
            return self._send_json({"error": "tool_name이 필요합니다"}, 400)
        mp = _get_marketplace()
        if not mp:
            return self._send_json({"error": "마켓플레이스 엔진을 사용할 수 없습니다"}, 503)
        try:
            result = mp.uninstall(tool_name)
            self._send_json(result, 200 if result.get("status") == "uninstalled" else 400)
        except Exception as e:
            self._send_json({"error": f"제거 실패: {e}"}, 500)

    # ---- 메모리 ----

    def _handle_memory_list(self):
        """GET /api/memory — 전체 메모리 항목"""
        store = _get_memory_store()
        if not store:
            return self._send_json({"error": "MemoryStore를 사용할 수 없습니다"}, 503)
        try:
            memories = store._load()
            self._send_json({"count": len(memories), "memories": memories})
        except Exception as e:
            self._send_json({"error": f"메모리 조회 실패: {e}"}, 500)

    def _handle_memory_add(self):
        """POST /api/memory — 메모리 추가 {"category","key","value","importance"}"""
        body = self._read_body()
        if body is None:
            return
        category, key = body.get("category", ""), body.get("key", "")
        if not category or not key:
            return self._send_json({"error": "category와 key가 필요합니다"}, 400)
        store = _get_memory_store()
        if not store:
            return self._send_json({"error": "MemoryStore를 사용할 수 없습니다"}, 503)
        try:
            entry = store.add(category, key, body.get("value", ""),
                              importance=body.get("importance", 3))
            self._send_json({"status": "added", "memory": entry}, 201)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            self._send_json({"error": f"메모리 추가 실패: {e}"}, 500)

    def _handle_memory_delete(self, memory_id):
        """DELETE /api/memory/<id> — 메모리 삭제"""
        store = _get_memory_store()
        if not store:
            return self._send_json({"error": "MemoryStore를 사용할 수 없습니다"}, 503)
        try:
            if store.delete(memory_id):
                self._send_json({"status": "deleted", "id": memory_id})
            else:
                self._send_json({"error": f"ID를 찾을 수 없습니다: {memory_id}"}, 404)
        except Exception as e:
            self._send_json({"error": f"메모리 삭제 실패: {e}"}, 500)

    # ---- 스케줄 ----

    def _handle_schedules_list(self):
        """GET /api/schedules — 전체 예약 작업"""
        scheduler = _get_scheduler()
        if not scheduler:
            return self._send_json({"error": "Scheduler를 사용할 수 없습니다"}, 503)
        try:
            schedules = scheduler.list_schedules()
            self._send_json({"count": len(schedules), "schedules": schedules})
        except Exception as e:
            self._send_json({"error": f"스케줄 조회 실패: {e}"}, 500)

    def _handle_schedule_add(self):
        """POST /api/schedules — 예약 추가 {"name","cron","action"}"""
        body = self._read_body()
        if body is None:
            return
        name, cron = body.get("name", ""), body.get("cron", "")
        if not name or not cron:
            return self._send_json({"error": "name과 cron이 필요합니다"}, 400)
        scheduler = _get_scheduler()
        if not scheduler:
            return self._send_json({"error": "Scheduler를 사용할 수 없습니다"}, 503)
        # cron 형식 자동 감지: 5개 필드면 recurring, 아니면 once
        cron_stripped = cron.strip()
        schedule_type = "recurring" if len(cron_stripped.split()) == 5 else "once"
        task = {"action": body.get("action", "remind"), "content": name,
                "created_by": "dashboard"}
        try:
            entry = scheduler.add_schedule(schedule_type, cron_stripped, task,
                                           description=name)
            self._send_json({"status": "added", "schedule": entry}, 201)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            self._send_json({"error": f"스케줄 추가 실패: {e}"}, 500)

    def _handle_schedule_delete(self, schedule_id):
        """DELETE /api/schedules/<id> — 예약 삭제"""
        scheduler = _get_scheduler()
        if not scheduler:
            return self._send_json({"error": "Scheduler를 사용할 수 없습니다"}, 503)
        try:
            if scheduler.remove_schedule(schedule_id):
                self._send_json({"status": "deleted", "id": schedule_id})
            else:
                self._send_json({"error": f"ID를 찾을 수 없습니다: {schedule_id}"}, 404)
        except Exception as e:
            self._send_json({"error": f"스케줄 삭제 실패: {e}"}, 500)

    # ---- 지식 베이스 ----

    def _handle_knowledge_stats(self):
        """GET /api/knowledge — 지식 베이스 통계 + 문서 목록"""
        kb = _get_knowledge_base()
        if not kb:
            return self._send_json({
                "available": False,
                "message": "KnowledgeBase 모듈이 설치되지 않았습니다",
                "stats": {"total_documents": 0}, "documents": [],
            })
        try:
            stats = kb.get_stats() if hasattr(kb, "get_stats") else {}
            docs = kb.list_documents() if hasattr(kb, "list_documents") else []
            self._send_json({"available": True, "stats": stats, "documents": docs})
        except Exception as e:
            self._send_json({"error": f"지식 베이스 조회 실패: {e}"}, 500)

    def _handle_knowledge_search(self):
        """POST /api/knowledge/search — 검색 {"query": "..."}"""
        body = self._read_body()
        if body is None:
            return
        query = body.get("query", "")
        if not query:
            return self._send_json({"error": "query가 필요합니다"}, 400)
        kb = _get_knowledge_base()
        if not kb:
            return self._send_json({"error": "KnowledgeBase 모듈이 설치되지 않았습니다"}, 503)
        try:
            if hasattr(kb, "search"):
                self._send_json({"query": query, "results": kb.search(query)})
            else:
                self._send_json({"error": "검색 기능을 사용할 수 없습니다"}, 501)
        except Exception as e:
            self._send_json({"error": f"검색 실패: {e}"}, 500)

    def _handle_knowledge_index(self):
        """POST /api/knowledge/index — 문서 인덱싱 {"title","content"}"""
        body = self._read_body()
        if body is None:
            return
        title, content = body.get("title", ""), body.get("content", "")
        if not title or not content:
            return self._send_json({"error": "title과 content가 필요합니다"}, 400)
        kb = _get_knowledge_base()
        if not kb:
            return self._send_json({"error": "KnowledgeBase 모듈이 설치되지 않았습니다"}, 503)
        try:
            if hasattr(kb, "add_document"):
                self._send_json({"status": "indexed",
                                 "result": kb.add_document(title, content)}, 201)
            else:
                self._send_json({"error": "인덱싱 기능을 사용할 수 없습니다"}, 501)
        except Exception as e:
            self._send_json({"error": f"인덱싱 실패: {e}"}, 500)

    # ---- 대화 ----

    def _handle_conversations_list(self, query):
        """GET /api/conversations — 대화 목록"""
        store = _get_conversation_store()
        if not store:
            return self._send_json({"error": "ConversationStore not available"}, 503)
        interface = query.get("interface", [None])[0]
        try:
            limit = min(max(1, int(query.get("limit", ["20"])[0])), 200)
        except (ValueError, IndexError):
            limit = 20
        convs = store.list_conversations(interface=interface, limit=limit)
        data = [{
            "id": c.id,
            "interface": c.interface,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        } for c in convs]
        return self._send_json(data)

    def _handle_conversation_detail(self, conv_id):
        """GET /api/conversations/<id> — 대화 상세"""
        store = _get_conversation_store()
        if not store:
            return self._send_json({"error": "ConversationStore not available"}, 503)
        conv = store.get_conversation(conv_id)
        if not conv:
            return self._send_json({"error": "Not found"}, 404)
        msgs = store.get_messages(conv_id, limit=100)
        return self._send_json({
            "id": conv.id,
            "interface": conv.interface,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "messages": msgs,
        })

    # ---- 사용자 관리 (Phase 8) ----

    def _handle_users_list(self):
        """GET /api/users -- 사용자 목록 (admin only)"""
        store = _get_user_store()
        if not store:
            return self._send_json({"error": "UserStore not available"}, 503)
        try:
            users = store.list_users() if hasattr(store, "list_users") else []
            users_data = [{"id": u.id, "username": u.username, "role": u.role, "api_key_prefix": u.api_key_prefix, "is_active": u.is_active, "created_at": u.created_at} for u in users]
            self._send_json({"count": len(users_data), "users": users_data})
        except Exception as e:
            self._send_json({"error": f"사용자 목록 조회 실패: {e}"}, 500)

    def _handle_users_create(self):
        """POST /api/users -- 사용자 생성 (admin only)"""
        body = self._read_body()
        if body is None:
            return
        username = body.get("username", "")
        if not username:
            return self._send_json({"error": "username이 필요합니다"}, 400)
        store = _get_user_store()
        if not store:
            return self._send_json({"error": "UserStore not available"}, 503)
        try:
            user, api_key = store.create_user(
                username=username,
                role=body.get("role", "user"),
            )
            self._send_json({"status": "created", "user": {"id": user.id, "username": user.username, "role": user.role, "api_key_prefix": user.api_key_prefix}, "api_key": api_key}, 201)
        except Exception as e:
            self._send_json({"error": f"사용자 생성 실패: {e}"}, 500)

    # ---- 대화 검색 / 태그 (Phase 8) ----

    def _handle_conversations_search(self):
        """POST /api/conversations/search -- 대화 검색"""
        body = self._read_body()
        if body is None:
            return
        query = body.get("query", "")
        if not query:
            return self._send_json({"error": "query가 필요합니다"}, 400)
        try:
            from openclaw.search import ConversationSearch
            from config import get_config
            searcher = ConversationSearch(get_config().conversation_db_path)
            results = searcher.search(query, limit=body.get("limit", 20))
            results_data = [{"conversation_id": r.conversation_id, "message_id": r.message_id, "role": r.role, "snippet": r.snippet, "rank": r.rank, "created_at": r.created_at} for r in results]
            self._send_json({"query": query, "results": results_data})
        except ImportError:
            self._send_json({"error": "search module not available"}, 503)
        except Exception as e:
            self._send_json({"error": f"대화 검색 실패: {e}"}, 500)

    def _handle_conversation_tags_get(self, conv_id):
        """GET /api/conversations/<id>/tags -- 태그 조회"""
        try:
            from openclaw.search import TagManager
            from config import get_config
            tag_mgr = TagManager(get_config().conversation_db_path)
            tags = tag_mgr.get_tags(conv_id)
            self._send_json({"conversation_id": conv_id, "tags": tags})
        except ImportError:
            self._send_json({"error": "search module not available"}, 503)
        except Exception as e:
            self._send_json({"error": f"태그 조회 실패: {e}"}, 500)

    def _handle_conversation_tags_add(self, conv_id):
        """POST /api/conversations/<id>/tags -- 태그 추가"""
        body = self._read_body()
        if body is None:
            return
        tag = body.get("tag", "")
        if not tag:
            return self._send_json({"error": "tag가 필요합니다"}, 400)
        try:
            from openclaw.search import TagManager
            from config import get_config
            tag_mgr = TagManager(get_config().conversation_db_path)
            tag_mgr.add_tag(conv_id, tag)
            self._send_json({"status": "added", "conversation_id": conv_id, "tag": tag}, 201)
        except ImportError:
            self._send_json({"error": "search module not available"}, 503)
        except Exception as e:
            self._send_json({"error": f"태그 추가 실패: {e}"}, 500)

    def _handle_tags_list(self):
        """GET /api/tags -- 전체 태그 목록"""
        try:
            from openclaw.search import TagManager
            from config import get_config
            tag_mgr = TagManager(get_config().conversation_db_path)
            tags = tag_mgr.list_all_tags()
            self._send_json({"count": len(tags), "tags": tags})
        except ImportError:
            self._send_json({"error": "search module not available"}, 503)
        except Exception as e:
            self._send_json({"error": f"태그 목록 조회 실패: {e}"}, 500)

    # ---- 감사 로그 (Phase 8) ----

    def _handle_audit_list(self):
        """GET /api/audit -- 감사 이벤트 목록 (admin only)"""
        audit = _get_audit_logger()
        if not audit:
            return self._send_json({"error": "AuditLogger not available"}, 503)
        try:
            events = audit.query(limit=100)
            events_data = [{"id": e.id, "timestamp": e.timestamp, "event_type": e.event_type, "user_id": e.user_id, "source_ip": e.source_ip, "interface": e.interface, "details": e.details, "severity": e.severity} for e in events]
            self._send_json({"count": len(events_data), "events": events_data})
        except Exception as e:
            self._send_json({"error": f"감사 로그 조회 실패: {e}"}, 500)

    # ---- 백업 (Phase 8) ----

    def _handle_backup_create(self):
        """POST /api/backup -- 백업 생성 (admin only)"""
        mgr = _get_backup_manager()
        if not mgr:
            return self._send_json({"error": "BackupManager not available"}, 503)
        try:
            if hasattr(mgr, "create_backup"):
                result = mgr.create_backup()
                self._send_json({"status": "created", "backup": result}, 201)
            else:
                self._send_json({"error": "백업 기능을 사용할 수 없습니다"}, 501)
        except Exception as e:
            self._send_json({"error": f"백업 생성 실패: {e}"}, 500)

    def _handle_backups_list(self):
        """GET /api/backups -- 백업 목록 (admin only)"""
        mgr = _get_backup_manager()
        if not mgr:
            return self._send_json({"error": "BackupManager not available"}, 503)
        try:
            if hasattr(mgr, "list_backups"):
                backups = mgr.list_backups()
            else:
                backups = []
            self._send_json({"count": len(backups), "backups": backups})
        except Exception as e:
            self._send_json({"error": f"백업 목록 조회 실패: {e}"}, 500)

    # ---- Phase 9 스텁 핸들러 (Wave 3-5에서 구현 예정) ----

    def _handle_metrics(self):
        """GET /metrics -- Prometheus text format"""
        try:
            from openclaw.metrics import get_metrics
            collector = get_metrics()
        except ImportError:
            return self._send_json({"error": "Metrics not available"}, 503)

        text = collector.export_prometheus()
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_chat_sync(self, ctx):
        """POST /api/v1/chat -- synchronous chat"""
        # Rate limit check
        limiter = _get_rate_limiter()
        if limiter:
            allowed, headers = limiter.check(ctx.user_id)
            if not allowed:
                return self._send_json({"error": "Rate limit exceeded", "retry_after": 60}, 429)

        api = _get_chat_api()
        if not api:
            return self._send_json({"error": "Chat API not available. ANTHROPIC_API_KEY may not be set."}, 503)

        body = self._read_body()
        if body is None:
            return
        message = body.get("message", "")
        if not message:
            return self._send_json({"error": "message field is required"}, 400)
        if len(message) > 10000:
            return self._send_json({"error": "Message too long (max 10000 chars)"}, 400)

        result = api.chat_sync(
            message,
            user_id=ctx.user_id,
            conversation_id=body.get("conversation_id"),
        )
        self._send_json(result)

    def _handle_chat_stream(self, ctx):
        """POST /api/v1/chat/stream -- SSE streaming chat"""
        api = _get_chat_api()
        if not api:
            return self._send_json({"error": "Chat API not available"}, 503)

        body = self._read_body()
        if body is None:
            return
        message = body.get("message", "")
        if not message:
            return self._send_json({"error": "message field is required"}, 400)

        # Send SSE headers
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            for event_type, data in api.chat_stream(
                message,
                user_id=ctx.user_id,
                conversation_id=body.get("conversation_id"),
            ):
                if isinstance(data, dict):
                    line = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                else:
                    line = f"data: {json.dumps({'type': event_type, 'text': data}, ensure_ascii=False)}\n\n"
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()
        except Exception as e:
            error_line = f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            self.wfile.write(error_line.encode("utf-8"))
            self.wfile.flush()

    def _handle_auth_token(self):
        """POST /api/auth/token -- issue JWT from API key"""
        body = self._read_body()
        if body is None:
            return
        api_key = body.get("api_key", "")
        if not api_key:
            return self._send_json({"error": "api_key is required"}, 400)

        try:
            from config import get_config
            cfg = get_config()
        except ImportError:
            return self._send_json({"error": "Config not available"}, 503)

        if not cfg.jwt_secret:
            return self._send_json({"error": "JWT is not configured"}, 501)

        store = _get_user_store()
        if not store:
            return self._send_json({"error": "UserStore not available"}, 503)

        user = store.authenticate_api_key(api_key)
        if not user:
            return self._send_json({"error": "Invalid API key"}, 401)

        from openclaw.jwt_auth import JWTManager
        jwt_mgr = JWTManager(cfg.jwt_secret)
        access_token = jwt_mgr.create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
            ttl=cfg.jwt_access_ttl,
        )
        refresh_token = jwt_mgr.create_refresh_token()

        # Store refresh token hash
        import hashlib
        refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        from datetime import timedelta
        expires_at = (datetime.utcnow() + timedelta(seconds=cfg.jwt_refresh_ttl)).isoformat()
        store.store_refresh_token(user.id, refresh_hash, expires_at)

        self._send_json({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": cfg.jwt_access_ttl,
        })

    def _handle_auth_refresh(self):
        """POST /api/auth/refresh -- refresh access token"""
        body = self._read_body()
        if body is None:
            return
        refresh_token = body.get("refresh_token", "")
        if not refresh_token:
            return self._send_json({"error": "refresh_token is required"}, 400)

        try:
            from config import get_config
            cfg = get_config()
        except ImportError:
            return self._send_json({"error": "Config not available"}, 503)

        if not cfg.jwt_secret:
            return self._send_json({"error": "JWT is not configured"}, 501)

        store = _get_user_store()
        if not store:
            return self._send_json({"error": "UserStore not available"}, 503)

        import hashlib
        refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        token_data = store.validate_refresh_token(refresh_hash)
        if not token_data:
            return self._send_json({"error": "Invalid or expired refresh token"}, 401)

        from openclaw.jwt_auth import JWTManager
        jwt_mgr = JWTManager(cfg.jwt_secret)
        access_token = jwt_mgr.create_access_token(
            user_id=token_data["user_id"],
            username=token_data["username"],
            role=token_data["role"],
            ttl=cfg.jwt_access_ttl,
        )

        self._send_json({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": cfg.jwt_access_ttl,
        })

    def _handle_auth_revoke(self, ctx):
        """POST /api/auth/revoke -- revoke refresh token"""
        body = self._read_body()
        if body is None:
            return
        refresh_token = body.get("refresh_token", "")
        if not refresh_token:
            return self._send_json({"error": "refresh_token is required"}, 400)

        store = _get_user_store()
        if not store:
            return self._send_json({"error": "UserStore not available"}, 503)

        import hashlib
        refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        revoked = store.revoke_refresh_token(refresh_hash, ctx.user_id)

        if revoked:
            self._send_json({"status": "revoked"})
        else:
            self._send_json({"error": "Token not found or already revoked"}, 404)

    def _handle_webhook_create(self, ctx):
        """POST /api/webhooks -- register webhook"""
        body = self._read_body()
        if body is None:
            return
        url = body.get("url", "")
        if not url:
            return self._send_json({"error": "url is required"}, 400)
        events = body.get("events", [])
        if not isinstance(events, list):
            return self._send_json({"error": "events must be a list"}, 400)

        store = _get_webhook_store()
        if not store:
            return self._send_json({"error": "Webhook system not available"}, 503)

        webhook = store.create_webhook(
            user_id=ctx.user_id,
            url=url,
            events=events,
            secret=body.get("secret"),
        )
        self._send_json({"status": "created", "webhook": webhook}, 201)

    def _handle_webhook_list(self, ctx):
        """GET /api/webhooks -- list user webhooks"""
        store = _get_webhook_store()
        if not store:
            return self._send_json({"error": "Webhook system not available"}, 503)

        webhooks = store.list_webhooks(ctx.user_id)
        self._send_json({"count": len(webhooks), "webhooks": webhooks})

    def _handle_webhook_delete(self, ctx, webhook_id):
        """DELETE /api/webhooks/{id} -- delete webhook (owner only)"""
        store = _get_webhook_store()
        if not store:
            return self._send_json({"error": "Webhook system not available"}, 503)

        deleted = store.delete_webhook(webhook_id, ctx.user_id)
        if deleted:
            self._send_json({"status": "deleted", "id": webhook_id})
        else:
            self._send_json({"error": "Webhook not found or access denied"}, 404)

    def _handle_retention_stats(self, ctx):
        """GET /api/retention/stats -- retention statistics (admin only)"""
        from openclaw.auth import _ROLE_RANK
        if _ROLE_RANK.get(ctx.role, 0) < _ROLE_RANK.get("admin", 2):
            return self._send_json({"error": "Admin access required"}, 403)

        try:
            from openclaw.retention import RetentionManager
            mgr = RetentionManager()
        except ImportError:
            return self._send_json({"error": "Retention manager not available"}, 503)

        stats = mgr.get_stats()
        self._send_json(stats)

    def _handle_retention_run(self, ctx):
        """POST /api/retention/run -- execute cleanup (admin only)"""
        from openclaw.auth import _ROLE_RANK
        if _ROLE_RANK.get(ctx.role, 0) < _ROLE_RANK.get("admin", 2):
            return self._send_json({"error": "Admin access required"}, 403)

        try:
            from openclaw.retention import RetentionManager
            mgr = RetentionManager()
        except ImportError:
            return self._send_json({"error": "Retention manager not available"}, 503)

        results = mgr.run_cleanup()
        self._send_json({"status": "completed", "deleted": results})

    # ---- 정적 파일 서빙 ----

    def _serve_static(self):
        """정적 파일 서빙 — 경로 탐색 방지(realpath 검증)"""
        path = urlparse(self.path).path
        # 루트 또는 /dashboard → index.html
        if path in ("/", "/dashboard", "/dashboard/"):
            path = "/dashboard/index.html"
        if not path.startswith("/dashboard/"):
            return self._send_404()
        relative = path[len("/dashboard/"):]
        # 기준 디렉토리 + 경로 탐색 방지
        base_dir = os.path.realpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard"))
        file_path = os.path.realpath(os.path.join(base_dir, relative))
        if not file_path.startswith(base_dir + os.sep) and file_path != base_dir:
            return self._send_json({"error": "접근 거부"}, 403)
        if not os.path.isfile(file_path):
            return self._send_404()
        # MIME 타입 결정 + 전송
        _, ext = os.path.splitext(file_path)
        content_type = _MIME_TYPES.get(ext.lower(), "application/octet-stream")
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self._send_json({"error": "파일 읽기 실패"}, 500)

    def _send_404(self):
        """404 응답"""
        body = b"404 Not Found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---- 서버 실행 ----

def run_dashboard(host="127.0.0.1", port=None):
    """대시보드 HTTP 서버 실행 (127.0.0.1 로컬 전용)"""
    port = port or int(os.environ.get("DASHBOARD_PORT", "8080"))
    token = os.environ.get("DASHBOARD_TOKEN", "")
    if not token:
        print("[대시보드] DASHBOARD_TOKEN 환경변수가 설정되지 않았습니다.")
        print("[대시보드] .env 파일에 DASHBOARD_TOKEN=<토큰> 을 추가하세요.")
        return
    server = http.server.ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"[대시보드] http://{host}:{port} 에서 실행 중...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[대시보드] 종료")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_dashboard()
