"""
knowledge_tool - AI가 지식 베이스를 검색/관리하는 도구

지식 베이스 엔진(knowledge_base.py)의 KnowledgeBase 클래스를 사용합니다.
"""

import json
import openclaw.knowledge_base as knowledge_base

SCHEMA = {
    "name": "knowledge",
    "description": "지식 베이스에서 문서를 검색, 추가, 삭제, 조회합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "수행할 작업: search(검색), add(추가), remove(삭제), list(목록), stats(통계)",
                "enum": ["search", "add", "remove", "list", "stats"],
            },
            "query": {
                "type": "string",
                "description": "검색어 (search 시)",
            },
            "title": {
                "type": "string",
                "description": "문서 제목 (add 시)",
            },
            "content": {
                "type": "string",
                "description": "문서 내용 (add 시)",
            },
            "doc_id": {
                "type": "string",
                "description": "문서 ID (remove 시)",
            },
        },
        "required": ["action"],
    },
}


def _handle_search(kb, query=None):
    if not query:
        return "Error: query가 필요합니다"
    results = kb.search(query, top_k=5)
    if not results:
        return "검색 결과가 없습니다."
    lines = [f"검색 결과 ({len(results)}건):", ""]
    for r in results:
        lines.append(f"  [{r['score']:.3f}] {r['title']}")
        lines.append(f"    {r['chunk'][:200]}...")
        lines.append("")
    return "\n".join(lines)


def _handle_add(kb, title=None, content=None):
    if not title or not content:
        return "Error: title과 content가 필요합니다"
    result = kb.add_document(title, content)
    return f"문서 추가 완료: {result['title']} (ID: {result['doc_id']}, 청크: {result['chunk_count']}개)"


def _handle_remove(kb, doc_id=None):
    if not doc_id:
        return "Error: doc_id가 필요합니다"
    if kb.remove_document(doc_id):
        return f"문서 삭제 완료: {doc_id}"
    return f"문서를 찾을 수 없습니다: {doc_id}"


def _handle_list(kb):
    docs = kb.list_documents()
    if not docs:
        return "지식 베이스에 문서가 없습니다."
    lines = [f"문서 목록 ({len(docs)}건):", ""]
    for d in docs:
        lines.append(f"  {d['title']} (ID: {d['doc_id']}, 청크: {d['chunk_count']}개, 출처: {d['source']})")
    return "\n".join(lines)


def _handle_stats(kb):
    stats = kb.get_stats()
    lines = [
        "지식 베이스 통계:",
        f"  문서 수: {stats['doc_count']}",
        f"  청크 수: {stats['chunk_count']}",
        f"  인덱스 크기: {stats['index_size']} bytes",
    ]
    return "\n".join(lines)


def main(action, query=None, title=None, content=None, doc_id=None):
    """지식 베이스 관리 도구 진입점"""
    try:
        kb = knowledge_base.KnowledgeBase()

        if action == "search":
            return _handle_search(kb, query)
        elif action == "add":
            return _handle_add(kb, title, content)
        elif action == "remove":
            return _handle_remove(kb, doc_id)
        elif action == "list":
            return _handle_list(kb)
        elif action == "stats":
            return _handle_stats(kb)
        else:
            return f"Error: 알 수 없는 action: {action} (search, add, remove, list, stats 중 선택)"
    except Exception as e:
        return f"Error: 작업 처리 실패 - {e}"


if __name__ == "__main__":
    print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
