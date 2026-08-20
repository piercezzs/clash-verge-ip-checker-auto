from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storage.ip_cache import build_cache_entry
from storage.results_store import get_recent_profile_ip_results, node_key, save_node_result


class ResultsStoreTests(unittest.TestCase):
    def test_recent_profile_view_uses_global_ip_result_and_large_batches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "results.sqlite3"
            proxies = [
                {"name": f"Node {index}", "server": f"node-{index}.example", "port": 443}
                for index in range(1001)
            ]
            node_result = {
                "id": 0,
                "original_name": "Node 0",
                "name": "Node 0【old】",
                "ip": "203.0.113.8",
                "risk": "70%",
                "bot": "N/A",
                "shared": "N/A",
                "type": "机房",
                "native": "原生",
                "source": "ippure",
                "status": "✅ IPPure",
            }
            built = build_cache_entry(
                {
                    "ip": "203.0.113.8",
                    "source": "ippure",
                    "pure_score": "12%",
                    "shared_users": "N/A",
                    "ip_attr": "机房",
                    "ip_src": "原生",
                    "full_string": "【🟢 机房|原生】",
                },
                mode="fast",
            )
            self.assertIsNotNone(built)
            cache_key_value, cache_entry = built or ("", {})

            with patch("storage.results_store.DB_PATH", db_path):
                save_node_result("profile-1", "Profile", proxies[0], node_result)
                checked_at, results = get_recent_profile_ip_results(
                    "profile-1",
                    proxies,
                    {cache_key_value: cache_entry},
                    mode="fast",
                )

            cached = results[node_key(proxies[0])]
            self.assertTrue(checked_at)
            self.assertEqual(cached["risk"], "12%")
            self.assertEqual(cached["status"], "♻️ IP缓存")
            self.assertEqual(cached["name"], "Node 0【🟢 机房|原生】")


if __name__ == "__main__":
    unittest.main()
