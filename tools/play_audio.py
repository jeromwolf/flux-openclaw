import os
from pathlib import Path
import pygame

# 전역 변수로 재생 상태 관리
_audio_playing = False
_current_music = None

# 허용된 오디오 파일 확장자
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".mid", ".midi"}

SCHEMA = {
    "name": "play_audio",
    "description": "음악 파일을 재생하거나 중지합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "수행할 작업 ('play', 'stop', 'pause', 'resume', 'status')",
                "enum": ["play", "stop", "pause", "resume", "status"]
            },
            "file_path": {
                "type": "string",
                "description": "재생할 음악 파일 경로 (action이 'play'일 때 필요)"
            },
            "volume": {
                "type": "number",
                "description": "볼륨 설정 (0.0 ~ 1.0, 선택사항)",
                "minimum": 0.0,
                "maximum": 1.0
            }
        },
        "required": ["action"],
    },
}


def main(action, file_path=None, volume=0.7):
    global _audio_playing, _current_music

    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()

        if action == "play":
            if not file_path:
                return "Error: 재생할 파일 경로를 지정해주세요."

            cwd = Path(".").resolve()
            resolved = Path(file_path).resolve()

            # 심볼릭 링크 차단
            if Path(file_path).is_symlink():
                return "Error: 심볼릭 링크는 허용되지 않습니다."

            # 워크스페이스 외부 접근 차단
            if not resolved == cwd and not str(resolved).startswith(str(cwd) + os.sep):
                return "Error: 현재 디렉토리 범위 밖에는 접근할 수 없습니다."

            if not resolved.exists():
                return f"Error: 파일이 존재하지 않습니다: {file_path}"

            # 오디오 파일 확장자 검증
            if resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
                return f"Error: 지원하지 않는 오디오 형식입니다. 허용: {', '.join(ALLOWED_EXTENSIONS)}"

            if _audio_playing:
                pygame.mixer.music.stop()

            pygame.mixer.music.load(str(resolved))
            pygame.mixer.music.set_volume(volume)
            pygame.mixer.music.play()

            _audio_playing = True
            _current_music = resolved.name

            return f"음악 재생을 시작했습니다: {resolved.name} (볼륨: {volume:.1f})"

        elif action == "stop":
            if _audio_playing:
                pygame.mixer.music.stop()
                _audio_playing = False
                name = _current_music or "알 수 없음"
                _current_music = None
                return f"음악 재생을 중지했습니다: {name}"
            return "재생 중인 음악이 없습니다."

        elif action == "pause":
            if _audio_playing and pygame.mixer.music.get_busy():
                pygame.mixer.music.pause()
                return f"음악을 일시정지했습니다: {_current_music or '알 수 없음'}"
            return "재생 중인 음악이 없습니다."

        elif action == "resume":
            if _audio_playing:
                pygame.mixer.music.unpause()
                return f"음악 재생을 재개했습니다: {_current_music or '알 수 없음'}"
            return "일시정지된 음악이 없습니다."

        elif action == "status":
            if _audio_playing and _current_music:
                status = "재생 중" if pygame.mixer.music.get_busy() else "일시정지됨"
                return f"상태: {status}, 파일: {_current_music}, 볼륨: {pygame.mixer.music.get_volume():.1f}"
            return "재생 중인 음악이 없습니다."

        else:
            return "Error: 알 수 없는 액션입니다."

    except Exception:
        return "Error: 오디오 처리 실패"


if __name__ == "__main__":
    import sys, json

    if len(sys.argv) >= 3:
        print(main(sys.argv[1], sys.argv[2]))
    elif len(sys.argv) > 1:
        print(main(sys.argv[1]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
