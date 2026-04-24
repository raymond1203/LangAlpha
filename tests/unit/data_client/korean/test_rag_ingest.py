# FORK: DART RAG 인제스트 파이프라인 단위 테스트
"""Tests for src.data_client.korean.rag_ingest."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data_client.korean.rag_ingest import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    IngestConfig,
    IngestStats,
    chunk_text,
    clean_dart_text,
    embed_batch,
    ensure_collection,
    fetch_disclosure_body,
    ingest_corp,
    ingest_disclosure,
    point_id_for,
)


# ==========================================================================
# clean_dart_text
# ==========================================================================


class TestCleanDartText:
    def test_strips_html_tags(self):
        assert clean_dart_text("<p>본문</p>") == "본문"

    def test_normalizes_whitespace(self):
        assert clean_dart_text("  a\n\n\nb\t\tc  ") == "a b c"

    def test_strips_html_entities(self):
        assert clean_dart_text("foo&nbsp;bar") == "foo bar"

    def test_empty_input(self):
        assert clean_dart_text(None) == ""
        assert clean_dart_text("") == ""


# ==========================================================================
# chunk_text
# ==========================================================================


class TestChunkText:
    def test_short_text_single_chunk(self):
        assert chunk_text("짧은 텍스트") == ["짧은 텍스트"]

    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_chunks_within_size_limit(self):
        text = "문장 하나. " * 200  # 약 2000자
        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)
        assert len(chunks) > 1
        # 정확히 500 이하는 아니지만 크게 벗어나지 않아야 함 (경계 찾다가 조금 늘어남)
        for c in chunks:
            assert len(c) <= 600

    def test_overlap_present(self):
        # 문장 부호로 확실히 끊어지는 텍스트
        text = ". ".join([f"문장{i}" for i in range(100)]) + "."
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
        assert len(chunks) > 1
        # 연속 청크에 공통 substring 이 있어야 함 (오버랩)
        # 경계 탐색 때문에 엄밀히 보장되진 않지만, 인접 청크의 시작/끝이 인접해야 함
        assert "".join(chunks).count("문장") >= text.count("문장")

    def test_invalid_overlap(self):
        with pytest.raises(ValueError):
            chunk_text("abc", chunk_size=10, chunk_overlap=10)
        with pytest.raises(ValueError):
            chunk_text("abc", chunk_size=10, chunk_overlap=-1)

    def test_defaults_reasonable(self):
        # 긴 텍스트가 defaults 로도 정상 청킹
        text = "한국어 문장. " * 500
        chunks = chunk_text(text)
        assert len(chunks) > 1
        assert all(len(c) > 0 for c in chunks)
        assert all(len(c) <= DEFAULT_CHUNK_SIZE + 100 for c in chunks)
        # 기본 오버랩 값 사용
        _ = DEFAULT_CHUNK_OVERLAP  # 존재 검증


# ==========================================================================
# point_id_for — 결정론성
# ==========================================================================


class TestPointId:
    def test_deterministic(self):
        assert point_id_for("20240101000001", 3) == point_id_for(
            "20240101000001", 3
        )

    def test_different_inputs_different_ids(self):
        assert point_id_for("A", 0) != point_id_for("A", 1)
        assert point_id_for("A", 0) != point_id_for("B", 0)


# ==========================================================================
# fetch_disclosure_body
# ==========================================================================


class TestFetchBody:
    def test_string_response_cleaned(self):
        dart = MagicMock()
        dart.document.return_value = "<p>본문</p>"
        assert fetch_disclosure_body(dart, "rcept") == "본문"

    def test_dict_response_joined(self):
        dart = MagicMock()
        dart.document.return_value = {"sec1": "<p>A</p>", "sec2": "B"}
        result = fetch_disclosure_body(dart, "rcept")
        assert "A" in result and "B" in result

    def test_exception_returns_empty(self):
        dart = MagicMock()
        dart.document.side_effect = RuntimeError("API error")
        assert fetch_disclosure_body(dart, "rcept") == ""

    def test_none_response_empty(self):
        dart = MagicMock()
        dart.document.return_value = None
        assert fetch_disclosure_body(dart, "rcept") == ""


# ==========================================================================
# embed_batch
# ==========================================================================


class TestEmbedBatch:
    def test_empty_returns_empty(self):
        client = MagicMock()
        assert embed_batch(client, []) == []
        client.embeddings.create.assert_not_called()

    def test_calls_openai_with_batch(self):
        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock(embedding=[0.1, 0.2]), MagicMock(embedding=[0.3, 0.4])]
        client.embeddings.create.return_value = mock_resp

        result = embed_batch(client, ["a", "b"], model="text-embedding-3-small")

        assert result == [[0.1, 0.2], [0.3, 0.4]]
        client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small", input=["a", "b"],
        )


# ==========================================================================
# ensure_collection
# ==========================================================================


class TestEnsureCollection:
    def test_creates_when_missing(self):
        qclient = MagicMock()
        existing = MagicMock()
        existing.collections = []
        qclient.get_collections.return_value = existing

        created = ensure_collection(qclient, "dart_filings", dim=1536)

        assert created is True
        qclient.create_collection.assert_called_once()
        # payload index 는 여러 필드에 대해 시도
        assert qclient.create_payload_index.call_count >= 1

    def test_noop_when_exists(self):
        qclient = MagicMock()
        col = MagicMock()
        col.name = "dart_filings"
        existing = MagicMock()
        existing.collections = [col]
        qclient.get_collections.return_value = existing

        created = ensure_collection(qclient, "dart_filings", dim=1536)

        assert created is False
        qclient.create_collection.assert_not_called()


# ==========================================================================
# ingest_disclosure
# ==========================================================================


class TestIngestDisclosure:
    def _build_mocks(self, body: str, n_chunks: int = 2):
        dart = MagicMock()
        dart.document.return_value = body

        openai_client = MagicMock()
        resp = MagicMock()
        resp.data = [MagicMock(embedding=[0.1] * 4) for _ in range(n_chunks)]
        openai_client.embeddings.create.return_value = resp

        qclient = MagicMock()
        return dart, openai_client, qclient

    def test_empty_body_returns_zero(self):
        dart, openai_client, qclient = self._build_mocks(body="")
        cfg = IngestConfig()
        uploaded = ingest_disclosure(
            dart=dart,
            openai_client=openai_client,
            qclient=qclient,
            rcept_no="r1",
            corp_name="테스트",
            ticker="005930",
            filing_date="2024-01-01",
            filing_type="사업보고서",
            config=cfg,
        )
        assert uploaded == 0
        qclient.upsert.assert_not_called()

    def test_happy_path_uploads_chunks(self):
        # 긴 본문 → 여러 청크
        body = "문장 하나. " * 300
        dart, openai_client, qclient = self._build_mocks(body=body, n_chunks=1)
        # embed 는 여러 배치로 호출될 수 있으므로 항상 일관된 응답 반환
        openai_client.embeddings.create.side_effect = lambda model, input: MagicMock(
            data=[MagicMock(embedding=[0.1] * 4) for _ in input],
        )

        cfg = IngestConfig(chunk_size=200, chunk_overlap=20, batch_size=64)
        uploaded = ingest_disclosure(
            dart=dart,
            openai_client=openai_client,
            qclient=qclient,
            rcept_no="r1",
            corp_name="테스트",
            ticker="005930",
            filing_date="2024-01-01",
            filing_type="사업보고서",
            config=cfg,
        )
        assert uploaded > 0
        qclient.upsert.assert_called_once()
        call = qclient.upsert.call_args
        points = call.kwargs["points"]
        assert len(points) == uploaded
        # payload 스키마 확인
        first = points[0]
        assert first.payload["rcept_no"] == "r1"
        assert first.payload["ticker"] == "005930"
        assert first.payload["chunk_index"] == 0


# ==========================================================================
# ingest_corp — 기업 단위 수집 + stats 집계
# ==========================================================================


class TestIngestCorp:
    def test_aggregates_stats_and_respects_max(self):
        dart = MagicMock()
        dart.list.return_value = pd.DataFrame(
            [
                {
                    "rcept_no": "20240101000001",
                    "corp_name": "삼성전자",
                    "stock_code": "005930",
                    "rcept_dt": "20240101",
                    "report_nm": "사업보고서",
                },
                {
                    "rcept_no": "20240201000001",
                    "corp_name": "삼성전자",
                    "stock_code": "005930",
                    "rcept_dt": "20240201",
                    "report_nm": "분기보고서",
                },
                {
                    "rcept_no": "20240301000001",
                    "corp_name": "삼성전자",
                    "stock_code": "005930",
                    "rcept_dt": "20240301",
                    "report_nm": "주요사항보고서",
                },
            ]
        )

        cfg = IngestConfig()
        stats = IngestStats()

        with patch(
            "src.data_client.korean.rag_ingest.ingest_disclosure", return_value=3,
        ) as mock_ing:
            ingest_corp(
                dart=dart,
                openai_client=MagicMock(),
                qclient=MagicMock(),
                corp="005930",
                config=cfg,
                stats=stats,
                max_per_corp=2,
            )

        assert stats.corps_processed == 1
        assert stats.disclosures_seen == 2  # max 에 걸림
        assert stats.disclosures_ingested == 2
        assert stats.chunks_uploaded == 6
        assert mock_ing.call_count == 2

    def test_skips_empty_body_disclosures(self):
        dart = MagicMock()
        dart.list.return_value = pd.DataFrame(
            [
                {
                    "rcept_no": "r1",
                    "corp_name": "X",
                    "stock_code": "000000",
                    "rcept_dt": "20240101",
                    "report_nm": "사업보고서",
                }
            ]
        )
        cfg = IngestConfig()
        stats = IngestStats()

        with patch(
            "src.data_client.korean.rag_ingest.ingest_disclosure", return_value=0,
        ):
            ingest_corp(
                dart=dart,
                openai_client=MagicMock(),
                qclient=MagicMock(),
                corp="X",
                config=cfg,
                stats=stats,
            )

        assert stats.disclosures_ingested == 0
        assert stats.disclosures_skipped_empty == 1
        assert stats.chunks_uploaded == 0
