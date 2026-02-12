"""텍스트 통계 도구 (글자수, 단어수, 문장수, 평균 단어길이, 최빈 단어 등)"""

import re
import collections
import math

SCHEMA = {
    "name": "text_statistics",
    "description": "텍스트의 통계 정보를 분석합니다. 글자수, 단어수, 문장수, 평균 단어길이, 최빈 단어, 줄 수 등을 제공합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "분석할 텍스트"
            },
            "action": {
                "type": "string",
                "enum": ["full", "chars", "words", "sentences", "frequency", "readability"],
                "description": "분석 유형 (기본값: full)"
            },
            "top_n": {
                "type": "integer",
                "description": "최빈 단어 상위 N개 (기본값: 10)"
            }
        },
        "required": ["text"]
    }
}


def _count_sentences(text):
    sentences = re.split(r'[.!?。？！]+', text)
    return len([s for s in sentences if s.strip()])


def _get_words(text):
    return re.findall(r'\b\w+\b', text.lower())


def _full_stats(text, top_n=10):
    chars_total = len(text)
    chars_no_space = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
    words = _get_words(text)
    word_count = len(words)
    sentence_count = _count_sentences(text)
    line_count = len(text.split("\n"))

    avg_word_len = 0
    if word_count > 0:
        avg_word_len = round(sum(len(w) for w in words) / word_count, 2)

    freq = collections.Counter(words)
    top_words = freq.most_common(top_n)

    # 고유 단어 수
    unique_words = len(set(words))

    return {
        "characters_total": chars_total,
        "characters_no_spaces": chars_no_space,
        "words": word_count,
        "unique_words": unique_words,
        "sentences": sentence_count,
        "lines": line_count,
        "average_word_length": avg_word_len,
        "top_words": [{"word": w, "count": c} for w, c in top_words],
        "paragraphs": len([p for p in text.split("\n\n") if p.strip()]),
    }


def main(**kwargs):
    text = kwargs.get("text", "")
    action = kwargs.get("action", "full")
    top_n = max(1, min(kwargs.get("top_n", 10), 100))

    if not text:
        return {"error": "text는 필수입니다."}

    if action == "full":
        return _full_stats(text, top_n)

    if action == "chars":
        return {
            "characters_total": len(text),
            "characters_no_spaces": len(text.replace(" ", "").replace("\n", "").replace("\t", "")),
            "lines": len(text.split("\n")),
        }

    if action == "words":
        words = _get_words(text)
        return {
            "words": len(words),
            "unique_words": len(set(words)),
            "average_word_length": round(sum(len(w) for w in words) / max(1, len(words)), 2),
        }

    if action == "sentences":
        return {
            "sentences": _count_sentences(text),
            "paragraphs": len([p for p in text.split("\n\n") if p.strip()]),
        }

    if action == "frequency":
        words = _get_words(text)
        freq = collections.Counter(words)
        top_words = freq.most_common(top_n)
        return {
            "total_words": len(words),
            "unique_words": len(set(words)),
            "top_words": [{"word": w, "count": c} for w, c in top_words],
        }

    if action == "readability":
        words = _get_words(text)
        sentence_count = max(1, _count_sentences(text))
        word_count = max(1, len(words))
        syllable_count = sum(max(1, len(re.findall(r'[aeiouAEIOU]', w))) for w in words)
        # Flesch Reading Ease (영문 기준 근사값)
        fre = 206.835 - 1.015 * (word_count / sentence_count) - 84.6 * (syllable_count / word_count)
        return {
            "words_per_sentence": round(word_count / sentence_count, 2),
            "syllables_per_word": round(syllable_count / word_count, 2),
            "flesch_reading_ease": round(fre, 2),
            "note": "Flesch Reading Ease는 영문 기준 근사값입니다.",
        }

    return {"error": f"알 수 없는 작업: {action}"}


if __name__ == "__main__":
    sample = "안녕하세요. 이것은 텍스트 통계 도구입니다. 글자수와 단어수를 세어볼까요?"
    print(main(text=sample, action="full"))
    print(main(text="Hello world. This is a test. How are you?", action="readability"))
