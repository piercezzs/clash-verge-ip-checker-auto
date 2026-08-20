from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from storage.ip_cache import (
    CACHE_SCHEMA_VERSION,
    IPCacheSnapshot,
    build_cache_entry,
    cache_key,
    get_fresh_result,
    load_shared_ip_cache,
    load_sqlite_ip_cache,
    merge_entries,
    save_shared_ip_cache,
    utc_now_text,
)


def provider_result(ip: str = "203.0.113.8", score: str = "12%") -> dict[str, object]:
    return {
        "ip": ip,
        "source": "ippure",
        "pure_score": score,
        "shared_users": "N/A",
        "ip_attr": "机房",
        "ip_src": "原生",
        "full_string": "【🟢 机房|原生】",
    }


class IPCacheTests(unittest.TestCase):
    def test_fourteen_day_boundary_is_reusable(self) -> None:
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        built = build_cache_entry(
            provider_result(),
            mode="fast",
            checked_at=utc_now_text(now - timedelta(days=14)),
        )
        self.assertIsNotNone(built)
        key, entry = built or ("", {})

        fresh = get_fresh_result({key: entry}, "203.0.113.8", now=now)
        self.assertIsNotNone(fresh)

    def test_result_older_than_fourteen_days_is_not_reused(self) -> None:
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        built = build_cache_entry(
            provider_result(),
            mode="fast",
            checked_at=utc_now_text(now - timedelta(days=14, seconds=1)),
        )
        self.assertIsNotNone(built)
        key, entry = built or ("", {})

        self.assertIsNone(get_fresh_result({key: entry}, "203.0.113.8", now=now))

    def test_failed_or_invalid_result_is_not_cacheable(self) -> None:
        self.assertIsNone(
            build_cache_entry(
                {"ip": "❓", "source": "failed", "pure_score": "❓"},
                mode="fast",
            )
        )

    def test_shared_json_round_trip_and_malformed_preservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ip_reputation_cache.json"
            built = build_cache_entry(provider_result(), mode="fast")
            self.assertIsNotNone(built)
            key, entry = built or ("", {})
            save_shared_ip_cache({key: entry}, path=path)

            loaded = load_shared_ip_cache(path)
            self.assertTrue(loaded.writable)
            self.assertEqual(loaded.entries[key]["pure_score"], "12%")

            path.write_text("<<<<<<< ours\n=======\n>>>>>>> theirs\n", encoding="utf-8")
            malformed = load_shared_ip_cache(path)
            self.assertFalse(malformed.writable)
            self.assertIn("不会覆盖", malformed.warning)

    def test_invalid_entry_keeps_valid_entries_but_makes_file_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ip_reputation_cache.json"
            built = build_cache_entry(provider_result(), mode="fast")
            self.assertIsNotNone(built)
            key, entry = built or ("", {})
            path.write_text(
                json.dumps(
                    {
                        "schema_version": CACHE_SCHEMA_VERSION,
                        "ttl_days": 14,
                        "results": {
                            key: entry,
                            "broken": {"ip": "not-an-ip"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_shared_ip_cache(path)

            self.assertFalse(loaded.writable)
            self.assertEqual(list(loaded.entries), [key])
            self.assertIn("1 条无效记录", loaded.warning)

    def test_merge_keeps_newest_entry(self) -> None:
        older = build_cache_entry(
            provider_result(score="12%"),
            mode="fast",
            checked_at="2026-08-19T10:00:00Z",
        )
        newer = build_cache_entry(
            provider_result(score="18%"),
            mode="fast",
            checked_at="2026-08-20T10:00:00Z",
        )
        self.assertIsNotNone(older)
        self.assertIsNotNone(newer)
        old_key, old_entry = older or ("", {})
        new_key, new_entry = newer or ("", {})

        merged = merge_entries({old_key: old_entry}, {new_key: new_entry})
        self.assertEqual(merged[old_key]["pure_score"], "18%")

    def test_sqlite_migration_excludes_node_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "results.sqlite3"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    create table node_results (
                        profile_uid text,
                        profile_name text,
                        node_key text,
                        checked_date text,
                        checked_at text,
                        result_json text
                    )
                    """
                )
                node_result = {
                    "ip": "203.0.113.8",
                    "risk": "12%",
                    "shared": "N/A",
                    "bot": "N/A",
                    "type": "机房",
                    "native": "原生",
                    "source": "ippure",
                    "original_name": "secret node name",
                    "name": "secret node name【🟢 机房|原生】",
                    "cached_at": "2026-08-20T10:00:00Z",
                }
                conn.execute(
                    "insert into node_results values (?, ?, ?, ?, ?, ?)",
                    (
                        "profile-secret",
                        "private subscription",
                        "node-key",
                        "2026-08-20",
                        "2026-08-20T10:00:00Z",
                        json.dumps(node_result, ensure_ascii=False),
                    ),
                )

            entries = load_sqlite_ip_cache(db_path)
            entry = entries[cache_key("203.0.113.8")]
            serialized = json.dumps(entry, ensure_ascii=False)
            self.assertNotIn("secret node name", serialized)
            self.assertNotIn("private subscription", serialized)
            self.assertEqual(entry["full_string"], "【🟢 机房|原生】")


if __name__ == "__main__":
    unittest.main()
