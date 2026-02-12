"""
flux-openclaw 스케줄러 엔진

cron-like 예약 작업 시스템. 독립 실행 가능 + 다른 서비스에서 import 가능.
표준 라이브러리만 사용.

데이터 파일:
- schedules.json: 예약된 작업 목록
- schedule_history.json: 실행 이력

사용법:
    python3 scheduler.py list                   # 예약 목록 조회
    python3 scheduler.py add --type once --datetime "2026-02-12 09:30" --content "회의 시작" --description "회의 리마인더"
    python3 scheduler.py add --type recurring --cron "30 9 * * 1-5" --content "출근 준비" --description "평일 리마인더"
    python3 scheduler.py remove --id <uuid>     # 예약 삭제
    python3 scheduler.py history                # 실행 이력 조회
    python3 scheduler.py run                    # 스케줄러 데몬 실행 (foreground)
"""

import os
import json
import uuid
import asyncio
from datetime import datetime, timedelta


# ============================================================
# Cron 표현식 파서
# ============================================================

class CronExpression:
    """cron 표현식 파서

    5필드: 분(0-59) 시(0-23) 일(1-31) 월(1-12) 요일(0-6, 0=일요일)
    특수문자: * (모든 값), */N (매 N), N-M (범위), N,M (목록)
    """

    FIELD_RANGES = [
        (0, 59),   # 분
        (0, 23),   # 시
        (1, 31),   # 일
        (1, 12),   # 월
        (0, 6),    # 요일 (0=일)
    ]
    FIELD_NAMES = ["minute", "hour", "day", "month", "weekday"]

    def __init__(self, expr: str):
        self.expr = expr.strip()
        parts = self.expr.split()
        if len(parts) != 5:
            raise ValueError(f"cron 표현식은 5개 필드가 필요합니다 (현재 {len(parts)}개): '{self.expr}'")
        self.fields = []
        for i, part in enumerate(parts):
            low, high = self.FIELD_RANGES[i]
            values = self._parse_field(part, low, high)
            if not values:
                raise ValueError(
                    f"cron 필드 '{self.FIELD_NAMES[i]}'의 값이 비어있습니다: '{part}'"
                )
            self.fields.append(values)

    @staticmethod
    def _parse_field(field: str, low: int, high: int) -> set:
        """단일 cron 필드를 정수 집합으로 파싱"""
        result = set()
        for token in field.split(","):
            token = token.strip()
            if not token:
                continue

            # */N  (매 N 간격)
            if token.startswith("*/"):
                step_str = token[2:]
                if not step_str.isdigit():
                    raise ValueError(f"잘못된 간격: '{token}'")
                step = int(step_str)
                if step <= 0:
                    raise ValueError(f"간격은 양수여야 합니다: '{token}'")
                for v in range(low, high + 1, step):
                    result.add(v)

            # N-M  (범위) 또는 N-M/S (범위+간격)
            elif "-" in token:
                if "/" in token:
                    range_part, step_str = token.split("/", 1)
                    if not step_str.isdigit():
                        raise ValueError(f"잘못된 간격: '{token}'")
                    step = int(step_str)
                else:
                    range_part = token
                    step = 1
                parts = range_part.split("-", 1)
                if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                    raise ValueError(f"잘못된 범위: '{token}'")
                start, end = int(parts[0]), int(parts[1])
                if start < low or end > high or start > end:
                    raise ValueError(
                        f"범위 초과: '{token}' (허용: {low}-{high})"
                    )
                if step <= 0:
                    raise ValueError(f"간격은 양수여야 합니다: '{token}'")
                for v in range(start, end + 1, step):
                    result.add(v)

            # *  (모든 값)
            elif token == "*":
                for v in range(low, high + 1):
                    result.add(v)

            # N  (단일 값)
            elif token.isdigit():
                val = int(token)
                if val < low or val > high:
                    raise ValueError(f"값 초과: {val} (허용: {low}-{high})")
                result.add(val)

            else:
                raise ValueError(f"알 수 없는 cron 토큰: '{token}'")

        return result

    def matches(self, dt: datetime) -> bool:
        """주어진 datetime이 cron 표현식에 매칭되는지 검사"""
        minute = dt.minute
        hour = dt.hour
        day = dt.day
        month = dt.month
        # Python: Monday=0 ... Sunday=6 → cron: Sunday=0, Monday=1 ... Saturday=6
        weekday = (dt.weekday() + 1) % 7

        return (
            minute in self.fields[0]
            and hour in self.fields[1]
            and day in self.fields[2]
            and month in self.fields[3]
            and weekday in self.fields[4]
        )

    def next_occurrence(self, after: datetime) -> datetime:
        """after 이후 다음 매칭 시각을 계산 (최대 2년 탐색)"""
        # 초/마이크로초 제거, 1분 뒤부터 탐색
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = after + timedelta(days=730)

        while candidate <= limit:
            if self.matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)

        raise ValueError(f"2년 내 매칭되는 시각을 찾을 수 없습니다: '{self.expr}'")


# ============================================================
# 스케줄러 엔진
# ============================================================

class Scheduler:
    """예약 작업 관리 엔진"""

    SCHEDULES_FILE = "schedules.json"
    HISTORY_FILE = "schedule_history.json"
    MAX_SCHEDULES = 50
    MAX_HISTORY = 200

    def __init__(self, base_dir=None):
        """초기화

        Args:
            base_dir: 데이터 파일이 저장될 디렉토리. None이면 현재 작업 디렉토리.
        """
        if base_dir:
            os.makedirs(base_dir, exist_ok=True)
            self._schedules_path = os.path.join(base_dir, self.SCHEDULES_FILE)
            self._history_path = os.path.join(base_dir, self.HISTORY_FILE)
        else:
            self._schedules_path = self.SCHEDULES_FILE
            self._history_path = self.HISTORY_FILE

    # --- 파일 I/O ---

    def _load_schedules(self) -> list:
        """schedules.json에서 예약 목록 로드"""
        if not os.path.exists(self._schedules_path):
            return []
        try:
            with open(self._schedules_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError, OSError):
            pass
        return []

    def _save_schedules(self, schedules: list):
        """schedules.json에 예약 목록 저장"""
        with open(self._schedules_path, "w", encoding="utf-8") as f:
            json.dump(schedules, f, ensure_ascii=False, indent=2)

    def _load_history(self) -> list:
        """schedule_history.json에서 실행 이력 로드"""
        if not os.path.exists(self._history_path):
            return []
        try:
            with open(self._history_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError, OSError):
            pass
        return []

    def _save_history(self, history: list):
        """schedule_history.json에 실행 이력 저장 (MAX_HISTORY 초과 시 오래된 항목 삭제)"""
        if len(history) > self.MAX_HISTORY:
            history = history[-self.MAX_HISTORY:]
        with open(self._history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    # --- 스케줄 관리 ---

    def add_schedule(self, schedule_type: str, cron_or_datetime: str,
                     task: dict, description: str = "") -> dict:
        """새 예약 작업 추가

        Args:
            schedule_type: "once" (일회성) 또는 "recurring" (반복)
            cron_or_datetime: recurring이면 cron 표현식, once이면 "YYYY-MM-DD HH:MM" 형식
            task: {"action": "remind|message|tool", "content": "...", "tool_name": None, "tool_args": None}
            description: 사용자가 읽을 수 있는 설명

        Returns:
            생성된 스케줄 항목 dict

        Raises:
            ValueError: 유효하지 않은 입력
        """
        schedules = self._load_schedules()

        if len(schedules) >= self.MAX_SCHEDULES:
            raise ValueError(f"최대 예약 수({self.MAX_SCHEDULES}개)에 도달했습니다.")

        if schedule_type not in ("once", "recurring"):
            raise ValueError(f"잘못된 타입: '{schedule_type}' (once 또는 recurring)")

        now = datetime.now()

        if schedule_type == "recurring":
            cron = CronExpression(cron_or_datetime)
            next_run = cron.next_occurrence(now)
            cron_str = cron_or_datetime.strip()
        else:
            # 일회성: datetime 문자열 파싱
            try:
                target_dt = datetime.strptime(cron_or_datetime.strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                raise ValueError(
                    f"날짜 형식 오류: '{cron_or_datetime}' (올바른 형식: 'YYYY-MM-DD HH:MM')"
                )
            if target_dt <= now:
                raise ValueError("과거 시각에는 예약할 수 없습니다.")
            next_run = target_dt
            cron_str = None

        # task 유효성 검사
        if not isinstance(task, dict):
            raise ValueError("task는 딕셔너리여야 합니다.")
        action = task.get("action", "remind")
        if action not in ("remind", "message", "tool"):
            raise ValueError(f"잘못된 action: '{action}' (remind, message, tool 중 선택)")

        entry = {
            "id": str(uuid.uuid4()),
            "type": schedule_type,
            "cron": cron_str,
            "next_run": next_run.strftime("%Y-%m-%dT%H:%M:%S"),
            "task": {
                "action": task.get("action", "remind"),
                "content": task.get("content", ""),
                "tool_name": task.get("tool_name"),
                "tool_args": task.get("tool_args"),
            },
            "created_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "created_by": task.get("created_by", "user"),
            "enabled": True,
            "description": description,
        }

        schedules.append(entry)
        self._save_schedules(schedules)
        return entry

    def remove_schedule(self, schedule_id: str) -> bool:
        """예약 작업 삭제

        Args:
            schedule_id: 삭제할 스케줄의 UUID

        Returns:
            삭제 성공 여부
        """
        schedules = self._load_schedules()
        original_len = len(schedules)
        schedules = [s for s in schedules if s.get("id") != schedule_id]
        if len(schedules) == original_len:
            return False
        self._save_schedules(schedules)
        return True

    def list_schedules(self) -> list:
        """활성화된 모든 예약 작업 목록 반환"""
        return self._load_schedules()

    def get_due_tasks(self) -> list:
        """현재 시각 기준으로 실행할 작업 목록 반환

        next_run이 현재 시각 이전이고 enabled인 항목을 반환합니다.
        """
        now = datetime.now()
        schedules = self._load_schedules()
        due = []

        for entry in schedules:
            if not entry.get("enabled", True):
                continue
            try:
                next_run = datetime.strptime(entry["next_run"], "%Y-%m-%dT%H:%M:%S")
            except (ValueError, KeyError):
                continue
            if next_run <= now:
                due.append(entry)

        return due

    def mark_executed(self, schedule_id: str, result: str = ""):
        """작업 실행 완료 처리

        - 반복(recurring): next_run을 다음 실행 시각으로 갱신
        - 일회성(once): enabled를 False로 변경

        Args:
            schedule_id: 실행 완료된 스케줄 ID
            result: 실행 결과 메시지
        """
        now = datetime.now()
        schedules = self._load_schedules()
        updated = False

        for entry in schedules:
            if entry.get("id") != schedule_id:
                continue

            if entry["type"] == "recurring" and entry.get("cron"):
                try:
                    cron = CronExpression(entry["cron"])
                    next_run = cron.next_occurrence(now)
                    entry["next_run"] = next_run.strftime("%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    entry["enabled"] = False
            else:
                # 일회성: 비활성화
                entry["enabled"] = False

            updated = True
            break

        if updated:
            self._save_schedules(schedules)

        # 이력 기록
        history = self._load_history()
        history.append({
            "schedule_id": schedule_id,
            "executed_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "result": result,
        })
        self._save_history(history)

    def get_history(self, limit: int = 20) -> list:
        """실행 이력 조회

        Args:
            limit: 반환할 최대 항목 수

        Returns:
            최근 실행 이력 (최신순)
        """
        history = self._load_history()
        return list(reversed(history[-limit:]))

    def cleanup_disabled(self) -> int:
        """비활성화된 일회성 작업 정리

        Returns:
            삭제된 항목 수
        """
        schedules = self._load_schedules()
        original_len = len(schedules)
        schedules = [
            s for s in schedules
            if s.get("enabled", True) or s.get("type") == "recurring"
        ]
        removed = original_len - len(schedules)
        if removed > 0:
            self._save_schedules(schedules)
        return removed

    # --- 비동기 실행 루프 ---

    async def run_loop(self, callback=None):
        """메인 스케줄러 루프 - 30초마다 due 작업 체크

        Args:
            callback: 실행할 작업이 있을 때 호출되는 함수.
                      callback(entry) 형태. None이면 콘솔에 출력.
        """
        print(f"[스케줄러] 시작됨 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
        print("[스케줄러] 30초 간격으로 예약 작업을 확인합니다. Ctrl+C로 종료.")

        try:
            while True:
                due_tasks = self.get_due_tasks()

                for entry in due_tasks:
                    task = entry.get("task", {})
                    action = task.get("action", "remind")
                    content = task.get("content", "")
                    desc = entry.get("description", "")

                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if callback:
                        try:
                            result = callback(entry)
                            self.mark_executed(entry["id"], result=str(result) if result else "OK")
                        except Exception as e:
                            self.mark_executed(entry["id"], result=f"Error: {e}")
                    else:
                        # 기본: 콘솔 출력
                        print(f"\n{'='*50}")
                        print(f"[{now_str}] 예약 작업 실행")
                        if desc:
                            print(f"  설명: {desc}")
                        print(f"  유형: {action}")
                        print(f"  내용: {content}")
                        if action == "tool" and task.get("tool_name"):
                            print(f"  도구: {task['tool_name']}")
                            print(f"  인자: {task.get('tool_args', {})}")
                        print(f"{'='*50}\n")
                        self.mark_executed(entry["id"], result="콘솔 출력 완료")

                # 주기적으로 비활성화된 일회성 작업 정리
                self.cleanup_disabled()

                await asyncio.sleep(30)

        except asyncio.CancelledError:
            print("\n[스케줄러] 종료 요청됨")
        except KeyboardInterrupt:
            print("\n[스케줄러] Ctrl+C로 종료됨")


# ============================================================
# CLI 인터페이스
# ============================================================

def _format_schedule(entry: dict) -> str:
    """스케줄 항목을 읽기 좋은 문자열로 포맷"""
    status = "ON" if entry.get("enabled", True) else "OFF"
    stype = entry.get("type", "?")
    desc = entry.get("description", "")
    cron = entry.get("cron", "")
    next_run = entry.get("next_run", "")
    task = entry.get("task", {})
    content = task.get("content", "")
    sid = entry.get("id", "?")

    lines = [f"  [{status}] {desc}" if desc else f"  [{status}] (설명 없음)"]
    lines.append(f"       ID: {sid}")
    lines.append(f"       유형: {stype}")
    if cron:
        lines.append(f"       cron: {cron}")
    lines.append(f"       다음 실행: {next_run}")
    if content:
        lines.append(f"       내용: {content}")
    if task.get("action") == "tool" and task.get("tool_name"):
        lines.append(f"       도구: {task['tool_name']} ({task.get('tool_args', {})})")

    return "\n".join(lines)


def _cli_list(scheduler: Scheduler):
    """예약 목록 출력"""
    schedules = scheduler.list_schedules()
    if not schedules:
        print("예약된 작업이 없습니다.")
        return

    enabled = [s for s in schedules if s.get("enabled", True)]
    disabled = [s for s in schedules if not s.get("enabled", True)]

    print(f"\n예약 작업 ({len(enabled)}개 활성, {len(disabled)}개 비활성):\n")
    for entry in enabled:
        print(_format_schedule(entry))
        print()
    if disabled:
        print(f"--- 비활성 ({len(disabled)}개) ---")
        for entry in disabled:
            print(_format_schedule(entry))
            print()


def _cli_add(scheduler: Scheduler, args: list):
    """CLI에서 예약 추가"""
    import argparse
    parser = argparse.ArgumentParser(prog="scheduler.py add", description="예약 작업 추가")
    parser.add_argument("--type", required=True, choices=["once", "recurring"], help="once 또는 recurring")
    parser.add_argument("--datetime", dest="dt", help="일회성: 'YYYY-MM-DD HH:MM'")
    parser.add_argument("--cron", help="반복: cron 표현식 (예: '30 9 * * 1-5')")
    parser.add_argument("--content", required=True, help="리마인더 메시지")
    parser.add_argument("--description", default="", help="설명")
    parser.add_argument("--action", default="remind", choices=["remind", "message", "tool"], help="작업 유형")
    parser.add_argument("--tool-name", help="tool 액션 시 도구 이름")
    parser.add_argument("--tool-args", help="tool 액션 시 도구 인자 (JSON)")

    parsed = parser.parse_args(args)

    if parsed.type == "once":
        if not parsed.dt:
            print("Error: 일회성 작업은 --datetime이 필요합니다.")
            return
        cron_or_datetime = parsed.dt
    else:
        if not parsed.cron:
            print("Error: 반복 작업은 --cron이 필요합니다.")
            return
        cron_or_datetime = parsed.cron

    task = {
        "action": parsed.action,
        "content": parsed.content,
        "tool_name": parsed.tool_name,
        "tool_args": json.loads(parsed.tool_args) if parsed.tool_args else None,
    }

    try:
        entry = scheduler.add_schedule(parsed.type, cron_or_datetime, task, parsed.description)
        print(f"예약 추가 완료:")
        print(_format_schedule(entry))
    except ValueError as e:
        print(f"Error: {e}")


def _cli_remove(scheduler: Scheduler, args: list):
    """CLI에서 예약 삭제"""
    if not args or args[0] != "--id" or len(args) < 2:
        print("사용법: python3 scheduler.py remove --id <uuid>")
        return
    schedule_id = args[1]
    if scheduler.remove_schedule(schedule_id):
        print(f"삭제 완료: {schedule_id}")
    else:
        print(f"해당 ID를 찾을 수 없습니다: {schedule_id}")


def _cli_history(scheduler: Scheduler):
    """실행 이력 출력"""
    history = scheduler.get_history(limit=20)
    if not history:
        print("실행 이력이 없습니다.")
        return
    print(f"\n최근 실행 이력 ({len(history)}건):\n")
    for h in history:
        print(f"  [{h.get('executed_at', '?')}] ID: {h.get('schedule_id', '?')[:8]}... => {h.get('result', '')}")


def _cli_run(scheduler: Scheduler):
    """스케줄러 데몬 실행"""
    asyncio.run(scheduler.run_loop())


def cli_main():
    """CLI 진입점"""
    import sys as _sys
    args = _sys.argv[1:]

    if not args:
        print("사용법: python3 scheduler.py <command>")
        print("  list     - 예약 목록 조회")
        print("  add      - 예약 추가 (--type, --datetime/--cron, --content, --description)")
        print("  remove   - 예약 삭제 (--id <uuid>)")
        print("  history  - 실행 이력 조회")
        print("  run      - 스케줄러 데몬 실행 (foreground)")
        return

    scheduler = Scheduler()
    command = args[0]

    if command == "list":
        _cli_list(scheduler)
    elif command == "add":
        _cli_add(scheduler, args[1:])
    elif command == "remove":
        _cli_remove(scheduler, args[1:])
    elif command == "history":
        _cli_history(scheduler)
    elif command == "run":
        _cli_run(scheduler)
    else:
        print(f"알 수 없는 명령: {command}")


if __name__ == "__main__":
    cli_main()
