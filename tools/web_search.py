from ddgs import DDGS

SCHEMA = {
    "name": "web_search",
    "description": "인터넷에서 최신 정보를 검색합니다. 뉴스, 사실 확인, 최신 기술 정보 등을 찾을 때 사용합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "검색할 키워드 또는 질문"},
            "max_results": {
                "type": "integer",
                "description": "반환할 최대 검색 결과 수 (기본값: 5)",
            },
        },
        "required": ["query"],
    },
}


def main(query, max_results=5):
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, backend="lite", max_results=max_results)

        if not results:
            return "검색 결과가 없습니다."

        output = []
        for i, r in enumerate(results, 1):
            output.append(f"{i}. {r['title']}\n   URL: {r['href']}\n   {r['body']}")

        return "\n\n".join(output)
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    import sys, json

    if len(sys.argv) > 1:
        print(main(sys.argv[1]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
