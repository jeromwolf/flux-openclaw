SCHEMA = {
    "name": "multiply_two_numbers",
    "description": "두 숫자를 곱합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "a": {"type": "number", "description": "첫 번째 숫자"},
            "b": {"type": "number", "description": "두 번째 숫자"},
        },
        "required": ["a", "b"],
    },
}


def main(a, b):
    return str(float(a) * float(b))


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) > 2:
        print(main(sys.argv[1], sys.argv[2]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
