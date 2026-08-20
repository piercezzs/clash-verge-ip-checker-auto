from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from curl_cffi import CurlOpt
from curl_cffi.const import CurlIpResolve

from core.sources.ippure import (
    IPPURE_INFO_URL,
    IPPureSource,
    SCORE_AVAILABLE,
    SCORE_IP_MISMATCH,
    SCORE_IPV6_UNSUPPORTED,
    SCORE_UNAVAILABLE,
    parse_ippure_payload,
)


class IPPurePayloadTests(unittest.TestCase):
    def test_matching_ipv4_returns_score_and_classifications(self) -> None:
        result = parse_ippure_payload(
            {
                "ip": "103.152.113.67",
                "fraudScore": 61,
                "isResidential": False,
                "isBroadcast": False,
            },
            expected_ip="103.152.113.67",
        )

        self.assertEqual(result["score_status"], SCORE_AVAILABLE)
        self.assertEqual(result["pure_score"], "61%")
        self.assertEqual(result["ip_attr"], "机房")
        self.assertEqual(result["ip_src"], "原生")

    def test_ipv6_without_score_is_explicitly_unscored(self) -> None:
        result = parse_ippure_payload(
            {
                "ip": "2602:feda:30:ae86:295:dff:fe84:68f4",
                "isResidential": False,
                "isBroadcast": False,
            },
            expected_ip="103.152.113.67",
        )

        self.assertEqual(result["score_status"], SCORE_IPV6_UNSUPPORTED)
        self.assertEqual(result["pure_score"], "IPv6无评分")
        self.assertIn("IPv6无评分", result["full_string"])

    def test_mismatched_ipv4_score_is_not_applied_to_expected_ip(self) -> None:
        result = parse_ippure_payload(
            {"ip": "198.51.100.20", "fraudScore": 5},
            expected_ip="203.0.113.8",
        )

        self.assertEqual(result["score_status"], SCORE_IP_MISMATCH)
        self.assertEqual(result["pure_score"], "出口不一致")

    def test_missing_boolean_fields_remain_unknown(self) -> None:
        result = parse_ippure_payload(
            {"ip": "203.0.113.8"},
            expected_ip="203.0.113.8",
        )

        self.assertEqual(result["score_status"], SCORE_UNAVAILABLE)
        self.assertEqual(result["ip_attr"], "❓")
        self.assertEqual(result["ip_src"], "❓")


class IPPureTransportTests(unittest.TestCase):
    @patch("core.sources.ippure.Session")
    def test_transport_forces_ipv4_and_uses_supplied_socks_proxy(self, session_type) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "ip": "203.0.113.8",
            "fraudScore": 12,
            "isResidential": False,
            "isBroadcast": False,
        }
        session = session_type.return_value.__enter__.return_value
        session.get.return_value = response

        result = IPPureSource()._check_sync(
            "socks5://127.0.0.1:7890",
            expected_ip="203.0.113.8",
        )

        session_type.assert_called_once_with(
            proxies={
                "http": "socks5://127.0.0.1:7890",
                "https": "socks5://127.0.0.1:7890",
            },
            impersonate="chrome110",
            timeout=5,
            curl_options={CurlOpt.IPRESOLVE: CurlIpResolve.V4},
        )
        session.get.assert_called_once_with(IPPURE_INFO_URL)
        self.assertEqual(result["score_status"], SCORE_AVAILABLE)


if __name__ == "__main__":
    unittest.main()
