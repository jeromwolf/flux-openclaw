"""
flux-openclaw TF-IDF 기반 지식 베이스 엔진

문서를 청크 단위로 분할하고 TF-IDF 인덱스를 구축하여
의미 기반 검색을 제공합니다. 외부 의존성 없이 표준 라이브러리만 사용합니다.

저장 경로:
- 문서: knowledge/docs/{uuid}.json
- 인덱스: knowledge/index.json

사용처:
- core.py에서 get_context()로 시스템 프롬프트에 관련 지식 포함
- tools/knowledge_manage.py (AI 도구)에서 문서 추가/검색
"""

import json
import uuid
import fcntl
import os
import re
import math
from collections import Counter
from datetime import datetime


class KnowledgeBase:
    """TF-IDF 기반 지식 베이스 저장소"""

    # 파일 크기 제한 (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024

    # 허용되는 파일 확장자
    ALLOWED_EXTENSIONS = {".txt", ".md", ".json"}

    # 불용어 목록 (한국어 + 영어 최소 집합)
    STOP_WORDS = frozenset({
        # 한국어 조사/어미
        "은", "는", "이", "가", "을", "를", "의", "에", "에서", "로", "으로",
        "와", "과", "도", "만", "부터", "까지", "에게", "한테", "께",
        # 영어 기능어
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "in", "on", "at", "of", "and", "or", "to", "for", "with", "by",
        "from", "as", "into", "about", "that", "this", "it", "not", "but",
    })

    # 한국어 조사 접미사 (토큰 끝에서 제거, 긴 것부터 매칭)
    KOREAN_SUFFIXES = (
        "에서는", "으로는", "에서", "으로", "부터", "까지",
        "에게", "한테", "이나", "이란", "이라",
        "은", "는", "이", "가", "을", "를", "의", "에",
        "로", "와", "과", "도", "만", "께",
    )

    # 청크 분할 최대 길이
    CHUNK_MAX_CHARS = 500

    def __init__(self, knowledge_dir=None):
        """지식 베이스 초기화

        Args:
            knowledge_dir: 지식 베이스 루트 디렉토리 (기본값: "knowledge")
        """
        self.knowledge_dir = knowledge_dir or "knowledge"
        self.docs_dir = os.path.join(self.knowledge_dir, "docs")
        self.index_path = os.path.join(self.knowledge_dir, "index.json")
        self._ensure_dirs()

    def _ensure_dirs(self):
        """지식 베이스 디렉토리 구조 생성"""
        os.makedirs(self.docs_dir, exist_ok=True)

    # ---- 파일 잠금 I/O ----

    def _load_json(self, path):
        """JSON 파일 로드 (공유 잠금 사용)"""
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            return data
        except (json.JSONDecodeError, ValueError, OSError):
            return None

    def _save_json(self, path, data):
        """JSON 파일 저장 (배타적 잠금 사용)"""
        dirpath = os.path.dirname(path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
        try:
            with open(path, "a+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    f.truncate()
                    json.dump(data, f, ensure_ascii=False, indent=2)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except OSError as e:
            print(f" [지식베이스] 저장 실패: {e}")

    # ---- 토큰화 ----

    def _tokenize(self, text):
        """텍스트를 토큰 리스트로 변환 (한국어 + 영어 지원)

        소문자 변환 후 알파벳, 한글, 숫자 단위로 분리합니다.
        한국어 조사 접미사를 제거하고 불용어를 필터링합니다.
        """
        raw_tokens = re.findall(r'[a-zA-Z가-힣0-9]+', text.lower())
        result = []
        for token in raw_tokens:
            # 한국어 토큰에서 조사 접미사 제거
            stripped = self._strip_korean_suffix(token)
            if stripped and stripped not in self.STOP_WORDS:
                result.append(stripped)
        return result

    def _strip_korean_suffix(self, token):
        """한국어 토큰 끝의 조사 접미사 제거

        토큰이 한글을 포함하는 경우에만 적용합니다.
        접미사를 제거한 후 최소 1글자 이상 남아야 합니다.
        """
        # 한글이 포함된 토큰에만 적용
        if not re.search(r'[가-힣]', token):
            return token

        for suffix in self.KOREAN_SUFFIXES:
            if token.endswith(suffix) and len(token) > len(suffix):
                return token[:-len(suffix)]
        return token

    # ---- 청크 분할 ----

    def _split_chunks(self, text):
        """텍스트를 문단 단위로 분할 후, 긴 문단은 문장 경계에서 재분할

        분할 기준:
        1. 빈 줄(\\n\\n)로 문단 분리
        2. 500자 초과 문단은 문장 종결 부호(. ! ? 。)에서 분리
        """
        # 빈 줄 기준 문단 분리
        paragraphs = re.split(r'\n\s*\n', text.strip())
        chunks = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(para) <= self.CHUNK_MAX_CHARS:
                chunks.append(para)
            else:
                # 문장 경계에서 분할
                sentences = re.split(r'(?<=[.!?。])\s+', para)
                current = ""
                for sent in sentences:
                    if current and len(current) + len(sent) + 1 > self.CHUNK_MAX_CHARS:
                        chunks.append(current.strip())
                        current = sent
                    else:
                        current = current + " " + sent if current else sent
                if current.strip():
                    chunks.append(current.strip())

        # 빈 청크 방지
        return [c for c in chunks if c.strip()]

    # ---- TF-IDF 계산 ----

    def _compute_tf(self, tokens):
        """단어 빈도(TF) 계산 — 토큰 길이로 정규화"""
        if not tokens:
            return {}
        counts = Counter(tokens)
        length = len(tokens)
        return {term: count / length for term, count in counts.items()}

    def _compute_idf(self, chunk_map):
        """역문서 빈도(IDF) 계산 — 전체 청크 수 기반

        IDF(t) = log((N + 1) / (1 + df(t)))
        분자에 +1을 추가하여 소규모 코퍼스에서도 IDF가 0이 되지 않도록 합니다.
        """
        n = len(chunk_map)
        if n == 0:
            return {}

        # 문서 빈도 계산 (각 청크에서 등장하는 용어 수)
        df = Counter()
        for chunk_info in chunk_map.values():
            unique_terms = set(chunk_info.get("tf", {}).keys())
            for term in unique_terms:
                df[term] += 1

        return {term: math.log((n + 1) / (1 + freq)) for term, freq in df.items()}

    def _cosine_similarity(self, vec_a, vec_b):
        """코사인 유사도 계산

        두 TF-IDF 벡터 간의 유사도를 [0, 1] 범위로 반환합니다.
        """
        # 공통 키에 대한 내적 계산
        common_terms = set(vec_a.keys()) & set(vec_b.keys())
        if not common_terms:
            return 0.0

        dot = sum(vec_a[t] * vec_b[t] for t in common_terms)
        norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
        norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return dot / (norm_a * norm_b)

    # ---- 인덱스 관리 ----

    def _load_index(self):
        """TF-IDF 인덱스 로드. 없으면 빈 인덱스 반환."""
        data = self._load_json(self.index_path)
        if data and isinstance(data, dict) and data.get("version") == 1:
            return data
        return {
            "version": 1,
            "doc_count": 0,
            "chunk_count": 0,
            "idf": {},
            "chunks": {},
        }

    def _save_index(self, index):
        """TF-IDF 인덱스 저장"""
        self._save_json(self.index_path, index)

    def _add_to_index(self, doc_id, chunks_data):
        """문서 청크를 인덱스에 추가하고 IDF 재계산"""
        index = self._load_index()

        for chunk in chunks_data:
            chunk_key = f"{doc_id}:{chunk['chunk_id']}"
            tf = self._compute_tf(chunk["tokens"])
            index["chunks"][chunk_key] = {
                "tf": tf,
                "doc_id": doc_id,
                "chunk_id": chunk["chunk_id"],
            }

        # IDF 재계산
        index["idf"] = self._compute_idf(index["chunks"])
        index["chunk_count"] = len(index["chunks"])

        # 고유 문서 수 계산
        doc_ids = set(v["doc_id"] for v in index["chunks"].values())
        index["doc_count"] = len(doc_ids)

        self._save_index(index)

    def _remove_from_index(self, doc_id):
        """문서 청크를 인덱스에서 제거하고 IDF 재계산"""
        index = self._load_index()

        # 해당 문서의 청크 키 수집
        keys_to_remove = [
            k for k, v in index["chunks"].items()
            if v["doc_id"] == doc_id
        ]

        if not keys_to_remove:
            return

        for key in keys_to_remove:
            del index["chunks"][key]

        # IDF 재계산
        index["idf"] = self._compute_idf(index["chunks"])
        index["chunk_count"] = len(index["chunks"])

        doc_ids = set(v["doc_id"] for v in index["chunks"].values())
        index["doc_count"] = len(doc_ids)

        self._save_index(index)

    # ---- 보안 검증 ----

    def _validate_doc_path(self, doc_id):
        """문서 경로 검증 — 경로 탐색 공격 방지

        해석된 경로가 docs 디렉토리 하위인지 확인합니다.
        """
        doc_path = os.path.join(self.docs_dir, f"{doc_id}.json")
        real_docs = os.path.realpath(self.docs_dir)
        real_path = os.path.realpath(doc_path)

        if not real_path.startswith(real_docs + os.sep) and real_path != real_docs:
            raise ValueError(f"잘못된 문서 경로: {doc_id}")
        return doc_path

    def _validate_file_path(self, file_path):
        """외부 파일 경로 검증 — 확장자 및 크기 확인"""
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise ValueError(
                f"허용되지 않는 파일 형식: {ext}. "
                f"가능한 형식: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
            )

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        file_size = os.path.getsize(file_path)
        if file_size > self.MAX_FILE_SIZE:
            raise ValueError(
                f"파일 크기 초과: {file_size} bytes "
                f"(최대 {self.MAX_FILE_SIZE} bytes)"
            )

    # ---- CRUD ----

    def add_document(self, title, content, source="user"):
        """문서를 추가하고 인덱스에 등록

        Args:
            title: 문서 제목
            content: 문서 원본 텍스트
            source: 출처 (기본값: "user")

        Returns:
            dict: {"doc_id": str, "title": str, "chunk_count": int}
        """
        doc_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        # 청크 분할 및 토큰화
        raw_chunks = self._split_chunks(content)
        chunks = []
        for i, text in enumerate(raw_chunks):
            tokens = self._tokenize(text)
            chunks.append({
                "chunk_id": i,
                "text": text,
                "tokens": tokens,
            })

        # 문서 메타데이터 저장
        doc_data = {
            "id": doc_id,
            "title": title,
            "content": content,
            "source": source,
            "created_at": now,
            "chunks": chunks,
        }

        doc_path = self._validate_doc_path(doc_id)
        self._save_json(doc_path, doc_data)

        # 인덱스 업데이트
        self._add_to_index(doc_id, chunks)

        return {
            "doc_id": doc_id,
            "title": title,
            "chunk_count": len(chunks),
        }

    def remove_document(self, doc_id):
        """문서 및 인덱스에서 제거

        Args:
            doc_id: 삭제할 문서 ID

        Returns:
            bool: 삭제 성공 여부
        """
        try:
            doc_path = self._validate_doc_path(doc_id)
        except ValueError:
            return False

        if not os.path.exists(doc_path):
            return False

        # 인덱스에서 제거
        self._remove_from_index(doc_id)

        # 문서 파일 삭제
        try:
            os.remove(doc_path)
        except OSError:
            return False

        return True

    # ---- 검색 ----

    def search(self, query, top_k=5):
        """TF-IDF 기반 유사도 검색

        쿼리를 토큰화하고 인덱스의 각 청크와 코사인 유사도를 계산합니다.

        Args:
            query: 검색 쿼리 문자열
            top_k: 반환할 최대 결과 수 (기본값: 5)

        Returns:
            list: [{"doc_id": str, "title": str, "chunk": str, "score": float}]
        """
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        index = self._load_index()
        if not index["chunks"]:
            return []

        # 쿼리 TF 계산
        query_tf = self._compute_tf(query_tokens)

        # 쿼리 TF-IDF 벡터 생성
        idf = index["idf"]
        query_vec = {
            term: tf_val * idf.get(term, 0.0)
            for term, tf_val in query_tf.items()
        }

        # 각 청크와 코사인 유사도 계산
        results = []
        for chunk_key, chunk_info in index["chunks"].items():
            chunk_tf = chunk_info["tf"]
            # 청크 TF-IDF 벡터 생성
            chunk_vec = {
                term: tf_val * idf.get(term, 0.0)
                for term, tf_val in chunk_tf.items()
            }

            score = self._cosine_similarity(query_vec, chunk_vec)
            if score > 0.0:
                results.append({
                    "doc_id": chunk_info["doc_id"],
                    "chunk_id": chunk_info["chunk_id"],
                    "score": score,
                })

        # 점수 내림차순 정렬
        results.sort(key=lambda x: -x["score"])
        results = results[:top_k]

        # 문서 정보 및 청크 텍스트 부착
        enriched = []
        doc_cache = {}
        for r in results:
            doc_id = r["doc_id"]

            # 문서 캐시 활용
            if doc_id not in doc_cache:
                try:
                    doc_path = self._validate_doc_path(doc_id)
                    doc_cache[doc_id] = self._load_json(doc_path)
                except (ValueError, OSError):
                    doc_cache[doc_id] = None

            doc = doc_cache[doc_id]
            if not doc:
                continue

            # 청크 텍스트 추출
            chunk_text = ""
            for c in doc.get("chunks", []):
                if c["chunk_id"] == r["chunk_id"]:
                    chunk_text = c["text"]
                    break

            enriched.append({
                "doc_id": doc_id,
                "title": doc.get("title", ""),
                "chunk": chunk_text,
                "score": round(r["score"], 4),
            })

        return enriched

    def get_context(self, query, max_chars=1000):
        """검색 결과를 기반으로 AI 컨텍스트 문자열 생성

        상위 검색 결과를 max_chars 이내로 연결하여 반환합니다.

        Args:
            query: 검색 쿼리
            max_chars: 최대 문자 수 (기본값: 1000)

        Returns:
            str: 검색 결과 컨텍스트 문자열
        """
        results = self.search(query, top_k=10)
        if not results:
            return ""

        parts = []
        total_len = 0
        for r in results:
            # 출처 헤더 + 청크 텍스트
            entry = f"[{r['title']}] {r['chunk']}"

            if total_len + len(entry) + 1 > max_chars:
                # 남은 공간이 있으면 잘라서 추가
                remaining = max_chars - total_len
                if remaining > 50:
                    parts.append(entry[:remaining])
                break

            parts.append(entry)
            total_len += len(entry) + 1  # 줄바꿈 포함

        return "\n".join(parts)

    # ---- 통계 및 목록 ----

    def get_stats(self):
        """지식 베이스 통계 반환

        Returns:
            dict: {"doc_count": int, "chunk_count": int, "index_size": int}
        """
        index = self._load_index()

        # 인덱스 파일 크기 계산
        index_size = 0
        if os.path.exists(self.index_path):
            index_size = os.path.getsize(self.index_path)

        return {
            "doc_count": index.get("doc_count", 0),
            "chunk_count": index.get("chunk_count", 0),
            "index_size": index_size,
        }

    def list_documents(self):
        """등록된 모든 문서 목록 반환

        Returns:
            list: [{"doc_id": str, "title": str, "source": str,
                     "created_at": str, "chunk_count": int}]
        """
        documents = []

        if not os.path.isdir(self.docs_dir):
            return documents

        for filename in os.listdir(self.docs_dir):
            if not filename.endswith(".json"):
                continue

            doc_path = os.path.join(self.docs_dir, filename)
            doc = self._load_json(doc_path)
            if not doc or not isinstance(doc, dict):
                continue

            documents.append({
                "doc_id": doc.get("id", ""),
                "title": doc.get("title", ""),
                "source": doc.get("source", ""),
                "created_at": doc.get("created_at", ""),
                "chunk_count": len(doc.get("chunks", [])),
            })

        # 생성일 내림차순 정렬 (최신 먼저)
        documents.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return documents

    # ---- 파일/디렉토리 인덱싱 ----

    def index_file(self, file_path):
        """텍스트/마크다운 파일을 읽어 문서로 추가

        Args:
            file_path: 인덱싱할 파일 경로

        Returns:
            dict: add_document 결과 {"doc_id": str, "title": str, "chunk_count": int}
        """
        self._validate_file_path(file_path)

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 파일명에서 제목 추출
        title = os.path.basename(file_path)

        return self.add_document(
            title=title,
            content=content,
            source=f"file:{file_path}",
        )

    def index_directory(self, dir_path):
        """디렉토리 내 모든 .txt/.md 파일을 인덱싱

        Args:
            dir_path: 인덱싱할 디렉토리 경로

        Returns:
            list: 각 파일의 add_document 결과 리스트
        """
        if not os.path.isdir(dir_path):
            raise NotADirectoryError(f"디렉토리를 찾을 수 없습니다: {dir_path}")

        results = []
        for filename in sorted(os.listdir(dir_path)):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in {".txt", ".md"}:
                continue

            file_path = os.path.join(dir_path, filename)
            if not os.path.isfile(file_path):
                continue

            try:
                result = self.index_file(file_path)
                results.append(result)
            except (ValueError, OSError) as e:
                print(f" [지식베이스] 파일 인덱싱 실패 ({filename}): {e}")

        return results

    # ---- 인덱스 재구축 ----

    def rebuild_index(self):
        """전체 인덱스를 문서 파일들로부터 재구축

        모든 문서를 다시 읽고 TF-IDF 인덱스를 처음부터 생성합니다.

        Returns:
            dict: {"doc_count": int, "chunk_count": int}
        """
        # 빈 인덱스로 초기화
        index = {
            "version": 1,
            "doc_count": 0,
            "chunk_count": 0,
            "idf": {},
            "chunks": {},
        }

        if not os.path.isdir(self.docs_dir):
            self._save_index(index)
            return {"doc_count": 0, "chunk_count": 0}

        # 모든 문서 파일에서 청크 수집
        doc_ids = set()
        for filename in os.listdir(self.docs_dir):
            if not filename.endswith(".json"):
                continue

            doc_path = os.path.join(self.docs_dir, filename)
            doc = self._load_json(doc_path)
            if not doc or not isinstance(doc, dict):
                continue

            doc_id = doc.get("id", "")
            if not doc_id:
                continue

            doc_ids.add(doc_id)

            for chunk in doc.get("chunks", []):
                chunk_key = f"{doc_id}:{chunk['chunk_id']}"
                tf = self._compute_tf(chunk.get("tokens", []))
                index["chunks"][chunk_key] = {
                    "tf": tf,
                    "doc_id": doc_id,
                    "chunk_id": chunk["chunk_id"],
                }

        # IDF 재계산
        index["idf"] = self._compute_idf(index["chunks"])
        index["doc_count"] = len(doc_ids)
        index["chunk_count"] = len(index["chunks"])

        self._save_index(index)

        return {
            "doc_count": index["doc_count"],
            "chunk_count": index["chunk_count"],
        }
