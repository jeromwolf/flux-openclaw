"""browser_tool.py - AI 웹 브라우저 자동화 도구

Playwright가 설치되어 있으면 풀 브라우저 자동화를 사용하고,
없으면 requests + BeautifulSoup으로 폴백하여 기본 탐색/텍스트 추출을 지원합니다.
보안: SSRF 방어(프라이빗 IP 차단), 위험 스킴 차단, 타임아웃 제한
"""

import re
import json
import time
import socket
import ipaddress
import datetime
import atexit
from urllib.parse import urlparse
from pathlib import Path

# Playwright (선택적)
try:
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

# Fallback: requests + BeautifulSoup
try:
    import requests
    from bs4 import BeautifulSoup
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

# --- SCHEMA ---

SCHEMA = {
    "name": "browser",
    "description": "웹 브라우저를 자동으로 제어합니다. 페이지 탐색, 클릭, 입력, 스크린샷, 텍스트/링크 추출이 가능합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "수행할 브라우저 작업",
                "enum": ["navigate", "click", "type_text", "get_text",
                         "screenshot", "get_links", "wait", "scroll"],
            },
            "url": {"type": "string", "description": "이동할 URL (navigate 시 필수)"},
            "selector": {"type": "string", "description": "CSS 선택자 (click, type_text, get_text, wait 시)"},
            "text": {"type": "string", "description": "입력할 텍스트 (type_text 시 필수)"},
            "max_chars": {"type": "integer", "description": "반환할 최대 문자 수 (기본값: 5000)"},
            "wait_seconds": {"type": "integer", "description": "대기 시간 초 (wait 시, 기본값: 2, 최대: 10)"},
            "direction": {
                "type": "string",
                "description": "스크롤 방향 (scroll 시)",
                "enum": ["up", "down"],
            },
        },
        "required": ["action"],
    },
}

# --- 상수 ---

_BLOCKED_SCHEMES = {"file", "ftp", "data", "javascript", "vbscript", "blob", "chrome", "about"}
_MAX_TIMEOUT = 30
_MAX_RESPONSE_CHARS = 50000
_SCREENSHOT_DIR = "screenshots"
_PLAYWRIGHT_REQUIRED_MSG = (
    "Error: 이 작업은 Playwright가 필요합니다. "
    "설치: pip install playwright && python -m playwright install chromium"
)

# --- SSRF 방어 ---

def _is_safe_url(url: str) -> tuple:
    """URL 안전성 검증. Returns: (is_safe, error_message)"""
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL을 파싱할 수 없습니다."

    # 스킴 검증
    scheme = (parsed.scheme or "").lower()
    if scheme in _BLOCKED_SCHEMES:
        return False, f"차단된 프로토콜입니다: {scheme}"
    if scheme not in ("http", "https"):
        return False, "http 또는 https URL만 허용됩니다."

    # 호스트명 검증
    hostname = parsed.hostname
    if not hostname:
        return False, "유효한 호스트명이 필요합니다."

    # DNS 해석 + 프라이빗 IP 차단
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, f"호스트를 찾을 수 없습니다: {hostname}"

    for _, _, _, _, addr in infos:
        try:
            ip = ipaddress.ip_address(addr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, "내부 네트워크 주소는 접근할 수 없습니다."
        except ValueError:
            continue

    return True, None

# --- 브라우저 세션 관리 (Playwright 싱글턴) ---

_playwright_instance = None
_browser = None
_page = None

def _get_page():
    """Playwright 페이지 인스턴스 (lazy init, 싱글턴)"""
    global _playwright_instance, _browser, _page
    if not _HAS_PLAYWRIGHT:
        raise RuntimeError(_PLAYWRIGHT_REQUIRED_MSG)
    if _page is None:
        _playwright_instance = sync_playwright().start()
        _browser = _playwright_instance.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--disable-dev-shm-usage", "--disable-extensions",
                  "--disable-background-networking", "--no-first-run"],
        )
        context = _browser.new_context(permissions=[], bypass_csp=False)
        _page = context.new_page()
    return _page

def _close_browser():
    """브라우저 자원 정리"""
    global _playwright_instance, _browser, _page
    for obj in (_page, _browser):
        if obj:
            try: obj.close()
            except Exception: pass
    if _playwright_instance:
        try: _playwright_instance.stop()
        except Exception: pass
    _page = _browser = _playwright_instance = None

# 프로세스 종료 시 브라우저 자원 정리
atexit.register(_close_browser)

# --- HTML 유틸리티 ---

def _clean_html_text(html: str, max_chars: int = 5000) -> str:
    """HTML에서 불필요한 태그를 제거하고 텍스트를 추출"""
    if not _HAS_REQUESTS:
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
    else:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    clean = "\n".join(lines)
    if len(clean) > max_chars:
        clean = clean[:max_chars] + "\n...[내용이 잘렸습니다]"
    return clean

def _extract_title(html: str) -> str:
    """HTML에서 <title> 텍스트 추출"""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""

# --- 액션: navigate ---

def _navigate(url: str, max_chars: int = 5000) -> str:
    """URL로 이동하고 페이지 텍스트를 반환"""
    max_chars = max(100, min(int(max_chars), _MAX_RESPONSE_CHARS))

    if _HAS_PLAYWRIGHT:
        try:
            page = _get_page()
            page.goto(url, timeout=_MAX_TIMEOUT * 1000, wait_until="domcontentloaded")
            title = page.title() or ""
            text = _clean_html_text(page.content(), max_chars)
            return (f"[제목] {title}\n\n" if title else "") + text
        except RuntimeError:
            return _PLAYWRIGHT_REQUIRED_MSG
        except Exception as e:
            return f"Error: 페이지 로드 실패 - {e}"

    # Fallback: requests + BeautifulSoup
    if not _HAS_REQUESTS:
        return "Error: requests 또는 playwright가 설치되어 있지 않습니다."
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        resp.raise_for_status()

        # Redirect SSRF 방어: 최종 URL 재검증
        if resp.url != url:
            final_safe, final_err = _is_safe_url(resp.url)
            if not final_safe:
                return f"Error: 리다이렉트 대상이 차단됨 - {final_err}"

        if len(resp.content) > 5 * 1024 * 1024:
            return "Error: 응답이 너무 큽니다 (5MB 초과)."
        title = _extract_title(resp.text)
        text = _clean_html_text(resp.text, max_chars)
        return (f"[제목] {title}\n\n" if title else "") + text
    except requests.exceptions.Timeout:
        return "Error: 요청 시간 초과"
    except requests.exceptions.ConnectionError:
        return "Error: 연결 실패"
    except requests.exceptions.HTTPError as e:
        return f"Error: HTTP 오류 {e.response.status_code}"
    except Exception as e:
        return f"Error: 웹 페이지를 가져올 수 없습니다 - {e}"

# --- 액션: click ---

def _click(selector: str) -> str:
    """CSS 선택자로 요소를 클릭 (Playwright 전용)"""
    if not _HAS_PLAYWRIGHT:
        return _PLAYWRIGHT_REQUIRED_MSG
    try:
        page = _get_page()
        page.click(selector, timeout=5000)
        page.wait_for_load_state("domcontentloaded", timeout=5000)
        return f"클릭 완료: {selector}"
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Error: 클릭 실패 ({selector}) - {e}"

# --- 액션: type_text ---

def _type_text(selector: str, text: str) -> str:
    """CSS 선택자로 요소에 텍스트 입력 (Playwright 전용)"""
    if not _HAS_PLAYWRIGHT:
        return _PLAYWRIGHT_REQUIRED_MSG
    try:
        page = _get_page()
        page.fill(selector, text, timeout=5000)
        preview = text[:50] + ("..." if len(text) > 50 else "")
        return f"텍스트 입력 완료: {selector} <- '{preview}'"
    except Exception:
        # fill() 실패 시 type()으로 폴백 (contenteditable 등)
        try:
            page = _get_page()
            page.click(selector, timeout=3000)
            page.keyboard.type(text)
            return f"텍스트 입력 완료 (type 방식): {selector}"
        except Exception as e:
            return f"Error: 텍스트 입력 실패 ({selector}) - {e}"

# --- 액션: get_text ---

def _get_text(selector: str = None, max_chars: int = 5000) -> str:
    """페이지 또는 특정 요소의 텍스트 반환"""
    max_chars = max(100, min(int(max_chars), _MAX_RESPONSE_CHARS))

    if _HAS_PLAYWRIGHT:
        try:
            page = _get_page()
            if selector:
                element = page.query_selector(selector)
                if not element:
                    return f"Error: 요소를 찾을 수 없습니다: {selector}"
                text = element.inner_text()
                if len(text) > max_chars:
                    text = text[:max_chars] + "\n...[내용이 잘렸습니다]"
                return text
            else:
                return _clean_html_text(page.content(), max_chars)
        except RuntimeError as e:
            return str(e)
        except Exception as e:
            return f"Error: 텍스트 추출 실패 - {e}"

    return "Error: 현재 열린 페이지가 없습니다. 먼저 navigate 액션으로 페이지를 열어주세요."

# --- 액션: screenshot ---

def _screenshot() -> str:
    """현재 페이지 스크린샷 저장 (Playwright 전용)"""
    if not _HAS_PLAYWRIGHT:
        return _PLAYWRIGHT_REQUIRED_MSG
    try:
        page = _get_page()
        cwd = Path(".").resolve()
        screenshots_dir = cwd / _SCREENSHOT_DIR
        screenshots_dir.mkdir(exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = screenshots_dir / f"browser_{timestamp}.png"
        raw = page.screenshot(full_page=False, timeout=10000)
        # 크기 제한: 2MB
        if len(raw) > 2 * 1024 * 1024:
            return "Error: 스크린샷이 2MB를 초과합니다."
        filepath.write_bytes(raw)
        return f"스크린샷 저장 완료: {filepath.relative_to(cwd)}"
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Error: 스크린샷 실패 - {e}"

# --- 액션: get_links ---

def _get_links(max_links: int = 50) -> str:
    """현재 페이지의 링크 목록 반환"""
    max_links = max(1, min(int(max_links), 100))

    if _HAS_PLAYWRIGHT:
        try:
            page = _get_page()
            anchors = page.query_selector_all("a[href]")
            links = []
            for a in anchors[:max_links]:
                href = a.get_attribute("href") or ""
                text = (a.inner_text() or "").strip()
                if not text:
                    text = a.get_attribute("title") or a.get_attribute("aria-label") or ""
                text = text[:80]
                if href:
                    links.append(f"- [{text}]({href})")
            if not links:
                return "링크를 찾을 수 없습니다."
            return f"링크 {len(links)}개 발견:\n" + "\n".join(links)
        except RuntimeError as e:
            return str(e)
        except Exception as e:
            return f"Error: 링크 추출 실패 - {e}"

    return "Error: 현재 열린 페이지가 없습니다. 먼저 navigate 액션으로 페이지를 열어주세요."

# --- 액션: wait ---

def _wait(wait_seconds: int = 2) -> str:
    """지정된 시간만큼 대기"""
    wait_seconds = max(1, min(int(wait_seconds), 10))
    time.sleep(wait_seconds)
    return f"{wait_seconds}초 대기 완료."

# --- 액션: scroll ---

def _scroll(direction: str = "down") -> str:
    """페이지 스크롤 (Playwright 전용)"""
    if not _HAS_PLAYWRIGHT:
        return _PLAYWRIGHT_REQUIRED_MSG
    try:
        page = _get_page()
        pixels = 500 if direction == "down" else -500
        page.evaluate(f"window.scrollBy(0, {pixels})")
        direction_kr = "아래" if direction == "down" else "위"
        return f"페이지를 {direction_kr}로 스크롤했습니다."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Error: 스크롤 실패 - {e}"

# --- 메인 디스패처 ---

def main(action, url=None, selector=None, text=None,
         max_chars=5000, wait_seconds=2, direction="down"):
    """브라우저 액션 디스패치"""
    try:
        if action == "navigate":
            if not url:
                return "Error: url이 필요합니다."
            safe, err = _is_safe_url(url)
            if not safe:
                return f"Error: {err}"
            return _navigate(url, max_chars)
        elif action == "click":
            if not selector:
                return "Error: selector가 필요합니다."
            return _click(selector)
        elif action == "type_text":
            if not selector:
                return "Error: selector가 필요합니다."
            if not text:
                return "Error: text가 필요합니다."
            return _type_text(selector, text)
        elif action == "get_text":
            return _get_text(selector, max_chars)
        elif action == "screenshot":
            return _screenshot()
        elif action == "get_links":
            return _get_links()
        elif action == "wait":
            return _wait(wait_seconds)
        elif action == "scroll":
            if direction not in ("up", "down"):
                direction = "down"
            return _scroll(direction)
        else:
            return (f"Error: 알 수 없는 액션입니다: {action}. "
                    f"사용 가능: navigate, click, type_text, get_text, screenshot, get_links, wait, scroll")
    except Exception as e:
        return f"Error: 브라우저 작업 실패 - {e}"

# --- CLI 진입점 ---

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        action_arg = sys.argv[1]
        url_arg = sys.argv[2] if len(sys.argv) > 2 else None
        print(main(action=action_arg, url=url_arg))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
