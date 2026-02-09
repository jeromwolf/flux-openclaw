import os
import threading
import pygame

# 전역 변수로 재생 상태 관리
_audio_playing = False
_current_music = None

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
        # pygame 믹서 초기화 (한 번만)
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        
        if action == "play":
            if not file_path:
                return "Error: 재생할 파일 경로를 지정해주세요."
            
            # 파일 경로 보안 검증
            resolved = os.path.realpath(file_path)
            cwd = os.path.realpath(".")
            if not resolved.startswith(cwd + os.sep) and resolved != os.path.join(cwd, os.path.basename(file_path)):
                return "Error: 현재 디렉토리 범위 밖에는 접근할 수 없습니다."
            
            if not os.path.exists(resolved):
                return f"Error: 파일이 존재하지 않습니다: {file_path}"
            
            # 이전 음악이 재생 중이면 중지
            if _audio_playing:
                pygame.mixer.music.stop()
            
            # 음악 로드 및 재생
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.set_volume(volume)
            pygame.mixer.music.play()
            
            _audio_playing = True
            _current_music = file_path
            
            return f"음악 재생을 시작했습니다: {os.path.basename(file_path)} (볼륨: {volume:.1f})"
        
        elif action == "stop":
            if _audio_playing:
                pygame.mixer.music.stop()
                _audio_playing = False
                current_file = _current_music
                _current_music = None
                return f"음악 재생을 중지했습니다: {os.path.basename(current_file) if current_file else '알 수 없음'}"
            else:
                return "재생 중인 음악이 없습니다."
        
        elif action == "pause":
            if _audio_playing and pygame.mixer.music.get_busy():
                pygame.mixer.music.pause()
                return f"음악을 일시정지했습니다: {os.path.basename(_current_music) if _current_music else '알 수 없음'}"
            else:
                return "재생 중인 음악이 없습니다."
        
        elif action == "resume":
            if _audio_playing:
                pygame.mixer.music.unpause()
                return f"음악 재생을 재개했습니다: {os.path.basename(_current_music) if _current_music else '알 수 없음'}"
            else:
                return "일시정지된 음악이 없습니다."
        
        elif action == "status":
            if _audio_playing and _current_music:
                is_busy = pygame.mixer.music.get_busy()
                status = "재생 중" if is_busy else "일시정지됨"
                return f"상태: {status}, 파일: {os.path.basename(_current_music)}, 볼륨: {pygame.mixer.music.get_volume():.1f}"
            else:
                return "재생 중인 음악이 없습니다."
        
        else:
            return f"Error: 알 수 없는 액션입니다: {action}"
    
    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    import sys, json
    
    if len(sys.argv) > 1:
        if len(sys.argv) >= 3:
            # play action with file path
            result = main(sys.argv[1], sys.argv[2])
        else:
            # other actions
            result = main(sys.argv[1])
        print(result)
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))