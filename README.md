# flux-openclaw

Claude API 기반의 자기 확장형(Self-Extending) AI 에이전트입니다.
`tools/` 폴더에 파이썬 파일을 추가하면 실행 중에도 자동으로 인식하여 새 기능을 사용할 수 있습니다.

## 주요 기능

- **자동 도구 로딩** — `tools/` 폴더의 파일 추가·수정·삭제를 감지하여 자동 리로드
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

## 프로젝트 구조

```
flux-openclaw/
├── main.py                 # 메인 에이전트 (ToolManager + 대화 루프)
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
│   └── instruction.md      # 시스템 프롬프트
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

## 환경 변수

| 변수 | 설명 |
|------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 키 (필수) |

## 라이선스

MIT
