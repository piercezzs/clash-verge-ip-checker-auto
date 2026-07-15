import asyncio
import re
import aiohttp

from .sources.ippure import IPPureSource
from .sources.browser import BrowserSource

class IPChecker:
    def __init__(self, headless=True):
        self._headless = headless
        
        # Components
        self.ippure = IPPureSource()
        self.browser_source = BrowserSource(headless=headless)
        
        self.cache = {} # Map IP -> Result Dict

    def clear_cache(self):
        """Clears the IP result cache."""
        self.cache.clear()
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
        urls = ["http://api.ipify.org", "http://v4.ident.me"]
        for url in urls:
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

    async def check_browser(self, url="https://ippure.com/", proxy=None, timeout=20000):
        """Full browser check"""
        
        # 1. Cleaner Fast IP & Cache Logic
        current_ip = await self.get_simple_ip(proxy)
        if current_ip and current_ip in self.cache:
            # Strict mode: Only accept cache if it has bot_score (from browser check)
            cached = self.cache[current_ip]
            if "bot_score" in cached:
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

        # Cache Update
        if result["ip"] != "❓" and result["pure_score"] != "❓":
            self.cache[result["ip"]] = result.copy()
            
        return result

    async def check_fast(self, proxy=None, source="ippure", fallback=False):
        """
        Fast mode: Uses IPPure HTTP lookup.
        """
        try:
            # Hard timeout of 20 seconds for entire check
            return await asyncio.wait_for(
                self._check_fast_impl(proxy, source, fallback),
                timeout=15
            )
        except asyncio.TimeoutError:
            print(f"     [check_fast] Total timeout exceeded")
            return {
                "pure_emoji": "❓", "shared_emoji": "❓", "ip_attr": "❓", "ip_src": "❓",
                "pure_score": "❓", "shared_users": "N/A", "full_string": "【⏱️ Timeout】", 
                "ip": "❓", "error": "Timeout", "source": "timeout"
            }
    
    async def _check_fast_impl(self, proxy=None, source="ippure", fallback=False):
        """Internal implementation of IPPure fast checks."""
        # 0. Check Cache First (Optimization)
        try:
            fast_ip = await self.get_simple_ip(proxy)
            if fast_ip and fast_ip in self.cache:
                # print(f"     [Cache Hit] {fast_ip}")
                return self.cache[fast_ip]
        except Exception:
            pass # Ignore fast check errors and proceed to normal check

        result = await self.ippure.check(proxy)
        if result and result.get("ip") and result["ip"] != "❓":
            self.cache[result["ip"]] = result.copy()
            return result

        return {
            "pure_emoji": "❓", "shared_emoji": "❓", "ip_attr": "❓", "ip_src": "❓",
            "pure_score": "❓", "shared_users": "N/A", "full_string": "【❌ Check Failed】", 
            "ip": "❓", "error": "IPPure source failed", "source": "failed"
        }
