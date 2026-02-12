"""텍스트 변환 도구 (ROT13, 모스부호, 대소문자 등)"""

import string

SCHEMA = {
    "name": "text_translate",
    "description": "텍스트를 다양한 방식으로 변환합니다. ROT13, 모스부호, 대소문자 변환, 역순, 공백 제거 등을 지원합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "변환할 텍스트"
            },
            "mode": {
                "type": "string",
                "enum": ["rot13", "morse_encode", "morse_decode", "upper", "lower",
                         "title", "swapcase", "reverse", "strip_spaces", "capitalize_words"],
                "description": "변환 모드"
            }
        },
        "required": ["text", "mode"]
    }
}

MORSE_CODE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".",
    "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---",
    "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--",
    "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--",
    "4": "....-", "5": ".....", "6": "-....", "7": "--...",
    "8": "---..", "9": "----.",
    " ": "/", ".": ".-.-.-", ",": "--..--", "?": "..--..",
    "!": "-.-.--", "'": ".----.", "-": "-....-",
}

MORSE_DECODE_MAP = {v: k for k, v in MORSE_CODE.items()}


def _rot13(text):
    result = []
    for ch in text:
        if "a" <= ch <= "z":
            result.append(chr((ord(ch) - ord("a") + 13) % 26 + ord("a")))
        elif "A" <= ch <= "Z":
            result.append(chr((ord(ch) - ord("A") + 13) % 26 + ord("A")))
        else:
            result.append(ch)
    return "".join(result)


def _morse_encode(text):
    result = []
    for ch in text.upper():
        if ch in MORSE_CODE:
            result.append(MORSE_CODE[ch])
        else:
            result.append(ch)
    return " ".join(result)


def _morse_decode(text):
    words = text.strip().split(" / ")
    decoded_words = []
    for word in words:
        chars = word.strip().split()
        decoded = ""
        for code in chars:
            decoded += MORSE_DECODE_MAP.get(code, "?")
        decoded_words.append(decoded)
    return " ".join(decoded_words)


def main(**kwargs):
    text = kwargs.get("text", "")
    mode = kwargs.get("mode", "rot13")

    if not text and mode != "strip_spaces":
        return {"error": "text는 필수입니다."}

    actions = {
        "rot13": lambda t: _rot13(t),
        "morse_encode": lambda t: _morse_encode(t),
        "morse_decode": lambda t: _morse_decode(t),
        "upper": lambda t: t.upper(),
        "lower": lambda t: t.lower(),
        "title": lambda t: t.title(),
        "swapcase": lambda t: t.swapcase(),
        "reverse": lambda t: t[::-1],
        "strip_spaces": lambda t: t.replace(" ", ""),
        "capitalize_words": lambda t: " ".join(w.capitalize() for w in t.split()),
    }

    if mode not in actions:
        return {"error": f"알 수 없는 모드: {mode}. 지원: {list(actions.keys())}"}

    result = actions[mode](text)
    return {"result": result, "mode": mode, "original_length": len(text), "result_length": len(result)}


if __name__ == "__main__":
    print(main(text="Hello World", mode="rot13"))
    print(main(text="SOS", mode="morse_encode"))
    print(main(text="... --- ...", mode="morse_decode"))
    print(main(text="hello world", mode="title"))
