from __future__ import annotations

import ipaddress
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


CACHE_SCHEMA_VERSION = 1
IP_CACHE_TTL_DAYS = 14
SHARED_CACHE_PATH = Path("sync") / "ip_reputation_cache.json"
DEFAULT_RESULTS_DB_PATH = Path("data") / "results.sqlite3"


@dataclass(frozen=True)
class IPCacheSnapshot:
    entries: dict[str, dict[str, object]]
    writable: bool = True
    warning: str = ""
    needs_save: bool = False


def cache_key(ip: str, source: str = "ippure", mode: str = "fast") -> str:
    return f"{source.strip().lower()}:{mode.strip().lower()}:{ip.strip()}"


def utc_now_text(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_cache_entry(
    result: dict[str, object],
    mode: str,
    checked_at: str | None = None,
) -> tuple[str, dict[str, object]] | None:
    ip = str(result.get("ip") or "").strip()
    source = str(result.get("source") or "").strip().lower()
    pure_score = str(result.get("pure_score") or "").strip()
    normalized_mode = mode.strip().lower()

    if source != "ippure" or normalized_mode not in {"fast", "browser"}:
        return None
    if not _is_ipv4(ip) or not _is_score(pure_score):
        return None
    if normalized_mode == "browser" and not str(result.get("bot_score") or "").strip():
        return None

    timestamp = _normalized_timestamp(checked_at) or utc_now_text()
    entry: dict[str, object] = {
        "ip": ip,
        "source": source,
        "mode": normalized_mode,
        "checked_at": timestamp,
        "pure_score": pure_score,
        "shared_users": result.get("shared_users", "N/A"),
        "ip_attr": result.get("ip_attr", "❓"),
        "ip_src": result.get("ip_src", "❓"),
        "full_string": result.get("full_string", ""),
    }
    if "bot_score" in result:
        entry["bot_score"] = result.get("bot_score", "N/A")

    return cache_key(ip, source, normalized_mode), entry


def get_fresh_result(
    entries: dict[str, dict[str, object]],
    ip: str,
    source: str = "ippure",
    mode: str = "fast",
    now: datetime | None = None,
    ttl_days: int = IP_CACHE_TTL_DAYS,
) -> dict[str, object] | None:
    entry = entries.get(cache_key(ip, source, mode))
    if not entry or not is_entry_fresh(entry, now=now, ttl_days=ttl_days):
        return None

    result = {
        field: entry[field]
        for field in (
            "ip",
            "source",
            "pure_score",
            "shared_users",
            "bot_score",
            "ip_attr",
            "ip_src",
            "full_string",
        )
        if field in entry
    }
    result["cache_hit"] = True
    result["cached_at"] = entry.get("checked_at", "")
    return result


def is_entry_fresh(
    entry: dict[str, object],
    now: datetime | None = None,
    ttl_days: int = IP_CACHE_TTL_DAYS,
) -> bool:
    checked_at = _parse_timestamp(str(entry.get("checked_at") or ""))
    if checked_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.astimezone()
    age = current.astimezone(timezone.utc) - checked_at
    return timedelta(minutes=-5) <= age <= timedelta(days=ttl_days)


def merge_entries(
    *collections: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for entries in collections:
        for key, entry in entries.items():
            normalized = _normalized_entry(key, entry)
            if normalized is None:
                continue
            existing = merged.get(key)
            if existing is None or _entry_time(normalized) > _entry_time(existing):
                merged[key] = normalized
    return dict(sorted(merged.items()))


def prune_expired_entries(
    entries: dict[str, dict[str, object]],
    now: datetime | None = None,
    ttl_days: int = IP_CACHE_TTL_DAYS,
) -> dict[str, dict[str, object]]:
    return {
        key: entry
        for key, entry in sorted(entries.items())
        if is_entry_fresh(entry, now=now, ttl_days=ttl_days)
    }


def load_combined_ip_cache(
    shared_path: Path = SHARED_CACHE_PATH,
    db_path: Path = DEFAULT_RESULTS_DB_PATH,
) -> IPCacheSnapshot:
    shared = load_shared_ip_cache(shared_path)
    sqlite_entries = load_sqlite_ip_cache(db_path)
    merged = prune_expired_entries(merge_entries(shared.entries, sqlite_entries))
    return IPCacheSnapshot(
        entries=merged,
        writable=shared.writable,
        warning=shared.warning,
        needs_save=shared.writable and merged != shared.entries,
    )


def load_shared_ip_cache(path: Path = SHARED_CACHE_PATH) -> IPCacheSnapshot:
    if not path.exists():
        return IPCacheSnapshot(entries={})

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return IPCacheSnapshot(
            entries={},
            writable=False,
            warning=f"共享 IP 缓存无法读取，已保留原文件且本次不会覆盖：{error}",
        )

    if not isinstance(payload, dict) or payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        return IPCacheSnapshot(
            entries={},
            writable=False,
            warning="共享 IP 缓存版本不兼容，已保留原文件且本次不会覆盖",
        )

    raw_entries = payload.get("results")
    if not isinstance(raw_entries, dict):
        return IPCacheSnapshot(
            entries={},
            writable=False,
            warning="共享 IP 缓存缺少 results 对象，已保留原文件且本次不会覆盖",
        )

    candidates: dict[str, dict[str, object]] = {}
    invalid_count = 0
    for key, value in raw_entries.items():
        normalized = (
            _normalized_entry(str(key), value)
            if isinstance(value, dict)
            else None
        )
        if normalized is None:
            invalid_count += 1
            continue
        candidates[str(key)] = normalized

    entries = dict(sorted(candidates.items()))
    if invalid_count:
        return IPCacheSnapshot(
            entries=entries,
            writable=False,
            warning=(
                f"共享 IP 缓存包含 {invalid_count} 条无效记录，"
                "已保留原文件且本次不会覆盖"
            ),
        )

    return IPCacheSnapshot(entries=entries)


def save_shared_ip_cache(
    entries: dict[str, dict[str, object]],
    path: Path = SHARED_CACHE_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "ttl_days": IP_CACHE_TTL_DAYS,
        "results": prune_expired_entries(merge_entries(entries)),
    }
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def load_sqlite_ip_cache(
    db_path: Path = DEFAULT_RESULTS_DB_PATH,
) -> dict[str, dict[str, object]]:
    if not db_path.exists():
        return {}

    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "select checked_at, result_json from node_results order by checked_at"
            ).fetchall()
    except sqlite3.Error:
        return {}

    entries: dict[str, dict[str, object]] = {}
    for checked_at, result_json in rows:
        try:
            node_result = json.loads(result_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(node_result, dict):
            continue

        provider_result = _provider_result_from_node_result(node_result)
        mode = _mode_from_node_result(node_result)
        built = build_cache_entry(
            provider_result,
            mode=mode,
            checked_at=str(node_result.get("cached_at") or checked_at or ""),
        )
        if built is None:
            continue
        key, entry = built
        existing = entries.get(key)
        if existing is None or _entry_time(entry) > _entry_time(existing):
            entries[key] = entry

    return dict(sorted(entries.items()))


def _provider_result_from_node_result(node_result: dict[str, object]) -> dict[str, object]:
    original_name = str(node_result.get("original_name") or "")
    decorated_name = str(node_result.get("name") or "")
    full_string = ""
    if original_name and decorated_name.startswith(original_name):
        full_string = decorated_name[len(original_name):]

    return {
        "ip": node_result.get("ip", ""),
        "source": node_result.get("source", ""),
        "pure_score": node_result.get("risk", ""),
        "shared_users": node_result.get("shared", "N/A"),
        "bot_score": node_result.get("bot", "N/A"),
        "ip_attr": node_result.get("type", "❓"),
        "ip_src": node_result.get("native", "❓"),
        "full_string": full_string,
    }


def _mode_from_node_result(node_result: dict[str, object]) -> str:
    bot_score = str(node_result.get("bot") or "").strip().upper()
    return "browser" if bot_score not in {"", "N/A", "❓"} else "fast"


def _normalized_entry(key: str, entry: dict[str, object]) -> dict[str, object] | None:
    expected_key = cache_key(
        str(entry.get("ip") or ""),
        str(entry.get("source") or ""),
        str(entry.get("mode") or ""),
    )
    if key != expected_key:
        return None
    built = build_cache_entry(
        entry,
        mode=str(entry.get("mode") or ""),
        checked_at=str(entry.get("checked_at") or ""),
    )
    return built[1] if built is not None else None


def _normalized_timestamp(value: str | None) -> str | None:
    parsed = _parse_timestamp(value or "")
    return utc_now_text(parsed) if parsed is not None else None


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)


def _entry_time(entry: dict[str, object]) -> datetime:
    return _parse_timestamp(str(entry.get("checked_at") or "")) or datetime.min.replace(
        tzinfo=timezone.utc
    )


def _is_ipv4(value: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
    except ValueError:
        return False


def _is_score(value: str) -> bool:
    if not value.endswith("%"):
        return False
    try:
        score = int(value[:-1])
    except ValueError:
        return False
    return 0 <= score <= 100
