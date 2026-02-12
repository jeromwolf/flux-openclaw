"""
flux-openclaw 플러그인 SDK

도구 개발을 위한 CLI 도구입니다.
새 도구 생성, 보안 검사, 테스트, 마켓플레이스 패키징을 지원합니다.

사용법:
    python3 plugin_sdk.py new <name>          # 새 도구 생성
    python3 plugin_sdk.py check <file>        # 보안 검사
    python3 plugin_sdk.py test <file>         # 자동 테스트
    python3 plugin_sdk.py package <file>      # 마켓플레이스 패키징
"""

import argparse
import re
import os
import sys
import json
import ast
import hashlib
import importlib.util
from core import _DANGEROUS_RE, ToolManager


TOOL_TEMPLATE = '''"""
{name} - {description}

flux-openclaw 도구 플러그인
"""

SCHEMA = {{
    "name": "{name}",
    "description": "{description}",
    "input_schema": {{
        "type": "object",
        "properties": {{
            "input_text": {{
                "type": "string",
                "description": "입력 텍스트",
            }},
        }},
        "required": ["input_text"],
    }},
}}


def main(input_text):
    """{name} 도구 실행"""
    # TODO: 여기에 도구 로직을 구현하세요
    return f"결과: {{input_text}}"


if __name__ == "__main__":
    import json, sys
    if len(sys.argv) > 1:
        print(main(sys.argv[1]))
    else:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
'''


def validate_name(name):
    """도구 이름 검증: ^[a-z][a-z0-9_]{1,30}$"""
    if not re.match(r'^[a-z][a-z0-9_]{1,30}$', name):
        return False
    return True


def cmd_new(args):
    """새 도구 생성 (new 서브커맨드)"""
    name = args.name
    description = args.description or f"{name} 도구"

    if not validate_name(name):
        print("❌ 오류: 도구 이름은 소문자로 시작하고, 소문자/숫자/밑줄만 사용하며, 2-31자여야 합니다.")
        return 1

    output_file = f"{name}.py"
    if os.path.exists(output_file):
        print(f"❌ 오류: {output_file} 파일이 이미 존재합니다.")
        return 1

    code = TOOL_TEMPLATE.format(name=name, description=description)
    with open(output_file, "w") as f:
        f.write(code)

    print(f"✅ 새 도구 생성됨: {output_file}")
    print(f"   편집 후 'python3 plugin_sdk.py check {output_file}'로 검사하세요.")
    return 0


def cmd_check(args):
    """보안 검사 (check 서브커맨드)"""
    filepath = args.file
    if not os.path.exists(filepath):
        print(f"❌ 오류: 파일을 찾을 수 없습니다: {filepath}")
        return 1

    with open(filepath, "r") as f:
        code = f.read()

    findings = []

    # 1. Regex 보안 스캔
    regex_hits = _DANGEROUS_RE.findall(code)
    if regex_hits:
        findings.append(("CRITICAL", f"위험 패턴 발견: {regex_hits}"))

    # 2. AST 보안 스캔
    tm = ToolManager.__new__(ToolManager)
    ast_hits = tm._check_dangerous_ast(code)
    if ast_hits:
        findings.append(("CRITICAL", f"AST 위험 코드: {ast_hits}"))

    # CRITICAL 발견 시 모듈 로드 없이 즉시 종료 (임의 코드 실행 방지)
    has_critical = any(sev == "CRITICAL" for sev, _ in findings)
    if has_critical:
        findings.append(("WARNING", "보안 문제로 SCHEMA/main 컨벤션 검사를 건너뜁니다"))
        for severity, msg in findings:
            symbol = {"CRITICAL": "✗", "WARNING": "△", "OK": "✓"}.get(severity, "?")
            print(f"  [{symbol}] [{severity}] {msg}")
        return 1

    # 3. SCHEMA 컨벤션 검사
    try:
        module_spec = importlib.util.spec_from_file_location("check_module", filepath)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)

        if not hasattr(module, "SCHEMA"):
            findings.append(("WARNING", "SCHEMA 딕셔너리가 정의되지 않았습니다."))
        else:
            schema = module.SCHEMA
            if not isinstance(schema, dict):
                findings.append(("WARNING", "SCHEMA는 딕셔너리여야 합니다."))
            else:
                if "name" not in schema:
                    findings.append(("WARNING", "SCHEMA에 'name' 필드가 없습니다."))
                if "description" not in schema:
                    findings.append(("WARNING", "SCHEMA에 'description' 필드가 없습니다."))
                if "input_schema" not in schema:
                    findings.append(("WARNING", "SCHEMA에 'input_schema' 필드가 없습니다."))

        if not hasattr(module, "main"):
            findings.append(("WARNING", "main() 함수가 정의되지 않았습니다."))
        elif not callable(module.main):
            findings.append(("WARNING", "main은 호출 가능한 함수여야 합니다."))
    except Exception as e:
        findings.append(("CRITICAL", f"모듈 로드 실패: {e}"))

    # 결과 출력
    if not findings:
        print("✅ 검사 통과: 문제가 발견되지 않았습니다.")
        return 0
    else:
        critical_count = sum(1 for sev, _ in findings if sev == "CRITICAL")
        warning_count = sum(1 for sev, _ in findings if sev == "WARNING")

        print(f"⚠️  검사 결과: CRITICAL {critical_count}건, WARNING {warning_count}건\n")
        for severity, msg in findings:
            emoji = "🔴" if severity == "CRITICAL" else "🟡"
            print(f"{emoji} [{severity}] {msg}")

        return 1 if critical_count > 0 else 0


def cmd_test(args):
    """자동 테스트 (test 서브커맨드)"""
    filepath = args.file
    if not os.path.exists(filepath):
        print(f"❌ 오류: 파일을 찾을 수 없습니다: {filepath}")
        return 1

    # 보안 검사 먼저 실행
    with open(filepath, "r") as f:
        code = f.read()
    regex_hits = _DANGEROUS_RE.findall(code)
    tm = ToolManager.__new__(ToolManager)
    ast_hits = tm._check_dangerous_ast(code)
    if regex_hits or ast_hits:
        print(f"❌ 보안 검사 실패: 위험한 패턴이 발견되었습니다 (CRITICAL)")
        print(f"   'python3 plugin_sdk.py check {filepath}'로 자세한 내용을 확인하세요.")
        return 1

    try:
        module_spec = importlib.util.spec_from_file_location("test_module", filepath)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    except Exception as e:
        print(f"❌ 모듈 로드 실패: {e}")
        return 1

    # 1. SCHEMA 검증
    if not hasattr(module, "SCHEMA"):
        print("❌ SCHEMA 딕셔너리가 없습니다.")
        return 1

    schema = module.SCHEMA
    if not isinstance(schema, dict):
        print("❌ SCHEMA는 딕셔너리여야 합니다.")
        return 1

    if "name" not in schema or "description" not in schema or "input_schema" not in schema:
        print("❌ SCHEMA에 필수 필드(name, description, input_schema)가 없습니다.")
        return 1

    print(f"✅ SCHEMA 검증 통과: {schema['name']}")

    # 2. main() 함수 검증
    if not hasattr(module, "main"):
        print("❌ main() 함수가 없습니다.")
        return 1

    if not callable(module.main):
        print("❌ main은 호출 가능한 함수여야 합니다.")
        return 1

    # 3. 파라미터 이름 검증
    import inspect
    sig = inspect.signature(module.main)
    param_names = list(sig.parameters.keys())
    schema_props = schema.get("input_schema", {}).get("properties", {})
    schema_params = list(schema_props.keys())

    if set(param_names) != set(schema_params):
        print(f"⚠️  경고: main() 파라미터 ({param_names})와 SCHEMA 프로퍼티 ({schema_params})가 일치하지 않습니다.")
    else:
        print(f"✅ main() 파라미터 검증 통과: {param_names}")

    # 4. 샘플 입력으로 호출 테스트
    sample_inputs = {}
    for prop_name, prop_spec in schema_props.items():
        prop_type = prop_spec.get("type", "string")
        if prop_type == "string":
            sample_inputs[prop_name] = "test"
        elif prop_type == "integer":
            sample_inputs[prop_name] = 0
        elif prop_type == "number":
            sample_inputs[prop_name] = 0.0
        elif prop_type == "boolean":
            sample_inputs[prop_name] = True
        else:
            sample_inputs[prop_name] = None

    try:
        result = module.main(**sample_inputs)
        print(f"✅ 샘플 실행 성공: {result}")
    except Exception as e:
        print(f"❌ 샘플 실행 실패: {e}")
        return 1

    print("\n✅ 모든 테스트 통과!")
    return 0


def cmd_package(args):
    """마켓플레이스 패키징 (package 서브커맨드)"""
    filepath = args.file
    if not os.path.exists(filepath):
        print(f"❌ 오류: 파일을 찾을 수 없습니다: {filepath}")
        return 1

    # 1. check 통과 확인 (CRITICAL 없어야 함)
    with open(filepath, "r") as f:
        code = f.read()

    regex_hits = _DANGEROUS_RE.findall(code)
    tm = ToolManager.__new__(ToolManager)
    ast_hits = tm._check_dangerous_ast(code)

    if regex_hits or ast_hits:
        print("❌ 보안 검사 실패: CRITICAL 문제가 발견되었습니다.")
        print("   'python3 plugin_sdk.py check <file>'로 자세한 내용을 확인하세요.")
        return 1

    # 2. SHA-256 해시 계산
    with open(filepath, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    # 3. SCHEMA 메타데이터 추출
    try:
        module_spec = importlib.util.spec_from_file_location("package_module", filepath)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    except Exception as e:
        print(f"❌ 모듈 로드 실패: {e}")
        return 1

    if not hasattr(module, "SCHEMA"):
        print("❌ SCHEMA가 정의되지 않았습니다.")
        return 1

    schema = module.SCHEMA
    tool_name = schema.get("name", "unknown")
    description = schema.get("description", "")
    params = list(schema.get("input_schema", {}).get("properties", {}).keys())

    filename = os.path.basename(filepath)

    # 4. registry.json 엔트리 생성
    entry = {
        "name": tool_name,
        "filename": filename,
        "description": description,
        "version": "1.0.0",
        "author": "community",
        "category": "utility",
        "tags": [],
        "dependencies": [],
        "sha256": file_hash,
        "security_level": "safe",
        "source": "community",
        "schema_preview": {
            "name": tool_name,
            "params": params
        }
    }

    print("✅ 패키징 성공! 아래 JSON을 marketplace/registry.json에 추가하세요:\n")
    print(json.dumps(entry, indent=2, ensure_ascii=False))
    return 0


def main():
    """CLI 엔트리포인트"""
    parser = argparse.ArgumentParser(
        description="flux-openclaw 플러그인 SDK",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python3 plugin_sdk.py new my_tool --description "내 도구"
  python3 plugin_sdk.py check my_tool.py
  python3 plugin_sdk.py test my_tool.py
  python3 plugin_sdk.py package my_tool.py
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="서브커맨드")

    # new 서브커맨드
    parser_new = subparsers.add_parser("new", help="새 도구 생성")
    parser_new.add_argument("name", help="도구 이름 (예: my_tool)")
    parser_new.add_argument("--description", help="도구 설명", default=None)

    # check 서브커맨드
    parser_check = subparsers.add_parser("check", help="보안 검사")
    parser_check.add_argument("file", help="검사할 도구 파일")

    # test 서브커맨드
    parser_test = subparsers.add_parser("test", help="자동 테스트")
    parser_test.add_argument("file", help="테스트할 도구 파일")

    # package 서브커맨드
    parser_package = subparsers.add_parser("package", help="마켓플레이스 패키징")
    parser_package.add_argument("file", help="패키징할 도구 파일")

    args = parser.parse_args()

    if args.command == "new":
        return cmd_new(args)
    elif args.command == "check":
        return cmd_check(args)
    elif args.command == "test":
        return cmd_test(args)
    elif args.command == "package":
        return cmd_package(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
