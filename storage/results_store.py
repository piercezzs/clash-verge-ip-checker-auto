from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path("data") / "results.sqlite3"


def node_key(proxy: dict[str, object]) -> str:
    payload = json.dumps(proxy, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_today_results(
    profile_uid: str,
    proxies: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    keys = [node_key(proxy) for proxy in proxies]
    if not keys:
        return {}

    _ensure_schema()
    placeholders = ",".join("?" for _ in keys)
    params = [profile_uid, date.today().isoformat(), *keys]
    sql = (
        "select node_key, result_json from node_results "
        f"where profile_uid = ? and checked_date = ? and node_key in ({placeholders})"
    )
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(sql, params).fetchall()
    return {key: json.loads(result_json) for key, result_json in rows}


def get_latest_profile_results(
    profile_uid: str,
    proxies: list[dict[str, object]],
) -> tuple[str, str, dict[str, dict[str, object]]]:
    keys = [node_key(proxy) for proxy in proxies]
    if not keys:
        return "", "", {}

    _ensure_schema()
    with sqlite3.connect(DB_PATH) as conn:
        latest = conn.execute(
            """
            select checked_date, max(checked_at)
            from node_results
            where profile_uid = ?
            group by checked_date
            order by checked_date desc
            limit 1
            """,
            (profile_uid,),
        ).fetchone()
        if not latest:
            return "", "", {}

        checked_date, checked_at = latest
        placeholders = ",".join("?" for _ in keys)
        params = [profile_uid, checked_date, *keys]
        sql = (
            "select node_key, result_json from node_results "
            f"where profile_uid = ? and checked_date = ? and node_key in ({placeholders})"
        )
        rows = conn.execute(sql, params).fetchall()

    return checked_date, checked_at, {key: json.loads(result_json) for key, result_json in rows}


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
    result["cached_at"] = datetime.now().isoformat(timespec="seconds")

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
