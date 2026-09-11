import asyncio
import datetime as dt
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.rate_limiter import AsyncRateLimiter, RateLimitExceededError, get_rate_limiter


class TestRateLimiter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.limiter = AsyncRateLimiter()

    def test_extract_host(self):
        self.assertEqual(self.limiter.extract_host("http://prowlarr.local:9696/1/api?t=search"), "prowlarr.local:9696/1")
        self.assertEqual(self.limiter.extract_host("http://prowlarr.local:9696/2/api"), "prowlarr.local:9696/2")
        self.assertEqual(self.limiter.extract_host("http://jackett:9117/api/v2.0/indexers/rutracker/results/torznab/api"), "jackett:9117/api/v2.0/indexers/rutracker")
        self.assertEqual(self.limiter.extract_host("https://nyaa.si/?page=rss"), "nyaa.si")
        self.assertEqual(self.limiter.extract_host("TRACKER_CUSTOM"), "tracker_custom")

    def test_parse_retry_after_seconds(self):
        self.assertEqual(self.limiter.parse_retry_after("60"), 60.0)
        self.assertEqual(self.limiter.parse_retry_after("12.5"), 12.5)
        self.assertEqual(self.limiter.parse_retry_after("0"), 1.0)  # min 1.0s
        self.assertIsNone(self.limiter.parse_retry_after(None))
        self.assertIsNone(self.limiter.parse_retry_after(""))
        self.assertIsNone(self.limiter.parse_retry_after("invalid"))

    def test_parse_retry_after_http_date(self):
        future_date = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=120)
        http_date_str = future_date.strftime("%a, %d %b %Y %H:%M:%S GMT")
        parsed = self.limiter.parse_retry_after(http_date_str)
        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed, 120.0, delta=5.0)

    async def test_acquire_pacing_same_host(self):
        host = "http://indexer.test/api"
        # First acquire should be immediate
        t0 = time.monotonic()
        await self.limiter.acquire(host, min_interval_seconds=0.1)
        t1 = time.monotonic()
        self.assertLess(t1 - t0, 0.05)

        # Second acquire to same host must be delayed by ~0.1s
        await self.limiter.acquire(host, min_interval_seconds=0.1)
        t2 = time.monotonic()
        self.assertGreaterEqual(t2 - t1, 0.08)

    async def test_acquire_independent_hosts(self):
        host_a = "http://indexer-a.test/api"
        host_b = "http://indexer-b.test/api"

        t0 = time.monotonic()
        # Acquire host A and host B concurrently
        await asyncio.gather(
            self.limiter.acquire(host_a, min_interval_seconds=0.2),
            self.limiter.acquire(host_b, min_interval_seconds=0.2),
        )
        t1 = time.monotonic()
        # Different hosts should not block each other
        self.assertLess(t1 - t0, 0.1)

    def test_escalation_backoff_ladder(self):
        host = "http://tracker.test/api"

        # Level 1: 60s
        b1 = self.limiter.record_429(host)
        self.assertEqual(b1, 60.0)
        blocked, remaining = self.limiter.is_blocked(host)
        self.assertTrue(blocked)
        self.assertAlmostEqual(remaining, 60.0, delta=2.0)

        # Level 2: 300s (5 min)
        b2 = self.limiter.record_429(host)
        self.assertEqual(b2, 300.0)

        # Level 3: 900s (15 min)
        b3 = self.limiter.record_429(host)
        self.assertEqual(b3, 900.0)

        # Custom explicit Retry-After overrides ladder duration
        b_custom = self.limiter.record_429(host, retry_after=45.0)
        self.assertEqual(b_custom, 45.0)

    async def test_acquire_raises_when_blocked(self):
        host = "http://blocked.test/api"
        self.limiter.record_429(host, retry_after=30.0)

        with self.assertRaises(RateLimitExceededError) as ctx:
            await self.limiter.acquire(host)

        self.assertEqual(ctx.exception.host, "blocked.test")
        self.assertGreater(ctx.exception.retry_after, 0)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_record_success_resets_escalation_and_block(self):
        host = "http://deescalate.test/api"
        self.limiter.record_429(host)
        self.limiter.record_429(host)
        self.assertEqual(self.limiter._escalation_levels.get("deescalate.test"), 2)
        blocked, _ = self.limiter.is_blocked(host)
        self.assertTrue(blocked)

        self.limiter.record_success(host)
        self.assertEqual(self.limiter._escalation_levels.get("deescalate.test", 0), 0)
        blocked, _ = self.limiter.is_blocked(host)
        self.assertFalse(blocked)

    def test_max_backoff_cap_at_30_minutes(self):
        host = "http://large-retry.test/api"
        # 21 hours (75896s) from remote server must be capped at 1800s (30 min)
        b = self.limiter.record_429(host, retry_after=75896.0)
        self.assertEqual(b, 1800.0)

    async def test_probe_bypasses_block_and_unblocks_on_success(self):
        host = "http://probe-test.test/api"
        self.limiter.record_429(host, retry_after=1800.0)
        blocked, remaining = self.limiter.is_blocked(host)
        self.assertTrue(blocked)

        # Standard acquire must fail with RateLimitExceededError
        with self.assertRaises(RateLimitExceededError):
            await self.limiter.acquire(host, min_interval_seconds=0.0, is_probe=False)

        # Health Check probe with is_probe=True must succeed through acquire
        await self.limiter.acquire(host, min_interval_seconds=0.0, is_probe=True)

        # On successful response from probe, record_success unblocks host
        self.limiter.record_success(host)
        blocked_after, _ = self.limiter.is_blocked(host)
        self.assertFalse(blocked_after)


class TestIndexerRateLimitingIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        get_rate_limiter().reset()

    def tearDown(self):
        get_rate_limiter().reset()

    async def test_torznab_client_429_triggers_rate_limit_error(self):
        from app.services.indexer_service import TorznabIndexerClient

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {"Retry-After": "15"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.indexer_service.httpx", mock_httpx):
            client = TorznabIndexerClient(base_url="http://test-indexer.com", api_key="secret", rate_limit_seconds=0.0)

            with self.assertRaises(RateLimitExceededError) as ctx:
                await client.search("Naruto")

            self.assertEqual(ctx.exception.host, "test-indexer.com")
            self.assertEqual(ctx.exception.retry_after, 15.0)

            # Subsequent search should immediately fail with RateLimitExceededError without making HTTP call
            mock_client.get.reset_mock()
            with self.assertRaises(RateLimitExceededError):
                await client.search("Bleach")
            mock_client.get.assert_not_called()

    async def test_download_torrent_429_short_retry(self):
        from app.services.download_client import _fetch_torrent_content_if_url

        # 1st call returns 429 with Retry-After: 0.1
        # 2nd call returns 200 with torrent bytes
        resp_429 = MagicMock(status_code=429, headers={"Retry-After": "0.1"})
        resp_200 = MagicMock(status_code=200, headers={}, content=b"d8:announce3:url4:infod4:name4:testee")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[resp_429, resp_200])
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.download_client.httpx", mock_httpx):
            content, url = await _fetch_torrent_content_if_url("http://tracker.org/download.torrent")
            self.assertEqual(content, b"d8:announce3:url4:infod4:name4:testee")
            self.assertEqual(url, "http://tracker.org/download.torrent")
            self.assertEqual(mock_client.get.call_count, 2)

    async def test_download_torrent_429_fallback_to_url(self):
        from app.services.download_client import _fetch_torrent_content_if_url

        # Returns 429 with long Retry-After: 60s -> should fallback to passing URL directly
        resp_429 = MagicMock(status_code=429, headers={"Retry-After": "60"})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp_429)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.download_client.httpx", mock_httpx):
            content, url = await _fetch_torrent_content_if_url("http://tracker.org/download.torrent")
            self.assertIsNone(content)
            self.assertEqual(url, "http://tracker.org/download.torrent")

    async def test_auto_search_fetch_indexer_term_handles_429(self):
        from app.services.auto_search import _collect_candidates

        indexer = MagicMock(
            id=1,
            name="TestTorznab",
            type="torznab",
            base_url="http://indexer-429.test",
            api_key="123",
            enabled=True,
            priority=1,
            timeout_seconds=10,
        )

        mock_resp = MagicMock(status_code=429, headers={"Retry-After": "30"})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        mock_show = MagicMock(id=1, content_type="series", year=2024, quality_profile_id=None)
        mock_db = MagicMock()
        mock_db.get.return_value = None
        mock_db.query.return_value.filter.return_value.all.return_value = []

        with patch("app.services.indexer_service.httpx", mock_httpx), \
             patch("app.services.auto_search.build_alias_candidates", return_value=[]):
            candidates = await _collect_candidates(
                mock_db,
                mock_show,
                indexers=[indexer],
                wanted_episodes=[],
            )
            # Should handle 429 gracefully and return empty list without crashing
            self.assertEqual(len(candidates), 0)


if __name__ == "__main__":
    unittest.main()
