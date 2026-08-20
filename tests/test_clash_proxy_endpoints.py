from __future__ import annotations

import unittest

from core.clash_api import proxy_endpoints_from_configs


class ClashProxyEndpointTests(unittest.TestCase):
    def test_mixed_port_uses_http_for_preflight_and_socks5_for_ipv4_lookup(self) -> None:
        endpoints = proxy_endpoints_from_configs({"mixed-port": 7890})

        self.assertEqual(endpoints.request_url, "http://127.0.0.1:7890")
        self.assertEqual(endpoints.ipv4_lookup_url, "socks5://127.0.0.1:7890")
        self.assertTrue(endpoints.ipv4_lookup_forced)

    def test_http_only_port_keeps_http_and_marks_force_unavailable(self) -> None:
        endpoints = proxy_endpoints_from_configs({"mixed-port": 0, "port": "7891"})

        self.assertEqual(endpoints.request_url, "http://127.0.0.1:7891")
        self.assertEqual(endpoints.ipv4_lookup_url, endpoints.request_url)
        self.assertFalse(endpoints.ipv4_lookup_forced)

    def test_invalid_ports_use_default_mixed_port_assumption(self) -> None:
        endpoints = proxy_endpoints_from_configs({"mixed-port": "invalid"})

        self.assertEqual(endpoints.request_url, "http://127.0.0.1:7897")
        self.assertEqual(endpoints.ipv4_lookup_url, "socks5://127.0.0.1:7897")


if __name__ == "__main__":
    unittest.main()
