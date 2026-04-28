"""
Tests for /analyst-data graceful 미지원 응답 (issue #33 backend slice).

KR ticker (.KS / .KQ) 호출 시 200 with unsupported=True 로 응답. user_id / DB /
cache 모두 무관 (early-return 분기) 이라 mock 없이 직접 함수 호출.

NOTE: /overview KR 분기는 #42 Stage A+B 에서 KoreanFundamentalsSource 로 채워짐
(test_kr_fundamentals_source.py 참조).
"""

import pytest

from src.server.app.market_data import (
    get_analyst_data,
    is_unsupported_analyst_market,
)


class TestIsUnsupportedAnalystMarket:
    """Helper 직접 검증 — analyst 외 endpoint 가 추후 같은 helper 쓸 수 있도록."""

    def test_kospi_kosdaq_suffixes(self):
        assert is_unsupported_analyst_market("005930.KS") is True
        assert is_unsupported_analyst_market("263750.KQ") is True

    def test_case_insensitive_via_normalize(self):
        # helper 자체가 strip + upper 처리 — handler 와 동일한 normalize 보장
        assert is_unsupported_analyst_market("005930.ks") is True
        assert is_unsupported_analyst_market("  263750.kq  ") is True

    def test_us_and_unknown_are_supported(self):
        assert is_unsupported_analyst_market("GOOGL") is False
        assert is_unsupported_analyst_market("AAPL") is False
        assert is_unsupported_analyst_market("0700.HK") is False  # 향후 추가 시 본 케이스 갱신


class TestAnalystDataKRUnsupported:
    @pytest.mark.asyncio
    async def test_kospi_ticker_returns_unsupported(self):
        result = await get_analyst_data(symbol="005930.KS", user_id="test-user")
        assert result.symbol == "005930.KS"
        assert result.unsupported is True
        assert result.message is not None
        assert result.priceTargets is None
        assert result.grades == []

    @pytest.mark.asyncio
    async def test_kosdaq_ticker_returns_unsupported(self):
        result = await get_analyst_data(symbol="263750.KQ", user_id="test-user")
        assert result.unsupported is True
