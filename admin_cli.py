"""
flux-openclaw 관리자 CLI 도구

argparse 기반 stdlib only 관리 CLI.
서브커맨드: status, usage, config, conversations, memory, users, backup, audit

사용법:
    python admin_cli.py status
    python admin_cli.py usage --json
    python admin_cli.py config show
    python admin_cli.py conversations list --limit 10
    python admin_cli.py conversations search "쿼리" --user user123
    python admin_cli.py memory search "프로젝트"
    python admin_cli.py users list
    python admin_cli.py users create john --role admin
    python admin_cli.py backup create
    python admin_cli.py audit list --type api_call --limit 100
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime


def build_parser() -> argparse.ArgumentParser:
    """argparse 파서 구성"""
    parser = argparse.ArgumentParser(
        prog="flux-admin",
        description="flux-openclaw 관리자 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="서브커맨드")

    # ========== status ==========
    status_parser = subparsers.add_parser("status", help="시스템 상태 표시")

    # ========== usage ==========
    usage_parser = subparsers.add_parser("usage", help="사용량/비용 통계")
    usage_parser.add_argument("--json", action="store_true", help="JSON 형식 출력")

    # ========== config ==========
    config_parser = subparsers.add_parser("config", help="설정 관리")
    config_sub = config_parser.add_subparsers(dest="config_action", help="config 액션")
    config_sub.add_parser("show", help="전체 설정 JSON 출력")
    config_get = config_sub.add_parser("get", help="특정 키 값 조회")
    config_get.add_argument("key", help="설정 키 (예: default_model)")
    config_set = config_sub.add_parser("set", help="특정 키 값 설정")
    config_set.add_argument("key", help="설정 키")
    config_set.add_argument("value", help="설정 값")

    # ========== conversations ==========
    conv_parser = subparsers.add_parser("conversations", help="대화 관리")
    conv_sub = conv_parser.add_subparsers(dest="conv_action", help="대화 액션")

    conv_list = conv_sub.add_parser("list", help="대화 목록")
    conv_list.add_argument("--interface", help="인터페이스 필터 (cli, ws, telegram 등)")
    conv_list.add_argument("--limit", type=int, default=20, help="표시할 항목 수")

    conv_show = conv_sub.add_parser("show", help="대화 상세 + 메시지")
    conv_show.add_argument("id", help="대화 ID")

    conv_delete = conv_sub.add_parser("delete", help="대화 삭제")
    conv_delete.add_argument("id", help="대화 ID")
    conv_delete.add_argument("--yes", action="store_true", help="확인 프롬프트 생략")

    conv_sub.add_parser("stats", help="대화 통계")
    conv_sub.add_parser("migrate", help="history/ → SQLite 마이그레이션")

    conv_search = conv_sub.add_parser("search", help="대화 검색")
    conv_search.add_argument("query", help="검색 쿼리")
    conv_search.add_argument("--user", help="사용자 ID 필터")
    conv_search.add_argument("--from", dest="date_from", help="시작 날짜 (YYYY-MM-DD)")
    conv_search.add_argument("--to", dest="date_to", help="종료 날짜 (YYYY-MM-DD)")
    conv_search.add_argument("--limit", type=int, default=20)

    # ========== users ==========
    users_parser = subparsers.add_parser("users", help="사용자 관리")
    users_sub = users_parser.add_subparsers(dest="users_action", help="사용자 액션")

    users_list = users_sub.add_parser("list", help="사용자 목록")
    users_list.add_argument("--limit", type=int, default=50)

    users_create = users_sub.add_parser("create", help="사용자 생성")
    users_create.add_argument("username", help="사용자명")
    users_create.add_argument("--role", default="user", choices=["admin", "user", "readonly"])

    users_deactivate = users_sub.add_parser("deactivate", help="사용자 비활성화")
    users_deactivate.add_argument("user_id", help="사용자 ID")

    users_rotate = users_sub.add_parser("rotate-key", help="API 키 갱신")
    users_rotate.add_argument("user_id", help="사용자 ID")

    # ========== backup ==========
    backup_parser = subparsers.add_parser("backup", help="백업 관리")
    backup_sub = backup_parser.add_subparsers(dest="backup_action", help="백업 액션")

    backup_sub.add_parser("create", help="백업 생성")
    backup_list = backup_sub.add_parser("list", help="백업 목록")
    backup_restore = backup_sub.add_parser("restore", help="백업 복원")
    backup_restore.add_argument("file", help="백업 파일 경로")

    # ========== audit ==========
    audit_parser = subparsers.add_parser("audit", help="감사 로그")
    audit_sub = audit_parser.add_subparsers(dest="audit_action", help="감사 액션")

    audit_list = audit_sub.add_parser("list", help="감사 로그 조회")
    audit_list.add_argument("--type", dest="event_type", help="이벤트 타입 필터")
    audit_list.add_argument("--user", help="사용자 ID 필터")
    audit_list.add_argument("--since", help="시작 날짜 (YYYY-MM-DD)")
    audit_list.add_argument("--limit", type=int, default=50)

    # ========== memory ==========
    mem_parser = subparsers.add_parser("memory", help="메모리 관리")
    mem_sub = mem_parser.add_subparsers(dest="mem_action", help="메모리 액션")

    mem_list = mem_sub.add_parser("list", help="메모리 항목 목록")
    mem_list.add_argument("--category", help="카테고리 필터")

    mem_search = mem_sub.add_parser("search", help="메모리 검색")
    mem_search.add_argument("query", help="검색 쿼리")
    mem_search.add_argument("--category", help="카테고리 필터")

    mem_delete = mem_sub.add_parser("delete", help="메모리 항목 삭제")
    mem_delete.add_argument("id", help="메모리 ID")
    mem_delete.add_argument("--yes", action="store_true", help="확인 프롬프트 생략")

    mem_sub.add_parser("stats", help="메모리 통계")
    mem_sub.add_parser("cleanup", help="만료 항목 정리")

    return parser


# ============================================================
# status
# ============================================================

def cmd_status(args):
    """시스템 상태 표시"""
    print("\n=== flux-openclaw 시스템 상태 ===\n")

    # 설정 요약
    try:
        from config import get_config
        cfg = get_config()
        print("[설정]")
        print(f"  - 모델: {cfg.default_model}")
        print(f"  - 최대 토큰: {cfg.max_tokens}")
        print(f"  - 최대 도구 라운드: {cfg.max_tool_rounds}")
        print(f"  - 일일 API 호출 제한: {cfg.max_daily_calls}")
        print(f"  - 로그 레벨: {cfg.log_level}")
        print()
    except Exception as e:
        print(f"[설정] 로드 실패: {e}\n")

    # 도구 수
    try:
        from core import ToolManager
        tool_mgr = ToolManager()
        print(f"[도구] {len(tool_mgr.functions)}개 로드됨")
        if tool_mgr.functions:
            print(f"  도구 목록: {', '.join(sorted(tool_mgr.functions.keys()))}")
        print()
    except Exception as e:
        print(f"[도구] 로드 실패: {e}\n")

    # 서비스 가용성 (health.py 체크)
    try:
        import core
        print("[서비스 가용성]")
        print("  - core.py: OK")
        print(f"  - tools/ 디렉토리: {'OK' if os.path.isdir('tools') else 'FAIL'}")
        print(f"  - memory/ 디렉토리: {'OK' if os.path.isdir('memory') else 'FAIL'}")
        print()
    except Exception:
        print("[서비스 가용성] core.py 로드 실패\n")

    # 메모리 통계
    try:
        from memory_store import MemoryStore
        store = MemoryStore()
        memories = store._load()
        print(f"[메모리] {len(memories)}개 항목 저장됨")
        if memories:
            by_cat = {}
            for m in memories:
                cat = m.get("category", "unknown")
                by_cat[cat] = by_cat.get(cat, 0) + 1
            for cat, count in sorted(by_cat.items()):
                print(f"  - {cat}: {count}개")
        print()
    except Exception as e:
        print(f"[메모리] 조회 실패: {e}\n")


# ============================================================
# usage
# ============================================================

def cmd_usage(args):
    """사용량/비용 통계 표시"""
    try:
        from core import load_usage
    except ImportError:
        print("Error: core.py 모듈을 로드할 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    usage = load_usage()
    today = datetime.now().strftime("%Y-%m-%d")

    if usage["date"] != today:
        usage = {"date": today, "calls": 0, "input_tokens": 0, "output_tokens": 0}

    # 비용 계산 (cost_tracker 연동)
    cost_usd = 0.0
    try:
        from cost_tracker import calculate_cost
        from config import get_config
        cfg = get_config()
        cost_result = calculate_cost(
            model=cfg.default_model,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
        )
        cost_usd = cost_result.total_cost_usd
    except ImportError:
        pass  # cost_tracker 없으면 0.0 유지

    if args.json:
        # JSON 출력
        output = {
            "date": usage["date"],
            "calls": usage["calls"],
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cost_usd": cost_usd,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        # 텍스트 출력
        print(f"\n=== 오늘의 사용량 ({usage['date']}) ===\n")
        print(f"API 호출: {usage['calls']}회")
        print(f"입력 토큰: {usage['input_tokens']:,}")
        print(f"출력 토큰: {usage['output_tokens']:,}")
        print(f"총 토큰: {usage['input_tokens'] + usage['output_tokens']:,}")
        print(f"예상 비용: ${cost_usd:.4f} USD")
        print()


# ============================================================
# config
# ============================================================

def cmd_config(args):
    """설정 관리"""
    if args.config_action == "show":
        cmd_config_show(args)
    elif args.config_action == "get":
        cmd_config_get(args)
    elif args.config_action == "set":
        cmd_config_set(args)
    else:
        print("Error: config 서브커맨드가 필요합니다 (show, get, set)", file=sys.stderr)
        sys.exit(1)


def cmd_config_show(args):
    """전체 설정 JSON 출력"""
    try:
        from config import get_config
        import dataclasses
        cfg = get_config()
        cfg_dict = dataclasses.asdict(cfg)
        print(json.dumps(cfg_dict, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Error: 설정 로드 실패: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_config_get(args):
    """특정 키 값 조회"""
    try:
        from config import get_config
        cfg = get_config()
        if hasattr(cfg, args.key):
            value = getattr(cfg, args.key)
            print(value)
        else:
            print(f"Error: 존재하지 않는 설정 키: {args.key}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Error: 설정 조회 실패: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_config_set(args):
    """특정 키 값 설정 (config.json 직접 수정)"""
    config_file = "config.json"

    # 기존 config.json 로드 또는 빈 dict
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    # 값 타입 추론 (숫자면 int/float, true/false면 bool, 나머지는 str)
    value_str = args.value
    if value_str.lower() in ("true", "false"):
        value = value_str.lower() == "true"
    elif value_str.isdigit():
        value = int(value_str)
    elif value_str.replace(".", "", 1).isdigit():
        value = float(value_str)
    else:
        value = value_str

    data[args.key] = value

    # 파일 저장
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"설정 저장됨: {args.key} = {value}")
    except OSError as e:
        print(f"Error: 설정 저장 실패: {e}", file=sys.stderr)
        sys.exit(1)


# ============================================================
# conversations
# ============================================================

def cmd_conversations(args):
    """대화 관리"""
    if args.conv_action == "list":
        cmd_conversations_list(args)
    elif args.conv_action == "show":
        cmd_conversations_show(args)
    elif args.conv_action == "delete":
        cmd_conversations_delete(args)
    elif args.conv_action == "stats":
        cmd_conversations_stats(args)
    elif args.conv_action == "migrate":
        cmd_conversations_migrate(args)
    elif args.conv_action == "search":
        cmd_conversations_search(args)
    else:
        print("Error: conversations 서브커맨드가 필요합니다", file=sys.stderr)
        sys.exit(1)


def cmd_conversations_list(args):
    """대화 목록 표시"""
    try:
        from conversation_store import ConversationStore
    except ImportError:
        print("Error: conversation_store 모듈을 찾을 수 없습니다.", file=sys.stderr)
        print("대화 저장소가 아직 구현되지 않았을 수 있습니다.", file=sys.stderr)
        sys.exit(1)

    store = ConversationStore()
    conversations = store.list_conversations(
        interface=args.interface,
        limit=args.limit,
    )

    print(f"\n=== 대화 목록 (최근 {len(conversations)}개) ===\n")
    for conv in conversations:
        conv_id = conv.id
        interface = conv.interface
        created = conv.created_at[:19] if conv.created_at else "N/A"
        msg_count = getattr(conv, "message_count", 0)
        print(f"{conv_id[:12]}... ({interface}) - {created} - {msg_count}개 메시지")
    print()


def cmd_conversations_show(args):
    """대화 상세 + 메시지 표시"""
    try:
        from conversation_store import ConversationStore
    except ImportError:
        print("Error: conversation_store 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    store = ConversationStore()
    conv = store.get_conversation(args.id)

    if not conv:
        print(f"Error: 대화를 찾을 수 없습니다: {args.id}", file=sys.stderr)
        sys.exit(1)

    messages = store.get_messages(args.id)

    print(f"\n=== 대화 상세: {conv.id} ===\n")
    print(f"인터페이스: {conv.interface}")
    print(f"생성 시각: {conv.created_at}")
    print(f"수정 시각: {conv.updated_at}")
    print(f"메시지 수: {len(messages)}")
    print()

    if messages:
        print("=== 메시지 ===\n")
        for i, msg in enumerate(messages, 1):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str):
                preview = content[:100].replace("\n", " ")
            else:
                preview = str(content)[:100]
            print(f"{i}. [{role}] {preview}...")
    print()


def cmd_conversations_delete(args):
    """대화 삭제"""
    try:
        from conversation_store import ConversationStore
    except ImportError:
        print("Error: conversation_store 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    if not args.yes:
        confirm = input(f"정말로 대화 {args.id}를(을) 삭제하시겠습니까? (Y/N): ").strip().upper()
        if confirm != "Y":
            print("취소되었습니다.")
            return

    store = ConversationStore()
    success = store.delete_conversation(args.id)

    if success:
        print(f"대화 삭제 완료: {args.id}")
    else:
        print(f"Error: 대화를 찾을 수 없습니다: {args.id}", file=sys.stderr)
        sys.exit(1)


def cmd_conversations_stats(args):
    """대화 통계 표시"""
    try:
        from conversation_store import ConversationStore
    except ImportError:
        print("Error: conversation_store 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    store = ConversationStore()
    stats = store.get_stats()

    print("\n=== 대화 통계 ===\n")
    print(f"총 대화 수: {stats.get('total_conversations', 0)}")
    print(f"총 메시지 수: {stats.get('total_messages', 0)}")
    print()

    by_interface = stats.get("conversations_by_interface", {})
    if by_interface:
        print("인터페이스별:")
        for interface, count in sorted(by_interface.items()):
            print(f"  - {interface}: {count}개")
    print()


def cmd_conversations_migrate(args):
    """history/ → SQLite 마이그레이션"""
    try:
        from conversation_store import ConversationStore
    except ImportError:
        print("Error: conversation_store 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    print("마이그레이션을 시작합니다...")
    store = ConversationStore()

    if hasattr(store, "migrate_from_history_dir"):
        count = store.migrate_from_history_dir("history")
        print(f"마이그레이션 완료: {count}개 대화가 이전되었습니다.")
    else:
        print("Error: migrate_from_history_dir 메서드가 구현되지 않았습니다.", file=sys.stderr)
        sys.exit(1)


def cmd_conversations_search(args):
    """대화 검색"""
    try:
        from search import ConversationSearch
        from config import get_config
    except ImportError:
        print("Error: search 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    cfg = get_config()
    searcher = ConversationSearch(db_path=cfg.conversation_db_path)
    results = searcher.search(
        query=args.query,
        user_id=args.user,
        date_from=args.date_from,
        date_to=args.date_to,
        limit=args.limit,
    )

    print(f"\n=== 대화 검색 결과: '{args.query}' ({len(results)}개) ===\n")
    for result in results:
        conv_id = result.conversation_id[:12] if len(result.conversation_id) > 12 else result.conversation_id
        created = result.created_at[:19] if result.created_at else "N/A"
        print(f"{conv_id}... [{result.role}] (rank: {result.rank:.2f}) - {created}")
        print(f"  {result.snippet}")
        print()
    print()


# ============================================================
# memory
# ============================================================

def cmd_memory(args):
    """메모리 관리"""
    if args.mem_action == "list":
        cmd_memory_list(args)
    elif args.mem_action == "search":
        cmd_memory_search(args)
    elif args.mem_action == "delete":
        cmd_memory_delete(args)
    elif args.mem_action == "stats":
        cmd_memory_stats(args)
    elif args.mem_action == "cleanup":
        cmd_memory_cleanup(args)
    else:
        print("Error: memory 서브커맨드가 필요합니다", file=sys.stderr)
        sys.exit(1)


def cmd_memory_list(args):
    """메모리 항목 목록"""
    try:
        from memory_store import MemoryStore
    except ImportError:
        print("Error: memory_store 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    store = MemoryStore()

    if args.category:
        memories = store.get_by_category(args.category)
        print(f"\n=== 메모리 목록 (카테고리: {args.category}) ===\n")
    else:
        memories = store._load()
        print(f"\n=== 메모리 목록 (전체 {len(memories)}개) ===\n")

    for mem in memories:
        mem_id = mem.get("id", "N/A")[:12]
        cat = mem.get("category", "unknown")
        key = mem.get("key", "")
        value_preview = str(mem.get("value", ""))[:50].replace("\n", " ")
        importance = mem.get("importance", 3)
        print(f"{mem_id}... [{cat}] (중요도: {importance}) {key}: {value_preview}...")
    print()


def cmd_memory_search(args):
    """메모리 검색"""
    try:
        from memory_store import MemoryStore
    except ImportError:
        print("Error: memory_store 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    store = MemoryStore()
    results = store.search(args.query, category=args.category)

    print(f"\n=== 검색 결과: '{args.query}' ({len(results)}개) ===\n")
    for mem in results:
        mem_id = mem.get("id", "N/A")[:12]
        cat = mem.get("category", "unknown")
        key = mem.get("key", "")
        value_preview = str(mem.get("value", ""))[:50].replace("\n", " ")
        importance = mem.get("importance", 3)
        print(f"{mem_id}... [{cat}] (중요도: {importance}) {key}: {value_preview}...")
    print()


def cmd_memory_delete(args):
    """메모리 항목 삭제"""
    try:
        from memory_store import MemoryStore
    except ImportError:
        print("Error: memory_store 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    if not args.yes:
        confirm = input(f"정말로 메모리 항목 {args.id}를(을) 삭제하시겠습니까? (Y/N): ").strip().upper()
        if confirm != "Y":
            print("취소되었습니다.")
            return

    store = MemoryStore()
    success = store.delete(args.id)

    if success:
        print(f"메모리 항목 삭제 완료: {args.id}")
    else:
        print(f"Error: 메모리 항목을 찾을 수 없습니다: {args.id}", file=sys.stderr)
        sys.exit(1)


def cmd_memory_stats(args):
    """메모리 통계"""
    try:
        from memory_store import MemoryStore
    except ImportError:
        print("Error: memory_store 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    store = MemoryStore()
    memories = store._load()

    print(f"\n=== 메모리 통계 ===\n")
    print(f"전체 항목 수: {len(memories)}")
    print(f"최대 용량: {store.MAX_MEMORIES}")
    print()

    by_cat = {}
    by_importance = {}
    for mem in memories:
        cat = mem.get("category", "unknown")
        imp = mem.get("importance", 3)
        by_cat[cat] = by_cat.get(cat, 0) + 1
        by_importance[imp] = by_importance.get(imp, 0) + 1

    print("카테고리별:")
    for cat in sorted(store.VALID_CATEGORIES):
        count = by_cat.get(cat, 0)
        limit = store.CATEGORY_LIMITS.get(cat, 0)
        print(f"  - {cat}: {count}/{limit}개")
    print()

    print("중요도별:")
    for imp in sorted(by_importance.keys()):
        count = by_importance[imp]
        print(f"  - 중요도 {imp}: {count}개")
    print()


def cmd_memory_cleanup(args):
    """만료 항목 정리"""
    try:
        from memory_store import MemoryStore
    except ImportError:
        print("Error: memory_store 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    store = MemoryStore()
    removed = store.cleanup_expired()
    print(f"만료된 항목 {removed}개가 정리되었습니다.")


# ============================================================
# users
# ============================================================

def cmd_users(args):
    """사용자 관리"""
    if args.users_action == "list":
        cmd_users_list(args)
    elif args.users_action == "create":
        cmd_users_create(args)
    elif args.users_action == "deactivate":
        cmd_users_deactivate(args)
    elif args.users_action == "rotate-key":
        cmd_users_rotate_key(args)
    else:
        print("Error: users 서브커맨드가 필요합니다", file=sys.stderr)
        sys.exit(1)


def cmd_users_list(args):
    """사용자 목록 표시"""
    try:
        from auth import UserStore
        from config import get_config
    except ImportError:
        print("Error: auth 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    store = UserStore(get_config().auth_db_path)
    users = store.list_users(limit=args.limit)

    print(f"\n=== 사용자 목록 ({len(users)}명) ===\n")
    for u in users:
        print(f"{u.id[:12]}... ({u.username}) [{u.role}] - 키: {u.api_key_prefix}...")
    print()


def cmd_users_create(args):
    """사용자 생성"""
    try:
        from auth import UserStore
        from config import get_config
    except ImportError:
        print("Error: auth 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    store = UserStore(get_config().auth_db_path)
    user, api_key = store.create_user(args.username, role=args.role)

    print(f"\n사용자 생성 완료:")
    print(f"  ID: {user.id}")
    print(f"  사용자명: {user.username}")
    print(f"  역할: {user.role}")
    print(f"  API 키: {api_key}")
    print(f"\n⚠ API 키는 다시 표시되지 않습니다. 안전한 곳에 저장하세요.")
    print()


def cmd_users_deactivate(args):
    """사용자 비활성화"""
    try:
        from auth import UserStore
        from config import get_config
    except ImportError:
        print("Error: auth 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    store = UserStore(get_config().auth_db_path)
    success = store.deactivate_user(args.user_id)

    if success:
        print(f"사용자 비활성화 완료: {args.user_id}")
    else:
        print(f"Error: 사용자를 찾을 수 없습니다: {args.user_id}", file=sys.stderr)
        sys.exit(1)


def cmd_users_rotate_key(args):
    """API 키 갱신"""
    try:
        from auth import UserStore
        from config import get_config
    except ImportError:
        print("Error: auth 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    store = UserStore(get_config().auth_db_path)
    user, new_key = store.rotate_api_key(args.user_id)

    if user:
        print(f"\nAPI 키가 갱신되었습니다:")
        print(f"  사용자: {user.username}")
        print(f"  새 API 키: {new_key}")
        print(f"\n⚠ 이전 키는 즉시 무효화됩니다.")
        print()
    else:
        print(f"Error: 사용자를 찾을 수 없습니다: {args.user_id}", file=sys.stderr)
        sys.exit(1)


# ============================================================
# backup
# ============================================================

def cmd_backup(args):
    """백업 관리"""
    if args.backup_action == "create":
        cmd_backup_create(args)
    elif args.backup_action == "list":
        cmd_backup_list(args)
    elif args.backup_action == "restore":
        cmd_backup_restore(args)
    else:
        print("Error: backup 서브커맨드가 필요합니다", file=sys.stderr)
        sys.exit(1)


def cmd_backup_create(args):
    """백업 생성"""
    try:
        from backup import BackupManager
        from config import get_config
    except ImportError:
        print("Error: backup 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    mgr = BackupManager(get_config().backup_dir)
    result = mgr.create_backup()

    size_mb = result.size_bytes / (1024 * 1024)
    print(f"\n백업 생성 완료: {result.file_path}")
    print(f"크기: {size_mb:.2f} MB")
    print(f"포함된 항목: {', '.join(result.contents)}")
    print()


def cmd_backup_list(args):
    """백업 목록 표시"""
    try:
        from backup import BackupManager
        from config import get_config
    except ImportError:
        print("Error: backup 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    mgr = BackupManager(get_config().backup_dir)
    backups = mgr.list_backups()

    print(f"\n=== 백업 목록 ({len(backups)}개) ===\n")
    for backup in backups:
        size_mb = backup.size_bytes / (1024 * 1024)
        print(f"{backup.file_path} - {size_mb:.2f} MB - {backup.created_at}")
    print()


def cmd_backup_restore(args):
    """백업 복원"""
    try:
        from backup import BackupManager
        from config import get_config
    except ImportError:
        print("Error: backup 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    mgr = BackupManager(get_config().backup_dir)
    try:
        result = mgr.restore_backup(args.file)
        print(f"백업 복원 완료: {args.file}")
        print(f"복원된 항목: {', '.join(result.contents)}")
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: 백업 복원 실패: {e}", file=sys.stderr)
        sys.exit(1)


# ============================================================
# audit
# ============================================================

def cmd_audit(args):
    """감사 로그 관리"""
    if args.audit_action == "list":
        cmd_audit_list(args)
    else:
        print("Error: audit 서브커맨드가 필요합니다", file=sys.stderr)
        sys.exit(1)


def cmd_audit_list(args):
    """감사 로그 조회"""
    try:
        from audit import AuditLogger
        from config import get_config
    except ImportError:
        print("Error: audit 모듈을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    logger = AuditLogger(get_config().audit_db_path)
    logs = logger.query(
        event_type=args.event_type,
        user_id=args.user,
        since=args.since,
        limit=args.limit,
    )

    print(f"\n=== 감사 로그 ({len(logs)}개) ===\n")
    for log in logs:
        timestamp = log.timestamp[:19] if log.timestamp else "N/A"
        event_type = log.event_type
        user_id = log.user_id[:12] if log.user_id and len(log.user_id) > 12 else log.user_id or "N/A"
        details = json.dumps(log.details) if log.details else ""
        severity = log.severity
        print(f"{timestamp} [{event_type}] ({severity}) {user_id}... - {details}")
    print()


# ============================================================
# main
# ============================================================

def main():
    """메인 엔트리포인트"""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # 서브커맨드 디스패치
    if args.command == "status":
        cmd_status(args)
    elif args.command == "usage":
        cmd_usage(args)
    elif args.command == "config":
        cmd_config(args)
    elif args.command == "conversations":
        cmd_conversations(args)
    elif args.command == "memory":
        cmd_memory(args)
    elif args.command == "users":
        cmd_users(args)
    elif args.command == "backup":
        cmd_backup(args)
    elif args.command == "audit":
        cmd_audit(args)
    else:
        print(f"Error: 알 수 없는 명령: {args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
