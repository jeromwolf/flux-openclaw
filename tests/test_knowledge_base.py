"""
knowledge_base.py 테스트
"""
import pytest
import os
import json
import sys

# knowledge_base.py를 임포트하기 위해 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openclaw.knowledge_base import KnowledgeBase


# ============================================================
# Fixture
# ============================================================

@pytest.fixture
def kb(tmp_path):
    """임시 디렉토리를 사용하는 KnowledgeBase 인스턴스"""
    return KnowledgeBase(knowledge_dir=str(tmp_path / "knowledge"))


# ============================================================
# 1. 초기화 테스트
# ============================================================

class TestInitialization:
    """KnowledgeBase 초기화 관련 테스트"""

    def test_init_creates_directories(self, tmp_path):
        """초기화 시 디렉토리가 생성되는지 확인"""
        knowledge_dir = str(tmp_path / "knowledge")
        kb = KnowledgeBase(knowledge_dir=knowledge_dir)

        assert os.path.isdir(knowledge_dir)
        assert os.path.isdir(os.path.join(knowledge_dir, "docs"))

    def test_init_default_path(self, monkeypatch, tmp_path):
        """기본 knowledge_dir은 'knowledge'"""
        monkeypatch.chdir(tmp_path)
        kb = KnowledgeBase()

        assert kb.knowledge_dir == "knowledge"
        assert os.path.isdir("knowledge")

    def test_init_custom_path(self, tmp_path):
        """커스텀 경로가 정상 동작하는지 확인"""
        custom_path = str(tmp_path / "my_custom_kb")
        kb = KnowledgeBase(knowledge_dir=custom_path)

        assert kb.knowledge_dir == custom_path
        assert os.path.isdir(custom_path)
        assert os.path.isdir(os.path.join(custom_path, "docs"))


# ============================================================
# 2. 문서 CRUD 테스트
# ============================================================

class TestDocumentCRUD:
    """문서 생성/조회/삭제 테스트"""

    def test_add_document(self, kb):
        """문서 추가 시 doc_id, title, chunk_count를 포함하는 dict 반환"""
        result = kb.add_document(title="테스트 문서", content="안녕하세요. 이것은 테스트입니다.")

        assert isinstance(result, dict)
        assert "doc_id" in result
        assert result["title"] == "테스트 문서"
        assert "chunk_count" in result
        assert result["chunk_count"] >= 1

    def test_add_document_creates_file(self, kb):
        """문서 추가 시 docs/ 디렉토리에 JSON 파일이 생성되는지 확인"""
        result = kb.add_document(title="파일 생성 테스트", content="테스트 내용입니다.")
        doc_id = result["doc_id"]

        doc_path = os.path.join(kb.docs_dir, f"{doc_id}.json")
        assert os.path.isfile(doc_path)

        with open(doc_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["id"] == doc_id
        assert data["title"] == "파일 생성 테스트"
        assert data["content"] == "테스트 내용입니다."

    def test_remove_document(self, kb):
        """문서 삭제 시 True 반환, 파일 삭제됨"""
        result = kb.add_document(title="삭제 테스트", content="삭제할 문서입니다.")
        doc_id = result["doc_id"]
        doc_path = os.path.join(kb.docs_dir, f"{doc_id}.json")

        assert os.path.isfile(doc_path)
        assert kb.remove_document(doc_id) is True
        assert not os.path.isfile(doc_path)

    def test_remove_nonexistent(self, kb):
        """존재하지 않는 문서 삭제 시 False 반환"""
        assert kb.remove_document("nonexistent-id-12345") is False

    def test_list_documents_empty(self, kb):
        """문서가 없을 때 빈 리스트 반환"""
        assert kb.list_documents() == []

    def test_list_documents(self, kb):
        """문서 추가 후 목록 조회"""
        kb.add_document(title="문서1", content="내용1")
        kb.add_document(title="문서2", content="내용2")

        docs = kb.list_documents()
        assert len(docs) == 2

        titles = {d["title"] for d in docs}
        assert titles == {"문서1", "문서2"}

        # 각 항목의 필드 확인
        for doc in docs:
            assert "doc_id" in doc
            assert "title" in doc
            assert "source" in doc
            assert "created_at" in doc
            assert "chunk_count" in doc

    def test_add_multiple_documents(self, kb):
        """여러 문서가 서로 공존하는지 확인"""
        r1 = kb.add_document(title="Alpha", content="First document content.")
        r2 = kb.add_document(title="Beta", content="Second document content.")
        r3 = kb.add_document(title="Gamma", content="Third document content.")

        assert r1["doc_id"] != r2["doc_id"] != r3["doc_id"]

        docs = kb.list_documents()
        assert len(docs) == 3


# ============================================================
# 3. 검색 테스트
# ============================================================

class TestSearch:
    """TF-IDF 기반 검색 테스트"""

    def test_search_basic(self, kb):
        """기본 검색이 관련 문서를 찾는지 확인"""
        kb.add_document(title="Python 가이드", content="Python is a programming language used for web development and data science.")
        kb.add_document(title="요리법", content="오늘의 요리는 김치찌개입니다. 재료는 김치, 두부, 돼지고기입니다.")

        results = kb.search("Python programming")
        assert len(results) >= 1
        assert results[0]["title"] == "Python 가이드"

    def test_search_korean(self, kb):
        """한국어 텍스트 검색이 동작하는지 확인"""
        kb.add_document(title="한국어 문서", content="인공지능 기술은 빠르게 발전하고 있습니다. 머신러닝과 딥러닝이 핵심입니다.")
        kb.add_document(title="영어 문서", content="This is an English document about something completely different.")

        results = kb.search("인공지능 머신러닝")
        assert len(results) >= 1
        assert results[0]["title"] == "한국어 문서"

    def test_search_no_results(self, kb):
        """관련 없는 쿼리로 검색 시 빈 리스트 반환"""
        kb.add_document(title="프로그래밍", content="Python is great for programming.")

        results = kb.search("김치찌개 요리법 레시피")
        assert results == []

    def test_search_ranking(self, kb):
        """관련성이 높은 문서가 더 높은 순위에 오는지 확인"""
        kb.add_document(
            title="Python 전문서",
            content="Python Python Python. Advanced Python programming. Python development. Python frameworks."
        )
        kb.add_document(
            title="일반 프로그래밍",
            content="Programming includes many languages like Java, Go, Rust, and sometimes Python."
        )
        # IDF가 0이 되지 않도록 Python을 포함하지 않는 문서 추가
        kb.add_document(
            title="요리책",
            content="김치찌개 레시피입니다. 재료는 김치 두부 돼지고기 양파 마늘입니다."
        )

        results = kb.search("Python")
        assert len(results) >= 2
        # Python이 더 많이 등장하는 문서가 상위에 위치
        assert results[0]["title"] == "Python 전문서"

    def test_search_top_k(self, kb):
        """top_k 파라미터가 결과 수를 제한하는지 확인"""
        for i in range(10):
            kb.add_document(title=f"문서{i}", content=f"machine learning algorithm model{i}")

        results = kb.search("machine learning", top_k=3)
        assert len(results) <= 3

    def test_search_empty_query(self, kb):
        """빈 쿼리 검색 시 빈 리스트 반환"""
        kb.add_document(title="문서", content="내용이 있습니다.")

        results = kb.search("")
        assert results == []

    def test_search_after_remove(self, kb):
        """삭제된 문서가 검색 결과에 나타나지 않는지 확인"""
        r1 = kb.add_document(title="삭제될 문서", content="unique_keyword_alpha")
        kb.add_document(title="남아있는 문서", content="different content entirely")

        # 삭제 전 검색
        results_before = kb.search("unique_keyword_alpha")
        assert len(results_before) >= 1

        # 삭제 후 검색
        kb.remove_document(r1["doc_id"])
        results_after = kb.search("unique_keyword_alpha")
        assert results_after == []

    def test_get_context(self, kb):
        """get_context가 max_chars 이내의 문자열을 반환하는지 확인"""
        kb.add_document(title="AI 문서", content="Artificial intelligence is transforming technology. Machine learning models are powerful.")
        kb.add_document(title="요리 문서", content="김치찌개를 만들어 봅시다.")

        context = kb.get_context("artificial intelligence", max_chars=200)
        assert isinstance(context, str)
        assert len(context) <= 200
        assert context != ""


# ============================================================
# 4. 청킹 테스트
# ============================================================

class TestChunking:
    """텍스트 분할(청킹) 테스트"""

    def test_chunk_short_text(self, kb):
        """짧은 텍스트는 1개의 청크가 되는지 확인"""
        result = kb.add_document(title="짧은 문서", content="짧은 내용입니다.")
        assert result["chunk_count"] == 1

    def test_chunk_long_text(self, kb):
        """긴 텍스트가 여러 청크로 분할되는지 확인"""
        # CHUNK_MAX_CHARS(500)를 초과하는 단일 문단 생성
        long_text = "This is a sentence. " * 100  # 약 2000자
        result = kb.add_document(title="긴 문서", content=long_text)
        assert result["chunk_count"] > 1

    def test_chunk_paragraphs(self, kb):
        """이중 줄바꿈으로 구분된 문단이 별도 청크로 분할되는지 확인"""
        text = "첫 번째 문단입니다.\n\n두 번째 문단입니다.\n\n세 번째 문단입니다."
        result = kb.add_document(title="문단 테스트", content=text)
        assert result["chunk_count"] == 3

    def test_chunk_count_in_result(self, kb):
        """add_document 결과의 chunk_count가 실제 청크 수와 일치하는지 확인"""
        text = "문단1\n\n문단2\n\n문단3\n\n문단4\n\n문단5"
        result = kb.add_document(title="카운트 테스트", content=text)

        # 문서 파일에서 실제 청크 수 확인
        doc_path = os.path.join(kb.docs_dir, f"{result['doc_id']}.json")
        with open(doc_path, "r", encoding="utf-8") as f:
            doc_data = json.load(f)

        assert result["chunk_count"] == len(doc_data["chunks"])
        assert result["chunk_count"] == 5


# ============================================================
# 5. 인덱스 테스트
# ============================================================

class TestIndex:
    """TF-IDF 인덱스 관련 테스트"""

    def test_rebuild_index(self, kb):
        """인덱스 재구축이 저장된 문서로부터 올바르게 동작하는지 확인"""
        kb.add_document(title="문서A", content="Alpha content here.")
        kb.add_document(title="문서B", content="Beta content here.")

        result = kb.rebuild_index()
        assert result["doc_count"] == 2
        assert result["chunk_count"] >= 2

    def test_index_persistence(self, tmp_path):
        """인덱스가 재인스턴스화 후에도 유지되는지 확인"""
        knowledge_dir = str(tmp_path / "knowledge")

        # 첫 번째 인스턴스에서 문서 추가 (IDF가 0이 되지 않도록 2개 이상 추가)
        kb1 = KnowledgeBase(knowledge_dir=knowledge_dir)
        kb1.add_document(title="영구 문서", content="persistent data for search verification")
        kb1.add_document(title="다른 문서", content="completely different topic about cooking recipes")

        # 두 번째 인스턴스 생성
        kb2 = KnowledgeBase(knowledge_dir=knowledge_dir)
        results = kb2.search("persistent data")

        assert len(results) >= 1
        assert results[0]["title"] == "영구 문서"

    def test_get_stats(self, kb):
        """get_stats가 올바른 doc_count, chunk_count, index_size를 반환하는지 확인"""
        # 빈 상태
        stats_empty = kb.get_stats()
        assert stats_empty["doc_count"] == 0
        assert stats_empty["chunk_count"] == 0

        # 문서 추가 후
        kb.add_document(title="통계 문서1", content="내용1")
        kb.add_document(title="통계 문서2", content="내용2\n\n내용3")

        stats = kb.get_stats()
        assert stats["doc_count"] == 2
        assert stats["chunk_count"] >= 3  # 문서2는 2개 청크
        assert stats["index_size"] > 0


# ============================================================
# 6. 파일 작업 테스트
# ============================================================

class TestFileOperations:
    """파일/디렉토리 인덱싱 테스트"""

    def test_index_file(self, kb, tmp_path):
        """텍스트 파일 인덱싱이 정상 동작하는지 확인"""
        test_file = tmp_path / "sample.txt"
        test_file.write_text("This is a sample text file for indexing.", encoding="utf-8")

        result = kb.index_file(str(test_file))
        assert result["title"] == "sample.txt"
        assert result["chunk_count"] >= 1
        assert "doc_id" in result

    def test_index_file_too_large(self, kb, tmp_path):
        """10MB 초과 파일은 거부되는지 확인"""
        large_file = tmp_path / "large.txt"
        # 10MB + 1byte 파일 생성
        large_file.write_bytes(b"x" * (10 * 1024 * 1024 + 1))

        with pytest.raises(ValueError, match="파일 크기 초과"):
            kb.index_file(str(large_file))

    def test_index_directory(self, kb, tmp_path):
        """디렉토리 내 모든 .txt/.md 파일이 인덱싱되는지 확인"""
        docs_dir = tmp_path / "source_docs"
        docs_dir.mkdir()

        (docs_dir / "file1.txt").write_text("First document content.", encoding="utf-8")
        (docs_dir / "file2.md").write_text("Second document content.", encoding="utf-8")
        (docs_dir / "file3.py").write_text("# Not indexed", encoding="utf-8")
        (docs_dir / "file4.json").write_text('{"key": "value"}', encoding="utf-8")

        results = kb.index_directory(str(docs_dir))

        # .txt와 .md만 인덱싱 (.json과 .py는 index_directory에서 제외)
        assert len(results) == 2
        titles = {r["title"] for r in results}
        assert titles == {"file1.txt", "file2.md"}


# ============================================================
# 7. 보안 테스트
# ============================================================

class TestSecurity:
    """보안 관련 테스트"""

    def test_path_traversal_blocked(self, kb):
        """경로 탐색 공격(path traversal)이 차단되는지 확인"""
        with pytest.raises(ValueError, match="잘못된 문서 경로"):
            kb._validate_doc_path("../../etc/passwd")

    def test_invalid_extension_blocked(self, kb, tmp_path):
        """허용되지 않은 확장자가 차단되는지 확인 (.txt/.md/.json만 허용)"""
        py_file = tmp_path / "script.py"
        py_file.write_text("print('hello')", encoding="utf-8")

        with pytest.raises(ValueError, match="허용되지 않는 파일 형식"):
            kb.index_file(str(py_file))

        exe_file = tmp_path / "program.exe"
        exe_file.write_bytes(b"\x00" * 100)

        with pytest.raises(ValueError, match="허용되지 않는 파일 형식"):
            kb.index_file(str(exe_file))
