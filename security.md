# 보안 가이드

이 문서는 flux-openclaw 프로젝트의 보안 설계와 방어 전략을 기록합니다. OpenClaw의 실제 보안 사고를 분석하여 동일한 취약점을 방지합니다.

## 핵심 원칙

- **기본이 차단, 명시적으로 허용** (Deny by Default): OpenClaw은 "기본이 허용"이라 뚫렸다.
- **최소 권한**: 에이전트에게 필요한 최소한의 권한만 부여한다.
- **심층 방어**: 하나의 방어가 뚫려도 다음 방어가 막는다.

## 경로 탈출 방지 (Path Traversal)

- **워크스페이스 격리**: 모든 파일 접근은 워크스페이스 디렉토리 내부로 제한한다.
- **pathlib.Path.resolve()**: 모든 파일 도구에서 `Path.resolve()` + `startswith(cwd)` 체크로 경로 탈출을 차단한다.
- **심볼릭 링크 차단**: `Path.is_symlink()` 체크로 symlink를 따라가지 않는다.

## 스킬 검증 (ToolManager)

- **위험 패턴 탐지**: 15종의 위험 패턴(`os.system`, `subprocess`, `eval`, `exec`, `__import__`, `compile`, `globals`, `getattr`, `importlib`, `ctypes`, `pickle`, `shutil.rmtree`, `socket`, `os.popen`, `os.exec*`)을 자동 검출한다.
- **첫 로드 검사**: 기존 도구도 위험 패턴을 검사하되 자동 승인한다.
- **새 도구 승인**: 새로 추가된 도구에 위험 패턴이 있으면 사용자 승인을 요청한다.
- **수정 시 재검증**: 수정된 도구는 재승인이 필요하다.

## 프롬프트 인젝션 방어

- **시스템/사용자 분리**: 시스템 프롬프트와 사용자 입력을 명확하게 분리한다.
- **도구 결과 경계 마커**: 도구 실행 결과를 `[TOOL OUTPUT]...[/TOOL OUTPUT]`으로 감싸서 지시문과 구분한다.
- **민감 정보 격리**: API 키, 토큰, .env 내용은 프롬프트에 절대 포함하지 않는다.

## API 키 보호

- **환경변수만 사용**: 모든 키는 `.env` 파일에만 저장하고 코드에 하드코딩하지 않는다.
- **.gitignore 필수**: `.env` 파일을 반드시 `.gitignore`에 등록한다.
- **로그 마스킹**: `_mask_secrets()` 함수로 `sk-ant-*`, `AIza*`, `sk-*` 패턴을 자동 `[REDACTED]` 처리한다.
- **읽기 차단**: `read_text_file`에서 `.env`, `.env.local` 등 환경변수 파일 읽기를 차단한다.
- **출력 마스킹**: `read_text_file` 결과에서 API 키 패턴을 자동 마스킹한다.

## SSRF 방어 (web_fetch)

- **프라이빗 IP 차단**: `is_private`, `is_loopback`, `is_link_local`, `is_reserved` 대역 차단 + DNS 해석 후 재검증한다.
- **리다이렉트 검증**: 최대 5회, 각 hop마다 스킴(`http/https`만)과 IP를 재검증한다.
- **응답 크기 제한**: `stream=True` + 5MB 제한으로 대용량 응답을 차단한다.
- **URL 스킴 제한**: `http`, `https`만 허용한다.

## 파일 보호

- **보호 파일**: `.env`, `main.py`, `instruction.md`, `.gitignore`, `requirements.txt`, `security.md`, `style.md`는 쓰기 차단된다.
- **보호 디렉토리**: `tools/` 내 기존 파일은 덮어쓰기가 차단된다.
- **콘텐츠 크기 제한**: 파일 저장 시 1MB 크기 제한을 적용한다.

## 서버/WebSocket 보안 (ws_server.py)

- **Origin 검증**: `WS_ALLOWED_ORIGINS` 환경변수에 등록된 origin만 허용한다. (CVE-2026-25253 방지)
- **토큰 인증**: 쿼리 파라미터 `?token=xxx`로 `WS_AUTH_TOKEN`과 대조하여 인증한다.
- **로컬 바인딩**: 기본 `127.0.0.1`에만 바인딩, `WS_HOST`로 명시적 변경 가능하다.
- **Rate Limiting**: 연결당 분당 30메시지 제한, 슬라이딩 윈도우 방식이다.
- **오류 정보 차단**: 내부 오류 메시지를 사용자에게 노출하지 않고 일반 오류만 반환한다.

## 텔레그램 봇 보안 (telegram_bot.py)

- **허용 사용자 목록**: `TELEGRAM_ALLOWED_USERS` 환경변수에 등록된 `chat_id`만 명령을 수락한다.
- **미등록 사용자 무시**: 허용 목록에 없는 메시지는 무시하고 로깅만 한다.
- **도구 제한**: `save_text_file`, `screen_capture`는 텔레그램에서 호출할 수 없다.
- **오류 정보 차단**: 내부 오류를 사용자에게 노출하지 않는다.

## 비용 보호 (usage_data.json)

- **일일 API 호출 상한**: 하루 최대 100회 (main.py, ws_server.py, telegram_bot.py 공유). OpenClaw 하룻밤 $20 소진 사례 방지.
- **토큰 사용량 추적**: 입력/출력 토큰을 `usage_data.json`에 일별 기록하고 콘솔에 표시한다.
- **세션 누적 표시**: 현재 세션의 누적 토큰 사용량을 실시간으로 표시한다.

## 입력 검증

- **도시 이름 화이트리스트**: `weather` 도구에서 영문/한글/공백/하이픈만 허용, 100자 제한.
- **검색 결과 수 상한**: `web_search`에서 `max_results` 최대 20개 제한.
- **URL 인코딩**: 도시명 등 외부 입력을 URL에 삽입할 때 `urllib.parse.quote()` 사용.

## OpenClaw 사고 대응표

| OpenClaw 사고 | 원인 | 우리의 방어 | 상태 |
|--------------|------|------------|------|
| CVE-2026-25253 (원클릭 RCE) | WebSocket origin 미검증 | origin + 토큰 이중 인증 (`ws_server.py`) | 구현됨 |
| ClawHavoc (악성 스킬 341개) | 스킬 검증 없음 | 15종 위험 패턴 탐지 + 사용자 승인 (`ToolManager`) | 구현됨 |
| API 키 150만 건 노출 | DB 설정 오류 | .env + 로그 마스킹 + 프롬프트 격리 | 구현됨 |
| 명령 인젝션 | shell=True | subprocess 미사용 + 위험 패턴 탐지 | 구현됨 |
| 프롬프트 인젝션 | 입력 미분리 | 도구 결과 경계 마커 `[TOOL OUTPUT]` | 구현됨 |
| 비용 폭주 ($20/밤) | 호출 제한 없음 | 일일 100회 API 호출 상한 (`usage_data.json`) | 구현됨 |
| 경로 탈출 | 경로 검증 없음 | `pathlib.Path.resolve()` + 심볼릭 링크 차단 | 구현됨 |
| SSRF | URL 검증 없음 | 프라이빗 IP 차단 + 리다이렉트 검증 | 구현됨 |
