# flux-openclaw

Claude API 기반의 자기 확장형(Self-Extending) AI 에이전트입니다.
`tools/` 폴더에 파이썬 파일을 추가하면 실행 중에도 자동으로 인식하여 새 기능을 사용할 수 있습니다.

## 주요 기능

- **자동 도구 로딩** — `tools/` 폴더의 파일 추가·수정·삭제를 감지하여 자동 리로드
- **영속 메모리** — `memory/memory.md`에 사용자 정보와 메모를 저장하고 세션 간 기억 유지
- **자기 확장** — AI가 대화 중 새로운 도구를 직접 만들어 `tools/`에 저장, 즉시 사용 가능
- **대화 히스토리** — 세션 종료 시 대화 기록 자동 저장, 다음 시작 시 복원 가능
- **비용 보호** — 일일 API 호출 100회 제한 + 토큰 사용량 실시간 추적
- **WebSocket 서버** — 웹 앱에서 접근 가능한 보안 WebSocket 인터페이스
- **텔레그램 봇** — 텔레그램 메신저를 통한 AI 채팅 인터페이스
- **웹 검색** — DuckDuckGo 기반 실시간 인터넷 검색
- **날씨 조회** — wttr.in API를 통한 현재 날씨 및 3일 예보
- **파일 관리** — 텍스트 파일 읽기·쓰기·목록 조회
- **오디오 재생** — pygame 기반 음악 파일 재생·일시정지·중지
- **스크린 캡처** — 화면 캡처 및 저장
- **웹 페이지 가져오기** — URL 내용을 텍스트로 추출

## 빠른 시작

```bash
# 저장소 클론
git clone git@github.com:jeromwolf/flux-openclaw.git
cd flux-openclaw

# 의존성 설치
pip install -r requirements.txt

# API 키 설정
cp .env.example .env
# .env 파일에 ANTHROPIC_API_KEY 입력

# 실행
python3 main.py
```

## 실행 모드

### CLI 모드 (기본)
```bash
python3 main.py
```

### WebSocket 서버
```bash
# .env에 WS_AUTH_TOKEN 설정 필요
python3 ws_server.py
```

### 텔레그램 봇
```bash
# .env에 TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USERS 설정 필요
python3 telegram_bot.py
```

## 프로젝트 구조

```
flux-openclaw/
├── main.py                 # CLI 에이전트 (ToolManager + 대화 루프)
├── ws_server.py            # WebSocket 서버 인터페이스
├── telegram_bot.py         # 텔레그램 봇 인터페이스
├── tools/                  # 도구 폴더 (자동 로딩)
│   ├── web_search.py       # 인터넷 검색
│   ├── weather.py          # 날씨 조회
│   ├── web_fetch.py        # 웹 페이지 가져오기
│   ├── read_text_file.py   # 파일 읽기
│   ├── save_text_file.py   # 파일 저장
│   ├── list_files.py       # 디렉토리 목록
│   ├── play_audio.py       # 오디오 재생
│   ├── screen_capture.py   # 스크린 캡처
│   ├── add_two_numbers.py  # 덧셈
│   └── multiply_two_numbers.py # 곱셈
├── memory/
│   ├── instruction.md      # 시스템 프롬프트
│   └── memory.md           # 영속 메모리 (AI가 읽고 쓰기)
├── history/                # 대화 히스토리 (자동 생성)
├── usage_data.json         # 일일 API 사용량 (자동 생성)
├── requirements.txt
├── security.md             # 보안 가이드
└── style.md                # 코딩 스타일 가이드
```

## 도구 만들기

`tools/` 폴더에 아래 형식의 `.py` 파일을 추가하면 자동으로 인식됩니다:

```python
SCHEMA = {
    "name": "my_tool",
    "description": "도구 설명",
    "input_schema": {
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "매개변수 설명"},
        },
        "required": ["param"],
    },
}

def main(param):
    return f"결과: {param}"
```

재시작 없이 다음 사용자 입력부터 바로 사용 가능합니다.

AI에게 "주사위 기능 만들어줘"라고 말하면 스스로 도구를 생성합니다.

## 메모리

AI는 `memory/memory.md` 파일을 통해 대화 간 기억을 유지합니다.

- 프로그램 시작 시 자동으로 시스템 프롬프트에 주입
- "기억해", "메모해" 등으로 요청하면 AI가 직접 저장
- 사용자 이름, 선호, 약속, 메모 등을 세션 간 유지

```
켈리: 내 이름은 켈리야. 기억해
AI: 기억했습니다! 다음에도 켈리라고 불러드릴게요.

(프로그램 재시작 후)

켈리: 내 이름이 뭐야?
AI: 켈리님이시죠!
```

## 대화 히스토리

- 프로그램 종료 시(`exit`/`quit`) 대화 기록이 `history/` 폴더에 자동 저장됩니다
- 다음 시작 시 마지막 세션을 복원할지 묻습니다
- 파일명 형식: `history/history_20260209_143000.json`

## 비용 보호

- 일일 API 호출 100회 제한 (모든 인터페이스에서 공유)
- 매 응답마다 토큰 사용량 표시: `[토큰] 입력: 1234 / 출력: 567 (누적: 5000/3000)`
- `usage_data.json`에 일별 사용량 기록
- 제한 도달 시 API 호출 자동 차단

## 보안

OpenClaw의 보안 사고를 분석하여 동일 취약점을 방지하는 심층 방어 구조를 적용했습니다.

| 방어 계층 | 내용 |
|-----------|------|
| **경로 탈출 방지** | 모든 파일 도구에서 `pathlib.Path.resolve()` + 심볼릭 링크 차단 |
| **SSRF 차단** | `web_fetch`에서 프라이빗 IP, 리다이렉트 스킴/IP 검증, 응답 5MB 제한 |
| **도구 로딩 검증** | 새 도구 추가 시 위험 패턴(`os.system`, `subprocess`, `eval` 등 15종) 탐지 + 사용자 승인 |
| **파일 보호** | `.env`, `main.py`, `instruction.md` 등 핵심 파일 쓰기/읽기 차단 |
| **로그 마스킹** | API 키 패턴(`sk-ant-*`, `AIza*`) 자동 `[REDACTED]` 처리 |
| **WebSocket 보안** | Origin 검증 + 토큰 인증 + 로컬 바인딩 + Rate Limiting |
| **텔레그램 보안** | 허용 사용자 목록 + 위험 도구 차단 + 오류 정보 차단 |
| **비용 보호** | 일일 100회 API 호출 상한 + 토큰 사용량 추적 |

자세한 내용은 [security.md](security.md) 참고.

## 환경 변수

| 변수 | 설명 | 필수 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 키 | O |
| `WS_AUTH_TOKEN` | WebSocket 인증 토큰 | WebSocket 사용 시 |
| `WS_ALLOWED_ORIGINS` | 허용 Origin (쉼표 구분) | 선택 (기본: localhost:3000) |
| `WS_PORT` | WebSocket 포트 | 선택 (기본: 8765) |
| `WS_HOST` | WebSocket 바인딩 주소 | 선택 (기본: 127.0.0.1) |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 | 텔레그램 사용 시 |
| `TELEGRAM_ALLOWED_USERS` | 허용 chat_id (쉼표 구분) | 텔레그램 사용 시 |

## 라이선스

MIT
