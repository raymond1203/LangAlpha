# FORK: DART RAG MCP 서버 도구 단위 테스트
"""Tests for mcp_servers.korean.kr_rag_mcp_server tools.

Qdrant 와 OpenAI 클라이언트는 mock. 실제 네트워크 호출 없음.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp_servers.korean.kr_rag_mcp_server import (
    _build_filter,
    _make_error,
    _make_response,
    get_filing_chunks,
    search_korean_filings,
)


# ==========================================================================
# Helpers
# ==========================================================================


class TestMakeResponse:
    def test_list_populates_count(self):
        resp = _make_response("foo", [1, 2, 3])
        assert resp["count"] == 3
        assert resp["data_type"] == "foo"
        assert resp["source"] == "dart_rag"

    def test_extra_fields_merged(self):
        resp = _make_response("foo", [], query="hello", top_k=5)
        assert resp["query"] == "hello"
        assert resp["top_k"] == 5


class TestMakeError:
    def test_has_error_marker(self):
        err = _make_error("boom")
        assert err["data_type"] == "error"
        assert err["error"] == "boom"


class TestBuildFilter:
    def test_all_none_returns_none(self):
        assert _build_filter(None, None, None, None, None) is None

    def test_ticker_creates_must(self):
        f = _build_filter("005930", None, None, None, None)
        assert f is not None
        assert len(f.must) == 1

    def test_date_range_creates_range_condition(self):
        f = _build_filter(None, None, None, "2024-01-01", "2024-12-31")
        assert f is not None
        assert len(f.must) == 1


# ==========================================================================
# Fixtures for search / scroll
# ==========================================================================


def _mock_hit(score: float, payload: dict):
    h = MagicMock()
    h.score = score
    h.payload = payload
    return h


@pytest.fixture
def mock_openai():
    with patch("mcp_servers.korean.kr_rag_mcp_server._get_openai") as mock:
        client = MagicMock()
        resp = MagicMock()
        resp.data = [MagicMock(embedding=[0.1] * 1536)]
        client.embeddings.create.return_value = resp
        mock.return_value = client
        yield client


@pytest.fixture
def mock_qdrant():
    with patch("mcp_servers.korean.kr_rag_mcp_server._get_qdrant") as mock:
        qclient = MagicMock()
        mock.return_value = qclient
        yield qclient


# ==========================================================================
# search_korean_filings
# ==========================================================================


class TestSearchKoreanFilings:
    def test_empty_query_returns_error(self, mock_openai, mock_qdrant):
        result = search_korean_filings(query="")
        assert result["data_type"] == "error"
        mock_qdrant.search.assert_not_called()

    def test_returns_ranked_hits(self, mock_openai, mock_qdrant):
        mock_qdrant.search.return_value = [
            _mock_hit(
                0.92,
                {
                    "rcept_no": "20240101000001",
                    "corp_name": "삼성전자",
                    "ticker": "005930",
                    "filing_date": "2024-01-01",
                    "filing_type": "사업보고서",
                    "chunk_index": 5,
                    "text": "메모리 반도체 수요 회복...",
                },
            ),
            _mock_hit(
                0.81,
                {
                    "rcept_no": "20240201000001",
                    "corp_name": "SK하이닉스",
                    "ticker": "000660",
                    "filing_date": "2024-02-01",
                    "filing_type": "분기보고서",
                    "chunk_index": 3,
                    "text": "DRAM 출하량 증가...",
                },
            ),
        ]

        result = search_korean_filings(query="반도체 수요", top_k=2)

        assert result["data_type"] == "dart_rag_search"
        assert result["count"] == 2
        assert result["data"][0]["corp_name"] == "삼성전자"
        assert result["data"][0]["score"] == 0.92
        assert result["top_k"] == 2

    def test_top_k_clamped(self, mock_openai, mock_qdrant):
        mock_qdrant.search.return_value = []
        search_korean_filings(query="x", top_k=9999)
        # limit 은 MAX_TOP_K (50) 이하로 clamp
        call_kwargs = mock_qdrant.search.call_args.kwargs
        assert call_kwargs["limit"] <= 50

    def test_ticker_filter_passed(self, mock_openai, mock_qdrant):
        mock_qdrant.search.return_value = []
        search_korean_filings(query="x", ticker="005930")
        call_kwargs = mock_qdrant.search.call_args.kwargs
        assert call_kwargs["query_filter"] is not None

    def test_qdrant_exception_returns_error(self, mock_openai, mock_qdrant):
        mock_qdrant.search.side_effect = RuntimeError("down")
        result = search_korean_filings(query="x")
        assert result["data_type"] == "error"
        assert "down" in result["error"]


# ==========================================================================
# get_filing_chunks
# ==========================================================================


class TestGetFilingChunks:
    def test_empty_rcept_returns_error(self, mock_qdrant):
        result = get_filing_chunks(rcept_no="")
        assert result["data_type"] == "error"

    def test_sorts_by_chunk_index(self, mock_qdrant):
        # scroll 은 (records, next_offset) 튜플 반환
        r2 = MagicMock()
        r2.payload = {"rcept_no": "r1", "chunk_index": 2, "text": "two"}
        r0 = MagicMock()
        r0.payload = {"rcept_no": "r1", "chunk_index": 0, "text": "zero"}
        r1 = MagicMock()
        r1.payload = {"rcept_no": "r1", "chunk_index": 1, "text": "one"}
        mock_qdrant.scroll.return_value = ([r2, r0, r1], None)

        result = get_filing_chunks(rcept_no="r1")
        assert result["data_type"] == "dart_rag_chunks"
        indices = [c["chunk_index"] for c in result["data"]]
        assert indices == [0, 1, 2]

    def test_limit_clamped(self, mock_qdrant):
        mock_qdrant.scroll.return_value = ([], None)
        get_filing_chunks(rcept_no="r1", limit=9999)
        call_kwargs = mock_qdrant.scroll.call_args.kwargs
        assert call_kwargs["limit"] <= 500
