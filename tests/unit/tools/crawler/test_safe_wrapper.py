"""Unit tests for SafeCrawlerWrapper.crawl() fault-tolerance paths."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.crawler.backend import CrawlOutput
from src.tools.crawler.safe_wrapper import (
    CircuitState,
    CrawlResult,
    CrawlerCircuitBreaker,
    SafeCrawlerWrapper,
    _build_configured_wrapper,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wrapper(**kwargs) -> SafeCrawlerWrapper:
    """Create a SafeCrawlerWrapper with a mocked backend so no real import occurs."""
    defaults = dict(
        max_concurrent=5,
        max_queue_size=10,
        default_timeout=5.0,
        slot_timeout=2.0,
        circuit_failure_threshold=3,
        circuit_recovery_timeout=60.0,
        circuit_success_threshold=2,
    )
    defaults.update(kwargs)
    wrapper = SafeCrawlerWrapper(**defaults)
    return wrapper


def _inject_mock_crawler(wrapper: SafeCrawlerWrapper) -> AsyncMock:
    """Inject a mock crawler so _get_crawler() returns it without importing real backends."""
    mock_crawler = AsyncMock()
    wrapper._crawler = mock_crawler
    return mock_crawler


# ---------------------------------------------------------------------------
# SafeCrawlerWrapper.crawl() fault-tolerance paths
# ---------------------------------------------------------------------------


class TestSafeCrawlerCrawl:
    """Tests for SafeCrawlerWrapper.crawl() covering all fault-tolerance paths."""

    @pytest.mark.asyncio
    async def test_circuit_open_returns_error(self):
        """When circuit breaker is OPEN, crawl returns immediately with circuit_open error."""
        wrapper = _make_wrapper()
        wrapper._circuit.state = CircuitState.OPEN
        # Ensure check_state does NOT transition (last failure was recent)
        wrapper._circuit.last_failure_time = time.time()

        result = await wrapper.crawl("https://example.com")

        assert isinstance(result, CrawlResult)
        assert result.success is False
        assert result.error_type == "circuit_open"
        assert result.markdown is None

    @pytest.mark.asyncio
    async def test_queue_full_returns_error(self):
        """When queue is at capacity, crawl returns queue_full error."""
        wrapper = _make_wrapper(max_queue_size=2)
        _inject_mock_crawler(wrapper)

        # Artificially fill the queue
        wrapper._queue_count = 2

        result = await wrapper.crawl("https://example.com")

        assert result.success is False
        assert result.error_type == "queue_full"
        assert "capacity" in result.error.lower()

    @pytest.mark.asyncio
    async def test_semaphore_slot_timeout(self):
        """When no semaphore slot is available within slot_timeout, returns queue_timeout."""
        wrapper = _make_wrapper(max_concurrent=1, slot_timeout=0.05)
        _inject_mock_crawler(wrapper)

        # Exhaust the semaphore
        await wrapper._semaphore.acquire()

        result = await wrapper.crawl("https://example.com")

        assert result.success is False
        assert result.error_type == "queue_timeout"
        assert "slot" in result.error.lower()

        # Clean up: release the semaphore we manually acquired
        wrapper._semaphore.release()

    @pytest.mark.asyncio
    async def test_crawl_timeout_returns_timeout_error(self):
        """When the crawl itself exceeds the timeout, returns timeout error."""
        wrapper = _make_wrapper(default_timeout=0.05)
        mock_crawler = _inject_mock_crawler(wrapper)

        # Simulate a crawl that never finishes
        async def slow_crawl(url):
            await asyncio.sleep(10)

        mock_crawler.crawl_with_metadata = slow_crawl

        result = await wrapper.crawl("https://example.com")

        assert result.success is False
        assert result.error_type == "timeout"
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_crawl_timeout_records_failure(self):
        """Timeout should be recorded as a circuit breaker failure."""
        wrapper = _make_wrapper(default_timeout=0.05, circuit_failure_threshold=1)
        mock_crawler = _inject_mock_crawler(wrapper)

        async def slow_crawl(url):
            await asyncio.sleep(10)

        mock_crawler.crawl_with_metadata = slow_crawl

        assert wrapper._circuit.state == CircuitState.CLOSED

        await wrapper.crawl("https://example.com")

        # With threshold=1, one failure should open the circuit
        assert wrapper._circuit.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_crawl_cancelled_returns_cancelled(self):
        """CancelledError returns cancelled error and does NOT record a failure."""
        wrapper = _make_wrapper(circuit_failure_threshold=1)
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(side_effect=asyncio.CancelledError())

        result = await wrapper.crawl("https://example.com")

        assert result.success is False
        assert result.error_type == "cancelled"
        # Circuit should remain CLOSED -- cancellation is not a fault
        assert wrapper._circuit.state == CircuitState.CLOSED
        assert wrapper._circuit.failure_count == 0

    @pytest.mark.asyncio
    async def test_dns_error(self):
        """DNS resolution errors are classified as dns_error."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            side_effect=Exception("net::ERR_NAME_NOT_RESOLVED at https://bogus.invalid")
        )

        result = await wrapper.crawl("https://bogus.invalid")

        assert result.success is False
        assert result.error_type == "dns_error"

    @pytest.mark.asyncio
    async def test_browser_closed_error_has_been_closed(self):
        """'has been closed' browser errors are classified as browser_closed."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            side_effect=Exception("Browser has been closed unexpectedly")
        )

        result = await wrapper.crawl("https://example.com")

        assert result.success is False
        assert result.error_type == "browser_closed"

    @pytest.mark.asyncio
    async def test_browser_closed_error_target_page(self):
        """'Target page' browser errors are classified as browser_closed."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            side_effect=Exception("Target page, context or browser has been closed")
        )

        result = await wrapper.crawl("https://example.com")

        assert result.success is False
        assert result.error_type == "browser_closed"

    @pytest.mark.asyncio
    async def test_connection_refused_error(self):
        """ERR_CONNECTION_REFUSED is classified as connection_refused."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            side_effect=Exception("net::ERR_CONNECTION_REFUSED")
        )

        result = await wrapper.crawl("https://localhost:9999")

        assert result.success is False
        assert result.error_type == "connection_refused"

    @pytest.mark.asyncio
    async def test_network_error_generic_net(self):
        """Generic net:: errors are classified as network_error."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            side_effect=Exception("net::ERR_CERT_AUTHORITY_INVALID")
        )

        result = await wrapper.crawl("https://self-signed.example.com")

        assert result.success is False
        assert result.error_type == "network_error"

    @pytest.mark.asyncio
    async def test_generic_crawl_error(self):
        """Unclassified exceptions fall through to crawl_error."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            side_effect=RuntimeError("Something completely unexpected")
        )

        result = await wrapper.crawl("https://example.com")

        assert result.success is False
        assert result.error_type == "crawl_error"
        assert "unexpected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_generic_crawl_error_truncates_long_message(self):
        """Long error messages are truncated to 200 characters."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        long_message = "X" * 500
        mock_crawler.crawl_with_metadata = AsyncMock(
            side_effect=RuntimeError(long_message)
        )

        result = await wrapper.crawl("https://example.com")

        assert result.success is False
        assert result.error_type == "crawl_error"
        assert len(result.error) == 200

    @pytest.mark.asyncio
    async def test_successful_crawl(self):
        """Successful crawl returns CrawlResult with markdown and title."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            return_value=CrawlOutput(
                title="Example Page",
                html="<p>Content</p>",
                markdown="# Example Page\n\nContent",
            )
        )

        result = await wrapper.crawl("https://example.com")

        assert result.success is True
        assert result.title == "Example Page"
        assert result.markdown == "# Example Page\n\nContent"
        assert result.error is None
        assert result.error_type is None

    @pytest.mark.asyncio
    async def test_successful_crawl_records_success(self):
        """Successful crawl resets failure count on the circuit breaker."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            return_value=CrawlOutput(title="OK", html="", markdown="Page content here")
        )

        # Simulate some prior failures (not enough to open circuit)
        wrapper._circuit.failure_count = 2

        await wrapper.crawl("https://example.com")

        assert wrapper._circuit.failure_count == 0

    @pytest.mark.asyncio
    async def test_empty_content_returns_failure(self):
        """Empty markdown from backend is treated as a failed crawl."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            return_value=CrawlOutput(title="", html="", markdown="")
        )

        result = await wrapper.crawl("https://example.com")

        assert result.success is False
        assert result.error_type == "empty_content"
        assert "empty content" in result.error.lower()

    @pytest.mark.asyncio
    async def test_empty_content_records_failure(self):
        """Empty content counts as a circuit breaker failure, not success."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            return_value=CrawlOutput(title="", html="", markdown="  ")
        )

        await wrapper.crawl("https://example.com")

        assert wrapper._circuit.failure_count == 1

    @pytest.mark.asyncio
    async def test_queue_count_decremented_on_success(self):
        """Queue count is properly decremented after a successful crawl."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            return_value=CrawlOutput(title="OK", html="", markdown="ok")
        )

        assert wrapper._queue_count == 0
        await wrapper.crawl("https://example.com")
        assert wrapper._queue_count == 0

    @pytest.mark.asyncio
    async def test_queue_count_decremented_on_error(self):
        """Queue count is properly decremented even when crawl fails."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        await wrapper.crawl("https://example.com")
        assert wrapper._queue_count == 0

    @pytest.mark.asyncio
    async def test_semaphore_released_on_error(self):
        """Semaphore slot is released after a crawl error so other requests can proceed."""
        wrapper = _make_wrapper(max_concurrent=1)
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        await wrapper.crawl("https://example.com")

        # If semaphore was not released, a second crawl would block.
        # Test that we can acquire it without timeout.
        acquired = await asyncio.wait_for(
            wrapper._semaphore.acquire(), timeout=0.1
        )
        assert acquired
        wrapper._semaphore.release()

    @pytest.mark.asyncio
    async def test_timeout_override(self):
        """Explicit timeout parameter overrides default_timeout."""
        wrapper = _make_wrapper(default_timeout=30.0)
        mock_crawler = _inject_mock_crawler(wrapper)

        async def slow_crawl(url):
            await asyncio.sleep(10)

        mock_crawler.crawl_with_metadata = slow_crawl

        result = await wrapper.crawl("https://example.com", timeout=0.05)

        assert result.success is False
        assert result.error_type == "timeout"
        # Error message should mention our custom timeout
        assert "0.05" in result.error

    @pytest.mark.asyncio
    async def test_connection_timeout_error(self):
        """ERR_CONNECTION_TIMED_OUT is classified as connection_timeout."""
        wrapper = _make_wrapper()
        mock_crawler = _inject_mock_crawler(wrapper)
        mock_crawler.crawl_with_metadata = AsyncMock(
            side_effect=Exception("net::ERR_CONNECTION_TIMED_OUT")
        )

        result = await wrapper.crawl("https://slow.example.com")

        assert result.success is False
        assert result.error_type == "connection_timeout"


# ---------------------------------------------------------------------------
# Circuit breaker state transitions
# ---------------------------------------------------------------------------


class TestCircuitBreakerTransitions:
    """Tests for CrawlerCircuitBreaker state machine transitions."""

    @pytest.mark.asyncio
    async def test_closed_to_open_after_threshold_failures(self):
        """CLOSED -> OPEN after failure_threshold consecutive failures."""
        cb = CrawlerCircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        assert cb.state == CircuitState.CLOSED

        for _ in range(3):
            await cb.record_failure()

        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

    @pytest.mark.asyncio
    async def test_stays_closed_below_threshold(self):
        """CLOSED stays CLOSED when failures are below threshold."""
        cb = CrawlerCircuitBreaker(failure_threshold=5)

        for _ in range(4):
            await cb.record_failure()

        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_open_to_half_open_after_recovery_timeout(self):
        """OPEN -> HALF_OPEN after recovery_timeout elapses."""
        cb = CrawlerCircuitBreaker(failure_threshold=1, recovery_timeout=0.05)

        await cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Simulate enough time passing
        cb.last_failure_time = time.time() - 1.0

        await cb.check_state()
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.success_count == 0

    @pytest.mark.asyncio
    async def test_open_stays_open_before_recovery_timeout(self):
        """OPEN stays OPEN when recovery_timeout has not elapsed."""
        cb = CrawlerCircuitBreaker(failure_threshold=1, recovery_timeout=60.0)

        await cb.record_failure()
        assert cb.state == CircuitState.OPEN

        await cb.check_state()
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_half_open_to_closed_after_success_threshold(self):
        """HALF_OPEN -> CLOSED after success_threshold successes."""
        cb = CrawlerCircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.05,
            success_threshold=2,
        )

        # Move to HALF_OPEN
        await cb.record_failure()
        cb.last_failure_time = time.time() - 1.0
        await cb.check_state()
        assert cb.state == CircuitState.HALF_OPEN

        # First success: still half-open
        await cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.success_count == 1

        # Second success: close the circuit
        await cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self):
        """HALF_OPEN -> OPEN on any failure (re-opens with backoff)."""
        cb = CrawlerCircuitBreaker(
            failure_threshold=1,
            recovery_timeout=10.0,
            success_threshold=2,
        )

        # Move to HALF_OPEN
        cb.state = CircuitState.OPEN
        cb.last_failure_time = time.time() - 20.0
        await cb.check_state()
        assert cb.state == CircuitState.HALF_OPEN

        # Fail during half-open
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb._consecutive_opens == 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_on_repeated_opens(self):
        """Recovery timeout doubles each time circuit re-opens from HALF_OPEN."""
        base_recovery = 10.0
        cb = CrawlerCircuitBreaker(
            failure_threshold=1,
            recovery_timeout=base_recovery,
            success_threshold=2,
        )

        # First open
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Transition to half-open, then fail again
        cb.last_failure_time = time.time() - base_recovery - 1
        await cb.check_state()
        assert cb.state == CircuitState.HALF_OPEN
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb._consecutive_opens == 1
        assert cb.recovery_timeout == base_recovery * 2  # 20s

        # Another half-open -> failure cycle
        cb.last_failure_time = time.time() - cb.recovery_timeout - 1
        await cb.check_state()
        assert cb.state == CircuitState.HALF_OPEN
        await cb.record_failure()
        assert cb._consecutive_opens == 2
        assert cb.recovery_timeout == base_recovery * 4  # 40s

    @pytest.mark.asyncio
    async def test_recovery_timeout_capped_at_max(self):
        """Recovery timeout is capped at _max_recovery_timeout (900s)."""
        cb = CrawlerCircuitBreaker(
            failure_threshold=1,
            recovery_timeout=500.0,
            success_threshold=2,
        )
        # Simulate many consecutive opens to exceed cap
        cb._consecutive_opens = 10
        cb.state = CircuitState.HALF_OPEN

        await cb.record_failure()

        assert cb.recovery_timeout == 900.0  # capped

    @pytest.mark.asyncio
    async def test_successful_recovery_resets_consecutive_opens(self):
        """Full recovery (HALF_OPEN -> CLOSED) resets consecutive_opens and recovery_timeout."""
        base_recovery = 10.0
        cb = CrawlerCircuitBreaker(
            failure_threshold=1,
            recovery_timeout=base_recovery,
            success_threshold=1,
        )

        # Open, then half-open, then fail (backoff once)
        await cb.record_failure()
        cb.last_failure_time = time.time() - base_recovery - 1
        await cb.check_state()
        await cb.record_failure()
        assert cb._consecutive_opens == 1
        assert cb.recovery_timeout == base_recovery * 2

        # Now recover
        cb.last_failure_time = time.time() - cb.recovery_timeout - 1
        await cb.check_state()
        assert cb.state == CircuitState.HALF_OPEN
        await cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb._consecutive_opens == 0
        assert cb.recovery_timeout == base_recovery

    @pytest.mark.asyncio
    async def test_success_in_closed_state_resets_failures(self):
        """record_success in CLOSED state resets failure_count."""
        cb = CrawlerCircuitBreaker(failure_threshold=5)

        cb.failure_count = 3
        await cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_record_failure_triggers_reset_callback(self):
        """When circuit opens, the trigger_reset callback is invoked."""
        cb = CrawlerCircuitBreaker(failure_threshold=1)
        reset_called = asyncio.Event()

        async def mock_reset():
            reset_called.set()

        await cb.record_failure(trigger_reset=mock_reset)
        assert cb.state == CircuitState.OPEN

        # Allow the background task to run
        await asyncio.sleep(0.01)
        assert reset_called.is_set()

    @pytest.mark.asyncio
    async def test_record_failure_no_callback_when_not_opening(self):
        """trigger_reset is NOT invoked when circuit does not transition to OPEN."""
        cb = CrawlerCircuitBreaker(failure_threshold=5)
        mock_reset = AsyncMock()

        await cb.record_failure(trigger_reset=mock_reset)
        assert cb.state == CircuitState.CLOSED
        mock_reset.assert_not_awaited()


# ---------------------------------------------------------------------------
# _build_configured_wrapper()
# ---------------------------------------------------------------------------


class TestBuildConfiguredWrapper:
    """Tests for _build_configured_wrapper factory function."""

    def test_happy_path_with_mock_config(self):
        """Builds wrapper with values from tool_settings helpers."""
        with patch(
            "src.config.tool_settings.get_crawler_max_concurrent",
            return_value=8,
        ), patch(
            "src.config.tool_settings.get_crawler_page_timeout",
            return_value=30000,  # ms
        ), patch(
            "src.config.tool_settings.get_crawler_queue_max_size",
            return_value=50,
        ), patch(
            "src.config.tool_settings.get_crawler_queue_slot_timeout",
            return_value=5.0,
        ), patch(
            "src.config.tool_settings.get_crawler_circuit_failure_threshold",
            return_value=4,
        ), patch(
            "src.config.tool_settings.get_crawler_circuit_recovery_timeout",
            return_value=120.0,
        ), patch(
            "src.config.tool_settings.get_crawler_circuit_success_threshold",
            return_value=3,
        ), patch(
            "src.config.tool_settings.get_crawler_backend",
            return_value="scrapling",
        ):
            wrapper = _build_configured_wrapper()

        assert wrapper._max_queue == 50
        assert wrapper._default_timeout == 30.0  # 30000ms -> 30s
        assert wrapper._slot_timeout == 5.0
        assert wrapper._circuit.failure_threshold == 4
        assert wrapper._circuit.recovery_timeout == 120.0
        assert wrapper._circuit.success_threshold == 3
        assert wrapper._backend == "scrapling"

    def test_fallback_on_import_error(self):
        """When config imports fail, returns wrapper with defaults."""
        with patch(
            "src.tools.crawler.safe_wrapper._build_configured_wrapper",
        ) as mock_build:
            # Test the real function, not the mock -- we want to trigger the except branch
            pass

        # Directly test: make the import inside _build_configured_wrapper raise
        with patch.dict(
            "sys.modules",
            {"src.config.tool_settings": None},
        ):
            wrapper = _build_configured_wrapper()

        # Should be the default values
        assert wrapper._max_queue == 100
        assert wrapper._default_timeout == 60.0
        assert wrapper._slot_timeout == 10.0
        assert wrapper._circuit.failure_threshold == 5
        assert wrapper._circuit.recovery_timeout == 60.0
        assert wrapper._circuit.success_threshold == 2
        assert wrapper._backend == "scrapling"

    def test_fallback_on_generic_exception(self):
        """When a config getter raises, returns wrapper with defaults."""
        with patch(
            "src.config.tool_settings.get_crawler_max_concurrent",
            side_effect=RuntimeError("config broken"),
        ):
            wrapper = _build_configured_wrapper()

        assert wrapper._max_queue == 100
        assert wrapper._default_timeout == 60.0
        assert wrapper._backend == "scrapling"


# ---------------------------------------------------------------------------
# get_status / is_healthy
# ---------------------------------------------------------------------------


class TestWrapperStatus:
    """Tests for get_status() and is_healthy() helper methods."""

    def test_get_status_initial(self):
        wrapper = _make_wrapper()
        status = wrapper.get_status()

        assert status["circuit_state"] == "closed"
        assert status["failure_count"] == 0
        assert status["success_count"] == 0
        assert status["consecutive_opens"] == 0
        assert status["queue_count"] == 0
        assert status["max_queue"] == 10
        assert status["last_failure_time"] is None

    def test_is_healthy_when_closed(self):
        wrapper = _make_wrapper()
        assert wrapper.is_healthy() is True

    def test_is_healthy_when_open(self):
        wrapper = _make_wrapper()
        wrapper._circuit.state = CircuitState.OPEN
        assert wrapper.is_healthy() is False

    def test_is_healthy_when_half_open(self):
        wrapper = _make_wrapper()
        wrapper._circuit.state = CircuitState.HALF_OPEN
        assert wrapper.is_healthy() is True
