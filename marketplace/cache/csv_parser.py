"""CSV 문자열 파싱 도구 (파일 I/O 없이 문자열 입력만 사용)"""

import re
import statistics

SCHEMA = {
    "name": "csv_parse",
    "description": "CSV 형식의 문자열을 파싱하고 행/열 추출, 통계 등을 수행합니다. 파일이 아닌 문자열 입력만 사용합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "csv_string": {
                "type": "string",
                "description": "CSV 형식의 문자열"
            },
            "action": {
                "type": "string",
                "enum": ["parse", "get_row", "get_column", "stats", "headers", "count"],
                "description": "수행할 작업"
            },
            "delimiter": {
                "type": "string",
                "description": "구분자 (기본값: ',')"
            },
            "index": {
                "type": "integer",
                "description": "행 또는 열 인덱스 (0부터 시작)"
            },
            "has_header": {
                "type": "boolean",
                "description": "헤더 행 존재 여부 (기본값: true)"
            }
        },
        "required": ["csv_string", "action"]
    }
}


def _parse_csv_line(line, delimiter=","):
    """간단한 CSV 라인 파서 (따옴표 처리 포함)"""
    fields = []
    current = ""
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"' and not in_quotes:
            in_quotes = True
        elif ch == '"' and in_quotes:
            if i + 1 < len(line) and line[i + 1] == '"':
                current += '"'
                i += 1
            else:
                in_quotes = False
        elif ch == delimiter and not in_quotes:
            fields.append(current.strip())
            current = ""
        else:
            current += ch
        i += 1
    fields.append(current.strip())
    return fields


def _parse_csv(csv_string, delimiter=","):
    lines = csv_string.strip().split("\n")
    return [_parse_csv_line(line, delimiter) for line in lines if line.strip()]


def _numeric_stats(values):
    nums = []
    for v in values:
        try:
            nums.append(float(v))
        except (ValueError, TypeError):
            continue
    if not nums:
        return {"count": 0, "message": "숫자 데이터가 없습니다."}
    return {
        "count": len(nums),
        "sum": round(sum(nums), 4),
        "mean": round(statistics.mean(nums), 4),
        "min": min(nums),
        "max": max(nums),
        "median": round(statistics.median(nums), 4),
        "stdev": round(statistics.stdev(nums), 4) if len(nums) > 1 else 0,
    }


def main(**kwargs):
    csv_string = kwargs.get("csv_string", "")
    action = kwargs.get("action", "parse")
    delimiter = kwargs.get("delimiter", ",")
    index = kwargs.get("index", 0)
    has_header = kwargs.get("has_header", True)

    if not csv_string.strip():
        return {"error": "csv_string은 필수입니다."}

    rows = _parse_csv(csv_string, delimiter)
    if not rows:
        return {"error": "파싱할 데이터가 없습니다."}

    headers = rows[0] if has_header else [f"col_{i}" for i in range(len(rows[0]))]
    data_rows = rows[1:] if has_header else rows

    if action == "parse":
        result = []
        for row in data_rows:
            record = {}
            for i, h in enumerate(headers):
                record[h] = row[i] if i < len(row) else ""
            result.append(record)
        return {"headers": headers, "rows": result, "row_count": len(data_rows)}

    if action == "headers":
        return {"headers": headers, "column_count": len(headers)}

    if action == "count":
        return {"row_count": len(data_rows), "column_count": len(headers)}

    if action == "get_row":
        if index < 0 or index >= len(data_rows):
            return {"error": f"행 인덱스 범위 초과: {index} (총 {len(data_rows)}행)"}
        row = data_rows[index]
        record = {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
        return {"row": record, "index": index}

    if action == "get_column":
        if index < 0 or index >= len(headers):
            return {"error": f"열 인덱스 범위 초과: {index} (총 {len(headers)}열)"}
        col_name = headers[index]
        values = [row[index] if index < len(row) else "" for row in data_rows]
        return {"column": col_name, "values": values}

    if action == "stats":
        if index < 0 or index >= len(headers):
            return {"error": f"열 인덱스 범위 초과: {index} (총 {len(headers)}열)"}
        col_name = headers[index]
        values = [row[index] if index < len(row) else "" for row in data_rows]
        return {"column": col_name, "stats": _numeric_stats(values)}

    return {"error": f"알 수 없는 작업: {action}"}


if __name__ == "__main__":
    sample = "이름,나이,점수\n홍길동,25,90\n김철수,30,85\n이영희,28,95"
    print(main(csv_string=sample, action="parse"))
    print(main(csv_string=sample, action="get_row", index=1))
    print(main(csv_string=sample, action="stats", index=2))
