from __future__ import annotations

import urllib.parse


def build_clash_import_url(file_url: str, profile_name: str) -> str:
    encoded_url = urllib.parse.quote(file_url, safe="")
    encoded_name = urllib.parse.quote(profile_name, safe="")
    return f"clash://install-config?url={encoded_url}&name={encoded_name}"

