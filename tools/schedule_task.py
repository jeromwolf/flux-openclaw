"""
schedule_task - AI가 예약 작업을 관리하는 도구

리마인더 설정, 예약 조회, 삭제를 수행합니다.
스케줄러 엔진(scheduler.py)의 Scheduler 클래스를 사용합니다.
"""

import json
import os

# scheduler 모듈은 프로젝트 루트에 위치하며,
# ToolManager가 프로젝트 루트에서 실행되므로 직접 import 가능
import openclaw.scheduler as scheduler

SCHEMA = {
    "name": "schedule_task",
    "description": "예약 작업을 관리합니다. 리마인더 설정, 예약 조회, 삭제 등이 가능합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "수행할 작업: add(추가), list(목록), remove(삭제), history(이력)",
                "enum": ["add", "list", "remove", "history"],
            },
            "schedule_type": {
                "type": "string",
                "description": "once(일회성) 또는 recurring(반복)",
                "enum": ["once", "recurring"],
            },
            "datetime_or_cron": {
                "type": "string",
                "description": "일회성: 'YYYY-MM-DD HH:MM' 형식, 반복: cron 표현식 (예: '30 9 * * 1-5')",
            },
            "content": {
                "type": "string",
                "description": "리마인더 메시지 또는 작업 내용",
            },
            "description": {
                "type": "string",
                "description": "이 예약에 대한 설명",
            },
            "schedule_id": {
                "type": "string",
                "description": "삭제 시 사용할 스케줄 ID",
            },
        },
        "required": ["action"],
    },
}


def _format_entry(entry):
    """스케줄 항목을 문자열로 포맷"""
    status = "ON" if entry.get("enabled", True) else "OFF"
    stype = entry.get("type", "?")
    desc = entry.get("description", "")
    cron = entry.get("cron", "")
    next_run = entry.get("next_run", "")
    task = entry.get("task", {})
    content = task.get("content", "")
    sid = entry.get("id", "?")

    lines = []
    lines.append(f"[{status}] {desc}" if desc else f"[{status}] (설명 없음)")
    lines.append(f"  ID: {sid}")
    lines.append(f"  유형: {stype}")
    if cron:
        lines.append(f"  cron: {cron}")
    lines.append(f"  다음 실행: {next_run}")
    if content:
        lines.append(f"  내용: {content}")

    return "\n".join(lines)


def _handle_add(sched, schedule_type, datetime_or_cron, content, description):
    """예약 추가 처리"""
    if not schedule_type:
        return "Error: schedule_type이 필요합니다 (once 또는 recurring)"
    if not datetime_or_cron:
        return "Error: datetime_or_cron이 필요합니다"
    if not content:
        return "Error: content가 필요합니다"

    task = {
        "action": "remind",
        "content": content,
        "tool_name": None,
        "tool_args": None,
    }

    try:
        entry = sched.add_schedule(schedule_type, datetime_or_cron, task, description or "")
        return f"예약이 추가되었습니다.\n\n{_format_entry(entry)}"
    except ValueError as e:
        return f"Error: {e}"


def _handle_list(sched):
    """예약 목록 처리"""
    schedules = sched.list_schedules()
    if not schedules:
        return "예약된 작업이 없습니다."

    enabled = [s for s in schedules if s.get("enabled", True)]
    disabled = [s for s in schedules if not s.get("enabled", True)]

    lines = [f"예약 작업 ({len(enabled)}개 활성, {len(disabled)}개 비활성):", ""]
    for entry in enabled:
        lines.append(_format_entry(entry))
        lines.append("")
    if disabled:
        lines.append(f"--- 비활성 ({len(disabled)}개) ---")
        for entry in disabled:
            lines.append(_format_entry(entry))
            lines.append("")

    return "\n".join(lines)


def _handle_remove(sched, schedule_id):
    """예약 삭제 처리"""
    if not schedule_id:
        return "Error: schedule_id가 필요합니다"

    if sched.remove_schedule(schedule_id):
        return f"예약이 삭제되었습니다: {schedule_id}"
    else:
        return f"해당 ID를 찾을 수 없습니다: {schedule_id}"


def _handle_history(sched):
    """실행 이력 처리"""
    history = sched.get_history(limit=20)
    if not history:
        return "실행 이력이 없습니다."

    lines = [f"최근 실행 이력 ({len(history)}건):", ""]
    for h in history:
        executed = h.get("executed_at", "?")
        sid = h.get("schedule_id", "?")[:8]
        result = h.get("result", "")
        lines.append(f"  [{executed}] {sid}... => {result}")

    return "\n".join(lines)


def main(action, schedule_type=None, datetime_or_cron=None,
         content=None, description=None, schedule_id=None):
    """예약 작업 관리 도구 진입점"""
    try:
        sched = scheduler.Scheduler()

        if action == "add":
            return _handle_add(sched, schedule_type, datetime_or_cron, content, description)
        elif action == "list":
            return _handle_list(sched)
        elif action == "remove":
            return _handle_remove(sched, schedule_id)
        elif action == "history":
            return _handle_history(sched)
        else:
            return f"Error: 알 수 없는 action: {action} (add, list, remove, history 중 선택)"
    except Exception as e:
        return f"Error: 작업 처리 실패 - {e}"


if __name__ == "__main__":
    print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
