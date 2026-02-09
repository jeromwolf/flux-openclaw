import os
import re
import sys
import json
import glob
import warnings
import importlib.util
from datetime import datetime

# pygame 환영 메시지 억제 (import 전에 설정 필요)
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

# urllib3 LibreSSL 경고 억제
warnings.filterwarnings("ignore", message=".*urllib3.*OpenSSL.*", category=Warning)

from dotenv import load_dotenv
import anthropic

load_dotenv()

# 로그 마스킹 패턴
_SECRET_RE = re.compile(r"(sk-ant-[a-zA-Z0-9_-]+|AIza[a-zA-Z0-9_-]+|sk-[a-zA-Z0-9_-]{20,})")


def _mask_secrets(text):
    return _SECRET_RE.sub("[REDACTED]", str(text))


def log(f, role, message):
    masked = _mask_secrets(message)
    f.write(f"## {role} ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n\n{masked}\n\n")
    f.flush()


_DANGEROUS_PATTERNS = [
    r"\bos\.system\b", r"\bos\.popen\b", r"\bos\.exec\w*\b",
    r"\bsubprocess\b", r"\beval\s*\(", r"\bexec\s*\(",
    r"\b__import__\b", r"\bcompile\s*\(", r"\bglobals\s*\(", r"\bgetattr\s*\(",
    r"\bimportlib\b", r"\bctypes\b", r"\bpickle\b",
    r"\bshutil\.rmtree\b", r"\bsocket\b",
]
_DANGEROUS_RE = re.compile("|".join(_DANGEROUS_PATTERNS))


class ToolManager:
    """tools/ 폴더를 감시하여 도구 파일 추가·수정·삭제 시 자동으로 리로드"""

    def __init__(self, tools_dir="tools"):
        self.tools_dir = tools_dir
        self.schemas = []
        self.functions = {}
        self._file_mtimes = {}
        self._approved = set()  # 사용자 승인된 파일
        self._load_all(first_load=True)

    def _scan_files(self):
        """tools/ 내 .py 파일의 {파일명: 수정시각} 반환"""
        mtimes = {}
        if not os.path.isdir(self.tools_dir):
            return mtimes
        for fname in os.listdir(self.tools_dir):
            if fname.endswith(".py"):
                path = os.path.join(self.tools_dir, fname)
                mtimes[fname] = os.path.getmtime(path)
        return mtimes

    def _check_dangerous(self, filepath):
        """위험 패턴 탐지. 발견된 패턴 목록 반환"""
        with open(filepath, "r") as f:
            code = f.read()
        return _DANGEROUS_RE.findall(code)

    def _load_module(self, filename, first_load=False):
        """단일 .py 파일을 로드하여 (schema, func) 또는 None 반환"""
        filepath = os.path.join(self.tools_dir, filename)
        module_name = filename[:-3]

        # 위험 패턴 검사 + 사용자 승인 (첫 로드 시에도 검사, 승인 프롬프트는 새 파일만)
        if filename not in self._approved:
            dangers = self._check_dangerous(filepath)
            if dangers:
                if first_load:
                    print(f" [보안 알림] {filename}: 위험 패턴 감지됨 (기존 도구이므로 자동 승인)")
                else:
                    print(f" [보안 경고] {filename}에서 위험 패턴 발견: {dangers}")
                    confirm = input(f" {filename}을(를) 로드하시겠습니까? (Y/N): ").strip().upper()
                    if confirm != "Y":
                        print(f" [도구 차단] {filename}")
                        return None

        spec = importlib.util.spec_from_file_location(module_name, filepath)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f" [도구 로드 실패] {filename}: {e}")
            return None
        if hasattr(module, "SCHEMA") and hasattr(module, "main"):
            self._approved.add(filename)
            return module.SCHEMA, module.main
        return None

    def _load_all(self, first_load=False):
        """전체 도구 파일을 스캔하여 로드"""
        self.schemas = []
        self.functions = {}
        self._file_mtimes = self._scan_files()
        for fname in sorted(self._file_mtimes):
            result = self._load_module(fname, first_load=first_load)
            if result:
                schema, func = result
                self.schemas.append(schema)
                self.functions[schema["name"]] = func
        print(f" [도구] {len(self.functions)}개 로드됨: {', '.join(self.functions.keys())}")

    def reload_if_changed(self):
        """파일 변경 감지 시 자동 리로드. 변경 있으면 True 반환"""
        current = self._scan_files()
        if current == self._file_mtimes:
            return False

        added = set(current) - set(self._file_mtimes)
        removed = set(self._file_mtimes) - set(current)
        modified = {
            f for f in set(current) & set(self._file_mtimes)
            if current[f] != self._file_mtimes[f]
        }

        if added:
            print(f" [도구 추가 감지] {', '.join(added)}")
        if removed:
            print(f" [도구 삭제 감지] {', '.join(removed)}")
        if modified:
            print(f" [도구 수정 감지] {', '.join(modified)}")
            # 수정된 파일은 재승인 필요
            self._approved -= modified

        self._load_all()
        return True


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
        return

    tool_mgr = ToolManager()

    client = anthropic.Anthropic(api_key=api_key)

    # 시스템 프롬프트 구성: instruction + memory
    instruction_path = "memory/instruction.md"
    memory_path = "memory/memory.md"

    if os.path.exists(instruction_path):
        with open(instruction_path, "r") as inf:
            system_prompt = inf.read()
    else:
        system_prompt = "당신은 도움이 되는 AI 어시스턴트입니다."

    if os.path.exists(memory_path):
        with open(memory_path, "r") as mf:
            memory_content = mf.read().strip()
        if memory_content:
            system_prompt += f"\n\n## 기억 (memory/memory.md)\n아래는 이전 대화에서 저장한 기억입니다. 참고하세요.\n\n{memory_content}"
            print(f" [메모리] memory.md 로드됨 ({len(memory_content)}자)")

    messages = []
    cumulative_input_tokens = 0
    cumulative_output_tokens = 0

    # --- S1: 일일 API 사용량 로드 ---
    usage_file = "usage_data.json"
    today_str = datetime.now().strftime("%Y-%m-%d")

    def load_usage():
        if os.path.exists(usage_file):
            with open(usage_file, "r") as uf:
                data = json.load(uf)
            if data.get("date") == today_str:
                return data
        return {"date": today_str, "calls": 0, "input_tokens": 0, "output_tokens": 0}

    def save_usage(data):
        with open(usage_file, "w") as uf:
            json.dump(data, uf, ensure_ascii=False)

    usage = load_usage()
    if usage["calls"] > 0:
        print(f" [사용량] 오늘 API 호출: {usage['calls']}/100, 입력토큰: {usage['input_tokens']}, 출력토큰: {usage['output_tokens']}")

    # --- F1: 이전 대화 복원 ---
    os.makedirs("history", exist_ok=True)
    history_files = sorted(glob.glob("history/history_*.json"))
    if history_files:
        restore = input(" [복원] 마지막 대화를 복원하시겠습니까? (Y/N): ").strip().upper()
        if restore == "Y":
            with open(history_files[-1], "r") as hf:
                saved = json.load(hf)
            messages = saved.get("messages", [])
            print(f" [복원] {len(messages)}개 메시지 복원됨 ({history_files[-1]})")

    with open("log.md", "w") as f:
        f.write(f"# Chat Log ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n\n")
        while True:
            user_input = input("켈리: ")
            if user_input.lower() in ["exit", "quit"]:
                # F1: 대화 기록 자동 저장
                if messages:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    save_path = f"history/history_{ts}.json"
                    with open(save_path, "w") as hf:
                        json.dump({"timestamp": ts, "messages": messages}, hf, ensure_ascii=False, indent=2)
                    print(f" [저장] 대화 기록이 저장되었습니다: {save_path}")
                break
            if not user_input.strip():
                continue

            # 매 턴마다 도구 변경 감지 및 리로드
            tool_mgr.reload_if_changed()

            log(f, "User", user_input)
            messages.append({"role": "user", "content": user_input})

            # S1: 일일 호출 한도 확인
            if usage["calls"] >= 100:
                print(" [제한] 오늘의 API 호출 한도(100회)에 도달했습니다. 내일 다시 시도해주세요.")
                messages.pop()  # 미처리 메시지 제거
                continue

            try:
                # 도구 호출이 연쇄적으로 발생할 수 있으므로 반복 처리 (최대 10회)
                MAX_TOOL_ROUNDS = 10
                tool_round = 0
                while tool_round < MAX_TOOL_ROUNDS:
                    print(" [대기중...] Claude 응답 생성 중")
                    response = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=4096,
                        system=system_prompt,
                        tools=tool_mgr.schemas,
                        messages=messages,
                    )
                    print(f" [수신] stop_reason={response.stop_reason}, blocks={len(response.content)}")

                    # S1: API 호출 카운트 및 토큰 누적
                    resp_input = response.usage.input_tokens
                    resp_output = response.usage.output_tokens
                    usage["calls"] += 1
                    usage["input_tokens"] += resp_input
                    usage["output_tokens"] += resp_output
                    cumulative_input_tokens += resp_input
                    cumulative_output_tokens += resp_output
                    save_usage(usage)

                    # F2: 토큰 사용량 표시
                    print(f" [토큰] 입력: {resp_input} / 출력: {resp_output} (누적: {cumulative_input_tokens}/{cumulative_output_tokens})")

                    log(f, "Claude", str(response))

                    # 응답이 잘린 경우 (max_tokens 초과) → 도구 실행하지 않음
                    if response.stop_reason == "max_tokens":
                        print(" [경고] 응답이 잘렸습니다. 도구 호출을 건너뜁니다.")
                        messages.append({"role": "assistant", "content": response.content})
                        # 잘린 tool_use에 대해 에러 tool_result 전달
                        tool_uses_cut = [b for b in response.content if b.type == "tool_use"]
                        if tool_uses_cut:
                            tool_results = [{
                                "type": "tool_result",
                                "tool_use_id": b.id,
                                "content": "Error: 응답이 잘려서 도구 실행 불가. 더 짧게 시도해주세요.",
                                "is_error": True,
                            } for b in tool_uses_cut]
                            messages.append({"role": "user", "content": tool_results})
                            tool_round += 1
                            continue
                        break

                    # tool_use 블록 확인
                    tool_uses = [b for b in response.content if b.type == "tool_use"]

                    if not tool_uses:
                        # 도구 호출 없음 → 텍스트 응답
                        messages.append({"role": "assistant", "content": response.content})
                        break

                    # 도구 호출 있음 → 실행 후 결과 전달
                    messages.append({"role": "assistant", "content": response.content})

                    tool_results = []
                    for tool_use in tool_uses:
                        fn = tool_mgr.functions.get(tool_use.name)
                        if not fn:
                            print(f" [DEBUG] 알 수 없는 도구: {tool_use.name}")
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": f"Error: 알 수 없는 도구: {tool_use.name}",
                            })
                            continue
                        try:
                            result = fn(**tool_use.input)
                        except Exception:
                            result = "Error: 도구 실행 실패"
                        tool_message = f"[도구 실행 결과] {tool_use.name}({tool_use.input}) => {result}"
                        log(f, "Tool->Claude", tool_message)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"[TOOL OUTPUT]\n{result}\n[/TOOL OUTPUT]",
                        })

                    messages.append({"role": "user", "content": tool_results})
                    tool_round += 1

                # 최대 횟수 초과 시 강제 종료
                if tool_round >= MAX_TOOL_ROUNDS:
                    print(f" [경고] 도구 호출이 {MAX_TOOL_ROUNDS}회를 초과하여 중단합니다.")

                # 텍스트 응답 출력
                for block in response.content:
                    if hasattr(block, "text"):
                        print(f"AI: {block.text}")

            except Exception as e:
                log(f, "Error", str(e))
                print("Error: 요청 처리 중 오류가 발생했습니다.")


if __name__ == "__main__":
    main()
