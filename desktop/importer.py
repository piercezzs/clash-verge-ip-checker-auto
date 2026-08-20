from __future__ import annotations

import urllib.parse
from collections.abc import Iterable
from typing import Optional

from desktop.verge_profiles import VergeProfile


TRANSIENT_EXPORT_QUERY_KEYS = frozenset({"name", "v"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"})
NormalizedSubscriptionUrl = tuple[
    str,
    str,
    Optional[int],
    str,
    tuple[tuple[str, str], ...],
]


def build_clash_import_url(file_url: str, profile_name: str) -> str:
    encoded_url = urllib.parse.quote(file_url, safe="")
    encoded_name = urllib.parse.quote(profile_name, safe="")
    return f"clash://install-config?url={encoded_url}&name={encoded_name}"


def normalize_subscription_url(value: str) -> NormalizedSubscriptionUrl | None:
    try:
        parsed = urllib.parse.urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        return None

    if host in LOOPBACK_HOSTS:
        host = "loopback"
    if (scheme, port) in {("http", 80), ("https", 443)}:
        port = None

    stable_query = tuple(
        sorted(
            (key, query_value)
            for key, query_value in urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if key.lower() not in TRANSIENT_EXPORT_QUERY_KEYS
        )
    )
    return (
        scheme,
        host,
        port,
        urllib.parse.unquote(parsed.path) or "/",
        stable_query,
    )


def find_matching_profiles(
    file_url: str,
    profiles: Iterable[VergeProfile],
) -> tuple[VergeProfile, ...]:
    target = normalize_subscription_url(file_url)
    if target is None:
        return ()

    return tuple(
        profile
        for profile in profiles
        if profile.url and normalize_subscription_url(profile.url) == target
    )
