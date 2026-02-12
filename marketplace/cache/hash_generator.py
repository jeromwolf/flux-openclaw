"""해시 생성 도구 (MD5, SHA-1, SHA-256, SHA-512)"""

import hashlib

SCHEMA = {
    "name": "hash_generate",
    "description": "텍스트의 해시 값을 생성합니다. MD5, SHA-1, SHA-256, SHA-512를 지원합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "해시할 텍스트"
            },
            "algorithm": {
                "type": "string",
                "enum": ["md5", "sha1", "sha256", "sha512", "all"],
                "description": "해시 알고리즘 (기본값: sha256)"
            },
            "encoding": {
                "type": "string",
                "enum": ["utf-8", "ascii", "latin-1"],
                "description": "텍스트 인코딩 (기본값: utf-8)"
            },
            "uppercase": {
                "type": "boolean",
                "description": "대문자 출력 여부 (기본값: false)"
            }
        },
        "required": ["text"]
    }
}

SUPPORTED_ALGORITHMS = {
    "md5": hashlib.md5,
    "sha1": hashlib.sha1,
    "sha256": hashlib.sha256,
    "sha512": hashlib.sha512,
}


def _compute_hash(text, algorithm, encoding="utf-8", uppercase=False):
    if algorithm not in SUPPORTED_ALGORITHMS:
        return None, f"지원하지 않는 알고리즘: {algorithm}"
    try:
        data = text.encode(encoding)
    except (UnicodeEncodeError, LookupError) as e:
        return None, f"인코딩 오류: {e}"
    h = SUPPORTED_ALGORITHMS[algorithm](data)
    digest = h.hexdigest()
    if uppercase:
        digest = digest.upper()
    return digest, None


def main(**kwargs):
    text = kwargs.get("text", "")
    algorithm = kwargs.get("algorithm", "sha256")
    encoding = kwargs.get("encoding", "utf-8")
    uppercase = kwargs.get("uppercase", False)

    if text is None:
        return {"error": "text는 필수입니다."}

    if algorithm == "all":
        results = {}
        for algo in SUPPORTED_ALGORITHMS:
            digest, err = _compute_hash(text, algo, encoding, uppercase)
            if err:
                return {"error": err}
            results[algo] = digest
        return {
            "hashes": results,
            "input_length": len(text),
            "encoding": encoding,
        }

    digest, err = _compute_hash(text, algorithm, encoding, uppercase)
    if err:
        return {"error": err}

    return {
        "hash": digest,
        "algorithm": algorithm,
        "input_length": len(text),
        "hash_length": len(digest),
        "encoding": encoding,
    }


if __name__ == "__main__":
    print(main(text="Hello, World!"))
    print(main(text="안녕하세요", algorithm="all"))
    print(main(text="test", algorithm="md5", uppercase=True))
