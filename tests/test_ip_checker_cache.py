from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from core.ip_checker import IPChecker, SIMPLE_IP_URLS
from storage.ip_cache import IPCacheSnapshot, build_cache_entry


def provider_result() -> dict[str, object]:
    return {
        "ip": "203.0.113.8",
        "source": "ippure",
        "pure_score": "12%",
        "shared_users": "N/A",
        "ip_attr": "机房",
        "ip_src": "原生",
        "full_string": "【🟢 机房|原生】",
    }


class IPCheckerCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_https_endpoints_are_used(self) -> None:
        self.assertEqual(
            SIMPLE_IP_URLS,
            ("https://api.ipify.org", "https://4.ident.me"),
        )

    async def test_persistent_cache_hit_skips_ippure(self) -> None:
        checker = IPChecker()
        built = build_cache_entry(provider_result(), mode="fast")
        self.assertIsNotNone(built)
        key, entry = built or ("", {})
        checker.configure_cache(IPCacheSnapshot(entries={key: entry}))
        checker.get_simple_ip = AsyncMock(return_value="203.0.113.8")
        checker.ippure.check = AsyncMock(return_value=provider_result())

        result = await checker.check_fast(proxy="http://127.0.0.1:7890")

        self.assertTrue(result["cache_hit"])
        self.assertEqual(result["cache_scope"], "shared")
        checker.ippure.check.assert_not_awaited()

    async def test_force_refresh_queries_once_per_ip_in_same_task(self) -> None:
        checker = IPChecker()
        built = build_cache_entry(provider_result(), mode="fast")
        self.assertIsNotNone(built)
        key, entry = built or ("", {})
        checker.configure_cache(IPCacheSnapshot(entries={key: entry}))
        checker.get_simple_ip = AsyncMock(return_value="203.0.113.8")
        checker.ippure.check = AsyncMock(return_value=provider_result())

        first = await checker.check_fast(force_refresh=True)
        second = await checker.check_fast(force_refresh=True)

        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(second["cache_scope"], "task")
        checker.ippure.check.assert_awaited_once()

    async def test_fresh_lookup_uses_ipv4_proxy_and_expected_ip(self) -> None:
        checker = IPChecker()
        checker.configure_cache(IPCacheSnapshot(entries={}))
        checker.get_simple_ip = AsyncMock(return_value="203.0.113.8")
        checker.ippure.check = AsyncMock(return_value=provider_result())

        result = await checker.check_fast(
            proxy="http://127.0.0.1:7890",
            ipv4_proxy="socks5://127.0.0.1:7890",
        )

        self.assertEqual(result["ip"], "203.0.113.8")
        checker.ippure.check.assert_awaited_once_with(
            "socks5://127.0.0.1:7890",
            expected_ip="203.0.113.8",
        )

    async def test_unscored_ipv6_result_is_not_cached(self) -> None:
        checker = IPChecker()
        checker.configure_cache(IPCacheSnapshot(entries={}))
        checker.get_simple_ip = AsyncMock(return_value="203.0.113.8")
        checker.ippure.check = AsyncMock(
            return_value={
                "ip": "2001:db8::8",
                "source": "ippure",
                "pure_score": "IPv6无评分",
                "score_status": "ipv6_unsupported",
                "ip_attr": "机房",
                "ip_src": "原生",
                "full_string": "【⚠️ IPv6无评分 机房|原生】",
            }
        )

        result = await checker.check_fast(
            proxy="http://127.0.0.1:7890",
            ipv4_proxy="socks5://127.0.0.1:7890",
        )

        self.assertEqual(result["score_status"], "ipv6_unsupported")
        self.assertEqual(checker.cache_entries(), {})


if __name__ == "__main__":
    unittest.main()
