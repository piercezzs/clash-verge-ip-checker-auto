from __future__ import annotations

import unittest

from routers.api import _status_from_result


class ResultStatusTests(unittest.TestCase):
    def test_valid_score_is_complete_ippure_success(self) -> None:
        self.assertEqual(
            _status_from_result(
                {
                    "source": "ippure",
                    "score_status": "available",
                    "pure_score": "12%",
                }
            ),
            "✅ IPPure",
        )

    def test_ipv6_without_score_is_partial(self) -> None:
        self.assertEqual(
            _status_from_result(
                {
                    "source": "ippure",
                    "score_status": "ipv6_unsupported",
                    "pure_score": "IPv6无评分",
                }
            ),
            "⚠️ IPv6无评分",
        )

    def test_mismatched_exit_is_partial(self) -> None:
        self.assertEqual(
            _status_from_result(
                {
                    "source": "ippure",
                    "score_status": "ip_mismatch",
                    "pure_score": "出口不一致",
                }
            ),
            "⚠️ 出口不一致",
        )

    def test_legacy_unknown_score_is_not_reported_as_success(self) -> None:
        self.assertEqual(
            _status_from_result({"source": "ippure", "pure_score": "❓"}),
            "⚠️ IPPure无评分",
        )


if __name__ == "__main__":
    unittest.main()
