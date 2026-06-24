"""Tests for the Redis-backed worker progress & cancellation registries (ARCH-2/ARCH-3).

These exercise the registries against an in-memory ``fakeredis`` injected through
``redis_client.set_client`` — no live Redis required. ``decode_responses=True``
matches production so the string→int/float coercion in ``progress.get`` is tested
on the same code path. The suite is skipped cleanly if ``fakeredis`` isn't
installed (see ``apps/worker/requirements-dev.txt``).
"""

import unittest

import pytest

fakeredis = pytest.importorskip("fakeredis")

from app.services import redis_client
from app.services.cancellation import registry as cancel_registry
from app.services.progress import registry as progress_registry


class _RaisingRedis:
    """Stand-in whose every command raises, to drive the fail-soft branches."""

    def __getattr__(self, name):
        def _boom(*args, **kwargs):
            raise ConnectionError("redis is down")

        return _boom


class ProgressRegistryTest(unittest.TestCase):
    def setUp(self):
        self.fake = fakeredis.FakeRedis(decode_responses=True)
        redis_client.set_client(self.fake)

    def tearDown(self):
        redis_client.set_client(None)

    def test_update_then_get_roundtrip_with_coercion(self):
        progress_registry.update("job1", 25, 100)
        snap = progress_registry.get("job1")
        self.assertEqual(snap["processed"], 25)
        self.assertEqual(snap["total"], 100)
        # Coerced back to numbers, not the raw strings Redis stores.
        self.assertIsInstance(snap["processed"], int)
        self.assertIsInstance(snap["total"], int)
        self.assertIsInstance(snap["updated_at"], float)
        self.assertGreater(snap["updated_at"], 0)

    def test_get_missing_returns_none(self):
        self.assertIsNone(progress_registry.get("does-not-exist"))

    def test_update_sets_and_bounds_ttl(self):
        progress_registry.update("job1", 1, 10)
        ttl = self.fake.ttl(redis_client.progress_key("job1"))
        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, redis_client.TTL_SECONDS)

    def test_latest_update_wins(self):
        progress_registry.update("job1", 10, 100)
        progress_registry.update("job1", 60, 100)
        self.assertEqual(progress_registry.get("job1")["processed"], 60)

    def test_clear_removes_snapshot(self):
        progress_registry.update("job1", 1, 10)
        progress_registry.clear("job1")
        self.assertIsNone(progress_registry.get("job1"))
        self.assertEqual(self.fake.exists(redis_client.progress_key("job1")), 0)

    def test_malformed_hash_treated_as_missing(self):
        # A partially-written hash (no total/updated_at) must not blow up get().
        self.fake.hset(redis_client.progress_key("job1"), mapping={"processed": "5"})
        self.assertIsNone(progress_registry.get("job1"))

    def test_get_failsoft_on_redis_error(self):
        redis_client.set_client(_RaisingRedis())
        self.assertIsNone(progress_registry.get("job1"))

    def test_update_and_clear_failsoft_on_redis_error(self):
        redis_client.set_client(_RaisingRedis())
        # Neither should raise — progress is best-effort.
        progress_registry.update("job1", 1, 2)
        progress_registry.clear("job1")


class CancellationRegistryTest(unittest.TestCase):
    def setUp(self):
        self.fake = fakeredis.FakeRedis(decode_responses=True)
        redis_client.set_client(self.fake)

    def tearDown(self):
        redis_client.set_client(None)

    def test_not_cancelled_by_default(self):
        self.assertFalse(cancel_registry.is_cancelled("job1"))

    def test_cancel_then_is_cancelled(self):
        cancel_registry.cancel("job1")
        self.assertTrue(cancel_registry.is_cancelled("job1"))

    def test_clear_resets_cancellation(self):
        cancel_registry.cancel("job1")
        cancel_registry.clear("job1")
        self.assertFalse(cancel_registry.is_cancelled("job1"))

    def test_cancel_is_scoped_to_job(self):
        cancel_registry.cancel("job1")
        self.assertFalse(cancel_registry.is_cancelled("job2"))

    def test_cancel_sets_and_bounds_ttl(self):
        cancel_registry.cancel("job1")
        ttl = self.fake.ttl(redis_client.cancel_key("job1"))
        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, redis_client.TTL_SECONDS)

    def test_is_cancelled_failsoft_returns_false(self):
        # A Redis outage must never abort a valid conversion.
        redis_client.set_client(_RaisingRedis())
        self.assertFalse(cancel_registry.is_cancelled("job1"))

    def test_cancel_and_clear_failsoft_on_redis_error(self):
        redis_client.set_client(_RaisingRedis())
        cancel_registry.cancel("job1")  # should not raise
        cancel_registry.clear("job1")  # should not raise


if __name__ == "__main__":
    unittest.main()
