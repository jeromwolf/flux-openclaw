"""
scheduler.py 테스트
"""
import pytest
import os
import json
import sys
from datetime import datetime, timedelta

# scheduler.py를 임포트하기 위해 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openclaw.scheduler import CronExpression, Scheduler


# ============================================================
# CronExpression 테스트
# ============================================================

def test_cron_every_minute():
    """'* * * * *'는 모든 시간에 매칭"""
    cron = CronExpression("* * * * *")
    dt1 = datetime(2026, 2, 11, 9, 30)
    dt2 = datetime(2026, 2, 11, 14, 45)
    dt3 = datetime(2026, 12, 31, 23, 59)
    assert cron.matches(dt1)
    assert cron.matches(dt2)
    assert cron.matches(dt3)


def test_cron_specific_time():
    """'30 9 * * *'는 매일 9:30에만 매칭"""
    cron = CronExpression("30 9 * * *")
    assert cron.matches(datetime(2026, 2, 11, 9, 30))
    assert not cron.matches(datetime(2026, 2, 11, 9, 29))
    assert not cron.matches(datetime(2026, 2, 11, 9, 31))
    assert not cron.matches(datetime(2026, 2, 11, 10, 30))


def test_cron_weekday_range():
    """'0 9 * * 1-5'는 평일(월-금) 9:00에만 매칭"""
    cron = CronExpression("0 9 * * 1-5")
    # 2026-02-09는 월요일, 2026-02-13은 금요일
    assert cron.matches(datetime(2026, 2, 9, 9, 0))  # 월
    assert cron.matches(datetime(2026, 2, 13, 9, 0))  # 금
    # 2026-02-14는 토요일, 2026-02-15는 일요일
    assert not cron.matches(datetime(2026, 2, 14, 9, 0))  # 토
    assert not cron.matches(datetime(2026, 2, 15, 9, 0))  # 일


def test_cron_step():
    """'*/15 * * * *'는 0, 15, 30, 45분에 매칭"""
    cron = CronExpression("*/15 * * * *")
    assert cron.matches(datetime(2026, 2, 11, 10, 0))
    assert cron.matches(datetime(2026, 2, 11, 10, 15))
    assert cron.matches(datetime(2026, 2, 11, 10, 30))
    assert cron.matches(datetime(2026, 2, 11, 10, 45))
    assert not cron.matches(datetime(2026, 2, 11, 10, 10))
    assert not cron.matches(datetime(2026, 2, 11, 10, 50))


def test_cron_list():
    """'0,30 * * * *'는 0분과 30분에 매칭"""
    cron = CronExpression("0,30 * * * *")
    assert cron.matches(datetime(2026, 2, 11, 10, 0))
    assert cron.matches(datetime(2026, 2, 11, 10, 30))
    assert not cron.matches(datetime(2026, 2, 11, 10, 15))
    assert not cron.matches(datetime(2026, 2, 11, 10, 45))


def test_cron_invalid_field_count():
    """필드 수가 5개가 아니면 ValueError"""
    with pytest.raises(ValueError, match="5개 필드가 필요"):
        CronExpression("* * *")
    with pytest.raises(ValueError, match="5개 필드가 필요"):
        CronExpression("* * * * * *")


def test_cron_invalid_range():
    """범위 초과 시 ValueError"""
    with pytest.raises(ValueError, match="값 초과|범위 초과"):
        CronExpression("60 * * * *")  # 분은 0-59
    with pytest.raises(ValueError, match="값 초과|범위 초과"):
        CronExpression("* 24 * * *")  # 시는 0-23
    with pytest.raises(ValueError, match="값 초과|범위 초과"):
        CronExpression("* * 32 * *")  # 일은 1-31
    with pytest.raises(ValueError, match="값 초과|범위 초과"):
        CronExpression("* * * 13 *")  # 월은 1-12
    with pytest.raises(ValueError, match="값 초과|범위 초과"):
        CronExpression("* * * * 7")  # 요일은 0-6


def test_cron_next_occurrence():
    """next_occurrence가 미래 시각 반환"""
    cron = CronExpression("30 9 * * *")
    now = datetime(2026, 2, 11, 8, 0)
    next_run = cron.next_occurrence(now)
    assert next_run > now
    assert next_run.hour == 9
    assert next_run.minute == 30


def test_cron_weekday_conversion():
    """Python weekday (Mon=0) vs cron weekday (Sun=0) 정확 변환"""
    # 2026-02-15는 일요일 (Python weekday=6, cron=0)
    # 2026-02-16은 월요일 (Python weekday=0, cron=1)
    cron_sunday = CronExpression("0 9 * * 0")
    cron_monday = CronExpression("0 9 * * 1")

    sunday = datetime(2026, 2, 15, 9, 0)
    monday = datetime(2026, 2, 16, 9, 0)

    assert cron_sunday.matches(sunday)
    assert not cron_sunday.matches(monday)
    assert cron_monday.matches(monday)
    assert not cron_monday.matches(sunday)


# ============================================================
# Scheduler 테스트
# ============================================================

@pytest.fixture
def scheduler(tmp_path):
    """임시 디렉토리를 사용하는 Scheduler 인스턴스"""
    return Scheduler(base_dir=str(tmp_path))


def test_add_recurring_schedule(scheduler):
    """반복 스케줄 추가"""
    task = {"action": "remind", "content": "출근 준비"}
    entry = scheduler.add_schedule(
        schedule_type="recurring",
        cron_or_datetime="30 9 * * 1-5",
        task=task,
        description="평일 리마인더"
    )

    assert entry["type"] == "recurring"
    assert entry["cron"] == "30 9 * * 1-5"
    assert entry["task"]["action"] == "remind"
    assert entry["task"]["content"] == "출근 준비"
    assert entry["description"] == "평일 리마인더"
    assert entry["enabled"] is True
    assert "id" in entry
    assert "next_run" in entry


def test_add_once_schedule(scheduler):
    """일회성 스케줄 추가"""
    future = datetime.now() + timedelta(hours=1)
    dt_str = future.strftime("%Y-%m-%d %H:%M")

    task = {"action": "remind", "content": "회의 시작"}
    entry = scheduler.add_schedule(
        schedule_type="once",
        cron_or_datetime=dt_str,
        task=task,
        description="회의 리마인더"
    )

    assert entry["type"] == "once"
    assert entry["cron"] is None
    assert entry["task"]["content"] == "회의 시작"
    assert entry["enabled"] is True


def test_add_past_datetime_error(scheduler):
    """과거 시각 예약 시 ValueError"""
    past = datetime.now() - timedelta(hours=1)
    dt_str = past.strftime("%Y-%m-%d %H:%M")

    task = {"action": "remind", "content": "테스트"}
    with pytest.raises(ValueError, match="과거 시각"):
        scheduler.add_schedule("once", dt_str, task)


def test_add_max_schedules(scheduler):
    """MAX_SCHEDULES 초과 시 ValueError"""
    task = {"action": "remind", "content": "테스트"}
    future = datetime.now() + timedelta(hours=1)
    dt_str = future.strftime("%Y-%m-%d %H:%M")

    # MAX_SCHEDULES까지 추가
    for i in range(Scheduler.MAX_SCHEDULES):
        scheduler.add_schedule("once", dt_str, task, f"스케줄 {i}")

    # 하나 더 추가하면 에러
    with pytest.raises(ValueError, match="최대 예약 수"):
        scheduler.add_schedule("once", dt_str, task)


def test_remove_schedule(scheduler):
    """스케줄 삭제"""
    task = {"action": "remind", "content": "테스트"}
    entry = scheduler.add_schedule("recurring", "0 9 * * *", task)

    schedule_id = entry["id"]
    assert scheduler.remove_schedule(schedule_id) is True

    schedules = scheduler.list_schedules()
    assert len(schedules) == 0


def test_remove_nonexistent(scheduler):
    """없는 ID 삭제 시 False"""
    assert scheduler.remove_schedule("nonexistent-id") is False


def test_get_due_tasks(scheduler):
    """due 작업 반환 (next_run이 과거인 항목)"""
    # 과거 시각의 next_run을 가진 스케줄 추가
    past = datetime.now() - timedelta(minutes=5)
    schedules = scheduler._load_schedules()
    schedules.append({
        "id": "test-id",
        "type": "recurring",
        "cron": "* * * * *",
        "next_run": past.strftime("%Y-%m-%dT%H:%M:%S"),
        "task": {"action": "remind", "content": "테스트"},
        "enabled": True,
    })
    scheduler._save_schedules(schedules)

    due_tasks = scheduler.get_due_tasks()
    assert len(due_tasks) == 1
    assert due_tasks[0]["id"] == "test-id"


def test_mark_executed_once(scheduler):
    """일회성 실행 후 disabled"""
    future = datetime.now() + timedelta(hours=1)
    dt_str = future.strftime("%Y-%m-%d %H:%M")

    task = {"action": "remind", "content": "일회성"}
    entry = scheduler.add_schedule("once", dt_str, task)
    schedule_id = entry["id"]

    scheduler.mark_executed(schedule_id, "완료")

    schedules = scheduler.list_schedules()
    schedule = next(s for s in schedules if s["id"] == schedule_id)
    assert schedule["enabled"] is False

    # 이력 확인
    history = scheduler.get_history(limit=1)
    assert len(history) == 1
    assert history[0]["schedule_id"] == schedule_id
    assert history[0]["result"] == "완료"


def test_mark_executed_recurring(scheduler):
    """반복 실행 후 next_run 갱신"""
    task = {"action": "remind", "content": "반복"}
    # 매 분마다 실행되는 cron을 사용
    entry = scheduler.add_schedule("recurring", "* * * * *", task)
    schedule_id = entry["id"]
    original_next_run_str = entry["next_run"]
    original_next_run = datetime.strptime(original_next_run_str, "%Y-%m-%dT%H:%M:%S")

    # 시간을 약간 진행시키기 위해 대기
    import time
    time.sleep(0.1)

    scheduler.mark_executed(schedule_id, "완료")

    schedules = scheduler.list_schedules()
    schedule = next(s for s in schedules if s["id"] == schedule_id)
    assert schedule["enabled"] is True  # 여전히 활성

    new_next_run = datetime.strptime(schedule["next_run"], "%Y-%m-%dT%H:%M:%S")
    # next_run이 원래보다 같거나 미래여야 함
    assert new_next_run >= original_next_run


def test_history_limit(scheduler):
    """이력 MAX_HISTORY 초과 시 오래된 항목 삭제"""
    task = {"action": "remind", "content": "테스트"}
    entry = scheduler.add_schedule("recurring", "0 9 * * *", task)
    schedule_id = entry["id"]

    # MAX_HISTORY + 10개 실행
    for i in range(Scheduler.MAX_HISTORY + 10):
        scheduler.mark_executed(schedule_id, f"실행 {i}")

    history = scheduler._load_history()
    assert len(history) <= Scheduler.MAX_HISTORY


def test_cleanup_disabled(scheduler):
    """비활성 일회성 작업 정리"""
    future = datetime.now() + timedelta(hours=1)
    dt_str = future.strftime("%Y-%m-%d %H:%M")

    task = {"action": "remind", "content": "일회성"}
    entry1 = scheduler.add_schedule("once", dt_str, task, "첫 번째")
    entry2 = scheduler.add_schedule("once", dt_str, task, "두 번째")
    entry3 = scheduler.add_schedule("recurring", "0 9 * * *", task, "반복")

    # 일회성 2개를 비활성화
    scheduler.mark_executed(entry1["id"])
    scheduler.mark_executed(entry2["id"])

    removed = scheduler.cleanup_disabled()
    assert removed == 2

    schedules = scheduler.list_schedules()
    assert len(schedules) == 1
    assert schedules[0]["id"] == entry3["id"]
