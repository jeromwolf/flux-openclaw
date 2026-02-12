#!/usr/bin/env python3
"""
flux-openclaw 데몬 프로세스 매니저

24/7 상시 운영을 위한 데몬 프로세스 매니저.
main.py, ws_server.py, telegram_bot.py를 자식 프로세스로 관리합니다.

사용법:
    python3 daemon.py start [service|all]
    python3 daemon.py stop [service|all]
    python3 daemon.py restart [service|all]
    python3 daemon.py status
    python3 daemon.py logs <service> [--lines N]
"""

from __future__ import annotations

import os
import sys
import signal
import time
import json
import subprocess
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# 로깅 설정
try:
    from logging_config import setup_logging, get_logger
    logger = get_logger("daemon")
except ImportError:
    import logging
    logger = logging.getLogger("daemon")

# 헬스 서버
try:
    from health import start_health_server
    _health_available = True
except ImportError:
    _health_available = False


# ---------------------------------------------------------------------------
# 서비스 정의
# ---------------------------------------------------------------------------

SERVICES = {
    "main": {
        "script": "main.py",
        "desc": "CLI 인터페이스 (대화형이므로 데몬 불가)",
        "daemonizable": False,
    },
    "ws": {
        "script": "ws_server.py",
        "desc": "WebSocket 서버",
        "daemonizable": True,
    },
    "telegram": {
        "script": "telegram_bot.py",
        "desc": "텔레그램 봇",
        "daemonizable": True,
    },
    "discord": {
        "script": "discord_bot.py",
        "desc": "Discord 봇",
        "daemonizable": True,
    },
    "slack": {
        "script": "slack_bot.py",
        "desc": "Slack 봇",
        "daemonizable": True,
    },
    "dashboard": {
        "script": "dashboard.py",
        "desc": "웹 대시보드",
        "daemonizable": True,
    },
}

DAEMONIZABLE_SERVICES = [k for k, v in SERVICES.items() if v["daemonizable"]]

# ---------------------------------------------------------------------------
# 경로 설정
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
PID_DIR = Path("/tmp")
LOG_DIR = BASE_DIR / "logs"

# 자동 재시작 정책
MAX_RESTARTS = 5
RESTART_DELAY = 5          # 초
RESTART_WINDOW = 60        # 초 (이 시간 내 MAX_RESTARTS 초과 시 포기)

# 메타데이터 저장 (시작 시각, 재시작 이력 등)
META_DIR = PID_DIR


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    """콘솔에 [daemon] 접두어로 메시지를 출력하고 로그에도 기록합니다."""
    print(f" [daemon] {msg}")
    logger.debug(msg)


def _format_uptime(seconds: float) -> str:
    """초 단위를 사람이 읽기 쉬운 형태로 변환합니다."""
    if seconds < 0:
        return "알 수 없음"
    td = timedelta(seconds=int(seconds))
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# DaemonManager
# ---------------------------------------------------------------------------

class DaemonManager:
    """서비스 프로세스를 관리하는 데몬 매니저."""

    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._shutdown_requested = False
        self._supervised: dict[str, subprocess.Popen] = {}

    # -- 경로 헬퍼 --------------------------------------------------------

    def _pid_file(self, service: str) -> Path:
        return PID_DIR / f"flux-openclaw-{service}.pid"

    def _meta_file(self, service: str) -> Path:
        return META_DIR / f"flux-openclaw-{service}.meta.json"

    def _log_file(self, service: str) -> Path:
        script = SERVICES[service]["script"]
        stem = Path(script).stem
        return LOG_DIR / f"{stem}.log"

    # -- PID 관리 ----------------------------------------------------------

    def _read_pid(self, service: str) -> int | None:
        """PID 파일에서 PID를 읽어 반환합니다. 없으면 None."""
        pf = self._pid_file(service)
        if not pf.exists():
            return None
        try:
            pid = int(pf.read_text().strip())
            return pid
        except (ValueError, OSError):
            return None

    def _write_pid(self, service: str, pid: int) -> None:
        self._pid_file(service).write_text(str(pid))

    def _remove_pid(self, service: str) -> None:
        pf = self._pid_file(service)
        if pf.exists():
            pf.unlink()

    def _write_meta(self, service: str, data: dict) -> None:
        self._meta_file(service).write_text(json.dumps(data))

    def _read_meta(self, service: str) -> dict:
        mf = self._meta_file(service)
        if not mf.exists():
            return {}
        try:
            return json.loads(mf.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _remove_meta(self, service: str) -> None:
        mf = self._meta_file(service)
        if mf.exists():
            mf.unlink()

    def _is_running(self, service: str) -> bool:
        """PID가 살아있는지 확인합니다."""
        pid = self._read_pid(service)
        if pid is None:
            return False
        try:
            os.kill(pid, 0)  # 시그널 0: 존재 확인만
            return True
        except ProcessLookupError:
            # 프로세스 없음 -- stale PID 파일 정리
            self._remove_pid(service)
            return False
        except PermissionError:
            # 프로세스는 있으나 권한 없음 -- 실행 중으로 간주
            return True

    # -- 핵심 명령 ---------------------------------------------------------

    def start(self, service: str) -> bool:
        """서비스를 시작합니다. 성공 시 True."""
        if service not in SERVICES:
            logger.error(f"알 수 없는 서비스: {service}")
            logger.info(f"사용 가능한 서비스: {', '.join(SERVICES.keys())}")
            return False

        svc = SERVICES[service]

        if not svc["daemonizable"]:
            _log(f"'{service}'({svc['desc']})는 대화형이므로 데몬화할 수 없습니다.")
            _log(f"직접 실행하세요: python3 {svc['script']}")
            return False

        if self._is_running(service):
            pid = self._read_pid(service)
            _log(f"{svc['desc']}이(가) 이미 실행 중입니다 (PID: {pid})")
            return False

        script_path = BASE_DIR / svc["script"]
        if not script_path.exists():
            logger.error(f"스크립트를 찾을 수 없습니다: {script_path}")
            return False

        log_file = self._log_file(service)
        _log(f"{svc['desc']}를 시작합니다...")

        try:
            log_fd = open(log_file, "a")
            # 구분선 + 시작 시각 기록
            start_marker = (
                f"\n{'='*60}\n"
                f"[daemon] 서비스 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"{'='*60}\n"
            )
            log_fd.write(start_marker)
            log_fd.flush()

            proc = subprocess.Popen(
                [sys.executable, str(script_path)],
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                cwd=str(BASE_DIR),
                start_new_session=True,  # 독립 세션으로 분리
                env={**os.environ},
            )
        except Exception as e:
            logger.error(f"시작 실패: {e}")
            return False

        # 잠시 대기 후 프로세스가 즉시 죽었는지 확인
        time.sleep(0.5)
        if proc.poll() is not None:
            _log(f"프로세스가 즉시 종료되었습니다 (exit code: {proc.returncode})")
            _log(f"로그를 확인하세요: {log_file}")
            return False

        self._write_pid(service, proc.pid)
        self._write_meta(service, {
            "started_at": datetime.now().isoformat(),
            "restarts": [],
        })

        _log(f"PID: {proc.pid} (logs/{log_file.name})")
        return True

    def stop(self, service: str, quiet: bool = False) -> bool:
        """서비스를 종료합니다. 성공 시 True."""
        if service not in SERVICES:
            logger.error(f"알 수 없는 서비스: {service}")
            return False

        svc = SERVICES[service]

        if not self._is_running(service):
            if not quiet:
                _log(f"{svc['desc']}이(가) 실행 중이지 않습니다.")
            return False

        pid = self._read_pid(service)
        if not quiet:
            _log(f"{svc['desc']}를 종료합니다... (PID: {pid})")

        try:
            # SIGTERM으로 graceful shutdown 시도
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self._remove_pid(service)
            self._remove_meta(service)
            if not quiet:
                _log("프로세스가 이미 종료되었습니다.")
            return True
        except PermissionError:
            logger.error(f"프로세스를 종료할 권한이 없습니다 (PID: {pid})")
            return False

        # graceful 종료 대기 (최대 10초)
        for _ in range(20):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        else:
            # SIGTERM이 안 먹히면 SIGKILL
            if not quiet:
                _log("SIGTERM 응답 없음, SIGKILL 전송...")
            try:
                os.kill(pid, signal.SIGKILL)
                time.sleep(1)
            except ProcessLookupError:
                pass

        self._remove_pid(service)
        self._remove_meta(service)
        if not quiet:
            _log("종료 완료")
        return True

    def restart(self, service: str) -> bool:
        """서비스를 재시작합니다."""
        if service not in SERVICES:
            logger.error(f"알 수 없는 서비스: {service}")
            return False

        svc = SERVICES[service]
        _log(f"{svc['desc']}를 재시작합니다...")

        if self._is_running(service):
            self.stop(service, quiet=True)
            time.sleep(1)

        return self.start(service)

    def status(self, service: str | None = None) -> None:
        """서비스 상태를 출력합니다."""
        targets = [service] if service else list(SERVICES.keys())

        _log("서비스 상태:")
        for svc_name in targets:
            if svc_name not in SERVICES:
                print(f"  {svc_name:10s}: 알 수 없는 서비스")
                continue

            svc = SERVICES[svc_name]

            if not svc["daemonizable"]:
                print(f"  {svc_name:10s}: 데몬화 불가 ({svc['desc']})")
                continue

            if self._is_running(svc_name):
                pid = self._read_pid(svc_name)
                meta = self._read_meta(svc_name)
                uptime_str = "알 수 없음"
                if "started_at" in meta:
                    try:
                        started = datetime.fromisoformat(meta["started_at"])
                        elapsed = (datetime.now() - started).total_seconds()
                        uptime_str = _format_uptime(elapsed)
                    except (ValueError, TypeError):
                        pass
                restart_count = len(meta.get("restarts", []))
                extra = f", restarts: {restart_count}" if restart_count > 0 else ""
                print(f"  {svc_name:10s}: 실행 중 (PID: {pid}, uptime: {uptime_str}{extra})")
            else:
                print(f"  {svc_name:10s}: 중지됨")

    def logs(self, service: str, lines: int = 50) -> None:
        """서비스의 최근 로그를 출력합니다."""
        if service not in SERVICES:
            logger.error(f"알 수 없는 서비스: {service}")
            return

        svc = SERVICES[service]
        log_file = self._log_file(service)

        if not log_file.exists():
            _log(f"{svc['desc']} 로그 파일이 없습니다: {log_file}")
            return

        _log(f"{svc['desc']} 로그 (최근 {lines}줄):")
        print("-" * 60)

        try:
            with open(log_file, "r", errors="replace") as f:
                all_lines = f.readlines()
            tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
            for line in tail:
                print(line, end="")
            if tail and not tail[-1].endswith("\n"):
                print()
        except OSError as e:
            logger.error(f"로그 읽기 실패: {e}")

        print("-" * 60)

    # -- 일괄 명령 ---------------------------------------------------------

    def start_all(self) -> None:
        """데몬화 가능한 모든 서비스를 시작합니다."""
        _log("모든 데몬 서비스를 시작합니다...")
        for svc_name in DAEMONIZABLE_SERVICES:
            self.start(svc_name)
            print()

    def stop_all(self) -> None:
        """실행 중인 모든 서비스를 종료합니다."""
        _log("모든 서비스를 종료합니다...")
        for svc_name in DAEMONIZABLE_SERVICES:
            if self._is_running(svc_name):
                self.stop(svc_name)
                print()

    def restart_all(self) -> None:
        """모든 데몬화 가능한 서비스를 재시작합니다."""
        _log("모든 데몬 서비스를 재시작합니다...")
        for svc_name in DAEMONIZABLE_SERVICES:
            self.restart(svc_name)
            print()

    # -- 감독 모드 (foreground) --------------------------------------------

    def supervise(self, services: list[str] | None = None) -> None:
        """
        포그라운드에서 서비스들을 감독합니다.
        프로세스 크래시 시 자동 재시작하며, SIGTERM/SIGINT 시 모든 자식을
        graceful하게 종료합니다.

        이 모드는 `python3 daemon.py start --supervise` 로 활성화됩니다.
        """
        targets = services or DAEMONIZABLE_SERVICES[:]

        # 시그널 핸들러 등록
        signal.signal(signal.SIGTERM, self._supervise_signal_handler)
        signal.signal(signal.SIGINT, self._supervise_signal_handler)

        restart_timestamps: dict[str, list[float]] = {s: [] for s in targets}

        _log("감독 모드 시작 (Ctrl+C로 종료)")

        # 초기 시작
        for svc_name in targets:
            self._supervise_start(svc_name)

        # 감독 루프
        try:
            while not self._shutdown_requested:
                for svc_name in targets:
                    proc = self._supervised.get(svc_name)
                    if proc is None:
                        continue

                    ret = proc.poll()
                    if ret is not None:
                        # 프로세스 종료 감지
                        _log(f"[감독] {svc_name} 프로세스 종료 감지 (exit code: {ret})")
                        self._remove_pid(svc_name)

                        if self._shutdown_requested:
                            break

                        # 재시작 제한 확인
                        now = time.time()
                        timestamps = restart_timestamps[svc_name]
                        # 윈도우 밖의 오래된 기록 제거
                        timestamps[:] = [
                            t for t in timestamps
                            if now - t < RESTART_WINDOW
                        ]

                        if len(timestamps) >= MAX_RESTARTS:
                            _log(
                                f"[감독] {svc_name}: {RESTART_WINDOW}초 내 "
                                f"{MAX_RESTARTS}회 재시작 초과, 포기합니다."
                            )
                            del self._supervised[svc_name]
                            continue

                        _log(
                            f"[감독] {svc_name}: {RESTART_DELAY}초 후 "
                            f"재시작합니다... "
                            f"({len(timestamps)+1}/{MAX_RESTARTS})"
                        )
                        time.sleep(RESTART_DELAY)

                        if self._shutdown_requested:
                            break

                        timestamps.append(time.time())
                        self._supervise_start(svc_name)

                        # 메타데이터에 재시작 기록
                        meta = self._read_meta(svc_name)
                        restarts = meta.get("restarts", [])
                        restarts.append(datetime.now().isoformat())
                        meta["restarts"] = restarts
                        self._write_meta(svc_name, meta)

                time.sleep(1)
        except KeyboardInterrupt:
            pass

        # 정리
        _log("[감독] 모든 자식 프로세스를 종료합니다...")
        self._supervise_stop_all()
        _log("[감독] 감독 모드를 종료합니다.")

    def _supervise_signal_handler(self, signum: int, frame) -> None:
        sig_name = signal.Signals(signum).name
        _log(f"시그널 수신: {sig_name}, 종료를 시작합니다...")
        self._shutdown_requested = True

    def _supervise_start(self, service: str) -> None:
        """감독 모드에서 단일 서비스를 시작합니다."""
        svc = SERVICES[service]
        script_path = BASE_DIR / svc["script"]
        log_file = self._log_file(service)

        try:
            log_fd = open(log_file, "a")
            start_marker = (
                f"\n{'='*60}\n"
                f"[daemon-supervisor] 서비스 시작: "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"{'='*60}\n"
            )
            log_fd.write(start_marker)
            log_fd.flush()

            proc = subprocess.Popen(
                [sys.executable, str(script_path)],
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                cwd=str(BASE_DIR),
                env={**os.environ},
            )
            self._supervised[service] = proc
            self._write_pid(service, proc.pid)
            self._write_meta(service, {
                "started_at": datetime.now().isoformat(),
                "restarts": self._read_meta(service).get("restarts", []),
            })
            _log(f"[감독] {service} 시작됨 (PID: {proc.pid})")
        except Exception as e:
            _log(f"[감독] {service} 시작 실패: {e}")

    def _supervise_stop_all(self) -> None:
        """감독 중인 모든 프로세스를 graceful하게 종료합니다."""
        for svc_name, proc in list(self._supervised.items()):
            if proc.poll() is None:
                _log(f"[감독] {svc_name} 종료 중 (PID: {proc.pid})...")
                try:
                    proc.terminate()
                except OSError:
                    pass

        # 최대 10초 대기
        deadline = time.time() + 10
        for svc_name, proc in list(self._supervised.items()):
            remaining = max(0, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                _log(f"[감독] {svc_name} SIGKILL 전송 (PID: {proc.pid})")
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass

            self._remove_pid(svc_name)

        self._supervised.clear()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    # 로깅 초기화
    try:
        setup_logging(level="INFO", log_format="text")
    except NameError:
        pass  # setup_logging이 없으면 무시

    # 헬스 서버 시작 (백그라운드)
    if _health_available:
        try:
            start_health_server()
        except Exception:
            pass  # 헬스 서버 시작 실패해도 계속 진행

    parser = argparse.ArgumentParser(
        description="flux-openclaw 데몬 프로세스 매니저",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python3 daemon.py start ws          WebSocket 서버 시작\n"
            "  python3 daemon.py start all         모든 데몬 서비스 시작\n"
            "  python3 daemon.py stop telegram     텔레그램 봇 종료\n"
            "  python3 daemon.py restart ws        WebSocket 서버 재시작\n"
            "  python3 daemon.py status            모든 서비스 상태 확인\n"
            "  python3 daemon.py logs ws           WebSocket 서버 로그 확인\n"
            "  python3 daemon.py start --supervise 감독 모드 (자동 재시작)\n"
        ),
    )

    parser.add_argument(
        "command",
        choices=["start", "stop", "restart", "status", "logs"],
        help="실행할 명령",
    )
    parser.add_argument(
        "service",
        nargs="?",
        default=None,
        help=f"대상 서비스 ({', '.join(SERVICES.keys())}, all)",
    )
    parser.add_argument(
        "--lines", "-n",
        type=int,
        default=50,
        help="logs 명령 시 출력할 줄 수 (기본: 50)",
    )
    parser.add_argument(
        "--supervise",
        action="store_true",
        help="감독 모드: 포그라운드에서 프로세스를 감독하고 자동 재시작",
    )

    args = parser.parse_args()
    dm = DaemonManager()

    if args.command == "start":
        if args.supervise:
            # 감독 모드
            targets = None
            if args.service and args.service != "all":
                if args.service not in SERVICES:
                    _log(f"알 수 없는 서비스: {args.service}")
                    sys.exit(1)
                if not SERVICES[args.service]["daemonizable"]:
                    _log(f"'{args.service}'은(는) 데몬화할 수 없습니다.")
                    sys.exit(1)
                targets = [args.service]
            dm.supervise(targets)
        elif args.service == "all":
            dm.start_all()
        elif args.service:
            if not dm.start(args.service):
                sys.exit(1)
        else:
            _log("서비스를 지정하세요. 예: python3 daemon.py start ws")
            _log(f"사용 가능한 서비스: {', '.join(SERVICES.keys())}, all")
            sys.exit(1)

    elif args.command == "stop":
        if args.service == "all" or args.service is None:
            dm.stop_all()
        else:
            if not dm.stop(args.service):
                sys.exit(1)

    elif args.command == "restart":
        if args.service == "all" or args.service is None:
            dm.restart_all()
        elif args.service:
            if not dm.restart(args.service):
                sys.exit(1)

    elif args.command == "status":
        dm.status(args.service)

    elif args.command == "logs":
        if not args.service:
            _log("서비스를 지정하세요. 예: python3 daemon.py logs ws")
            sys.exit(1)
        dm.logs(args.service, lines=args.lines)


if __name__ == "__main__":
    main()
