# flux-openclaw 프로젝트 가이드

flux-openclaw는 Claude API 기반의 자기 확장형(Self-Extending) AI 에이전트 플랫폼입니다. 이 문서는 이 프로젝트에서 작업하는 AI 에이전트(주로 Claude)를 위한 프로젝트 특화 지침입니다.

---

## 1. 프로젝트 구조 (4계층 아키텍처)

```
flux-openclaw/
├── [계층 1: 인터페이스 계층] 사용자 진입점
│   ├── main.py                 # CLI 인터페이스 (터미널)
│   ├── ws_server.py            # WebSocket 서버 (웹 앱)
│   ├── telegram_bot.py         # 텔레그램 봇
│   ├── discord_bot.py          # 디스코드 봇
│   ├── slack_bot.py            # 슬랙 봇
│   ├── api_gateway.py          # REST API 게이트웨이
│   └── dashboard.py            # 관리자 대시보드
│
├── [계층 2: 코어 엔진] 공유 비즈니스 로직
│   ├── conversation_engine.py  # 대화 루프 (5개 인터페이스 통합)
│   ├── core.py                 # ToolManager, 보안, 사용량 추적
│   ├── llm_provider.py         # LLM 추상화 (Anthropic/OpenAI/Google)
│   ├── config.py               # 중앙 집중식 설정
│   ├── resilience.py           # 재시도, 타임아웃 처리
│   ├── logging_config.py       # 구조화된 로깅 (비밀 마스킹)
│   ├── cost_tracker.py         # 비용 추적
│   ├── conversation_store.py   # 대화 히스토리 저장소
│   └── memory_store.py         # 메모리 저장소
│
├── [계층 3: 도구 계층] 외부 기능
│   ├── tools/
│   │   ├── memory_manage.py    # 메모리 관리 도구
│   │   ├── save_text_file.py   # 파일 저장 (보호됨)
│   │   ├── read_text_file.py   # 파일 읽기
│   │   ├── web_search.py       # 인터넷 검색
│   │   ├── weather.py          # 날씨 조회
│   │   ├── web_fetch.py        # 웹 페이지 가져오기 (SSRF 방어)
│   │   ├── list_files.py       # 디렉토리 목록
│   │   ├── screen_capture.py   # 스크린 캡처
│   │   ├── play_audio.py       # 오디오 재생
│   │   ├── browser_tool.py     # 브라우저 자동화
│   │   ├── schedule_task.py    # 예약 작업
│   │   ├── marketplace_tool.py # 마켓플레이스 관리
│   │   ├── knowledge_tool.py   # 지식 베이스 관리
│   │   ├── add_two_numbers.py  # 덧셈 (예제)
│   │   └── multiply_two_numbers.py # 곱셈 (예제)
│   └── plugin_sdk.py           # 플러그인 SDK
│
├── [계층 4: 영속성] 데이터 저장소
│   ├── memory/
│   │   ├── instruction.md      # 시스템 프롬프트 (보호됨)
│   │   └── memory.md           # 영속 메모리 (AI 읽기/쓰기)
│   ├── knowledge/              # 지식 베이스 문서
│   ├── marketplace/            # 도구 마켓플레이스
│   ├── dashboard/              # 대시보드 자산
│   ├── history/                # 대화 히스토리 (자동 생성)
│   ├── logs/                   # 로그 파일 (자동 생성)
│   ├── backups/                # 백업 (자동 생성)
│   └── [SQLite DB]             # 사용자, 인증, 메트릭 (자동 생성)
│
├── tests/                      # 36개 테스트 파일
├── requirements.txt            # Python 의존성
├── .env.example               # 환경 변수 템플릿
└── config.json                # 설정 파일 (선택)
```

---

## 2. 핵심 설계 원칙

### 2.1 대화 루프 통합 (ConversationEngine)

**중요:** 모든 인터페이스(CLI, WebSocket, Telegram, Discord, Slack, API)는 **동일한 대화 루프**를 사용합니다.

```python
# ❌ 금지: 인터페이스별로 도구 사용 루프를 중복 작성
# 이미 5개 인터페이스에서 576줄의 중복 코드 제거됨

# ✅ 권장: ConversationEngine 사용
from conversation_engine import ConversationEngine

engine = ConversationEngine(
    provider=provider,
    client=client,
    tool_mgr=tool_mgr,
    system_prompt=system_prompt,
    restricted_tools={"save_text_file"}  # 특정 인터페이스에서 차단할 도구
)
result = engine.run_turn(messages)  # 도구 사용, 재시도, 타임아웃 모두 처리됨
```

### 2.2 설정 통합 (config.py)

**모든 설정은 단일 진입점 `get_config()`를 통해 접근합니다.**

우선순위: 환경변수 > config.json > 기본값

```python
from config import get_config

cfg = get_config()
print(cfg.max_tokens)           # 4096
print(cfg.llm_retry_count)      # 3
print(cfg.ws_rate_limit)        # 30
```

### 2.3 보안 다층 방어

| 방어 계층 | 구현 위치 | 내용 |
|---------|---------|------|
| **경로 탈출 방지** | tools/*.py + save_text_file.py | `pathlib.Path.resolve()` + 심볼릭 링크 차단 + O_NOFOLLOW |
| **SSRF 차단** | tools/web_fetch.py | DNS 핀닝 + 프라이빗 IP 차단 + 리다이렉트 검증 |
| **도구 보안 스캔** | core.py ToolManager | 위험 패턴 탐지(os.system, subprocess, eval 등) + AST 분석 + 사용자 승인 |
| **파일 보호** | core.py + tools/*.py | .env, main.py, core.py, instruction.md 등 핵심 파일 쓰기/읽기 차단 |
| **로그 마스킹** | logging_config.py + core.py | API 키 패턴(sk-ant-*, AIza*) 자동 [REDACTED] 처리 |
| **WebSocket 보안** | ws_server.py | Origin 검증 + 토큰 인증 + 로컬 바인딩 + Rate Limiting |
| **봇 보안** | telegram_bot.py, discord_bot.py, slack_bot.py | 허용 사용자 목록 + 위험 도구 차단 + 오류 정보 마스킹 |
| **비용 보호** | core.py | 일일 100회 API 호출 상한 + 토큰 사용량 추적 |

---

## 3. 도구 시스템

### 3.1 도구 개발 템플릿

모든 도구는 `tools/` 폴더에 아래 형식의 `.py` 파일로 생성합니다:

```python
# tools/my_custom_tool.py

SCHEMA = {
    "name": "my_custom_tool",
    "description": "도구 설명",
    "input_schema": {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "매개변수 설명"},
            "param2": {"type": "integer", "description": "숫자 매개변수"},
        },
        "required": ["param1"],
    },
}

def main(param1, param2=None):
    """도구 구현 (kwargs 형식 권장)"""
    try:
        result = process(param1, param2)
        return f"성공: {result}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    import json
    print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
```

### 3.2 도구 생성 시 주의사항

#### 금지된 import 목록

도구에서 사용하면 안 되는 import (자동 탐지):

```
❌ subprocess, os.system, os.popen    # 쉘 명령 실행
❌ eval, exec, compile                # 동적 코드 실행
❌ __import__, importlib              # 메타프로그래밍
❌ ctypes, pickle, base64, codecs     # 난독화/직렬화
❌ socket, ssl                        # 네트워크 접근
❌ open()                             # 직접 파일 열기 (save_text_file 사용)
❌ shutil, os.remove, os.chmod        # 파일 시스템 조작
```

#### 보호된 파일/디렉토리

도구에서 수정할 수 없는 파일:

```python
PROTECTED_FILES = {
    ".env", "main.py", "core.py", "instruction.md",
    ".gitignore", "requirements.txt", "security.md",
    "ws_server.py", "telegram_bot.py", "daemon.py",
    # ... 총 20개
}

PROTECTED_DIRS = {"tools", "marketplace", "dashboard", "knowledge"}
```

### 3.3 도구 보안 검증 프로세스

새 도구 로드 시 자동 실행:

1. **정규식 패턴 검사**: 위험 패턴 15개 탐지
2. **AST 분석**: 난독화 우회 방지
3. **Import 차단 목록**: 위험한 import 검사
4. **사용자 승인**: 위험 패턴 발견 시 사용자에게 승인 요청
5. **.tool_approved.json**: 승인 기록 저장 (TOCTOU 방지)

---

## 4. 설정 및 환경 변수

### 4.1 필수 환경 변수

| 변수 | 설명 | 기본값 | 필수 |
|------|------|--------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 키 | - | ✅ |
| `LLM_PROVIDER` | 프로바이더 선택 (anthropic/openai/google) | anthropic | ❌ |
| `LLM_MODEL` | 모델명 | claude-sonnet-4-20250514 | ❌ |

### 4.2 인터페이스별 환경 변수

**WebSocket:**
```
WS_AUTH_TOKEN              # 인증 토큰 (필수)
WS_ALLOWED_ORIGINS         # 허용 Origin (기본: localhost:3000)
WS_PORT                    # 포트 (기본: 8765)
WS_HOST                    # 바인딩 주소 (기본: 127.0.0.1)
```

**Telegram:**
```
TELEGRAM_BOT_TOKEN         # 봇 토큰 (필수)
TELEGRAM_ALLOWED_USERS     # 허용 chat_id 쉼표 구분 (필수)
```

**Discord:**
```
DISCORD_BOT_TOKEN          # 봇 토큰 (필수)
DISCORD_ALLOWED_SERVERS    # 허용 서버 ID 쉼표 구분
```

**Slack:**
```
SLACK_BOT_TOKEN            # 봇 토큰 (필수)
SLACK_SIGNING_SECRET       # 서명 비밀 (필수)
SLACK_ALLOWED_CHANNELS     # 허용 채널 쉼표 구분
```

### 4.3 설정 우선순위

```
1순위: 환경변수 (.env 파일 또는 시스템 환경변수)
2순위: config.json (프로젝트 루트)
3순위: Config 클래스의 기본값 (config.py)
```

---

## 5. 자기 확장 (Self-Extension) 워크플로우

AI 에이전트가 새로운 도구를 자동으로 생성하는 방식:

```
사용자 요청
    ↓
"주사위 기능 만들어줘"
    ↓
AI: save_text_file로 tools/roll_dice.py 생성
    ↓
ToolManager: tools/ 폴더 감시, 파일 감지
    ↓
도구 보안 검증 실행
    ↓
위험 패턴 없음 → 즉시 로드
    ↓
다음 사용자 입력부터 roll_dice 도구 사용 가능
(프로그램 재시작 불필요)
```

### 5.1 핫 리로드 메커니즘

ToolManager는 `tools/` 폴더를 주기적으로 감시합니다:

- **파일 추가/수정**: 자동으로 로드
- **파일 삭제**: 도구 목록에서 제거
- **TOCTOU 방지**: `.tool_approved.json`으로 한 번 승인된 도구는 재승인 불필요

---

## 6. 메모리 시스템

### 6.1 메모리 아키텍처

```
메모리 계층 1: 시스템 프롬프트
├── memory/instruction.md (보호됨)
├── memory/memory.md (AI 읽기/쓰기)
└── → 모든 대화 시작 시 자동 포함

메모리 계층 2: 구조화된 메모리 (memory_manage 도구)
├── user_info: 사용자 개인정보
├── preferences: 선호도
├── facts: 사실 정보
├── notes: 일반 메모
└── reminders: 리마인더

메모리 계층 3: 대화 히스토리
├── history/*.json (세션별 저장)
└── → 프로그램 종료 시 자동 저장, 재시작 시 복원 옵션

메모리 계층 4: 대시보드 메트릭
├── SQLite DB
└── → 사용자, 인증, 메트릭 저장
```

### 6.2 메모리 관리 도구 (memory_manage.py)

```python
# 메모리 저장
action="save"
category="user_info"          # 또는 preferences, facts, notes, reminders
key="user_name"
value="켈리"
importance=5                   # 1-5 (5=가장 중요)
expires_days=None             # 선택: 만료일

# 메모리 검색
action="search"
query="켈리"
category=None                 # 선택: 특정 카테고리만

# 메모리 목록
action="list"
category="user_info"          # 선택: 특정 카테고리만

# 메모리 삭제
action="delete"
memory_id="mem_12345"
```

---

## 7. 비용 관리

### 7.1 비용 추적 메커니즘

```python
# core.py의 일일 사용량 추적
- load_usage()       # 일일 사용량 로드
- save_usage()       # 일일 사용량 저장
- check_daily_limit() # 일일 한도 확인 (기본: 100회)
- increment_usage()  # 사용량 증가

# cost_tracker.py (선택)
- calculate_cost() # USD 비용 계산
  ├── Anthropic: $3/M 입력, $15/M 출력
  ├── OpenAI: 모델별 상이
  └── Google: 모델별 상이
```

### 7.2 사용량 저장소

```json
// usage_data.json
{
  "2026-02-12": {
    "calls": 45,          // API 호출 수
    "input_tokens": 12500,
    "output_tokens": 5000,
    "cost_usd": 0.52
  }
}
```

---

## 8. 테스트 및 검증

### 8.1 테스트 실행

```bash
# 전체 테스트
pytest tests/ -v

# 특정 테스트 파일
pytest tests/test_tool_manager.py -v

# 커버리지 보고서
pytest tests/ --cov=. --cov-report=html

# 보안 관련 테스트만
pytest tests/test_tool_manager.py tests/test_path_security.py -v
```

### 8.2 주요 테스트 파일

| 파일 | 역할 |
|------|------|
| test_tool_manager.py | 도구 보안 스캔, 핫 리로드 |
| test_path_security.py | 경로 탈출 방지, 심볼릭 링크 차단 |
| test_filter_tool_input.py | 도구 입력 검증 및 타입 강제 |
| test_config.py | 설정 로딩 및 우선순위 |
| test_resilience.py | 재시도, 타임아웃 처리 |
| test_conversation_engine.py | 도구 사용 루프 통합 테스트 |
| test_llm_provider.py | 다중 LLM 프로바이더 추상화 |
| test_*.py (기타 33개) | 인터페이스, 봇, API, 마켓플레이스 등 |

---

## 9. 로깅 및 모니터링

### 9.1 로깅 설정

```python
from logging_config import get_logger

logger = get_logger("module_name")
logger.debug("디버그 메시지")      # 개발 중
logger.info("정보 메시지")         # 일반 로그
logger.warning("경고 메시지")      # 주의
logger.error("에러 메시지")        # 오류
```

### 9.2 로그 마스킹 규칙

자동으로 마스킹되는 패턴:

```
- Anthropic API 키:    sk-ant-* → [REDACTED]
- Google API 키:        AIza* → [REDACTED]
- OpenAI API 키:        sk-* (20자 이상) → [REDACTED]
- GitHub 토큰:         ghp_* → [REDACTED]
- GitLab 토큰:         glpat-* → [REDACTED]
- Slack 토큰:          xox[bpsa]-* → [REDACTED]
```

### 9.3 구조화된 로깅

```json
// logs/flux-openclaw.log (JSON 형식)
{
  "timestamp": "2026-02-12T14:30:00Z",
  "level": "INFO",
  "module": "conversation_engine",
  "message": "도구 실행: web_search",
  "tool": "web_search",
  "duration_ms": 1250,
  "status": "success"
}
```

---

## 10. 인터페이스별 특징

### 10.1 CLI (main.py)

- **진입점**: `python3 main.py [--user=username]`
- **특징**:
  - 대화형 입력 지원
  - 파일 입출력 가능 (워크스페이스 내)
  - 대화 히스토리 복원 옵션
  - 메모리 시스템 완전 지원
- **제한사항**: 로컬 환경에서만 실행

### 10.2 WebSocket 서버 (ws_server.py)

- **진입점**: `python3 ws_server.py`
- **특징**:
  - 웹 앱 연동 (`ws://127.0.0.1:8765`)
  - 토큰 기반 인증
  - Origin 검증 (CORS)
  - Rate Limiting (30 msg/min)
- **제한사항**: save_text_file, screen_capture 등 위험 도구 차단

### 10.3 Telegram 봇 (telegram_bot.py)

- **진입점**: `python3 telegram_bot.py`
- **특징**:
  - 허용 사용자 목록 기반 필터링
  - 장문 응답 자동 분할 (4000자 제한)
  - 위험 도구 차단
- **제한사항**: Rate Limiting (10 msg/min), 파일 도구 미지원

### 10.4 Discord 봇 (discord_bot.py)

- **진입점**: `python3 discord_bot.py`
- **특징**:
  - 서버/채널 기반 접근 제어
  - 2000자 메시지 분할
  - 타이핑 인디케이터 표시
- **제한사항**: Rate Limiting (10 msg/min), 제한된 도구

### 10.5 Slack 봇 (slack_bot.py)

- **진입점**: `python3 slack_bot.py`
- **특징**:
  - 채널 기반 권한 관리
  - 스레드 지원
  - 슬레이트 블록 UI 지원
- **제한사항**: Rate Limiting (10 msg/min), 파일 제한

### 10.6 REST API (api_gateway.py)

- **진입점**: `python3 api_gateway.py`
- **특징**:
  - HTTP 기반 API 인터페이스
  - API 키 인증 (flux_* 형식)
  - 비동기 요청 처리
  - Rate Limiting (60 req/min)
- **엔드포인트**: `/v1/messages`, `/v1/tools`, `/v1/health`

### 10.7 대시보드 (dashboard.py)

- **진입점**: `python3 dashboard.py`
- **포트**: 8080 (기본)
- **특징**:
  - 관리자 웹 UI
  - 사용량 모니터링
  - 도구 관리 및 통계
  - 대화 히스토리 조회

### 10.8 Daemon (daemon.py)

- **진입점**: `python3 daemon.py start|stop|restart`
- **특징**:
  - 모든 인터페이스 동시 실행
  - 자동 재시작 및 헬스 체크
  - 통합 로깅
  - 프로세스 관리

---

## 11. 작업 체크리스트 (AI 에이전트용)

### 새 도구 추가 시

```
[ ] 도구 파일을 tools/ 폴더에 작성
[ ] SCHEMA 정의 (name, description, input_schema 필수)
[ ] main() 함수 구현
[ ] 금지된 import 확인 및 제거
[ ] 경로 탈출 방지 (pathlib.Path.resolve() 사용)
[ ] 테스트 작성 (tests/test_your_tool.py)
[ ] 보안 테스트 실행: pytest tests/test_tool_manager.py
[ ] 모든 테스트 통과 확인: pytest tests/ -v
[ ] 문서 업데이트 (필요 시)
```

### 코어 모듈 수정 시

```
[ ] 영향 범위 파악 (다른 모듈의 import 확인)
[ ] 해당 테스트 파일 확인 (test_*.py)
[ ] 수정 후 테스트 실행: pytest tests/test_module.py -v
[ ] 통합 테스트 실행: pytest tests/test_conversation_engine.py -v
[ ] 모든 인터페이스 테스트 실행: pytest tests/ -v
[ ] 보안 영향도 검토 (필요 시 security.md 참조)
```

### 새 인터페이스 추가 시

```
[ ] 새 파일 생성 (예: my_interface.py)
[ ] ConversationEngine 사용 (코드 복제 금지)
[ ] 제한 도구 설정 (restricted_tools 파라미터)
[ ] Rate Limiting 설정 (config.py 참조)
[ ] 테스트 작성 (tests/test_my_interface.py)
[ ] 모든 테스트 통과 확인
[ ] 환경 변수 문서화 (이 문서에 추가)
[ ] 통합 테스트 통과 (pytest tests/ -v)
```

---

## 12. 일반 개발 규칙

### DO (권장)

```python
✅ ConversationEngine 사용하기
✅ config.py의 get_config() 사용하기
✅ ToolManager를 통한 도구 로드
✅ pathlib.Path 사용하기 (보안)
✅ logging_config.get_logger() 사용하기
✅ 도구에서 예외 처리하기 (try-except)
✅ 테스트 작성하기
```

### DON'T (금지)

```python
❌ 인터페이스별 도구 루프 중복 작성
❌ 하드코딩된 설정값 사용
❌ os.system, subprocess 사용
❌ eval, exec 사용
❌ 직접 os.open() 사용 (save_text_file 사용)
❌ 프로테고스된 파일 수정
❌ 비밀 로깅 (로그 마스킹됨)
❌ 테스트 없이 변경 제출
❌ 정규 import 금지 목록 사용
```

---

## 13. 유용한 명령어

```bash
# 개발 환경 설정
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 테스트 실행
pytest tests/ -v                              # 전체 테스트
pytest tests/test_tool_manager.py -v        # 보안 테스트
pytest tests/test_conversation_engine.py -v # 통합 테스트

# 코드 품질 검사
python3 -m pylint core.py conversation_engine.py
python3 -m black --check core.py             # 코드 포맷 검사

# 실행
python3 main.py                    # CLI
python3 ws_server.py              # WebSocket
python3 daemon.py start           # 모든 서비스

# Docker
docker-compose up -d              # 컨테이너 시작
docker-compose logs -f            # 로그 추적
docker-compose down               # 컨테이너 종료
```

---

## 14. 문제 해결

### API 호출 실패

```
증상: "ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다"
해결: .env 파일에 ANTHROPIC_API_KEY=sk-ant-... 추가

증상: 토큰 한도 초과 (일일 100회)
확인: usage_data.json 확인
해결: get_config().max_daily_calls 수정 또는 다음 날 재시도
```

### 도구 로드 실패

```
증상: "위험한 패턴 탐지됨"
확인: 도구의 import 문 검토 (금지된 모듈 확인)
해결: 위험 import 제거 또는 사용자 승인

증상: 도구가 로드되지 않음
확인: 파일 이름 확인 (.py 확장자)
확인: SCHEMA 및 main() 함수 존재 여부
해결: pytest tests/test_tool_manager.py -v로 디버그
```

### WebSocket 연결 실패

```
증상: "Origin not allowed"
확인: WS_ALLOWED_ORIGINS 환경 변수
해결: 올바른 Origin 추가 (쉼표 구분)

증상: "Authentication failed"
확인: WS_AUTH_TOKEN 환경 변수
해결: 토큰 재설정 및 클라이언트 재연결
```

---

## 15. 참고 문서

- **security.md** - 보안 정책 및 방어 계층
- **docs/ARCHITECTURE.md** - 상세 아키텍처 문서
- **memory/instruction.md** - AI 시스템 프롬프트
- **README.md** - 프로젝트 개요
- **requirements.txt** - 의존성 버전

---

## 요약

flux-openclaw는 **중복 없는 자기 확장형 AI 플랫폼**입니다. 핵심은:

1. **ConversationEngine**: 모든 인터페이스의 통합 대화 루프
2. **ToolManager**: 도구 자동 로드, 핫 리로드, 보안 스캔
3. **다층 보안**: 경로 탈출, SSRF, 메타프로그래밍 방지
4. **설정 통합**: 환경변수 > config.json > 기본값
5. **메모리 시스템**: 시스템 프롬프트 + 구조화된 메모리 + 히스토리

이 가이드를 따르면 새로운 기능을 안전하고 효율적으로 추가할 수 있습니다.
