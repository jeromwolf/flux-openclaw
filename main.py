import os
import json
import glob
from datetime import datetime

from dotenv import load_dotenv
import anthropic

from core import (
    ToolManager, log,
    load_system_prompt, load_usage,
)
from openclaw.conversation_engine import ConversationEngine
from config import get_config
from openclaw.conversation_store import ConversationStore

# LLM Provider 폴백 지원
try:
    from openclaw.llm_provider import get_provider
    _use_provider = True
except ImportError:
    _use_provider = False

load_dotenv()


def main():
    # --user 플래그 파싱
    import argparse as _argparse
    parser = _argparse.ArgumentParser(add_help=False)
    parser.add_argument("--user", default="default")
    args, _ = parser.parse_known_args()
    user_id = args.user

    # 온보딩 체크 (첫 실행 시 설정 마법사)
    try:
        from openclaw.onboarding import check_and_run_onboarding
        if not check_and_run_onboarding():
            return
    except ImportError:
        pass

    api_key = os.environ.get("ANTHROPIC_API_KEY")

    # LLM Provider 초기화 (폴백: Anthropic 직접 사용)
    provider = None
    client = None

    if _use_provider:
        try:
            provider = get_provider()
            print(f" [LLM] {provider.PROVIDER_NAME} ({provider.model})")
        except Exception as e:
            print(f" [LLM] 프로바이더 초기화 실패, Anthropic 직접 사용: {e}")
            provider = None

    if provider is None:
        if not api_key:
            print("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
            return
        client = anthropic.Anthropic(api_key=api_key)

    tool_mgr = ToolManager()

    # 시스템 프롬프트 (core.py의 통합 함수 사용)
    system_prompt = load_system_prompt()

    # ConversationEngine 초기화
    engine = ConversationEngine(
        provider=provider,
        client=client,
        tool_mgr=tool_mgr,
        system_prompt=system_prompt,
        on_llm_start=lambda: print(" [대기중...] Claude 응답 생성 중"),
        on_llm_response=lambda r: print(f" [수신] stop_reason={r.stop_reason}, blocks={len(r.content)}"),
    )

    # ConversationStore 초기화
    try:
        cfg = get_config()
        conv_store = ConversationStore(cfg.conversation_db_path)
        # 기존 history/ JSON 자동 마이그레이션 (최초 1회)
        migrated = conv_store.migrate_from_history_dir("history")
        if migrated > 0:
            print(f" [마이그레이션] {migrated}개의 이전 대화가 SQLite로 이관되었습니다.")
    except Exception:
        conv_store = None

    messages = []
    cumulative_input_tokens = 0
    cumulative_output_tokens = 0

    # --- 일일 API 사용량 ---
    usage = load_usage()
    if usage["calls"] > 0:
        print(f" [사용량] 오늘 API 호출: {usage['calls']}/100, 입력토큰: {usage['input_tokens']}, 출력토큰: {usage['output_tokens']}")

    # --- 이전 대화 복원 ---
    conversation_id = None
    if conv_store:
        recent = conv_store.list_conversations(interface="cli", limit=1)
        if recent:
            restore = input(f" [복원] 마지막 대화를 복원하시겠습니까? ({recent[0].id[:8]}...) (Y/N): ").strip().upper()
            if restore == "Y":
                messages = conv_store.get_messages(recent[0].id)
                conversation_id = recent[0].id
                print(f" [복원] {len(messages)}개 메시지 복원됨")
        if conversation_id is None:
            conv = conv_store.create_conversation(interface="cli", user_id=user_id)
            conversation_id = conv.id
    else:
        # ConversationStore 사용 불가 시 기존 history/ 방식 fallback
        os.makedirs("history", exist_ok=True)
        history_files = sorted(glob.glob("history/history_*.json"))
        if history_files:
            restore = input(" [복원] 마지막 대화를 복원하시겠습니까? (Y/N): ").strip().upper()
            if restore == "Y":
                with open(history_files[-1], "r") as hf:
                    saved = json.load(hf)
                messages = saved.get("messages", [])
                print(f" [복원] {len(messages)}개 메시지 복원됨 ({history_files[-1]})")

    with open("log.md", "a") as f:
        f.write(f"\n\n# Chat Log ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n\n")
        while True:
            user_input = input("켈리: ")
            if user_input.lower() in ["exit", "quit"]:
                if not conv_store and messages:
                    # ConversationStore 사용 불가 시 기존 JSON 저장
                    os.makedirs("history", exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    save_path = f"history/history_{ts}.json"
                    with open(save_path, "w") as hf:
                        json.dump({"timestamp": ts, "messages": messages}, hf, ensure_ascii=False, indent=2)
                    print(f" [저장] 대화 기록이 저장되었습니다: {save_path}")
                elif conv_store and conversation_id:
                    print(f" [저장] 대화가 SQLite에 자동 저장되었습니다 ({conversation_id[:8]}...)")
                break
            if not user_input.strip():
                continue

            log(f, "User", user_input)
            messages.append({"role": "user", "content": user_input})

            # 일일 호출 한도 확인
            usage = load_usage()
            if usage["calls"] >= 100:
                print(" [제한] 오늘의 API 호출 한도(100회)에 도달했습니다. 내일 다시 시도해주세요.")
                messages.pop()
                continue

            try:
                cfg = get_config()

                # ConversationStore에 사용자 메시지 저장
                if conv_store and conversation_id:
                    conv_store.add_message(conversation_id, "user", user_input)

                if cfg.streaming_enabled and hasattr(engine, 'run_turn_stream'):
                    # 스트리밍 모드
                    result = None
                    print("AI: ", end="", flush=True)
                    for event in engine.run_turn_stream(messages, user_id=user_id):
                        if event.type == "text_delta":
                            print(event.data, end="", flush=True)
                        elif event.type == "turn_complete":
                            result = event.data
                    print()  # 줄바꿈

                    if result is None:
                        result = engine.run_turn(messages, user_id=user_id)
                        if result.text:
                            print(f"AI: {result.text}")
                else:
                    # 비스트리밍 모드
                    result = engine.run_turn(messages, user_id=user_id)
                    if result.text:
                        print(f"AI: {result.text}")

                cumulative_input_tokens += result.input_tokens
                cumulative_output_tokens += result.output_tokens
                cost_info = f", 비용: ${result.cost_usd:.4f}" if result.cost_usd > 0 else ""
                print(f" [토큰] 입력: {result.input_tokens} / 출력: {result.output_tokens} (누적: {cumulative_input_tokens}/{cumulative_output_tokens}){cost_info}")
                log(f, "Claude", result.text or "(도구 실행만 수행)")

                # ConversationStore에 AI 응답 저장
                if conv_store and conversation_id and result.text:
                    conv_store.add_message(conversation_id, "assistant", result.text, token_count=result.output_tokens)

                if result.error:
                    print(f" [경고] {result.error}")

            except Exception as e:
                log(f, "Error", str(e))
                print("Error: 요청 처리 중 오류가 발생했습니다.")


if __name__ == "__main__":
    main()
