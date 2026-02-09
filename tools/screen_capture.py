import os
import datetime
from PIL import ImageGrab
import keyboard

SCHEMA = {
    "name": "screen_capture",
    "description": "화면을 캡처하여 이미지 파일로 저장합니다. Command+P 단축키로 실행할 수 있습니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "output_path": {"type": "string", "description": "저장할 파일 경로 (선택사항, 기본값: screenshots/screenshot_YYYYMMDD_HHMMSS.png)"},
            "mode": {"type": "string", "description": "캡처 모드 ('full': 전체화면, 'region': 영역선택)", "default": "full"},
        },
        "required": [],
    },
}


def capture_screenshot(output_path=None, mode="full"):
    """화면을 캡처하고 파일로 저장"""
    try:
        # 기본 저장 경로 설정
        if output_path is None:
            # screenshots 디렉토리 생성
            screenshots_dir = "screenshots"
            if not os.path.exists(screenshots_dir):
                os.makedirs(screenshots_dir)
            
            # 현재 시간으로 파일명 생성
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(screenshots_dir, f"screenshot_{timestamp}.png")
        
        # 화면 캡처
        if mode == "full":
            # 전체 화면 캡처
            screenshot = ImageGrab.grab()
        else:
            # 영역 선택 캡처 (여기서는 전체 화면으로 대체)
            print("영역 선택 모드는 현재 전체 화면 캡처로 동작합니다.")
            screenshot = ImageGrab.grab()
        
        # 파일 저장
        screenshot.save(output_path)
        return f"스크린샷이 저장되었습니다: {output_path}"
        
    except Exception as e:
        return f"Error: 스크린샷 캡처 중 오류가 발생했습니다: {str(e)}"


def setup_hotkey():
    """Command+P 단축키 설정 (macOS)"""
    try:
        # macOS에서 Command+P 단축키 등록
        keyboard.add_hotkey('cmd+p', lambda: print(capture_screenshot()))
        print("단축키 등록됨: Command+P로 스크린샷을 캡처할 수 있습니다.")
        print("프로그램을 종료하려면 Ctrl+C를 누르세요.")
        
        # 키보드 이벤트 대기
        keyboard.wait('esc')  # ESC 키로 종료
        
    except Exception as e:
        print(f"단축키 설정 오류: {str(e)}")
        print("Windows에서는 'ctrl+p'를 시도합니다.")
        try:
            keyboard.add_hotkey('ctrl+p', lambda: print(capture_screenshot()))
            print("단축키 등록됨: Ctrl+P로 스크린샷을 캡처할 수 있습니다.")
            keyboard.wait('esc')
        except Exception as e2:
            return f"Error: 단축키 설정 실패: {str(e2)}"


def main(output_path=None, mode="full"):
    """메인 함수"""
    return capture_screenshot(output_path, mode)


if __name__ == "__main__":
    import sys
    import json
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--hotkey":
            # 단축키 모드로 실행
            setup_hotkey()
        else:
            # 직접 캡처 실행
            output_path = sys.argv[1] if len(sys.argv) > 1 else None
            mode = sys.argv[2] if len(sys.argv) > 2 else "full"
            print(main(output_path, mode))
    else:
        # 스키마 출력
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
        print("\n사용법:")
        print("python screen_capture.py                    # 스키마 출력")
        print("python screen_capture.py [출력경로] [모드]   # 스크린샷 캡처")
        print("python screen_capture.py --hotkey           # 단축키 모드 실행")
        print("\n필요한 패키지 설치:")
        print("pip install pillow keyboard")