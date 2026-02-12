# flux-openclaw (켈리)

Claude API 기반의 자기 확장형(Self-Extending) AI 에이전트 플랫폼입니다.

`tools/` 폴더에 파이썬 파일을 추가하면 실행 중에도 자동으로 인식하여 새 기능을 사용할 수 있습니다. 7계층 보안 방어 아키텍처로 보호되는 프로덕션급 AI 플랫폼입니다.

## 주요 특징

### 인터페이스 (6개)
- **CLI** — 커맨드라인 AI 에이전트
- **WebSocket** — 실시간 웹 앱 연결
- **REST API** — 프로덕션 API 게이트웨이
- **텔레그램** — 텔레그램 메신저 봇
- **디스코드** — 디스코드 서버 봇
- **Slack** — Slack 워크스페이스 봇
- **웹 대시보드** — 관리자 UI + 설정

### 멀티 LLM 지원
- **Anthropic Claude** (기본) — claude-sonnet-4-20250514
- **OpenAI GPT-4o** — 고급 추론
- **Google Gemini 2.5** — 저비용 대안

LLM_PROVIDER 환경변수로 자유롭게 전환 가능합니다.

### 자기 확장 (Self-Extending)
- AI가 대화 중 새로운 도구를 직접 작성하여 `tools/` 폴더에 저장
- 즉시 인식하고 사용 가능 (재시작 불필요)
- 7계층 보안 검증으로 악의적 코드 자동 차단

### 15개 내장 도구
| 도구 | 설명 |
|------|------|
| **web_search** | DuckDuckGo 기반 인터넷 검색 |
| **web_fetch** | URL에서 웹 페이지 내용 추출 |
| **weather** | wttr.in 날씨 조회 |
| **read_text_file** | 텍스트 파일 읽기 |
| **save_text_file** | 텍스트 파일 저장 |
| **list_files** | 디렉토리 목록 조회 |
| **play_audio** | pygame 기반 음악 재생 |
| **screen_capture** | 화면 캡처 및 저장 |
| **memory_manage** | 구조화된 메모리 관리 |
| **schedule_task** | 크론 기반 작업 스케줄링 |
| **browser_tool** | Playwright 기반 브라우저 자동화 |
| **marketplace_tool** | 마켓플레이스 도구 설치/검색 |
| **knowledge_tool** | 지식 베이스 추가/검색 |
| **add_two_numbers** | 덧셈 계산 |
| **multiply_two_numbers** | 곱셈 계산 |

### 메모리 및 지식 관리

#### 구조화된 메모리 (Memory Store)
- SQLite FTS5 기반 영속 메모리
- 5개 카테고리: user_info, preferences, facts, notes, reminders
- 중요도 레벨 1~5
- 자동 만료 및 정리
- AI가 대화 중 자동 학습 및 저장

#### 지식 베이스 (RAG)
- TF-IDF 기반 의미 검색
- 한국어 토크나이저 내장
- 청크 단위 문서 저장
- 관련 지식 자동 컨텍스트 주입

### 도구 마켓플레이스
- 10+ 사전 패키지된 커뮤니티 도구
- 한 줄로 설치: "마켓플레이스에서 도구명 설치해줘"
- 7계층 보안 검증으로 안전한 설치
- 설치된 도구 자동 인식 및 로드

### 작업 스케줄러
- Cron 스타일 반복 작업
- 일회성 작업 지원
- 백그라운드 실행
- SQLite 기반 영속성

### 보안 (7계층 방어)

| 계층 | 방어 내용 |
|------|---------|
| **1. 입력 검증** | JSON 스키마 검증 + 타입 체크 |
| **2. 경로 탈출 방지** | pathlib.resolve() + 심볼릭 링크 차단 + O_NOFOLLOW |
| **3. SSRF 차단** | DNS 핀닝 + 프라이빗 IP 검증 + 응답 5MB 제한 |
| **4. 도구 코드 스캔** | 30개 위험 패턴 정규식 + AST 분석 |
| **5. 파일 보호** | .env, main.py, core.py 등 핵심 파일 차단 |
| **6. 레이트 리미팅** | 사용자별, 인터페이스별 속도 제한 |
| **7. 감사 로깅** | 모든 API 호출 기록 + 로그 마스킹 |

### 생산 준비 (Production-Ready)

#### 멀티 사용자 + 권한 관리
- 역할 기반 접근 제어 (RBAC)
- 역할: admin, user, readonly
- JWT 토큰 인증 (Access/Refresh)
- API 키 지원

#### 높은 가용성
- 자동 재시도 (exponential backoff)
- 타임아웃 관리
- Circuit breaker 패턴
- 헬스 체크 (Kubernetes 지원)

#### 관찰성
- 구조화된 JSON 로깅
- 성능 메트릭 추적
- 비용 추적 (API 비용 추산)
- 감사 로깅 (SQLite)

#### 배포
- Docker 컨테이너화
- docker-compose 오케스트레이션
- 데몬 프로세스 관리
- 자동 헬스 체크
- 백업 및 복구 시스템

### 테스트
- **426개 테스트**
- **85% 코드 커버리지**
- 보안, 경로, 입력, 사용량 등 모든 계층 검증

## 빠른 시작

### 설치

```bash
# 저장소 클론
git clone git@github.com:jeromwolf/flux-openclaw.git
cd flux-openclaw

# 의존성 설치
pip install -r requirements.txt

# 선택적 의존성 (필요한 것만)
# pip install openai google-generativeai  # 멀티 LLM
# pip install discord.py slack-bolt      # 봇
# pip install playwright && python -m playwright install chromium  # 브라우저
```

### 첫 실행

```bash
# .env 파일 생성
cp .env.example .env

# .env에서 필수 설정:
# - ANTHROPIC_API_KEY: Anthropic API 키

# CLI로 실행
python3 main.py
```

## 실행 모드

### 1. CLI 모드 (기본)
```bash
python3 main.py
```
커맨드라인에서 AI와 대화합니다.

### 2. WebSocket 서버
```bash
# .env에 WS_AUTH_TOKEN 설정 (최소 32자)
python3 ws_server.py
```
웹앱에서 ws://localhost:8765로 연결 가능합니다.

### 3. REST API 게이트웨이
```bash
python3 api_gateway.py
```
HTTP API로 모든 기능 제공 (인증, 레이트 리미팅, 구조화된 응답).

### 4. 웹 대시보드
```bash
python3 dashboard.py
```
관리자 UI로 사용자 관리, 통계, 설정: http://localhost:8080

### 5. 봇 인터페이스

**텔레그램 봇:**
```bash
python3 telegram_bot.py
```

**디스코드 봇:**
```bash
python3 discord_bot.py
```

**Slack 봇:**
```bash
python3 slack_bot.py
```

### 6. 데몬 모드 (모든 서비스 실행)
```bash
# 모든 서비스 시작
python3 daemon.py start

# 상태 확인
python3 daemon.py status

# 모든 서비스 중지
python3 daemon.py stop

# 로그 모니터링
python3 daemon.py logs
```

### 7. Docker 배포
```bash
# 컨테이너 빌드 및 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 중지
docker-compose down
```

## 프로젝트 구조

```
flux-openclaw/
├── 인터페이스 레이어
│   ├── main.py                 # CLI 에이전트
│   ├── ws_server.py            # WebSocket 서버
│   ├── api_gateway.py          # REST API 게이트웨이
│   ├── dashboard.py            # 웹 관리 대시보드
│   ├── telegram_bot.py         # 텔레그램 봇
│   ├── discord_bot.py          # 디스코드 봇
│   └── slack_bot.py            # Slack 봇
│
├── 코어 엔진
│   ├── core.py                 # 공유 코어 (ToolManager, 보안)
│   ├── conversation_engine.py  # 통합 대화 엔진
│   ├── llm_provider.py         # 멀티 LLM 프로바이더
│   ├── config.py               # 중앙 설정 관리
│   ├── resilience.py           # 복원력 (재시도, 타임아웃)
│   ├── logging_config.py       # 구조화된 로깅
│   └── health.py               # 헬스 체크
│
├── 인증 및 권한
│   ├── auth.py                 # 멀티 사용자 인증
│   ├── jwt_auth.py             # JWT 토큰 관리
│   ├── rate_limiter.py         # HTTP 레이트 리미팅
│   ├── cors.py                 # CORS 설정
│   └── admin_cli.py            # CLI 관리 도구
│
├── 메모리 및 지식
│   ├── memory_store.py         # 구조화된 메모리 (FTS5)
│   ├── knowledge_base.py       # 지식 베이스 (TF-IDF RAG)
│   ├── conversation_store.py   # 대화 영속성 (SQLite)
│   ├── search.py               # 검색 유틸리티
│   └── memory/
│       ├── instruction.md      # 시스템 프롬프트
│       └── memories.json       # 구조화된 메모리 (자동 생성)
│
├── 도구 및 마켓플레이스
│   ├── tool_marketplace.py     # 마켓플레이스 엔진
│   ├── plugin_sdk.py           # 플러그인 SDK
│   ├── tools/                  # 15개 내장 도구 (자동 로드)
│   │   ├── web_search.py
│   │   ├── web_fetch.py
│   │   ├── weather.py
│   │   ├── read_text_file.py
│   │   ├── save_text_file.py
│   │   ├── list_files.py
│   │   ├── play_audio.py
│   │   ├── screen_capture.py
│   │   ├── memory_manage.py
│   │   ├── schedule_task.py
│   │   ├── browser_tool.py
│   │   ├── marketplace_tool.py
│   │   ├── knowledge_tool.py
│   │   ├── add_two_numbers.py
│   │   └── multiply_two_numbers.py
│   ├── marketplace/            # 마켓플레이스 레지스트리
│   │   ├── registry.json       # 사용 가능한 도구 목록
│   │   ├── installed.json      # 설치된 도구 추적
│   │   └── cache/              # 설치된 도구 저장소
│   └── knowledge/              # 지식 베이스 문서 (자동 생성)
│
├── 스케줄링 및 작업
│   ├── scheduler.py            # 크론 스케줄러
│   ├── daemon.py               # 데몬 프로세스 관리
│   ├── onboarding.py           # 설정 마법사
│   └── webhook.py              # 웹훅 관리
│
├── 모니터링 및 관찰성
│   ├── audit.py                # 감사 로깅
│   ├── metrics.py              # 성능 메트릭
│   ├── cost_tracker.py         # API 비용 추적
│   ├── backup.py               # 백업 시스템
│   ├── retention.py            # 데이터 보존 정책
│   └── data/                   # 데이터 디렉토리 (자동 생성)
│       ├── conversations.db    # 대화 영속성
│       ├── auth.db             # 사용자 데이터
│       ├── audit.db            # 감사 로그
│       └── metrics.db          # 성능 메트릭
│
├── 테스트 (426개)
│   ├── test_tool_manager.py        # 도구 보안 스캔
│   ├── test_path_security.py       # 경로 보안
│   ├── test_filter_tool_input.py   # 입력 검증
│   ├── test_auth.py                # 인증
│   ├── test_api_gateway.py         # API 게이트웨이
│   ├── test_conversation_engine.py # 대화 엔진
│   ├── test_llm_provider.py        # LLM 프로바이더
│   ├── test_knowledge_base.py      # 지식 베이스
│   ├── test_marketplace.py         # 마켓플레이스
│   └── ... (36개 파일, 426개 테스트)
│
├── 문서
│   ├── docs/
│   │   └── ARCHITECTURE.md     # 상세 아키텍처
│   ├── README.md               # 이 파일
│   ├── security.md             # 보안 가이드
│   └── style.md                # 코딩 스타일
│
├── Docker
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── .dockerignore
│
├── 설정
│   ├── .env.example            # 환경변수 예시
│   ├── config.json             # 선택적 설정 파일
│   └── requirements.txt        # 의존성
│
└── 로그 및 데이터 (자동 생성)
    ├── logs/                   # 구조화된 로그
    ├── backups/                # 데이터베이스 백업
    └── history/                # 대화 히스토리 (사용하지 않음, SQLite 사용)
```

## 환경 변수

### 필수 설정

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `ANTHROPIC_API_KEY` | - | **필수** Anthropic Claude API 키 |

### LLM 설정

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `LLM_PROVIDER` | `anthropic` | 프로바이더: anthropic, openai, google |
| `LLM_MODEL` | claude-sonnet-4-20250514 | 모델명 |
| `OPENAI_API_KEY` | - | OpenAI API 키 (선택) |
| `GOOGLE_API_KEY` | - | Google Gemini API 키 (선택) |

### WebSocket 설정

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `WS_AUTH_TOKEN` | - | **필수** WebSocket 인증 토큰 (최소 32자) |
| `WS_HOST` | 127.0.0.1 | 바인딩 주소 |
| `WS_PORT` | 8765 | 포트 번호 |
| `WS_ALLOWED_ORIGINS` | localhost:3000 | CORS 허용 도메인 (쉼표 구분) |

### 텔레그램 설정

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `TELEGRAM_BOT_TOKEN` | - | **필수** 텔레그램 봇 토큰 |
| `TELEGRAM_ALLOWED_USERS` | - | **필수** 허용 chat_id (쉼표 구분) |

### 디스코드 설정

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DISCORD_BOT_TOKEN` | - | **필수** 디스코드 봇 토큰 |
| `DISCORD_ALLOWED_GUILDS` | - | 허용 서버 ID (쉼표 구분) |
| `DISCORD_ALLOWED_CHANNELS` | - | 허용 채널 ID (쉼표 구분) |

### Slack 설정

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `SLACK_BOT_TOKEN` | - | **필수** Slack 봇 토큰 |
| `SLACK_APP_TOKEN` | - | **필수** Slack 앱 토큰 |

### 대시보드 및 API

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DASHBOARD_TOKEN` | - | 웹 대시보드 인증 토큰 |
| `DASHBOARD_PORT` | 8080 | 대시보드 포트 |
| `HEALTH_PORT` | 8766 | 헬스 체크 포트 |

### 인증 및 권한

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `AUTH_ENABLED` | false | 멀티 사용자 인증 활성화 |
| `JWT_SECRET` | - | JWT 서명 비밀키 (auth_enabled=true 필수) |
| `MAX_DAILY_CALLS` | 100 | 일일 API 호출 제한 |

### 로깅 및 모니터링

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `LOG_LEVEL` | INFO | 로그 레벨: DEBUG, INFO, WARNING, ERROR |
| `LOG_FORMAT` | text | 로그 형식: text, json |
| `STREAMING_ENABLED` | true | 스트리밍 응답 활성화 |

### 고급 설정

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `MAX_TOKENS` | 4096 | 최대 생성 토큰 |
| `MAX_TOOL_ROUNDS` | 10 | 도구 최대 실행 라운드 |
| `TOOL_TIMEOUT` | 30 | 도구 타임아웃 (초) |
| `LLM_RETRY_COUNT` | 3 | API 재시도 횟수 |

## 도구 개발

### 새 도구 만들기

`tools/` 폴더에 아래 형식의 `.py` 파일을 추가합니다:

```python
SCHEMA = {
    "name": "my_tool",
    "description": "도구 설명",
    "input_schema": {
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "매개변수 설명"
            }
        },
        "required": ["param1"],
    },
}

def main(param1):
    """실제 구현"""
    return f"결과: {param1}"
```

재시작 없이 다음 사용자 입력부터 바로 사용 가능합니다.

### AI가 자동으로 도구 생성

AI에게 요청하면 스스로 도구를 만듭니다:
```
사용자: 주사위 기능 만들어줘
AI: (주사위 도구를 tools/ 폴더에 저장)
사용자: 주사위 굴려줘
AI: (새 도구 사용)
```

## 메모리 시스템

### 구조화된 메모리

AI는 `memory/memories.json`에 정보를 저장하고 학습합니다.

**5개 카테고리:**
- `user_info` — 사용자 이름, 직업, 관심사 등
- `preferences` — 선호도, 스타일
- `facts` — 학습한 사실, 규칙
- `notes` — 메모, 아이디어
- `reminders` — 중요 알림

**중요도 레벨:** 1~5 (5가 최고)

**사용 예시:**
```
사용자: 내 이름은 켈리야
AI: 기억했습니다! (메모리에 저장)

(프로그램 재시작 후)

사용자: 내 이름이 뭐야?
AI: 켈리님이시죠!
```

### 지식 베이스 (RAG)

AI는 문서를 학습하고 관련 내용을 자동으로 컨텍스트에 포함합니다.

```
사용자: 우리 회사 정책 문서 추가해줘
AI: (문서를 knowledge/ 폴더에 저장)

사용자: 연차 정책이 뭐야?
AI: (저장된 문서에서 자동으로 검색하여 답변)
```

## 대화 영속성

대화 기록은 SQLite 데이터베이스에 자동 저장됩니다 (`data/conversations.db`).

- 모든 메시지 저장
- 전체 토큰 사용량 추적
- 대화 검색 가능
- 자동 백업

## 테스트

```bash
# 전체 테스트 실행
pytest tests/ -v

# 특정 테스트만 실행
pytest tests/test_tool_manager.py -v

# 커버리지 확인
pytest tests/ --cov=. --cov-report=html

# 빠른 테스트 (외부 API 제외)
pytest tests/ -m "not slow"
```

## 배포

### Docker 배포 (권장)

```bash
# 컴포즈 파일로 배포
docker-compose up -d

# 상태 확인
docker-compose ps

# 로그 모니터링
docker-compose logs -f

# 중지
docker-compose down
```

**특징:**
- 비 root 사용자 실행
- SQLite 영속 볼륨
- 헬스 체크 포함
- 자동 재시작 정책

### Kubernetes 배포

헬스 체크가 Kubernetes 준비도/생존도 프로브 지원:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8766
  initialDelaySeconds: 10
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /ready
    port: 8766
  initialDelaySeconds: 5
  periodSeconds: 5
```

## 비용 추적

모든 API 호출의 비용을 자동으로 추적합니다.

```bash
# 비용 조회
python3 -c "from cost_tracker import get_daily_cost; print(get_daily_cost())"
```

**출력 예시:**
```
API 호출: 42회
입력 토큰: 12,345개
출력 토큰: 5,678개
총 비용: $0.45 (Anthropic 기준)
```

## 성능 메트릭

메트릭은 `data/metrics.db`에 수집됩니다.

- 평균 응답 시간
- 도구 실행 시간
- API 호출 성공률
- 에러 추적

## 감사 로깅

모든 API 호출과 도구 실행은 `data/audit.db`에 기록됩니다.

- 사용자 ID
- 요청 내용
- 응답 상태
- 타임스탬프
- IP 주소

## 관리자 도구

### 명령행 인터페이스

```bash
# 사용자 생성
python3 admin_cli.py user create --username alice --role user

# 사용자 목록
python3 admin_cli.py user list

# 통계 조회
python3 admin_cli.py stats

# 백업 생성
python3 admin_cli.py backup create

# 데이터베이스 정리
python3 admin_cli.py cleanup
```

### 웹 대시보드

http://localhost:8080에서:
- 사용자 관리
- 통계 및 메트릭
- 감사 로그 조회
- 백업 관리
- 설정 변경

## 의존성

### 필수

```
anthropic>=0.76.0        # Claude API
python-dotenv>=1.0.0    # 환경변수 관리
ddgs>=9.8.0             # DuckDuckGo 검색
requests>=2.32.0        # HTTP 요청
beautifulsoup4>=4.14.0  # HTML 파싱
pygame>=2.6.0           # 오디오 재생
pillow>=10.4.0          # 이미지 처리
websockets>=12.0        # WebSocket 서버
python-telegram-bot>=21.0 # 텔레그램 봇
```

### 선택 (필요한 것만 설치)

```
openai>=1.0.0           # OpenAI GPT-4o
google-generativeai>=0.8.0 # Google Gemini
discord.py>=2.3.0       # 디스코드 봇
slack-bolt>=1.18.0      # Slack 봇
playwright>=1.40.0      # 브라우저 자동화
```

## 문제 해결

### WebSocket 연결 실패

```bash
# 1. 토큰 확인
echo $WS_AUTH_TOKEN

# 2. 포트 확인
netstat -an | grep 8765

# 3. 로그 확인
tail -f logs/flux-openclaw.log
```

### 도구 실행 오류

```bash
# 1. 도구 검증
python3 -c "from core import ToolManager; tm = ToolManager(); print(tm.list_tools())"

# 2. 도구 테스트
python3 -c "from tools.web_search import main; print(main('test'))"
```

### API 비용 과다

```bash
# 1. 일일 제한 확인
echo $MAX_DAILY_CALLS

# 2. 사용량 조회
python3 -c "from cost_tracker import get_daily_cost; print(get_daily_cost())"

# 3. 제한 변경
export MAX_DAILY_CALLS=50
```

## 성능 최적화

### 응답 속도 개선

1. **스트리밍 활성화** (기본값: true)
   ```bash
   export STREAMING_ENABLED=true
   ```

2. **토큰 제한 조정**
   ```bash
   export MAX_TOKENS=2048  # 기본 4096
   ```

3. **도구 라운드 제한**
   ```bash
   export MAX_TOOL_ROUNDS=5  # 기본 10
   ```

### 메모리 사용 최소화

1. **대화 히스토리 제한**
   ```bash
   export MAX_HISTORY=20  # 기본 50
   ```

2. **메모리 정리**
   ```bash
   python3 admin_cli.py cleanup --age-days 30
   ```

## 보안 베스트 프랙티스

1. **API 키 관리**
   - `.env` 파일을 `.gitignore`에 추가
   - 프로덕션에는 환경변수 사용
   - 정기적으로 키 로테이션

2. **접근 제어**
   - AUTH_ENABLED=true로 멀티 사용자 활성화
   - 강력한 JWT_SECRET 설정
   - 역할 기반 권한 관리

3. **네트워크 보안**
   - 방화벽으로 포트 제한
   - HTTPS/WSS 프로토콜 사용 (프로덕션)
   - CORS 도메인 화이트리스트

4. **감시 및 로깅**
   - LOG_FORMAT=json으로 구조화된 로깅
   - 감사 로그 정기 검토
   - 비정상 패턴 모니터링

## 기여 가이드

1. Fork 저장소
2. Feature 브랜치 생성: `git checkout -b feature/my-feature`
3. 커밋: `git commit -am 'Add feature'`
4. 테스트 추가: `pytest tests/`
5. Push: `git push origin feature/my-feature`
6. Pull Request 생성

## 라이선스

MIT

## 참고 자료

- [아키텍처 문서](docs/ARCHITECTURE.md)
- [보안 가이드](security.md)
- [코딩 스타일](style.md)
- [API 문서](docs/API.md)

## 지원

문제가 발생하면:
1. [이슈 검색](https://github.com/jeromwolf/flux-openclaw/issues)
2. 새 이슈 생성 (스택 트레이스 포함)
3. 토론 포럼 참여

## 감사의 말

- Anthropic Claude API
- 오픈소스 커뮤니티
- 모든 기여자
