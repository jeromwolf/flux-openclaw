"""
marketplace_tool - AI가 도구 마켓플레이스를 관리하는 도구

도구 검색, 설치, 제거, 정보 조회를 수행합니다.
마켓플레이스 엔진(tool_marketplace.py)의 MarketplaceEngine 클래스를 사용합니다.
"""

import json
import tool_marketplace

SCHEMA = {
    "name": "marketplace",
    "description": "도구 마켓플레이스에서 도구를 검색, 설치, 제거, 조회합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "수행할 작업: search(검색), install(설치), uninstall(제거), list(설치목록), info(정보), verify(무결성검증)",
                "enum": ["search", "install", "uninstall", "list", "info", "verify"],
            },
            "query": {
                "type": "string",
                "description": "검색어 (search 시)",
            },
            "tool_name": {
                "type": "string",
                "description": "도구 이름 (install, uninstall, info 시)",
            },
            "category": {
                "type": "string",
                "description": "카테고리 필터 (search 시)",
                "enum": ["utility", "data", "web", "automation"],
            },
        },
        "required": ["action"],
    },
}


def _format_tool(tool):
    """도구 정보를 문자열로 포맷"""
    status = "[설치됨]" if tool.get("installed") else "[미설치]"
    lines = [
        f"{status} {tool['name']} v{tool.get('version', '?')}",
        f"  설명: {tool.get('description', '')}",
        f"  카테고리: {tool.get('category', '?')}",
        f"  태그: {', '.join(tool.get('tags', []))}",
    ]
    if tool.get("dependencies"):
        lines.append(f"  의존성: {', '.join(tool['dependencies'])}")
    return "\n".join(lines)


def _handle_search(engine, query=None, category=None):
    results = engine.search(query=query or "", category=category)
    if not results:
        return "검색 결과가 없습니다."
    lines = [f"검색 결과 ({len(results)}개):", ""]
    for tool in results:
        lines.append(_format_tool(tool))
        lines.append("")
    return "\n".join(lines)


def _handle_install(engine, tool_name):
    if not tool_name:
        return "Error: tool_name이 필요합니다"
    result = engine.install(tool_name)
    return result.get("message", str(result))


def _handle_uninstall(engine, tool_name):
    if not tool_name:
        return "Error: tool_name이 필요합니다"
    result = engine.uninstall(tool_name)
    return result.get("message", str(result))


def _handle_list(engine):
    installed = engine.list_installed()
    if not installed:
        return "설치된 마켓플레이스 도구가 없습니다."
    lines = [f"설치된 도구 ({len(installed)}개):", ""]
    for tool in installed:
        lines.append(f"  {tool['name']} v{tool.get('version', '?')} (설치: {tool.get('installed_at', '?')})")
    return "\n".join(lines)


def _handle_info(engine, tool_name):
    if not tool_name:
        return "Error: tool_name이 필요합니다"
    info = engine.get_info(tool_name)
    if not info:
        return f"도구를 찾을 수 없습니다: {tool_name}"
    return _format_tool(info)


def _handle_verify(engine):
    results = engine.verify_integrity()
    if not results:
        return "설치된 마켓플레이스 도구가 없습니다."

    issues = [r for r in results if r.get("status") != "ok"]
    ok_count = len(results) - len(issues)

    if not issues:
        return f"모든 설치된 도구의 무결성이 확인되었습니다. ({ok_count}개 정상)"

    lines = [f"무결성 검사 결과: {ok_count}개 정상, {len(issues)}개 문제:", ""]
    for issue in issues:
        status = issue.get("status", "unknown")
        name = issue.get("name", "?")
        if status == "tampered":
            lines.append(f"  [변조됨] {name}: 해시 불일치")
        elif status == "missing":
            lines.append(f"  [누락됨] {name}: 파일을 찾을 수 없음")
        else:
            lines.append(f"  [{status}] {name}")
    return "\n".join(lines)


def main(action, query=None, tool_name=None, category=None):
    """마켓플레이스 관리 도구 진입점"""
    try:
        engine = tool_marketplace.MarketplaceEngine()

        if action == "search":
            return _handle_search(engine, query, category)
        elif action == "install":
            return _handle_install(engine, tool_name)
        elif action == "uninstall":
            return _handle_uninstall(engine, tool_name)
        elif action == "list":
            return _handle_list(engine)
        elif action == "info":
            return _handle_info(engine, tool_name)
        elif action == "verify":
            return _handle_verify(engine)
        else:
            return f"Error: 알 수 없는 action: {action} (search, install, uninstall, list, info, verify 중 선택)"
    except Exception as e:
        return f"Error: 작업 처리 실패 - {e}"


if __name__ == "__main__":
    print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
