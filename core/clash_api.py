from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

import aiohttp


@dataclass(frozen=True)
class ClashProxyEndpoints:
    request_url: str
    ipv4_lookup_url: str
    ipv4_lookup_forced: bool


def proxy_endpoints_from_configs(configs: dict[str, object]) -> ClashProxyEndpoints:
    """Build request endpoints while preferring local IPv4 DNS over mixed-port SOCKS5."""
    mixed_port = _positive_port(configs.get("mixed-port"))
    if mixed_port:
        return ClashProxyEndpoints(
            request_url=f"http://127.0.0.1:{mixed_port}",
            ipv4_lookup_url=f"socks5://127.0.0.1:{mixed_port}",
            ipv4_lookup_forced=True,
        )

    http_port = _positive_port(configs.get("port"))
    if http_port:
        url = f"http://127.0.0.1:{http_port}"
        return ClashProxyEndpoints(
            request_url=url,
            ipv4_lookup_url=url,
            ipv4_lookup_forced=False,
        )

    socks_port = _positive_port(configs.get("socks-port"))
    if socks_port:
        return ClashProxyEndpoints(
            request_url=f"http://127.0.0.1:{socks_port}",
            ipv4_lookup_url=f"socks5://127.0.0.1:{socks_port}",
            ipv4_lookup_forced=True,
        )

    return ClashProxyEndpoints(
        request_url="http://127.0.0.1:7897",
        ipv4_lookup_url="socks5://127.0.0.1:7897",
        ipv4_lookup_forced=True,
    )


def _positive_port(value: object) -> int | None:
    try:
        port = int(value or 0)
    except (TypeError, ValueError):
        return None
    return port if 0 < port <= 65535 else None


class ClashController:
    def __init__(self, api_url, secret=""):
        self.api_url = api_url.rstrip('/')
        self.headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json"
        }

    async def switch_proxy(self, selector, proxy_name):
        """Switches the selector to the specified proxy."""
        url = f"{self.api_url}/proxies/{urllib.parse.quote(selector)}"
        payload = {"name": proxy_name}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(url, json=payload, headers=self.headers, timeout=5) as resp:
                    if resp.status == 204:
                        return True
                    else:
                        print(f"Failed to switch to {proxy_name}. Status: {resp.status}")
                        return False
        except Exception as e:
            print(f"API Error switching to {proxy_name}: {e}")
            return False

    async def set_mode(self, mode):
        """Sets the Clash mode (global, rule, direct)."""
        url = f"{self.api_url}/configs"
        payload = {"mode": mode}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, json=payload, headers=self.headers, timeout=5) as resp:
                    if resp.status == 204:
                        print(f"Successfully set mode to: {mode}")
                        return True
                    else:
                        print(f"Failed to set mode logic. Status: {resp.status}")
                        return False
        except Exception as e:
            print(f"API Error setting mode: {e}")
            return False

    async def get_configs(self):
        """Fetches runtime Clash configuration values."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_url}/configs", headers=self.headers, timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
        except Exception as e:
            print(f"API Error fetching configs: {e}")
            return None

    async def reload_config_path(self, path, force=True):
        """Reloads the Clash core with a config path."""
        url = f"{self.api_url}/configs"
        if force:
            url = f"{url}?force=true"
        payload = {"path": path}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(url, json=payload, headers=self.headers, timeout=20) as resp:
                    if resp.status in (200, 204):
                        return True
                    text = await resp.text()
                    print(f"Failed to reload config. Status: {resp.status}, Body: {text}")
                    return False
        except Exception as e:
            print(f"API Error reloading config: {e}")
            return False

    async def get_running_port(self):
        """Fetches the mixed-port or http-port from running instance."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_url}/configs", headers=self.headers) as resp:
                    if resp.status == 200:
                        conf = await resp.json()
                        if conf.get('mixed-port', 0) != 0: return conf['mixed-port']
                        if conf.get('port', 0) != 0: return conf['port']
                        if conf.get('socks-port', 0) != 0: return conf['socks-port']
        except Exception:
            pass
        return 7897 # Default fallback
    
    async def get_proxies(self):
        """Fetches all proxies."""
        try:
             async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_url}/proxies", headers=self.headers, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('proxies', {})
        except Exception as e:
            print(f"Error fetching proxies: {e}")
            return None
