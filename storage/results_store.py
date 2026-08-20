from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

from .ip_cache import get_fresh_result, utc_now_text

DB_PATH = Path("data") / "results.sqlite3"


def node_key(proxy: dict[str, object]) -> str:
    payload = json.dumps(proxy, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_recent_profile_ip_results(
    profile_uid: str,
    proxies: list[dict[str, object]],
    ip_entries: dict[str, dict[str, object]],
    mode: str,
) -> tuple[str, dict[str, dict[str, object]]]:
    keys = [node_key(proxy) for proxy in proxies]
    if not keys:
        return "", {}

    _ensure_schema()
    rows: list[tuple[str, str]] = []
    with sqlite3.connect(DB_PATH) as conn:
        for key_batch in _batches(keys, size=500):
            placeholders = ",".join("?" for _ in key_batch)
            params = [profile_uid, *key_batch]
            sql = (
                "select node_key, result_json from node_results "
                f"where profile_uid = ? and node_key in ({placeholders}) "
                "order by checked_at desc"
            )
            rows.extend(conn.execute(sql, params).fetchall())

    proxies_by_key = {node_key(proxy): proxy for proxy in proxies}
    cached_results: dict[str, dict[str, object]] = {}
    latest_checked_at = ""
    for key, result_json in rows:
        if key in cached_results:
            continue
        try:
            node_result = json.loads(result_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(node_result, dict):
            continue

        ip = str(node_result.get("ip") or "").strip()
        ip_result = get_fresh_result(ip_entries, ip=ip, mode=mode)
        if ip_result is None:
            continue

        proxy = proxies_by_key.get(key, {})
        original_name = str(proxy.get("name") or node_result.get("original_name") or "")
        cached_at = str(ip_result.get("cached_at") or "")
        cached_results[key] = {
            **node_result,
            "name": f"{original_name}{ip_result.get('full_string', '')}",
            "original_name": original_name,
            "ip": ip_result.get("ip", ip),
            "risk": ip_result.get("pure_score", "❓"),
            "bot": ip_result.get("bot_score", "N/A"),
            "shared": ip_result.get("shared_users", "N/A"),
            "type": ip_result.get("ip_attr", "❓"),
            "native": ip_result.get("ip_src", "❓"),
            "source": ip_result.get("source", "ippure"),
            "status": "♻️ IP缓存",
            "cache_hit": True,
            "cached_at": cached_at,
        }
        latest_checked_at = max(latest_checked_at, cached_at)

    return latest_checked_at, cached_results


def _batches(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def save_node_result(
    profile_uid: str,
    profile_name: str,
    proxy: dict[str, object],
    node_data: dict[str, object],
) -> None:
    _ensure_schema()
    key = node_key(proxy)
    result = {
        field: value
        for field, value in node_data.items()
        if field not in {"proxy_config"}
    }
    result["cached_at"] = utc_now_text()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            insert into node_results
                (profile_uid, profile_name, node_key, checked_date, checked_at, result_json)
            values (?, ?, ?, ?, ?, ?)
            on conflict(profile_uid, node_key, checked_date) do update set
                profile_name = excluded.profile_name,
                checked_at = excluded.checked_at,
                result_json = excluded.result_json
            """,
            (
                profile_uid,
                profile_name,
                key,
                date.today().isoformat(),
                result["cached_at"],
                json.dumps(result, ensure_ascii=False),
            ),
        )
        conn.commit()


def _ensure_schema() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            create table if not exists node_results (
                profile_uid text not null,
                profile_name text not null,
                node_key text not null,
                checked_date text not null,
                checked_at text not null,
                result_json text not null,
                primary key (profile_uid, node_key, checked_date)
            )
            """
        )
        conn.execute(
            """
            create index if not exists idx_node_results_profile_date
            on node_results(profile_uid, checked_date)
            """
        )
        conn.commit()
