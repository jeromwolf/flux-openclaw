import ipaddress
import re
import threading
from urllib.parse import urlparse
import socket
import requests
from bs4 import BeautifulSoup
import urllib3.util.connection

SCHEMA = {
    "name": "web_fetch",
    "description": "웹 페이지의 실제 내용을 가져옵니다. 검색 결과의 URL에서 상세 정보를 읽을 때 사용합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "가져올 웹 페이지 URL"},
            "max_chars": {
                "type": "integer",
                "description": "반환할 최대 문자 수 (기본값: 3000)",
            },
        },
        "required": ["url"],
    },
}

MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5MB
_dns_pin_lock = threading.Lock()


def _is_private_ip(hostname):
    """프라이빗/내부 IP 대역 차단"""
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        pass
    try:
        resolved = socket.getaddrinfo(hostname, None)
        for _, _, _, _, addr in resolved:
            ip = ipaddress.ip_address(addr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
    except (socket.gaierror, ValueError):
        pass
    return False


def _resolve_hostname(hostname):
    """호스트명을 IP로 해석하고 프라이빗 IP 차단. 안전한 IP 반환 또는 None."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return None
    for _, _, _, _, addr in infos:
        try:
            ip = ipaddress.ip_address(addr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return None
        except ValueError:
            continue
    # 첫 번째 유효한 IP 반환
    if infos:
        return infos[0][4][0]
    return None


def main(url, max_chars=3000):
    max_chars = max(100, min(int(max_chars), 50000))
    try:
        # URL 스킴 검증
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "Error: http 또는 https URL만 허용됩니다."
        if not parsed.hostname:
            return "Error: 유효한 호스트명이 필요합니다."

        # SSRF: DNS 해석 + 프라이빗 IP 차단 (DNS 리바인딩 방지를 위해 IP 핀닝)
        resolved_ip = _resolve_hostname(parsed.hostname)
        if not resolved_ip:
            return "Error: 내부 네트워크 주소는 접근할 수 없습니다."

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        # DNS 핀닝: 해석된 IP로 강제 연결 (DNS 리바인딩 공격 방지)
        _dns_pin_lock.acquire()
        _orig_create_conn = urllib3.util.connection.create_connection
        _pinned_hosts = {parsed.hostname: resolved_ip}

        def _pinned_create_connection(address, *args, **kwargs):
            host, port = address
            if host in _pinned_hosts:
                return _orig_create_conn((_pinned_hosts[host], port), *args, **kwargs)
            return _orig_create_conn(address, *args, **kwargs)

        urllib3.util.connection.create_connection = _pinned_create_connection
        try:
            # 리다이렉트 수동 제어, 응답 크기 제한
            response = requests.get(
                url, headers=headers, timeout=10,
                allow_redirects=False, stream=True,
            )

            # 리다이렉트 처리 (최대 5회, 스킴+IP 검증)
            redirects = 0
            while response.is_redirect and redirects < 5:
                redirect_url = response.headers.get("Location", "")
                rp = urlparse(redirect_url)
                if rp.scheme and rp.scheme not in ("http", "https"):
                    return "Error: 허용되지 않는 프로토콜로 리다이렉트됩니다."
                if rp.hostname and rp.hostname not in _pinned_hosts:
                    # 다른 호스트로 리다이렉트: 새로 DNS 해석 + 검증 + 핀닝
                    redirect_ip = _resolve_hostname(rp.hostname)
                    if not redirect_ip:
                        return "Error: 리다이렉트 대상이 내부 네트워크 주소입니다."
                    _pinned_hosts[rp.hostname] = redirect_ip
                response = requests.get(
                    redirect_url, headers=headers, timeout=10,
                    allow_redirects=False, stream=True,
                )
                redirects += 1
        finally:
            urllib3.util.connection.create_connection = _orig_create_conn
            _dns_pin_lock.release()

        response.raise_for_status()

        # 응답 크기 제한
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_RESPONSE_BYTES:
            return f"Error: 응답이 너무 큽니다 ({int(content_length) // 1024 // 1024}MB 초과)"

        # 제한된 크기만 읽기
        content = b""
        for chunk in response.iter_content(chunk_size=8192):
            content += chunk
            if len(content) > MAX_RESPONSE_BYTES:
                return "Error: 응답이 5MB를 초과합니다."
        response.close()

        soup = BeautifulSoup(content, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)

        if len(clean_text) > max_chars:
            clean_text = clean_text[:max_chars] + "...\n[내용이 잘렸습니다]"

        return clean_text

    except requests.exceptions.Timeout:
        return "Error: 요청 시간 초과"
    except requests.exceptions.ConnectionError:
        return "Error: 연결 실패"
    except requests.exceptions.HTTPError as e:
        return f"Error: HTTP 오류 {e.response.status_code}"
    except Exception:
        return "Error: 웹 페이지를 가져올 수 없습니다."


if __name__ == "__main__":
    import sys, json

    if len(sys.argv) > 1:
        print(main(sys.argv[1]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
