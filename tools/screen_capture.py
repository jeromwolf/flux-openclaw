import os
import datetime
from pathlib import Path

SCHEMA = {
    "name": "screen_capture",
    "description": "화면을 캡처하여 이미지 파일로 저장합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "output_path": {"type": "string", "description": "저장할 파일 경로 (선택사항, 기본값: screenshots/screenshot_YYYYMMDD_HHMMSS.png)"},
        },
        "required": [],
    },
}


def capture_screenshot(output_path=None):
    """화면을 캡처하고 파일로 저장"""
    try:
        from PIL import ImageGrab

        cwd = Path(".").resolve()

        if output_path is None:
            screenshots_dir = cwd / "screenshots"
            screenshots_dir.mkdir(exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            resolved = screenshots_dir / f"screenshot_{timestamp}.png"
        else:
            resolved = Path(output_path).resolve()
            # 심볼릭 링크 차단
            if Path(output_path).is_symlink():
                return "Error: 심볼릭 링크는 허용되지 않습니다."
            # 워크스페이스 외부 접근 차단
            if not str(resolved).startswith(str(cwd) + os.sep):
                return "Error: 현재 디렉토리 범위 밖에는 저장할 수 없습니다."

        screenshot = ImageGrab.grab()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        screenshot.save(str(resolved))
        return f"스크린샷이 저장되었습니다: {resolved.relative_to(cwd)}"

    except Exception as e:
        return "Error: 스크린샷 캡처 실패"


def main(output_path=None):
    return capture_screenshot(output_path)


if __name__ == "__main__":
    import sys, json

    if len(sys.argv) > 1:
        print(main(sys.argv[1]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
