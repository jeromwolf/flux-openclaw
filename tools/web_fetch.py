import requests
from bs4 import BeautifulSoup

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


def main(url, max_chars=3000):
    """
    Fetch the content of a web page and return it as clean text.

    Args:
        url: The URL to fetch
        max_chars: Maximum number of characters to return (default: 3000)

    Returns:
        The cleaned text content of the page, truncated to max_chars
    """
    try:
        # Set headers to avoid being blocked
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        # Fetch the URL with timeout
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.content, "html.parser")

        # Remove script, style, nav, footer, header tags
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # Extract text
        text = soup.get_text(separator="\n", strip=True)

        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)

        # Truncate to max_chars
        if len(clean_text) > max_chars:
            clean_text = clean_text[:max_chars] + "...\n[내용이 잘렸습니다]"

        return clean_text

    except requests.exceptions.Timeout:
        return f"Error: 요청 시간 초과 - URL이 응답하지 않습니다: {url}"
    except requests.exceptions.ConnectionError:
        return f"Error: 연결 실패 - 네트워크 연결을 확인하세요: {url}"
    except requests.exceptions.HTTPError as e:
        return f"Error: HTTP 오류 {e.response.status_code} - {url}"
    except requests.exceptions.InvalidURL:
        return f"Error: 잘못된 URL 형식입니다: {url}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


if __name__ == "__main__":
    import sys, json

    if len(sys.argv) > 1:
        print(main(sys.argv[1]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
