from __future__ import annotations

import asyncio
import re
import aiohttp

from .sources.ippure import IPPureSource
from .sources.browser import BrowserSource
from storage.ip_cache import (
    IPCacheSnapshot,
    build_cache_entry,
    cache_key,
    get_fresh_result,
)


SIMPLE_IP_URLS = ("https://api.ipify.org", "https://4.ident.me")


class IPChecker:
    def __init__(self, headless=True):
        self._headless = headless
        
        # Components
        self.ippure = IPPureSource()
        self.browser_source = BrowserSource(headless=headless)
        
        self.cache: dict[str, dict[str, object]] = {}
        self.cache_writable = True
        self.cache_warning = ""
        self.cache_dirty = False
        self.refreshed_keys: set[str] = set()

    def configure_cache(self, snapshot: IPCacheSnapshot) -> None:
        self.cache = dict(snapshot.entries)
        self.cache_writable = snapshot.writable
        self.cache_warning = snapshot.warning
        self.cache_dirty = snapshot.needs_save
        self.refreshed_keys.clear()

    def cache_entries(self) -> dict[str, dict[str, object]]:
        return dict(self.cache)

    def mark_cache_saved(self) -> None:
        self.cache_dirty = False

    def clear_cache(self):
        """Clears the task cache after persistent entries have been saved."""
        self.cache.clear()
        self.cache_writable = True
        self.cache_warning = ""
        self.cache_dirty = False
        self.refreshed_keys.clear()
        print("[IPChecker] Cache cleared.")

    @property
    def headless(self):
        return self._headless

    @headless.setter
    def headless(self, value):
        self._headless = value
        self.browser_source.headless = value

    async def start(self):
        await self.browser_source.start()

    async def stop(self):
        await self.browser_source.stop()

    async def get_simple_ip(self, proxy=None):
        """Fast IPv4 check for caching."""
        for url in SIMPLE_IP_URLS:
            try:
                # User modified timeout to 3s
                timeout = aiohttp.ClientTimeout(total=3)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, proxy=proxy) as resp:
                        if resp.status == 200:
                            ip = (await resp.text()).strip()
                            if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
                                return ip
            except Exception:
                continue 
        return None

    # --- Main Interface ---

    async def check_browser(
        self,
        url="https://ippure.com/",
        proxy=None,
        timeout=20000,
        force_refresh=False,
    ):
        """Full browser check"""
        
        # 1. Cleaner Fast IP & Cache Logic
        current_ip = await self.get_simple_ip(proxy)
        cached = self._cached_result(
            current_ip,
            mode="browser",
            source="ippure",
            force_refresh=force_refresh,
        )
        if cached is not None:
            print(f"     [Cache Hit] {current_ip}")
            return cached
        
        if current_ip:
            print(f"     [New IP] {current_ip}")
        else:
            print("     [Warning] Fast IP check failed. Scanning with browser...")

        # 2. Delegate to Browser Source
        result = await self.browser_source.check(proxy)
        
        # Inject IP if browser failed to find it but simple check passed
        if result["ip"] == "❓" and current_ip:
            result["ip"] = current_ip

        return self._remember_result(result, mode="browser")

    async def check_fast(
        self,
        proxy=None,
        ipv4_proxy=None,
        source="ippure",
        fallback=False,
        force_refresh=False,
    ):
        """
        Fast mode: Uses the IPPure API lookup.
        """
        try:
            # Hard timeout of 20 seconds for entire check
            return await asyncio.wait_for(
                self._check_fast_impl(
                    proxy,
                    ipv4_proxy,
                    source,
                    fallback,
                    force_refresh,
                ),
                timeout=15
            )
        except asyncio.TimeoutError:
            print(f"     [check_fast] Total timeout exceeded")
            return {
                "pure_emoji": "❓", "shared_emoji": "❓", "ip_attr": "❓", "ip_src": "❓",
                "pure_score": "❓", "shared_users": "N/A", "full_string": "【⏱️ Timeout】", 
                "ip": "❓", "error": "Timeout", "source": "timeout"
            }
    
    async def _check_fast_impl(
        self,
        proxy=None,
        ipv4_proxy=None,
        source="ippure",
        fallback=False,
        force_refresh=False,
    ):
        """Internal implementation of IPPure fast checks."""
        # 0. Check Cache First (Optimization)
        fast_ip = None
        try:
            fast_ip = await self.get_simple_ip(proxy)
            cached = self._cached_result(
                fast_ip,
                mode="fast",
                source=source,
                force_refresh=force_refresh,
            )
            if cached is not None:
                return cached
        except Exception:
            pass # Ignore fast check errors and proceed to normal check

        result = await self.ippure.check(
            ipv4_proxy or proxy,
            expected_ip=fast_ip,
        )
        if result and result.get("ip") and result["ip"] != "❓":
            return self._remember_result(result, mode="fast")

        return {
            "pure_emoji": "❓", "shared_emoji": "❓", "ip_attr": "❓", "ip_src": "❓",
            "pure_score": "❓", "shared_users": "N/A", "full_string": "【❌ Check Failed】", 
            "ip": "❓", "error": "IPPure source failed", "source": "failed"
        }

    def _cached_result(
        self,
        ip: str | None,
        mode: str,
        source: str,
        force_refresh: bool,
    ) -> dict[str, object] | None:
        if not ip:
            return None
        key = cache_key(ip, source=source, mode=mode)
        if force_refresh and key not in self.refreshed_keys:
            return None
        result = get_fresh_result(self.cache, ip=ip, source=source, mode=mode)
        if result is not None:
            result["cache_scope"] = "task" if key in self.refreshed_keys else "shared"
        return result

    def _remember_result(
        self,
        result: dict[str, object],
        mode: str,
    ) -> dict[str, object]:
        built = build_cache_entry(result, mode=mode)
        if built is None:
            return result

        key, entry = built
        self.cache[key] = entry
        self.refreshed_keys.add(key)
        self.cache_dirty = True
        stored_result = dict(result)
        stored_result["cache_hit"] = False
        stored_result["cached_at"] = entry["checked_at"]
        return stored_result
