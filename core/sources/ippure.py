from __future__ import annotations

import asyncio
import ipaddress
from typing import Dict, Optional

from curl_cffi import CurlOpt
from curl_cffi.const import CurlIpResolve
from curl_cffi.requests import Session

from .base import BaseCheckSource


IPPURE_INFO_URL = "https://my.ippure.com/v1/info"
SCORE_AVAILABLE = "available"
SCORE_IPV6_UNSUPPORTED = "ipv6_unsupported"
SCORE_IP_MISMATCH = "ip_mismatch"
SCORE_UNAVAILABLE = "unavailable"
SCORE_FAILED = "failed"


def parse_ippure_payload(
    payload: object,
    expected_ip: Optional[str] = None,
) -> Dict[str, object]:
    result = _empty_result()
    if not isinstance(payload, dict):
        result["error"] = "IPPure returned a non-object response"
        result["full_string"] = "【❌ IPPure响应异常】"
        return result

    provider_ip = str(payload.get("ip") or "").strip()
    ip_version = _ip_version(provider_ip)
    result["ip"] = provider_ip or "❓"
    result["expected_ip"] = str(expected_ip or "").strip()
    result["ip_version"] = ip_version or "unknown"
    result["ip_attr"] = _classification(payload.get("isResidential"), "住宅", "机房")
    result["ip_src"] = _classification(payload.get("isBroadcast"), "广播", "原生")
    result["shared_emoji"] = ""

    if not provider_ip or ip_version is None:
        result["error"] = "IPPure response did not contain a valid IP address"
        result["full_string"] = "【❌ IPPure未返回有效IP】"
        return result

    expected = str(expected_ip or "").strip()
    score = _score(payload.get("fraudScore"))
    if expected and not _same_ip(provider_ip, expected):
        if ip_version == 6 and score is None:
            result["score_status"] = SCORE_IPV6_UNSUPPORTED
            result["pure_score"] = "IPv6无评分"
            result["pure_emoji"] = "⚠️"
            result["error"] = f"IPPure used IPv6 {provider_ip} instead of detected IPv4 {expected}"
        else:
            result["score_status"] = SCORE_IP_MISMATCH
            result["pure_score"] = "出口不一致"
            result["pure_emoji"] = "⚠️"
            result["error"] = f"IPPure returned {provider_ip}, expected {expected}"
        result["full_string"] = _full_string(result)
        return result

    if score is not None:
        result["score_status"] = SCORE_AVAILABLE
        result["pure_score"] = f"{score:g}%"
        result["pure_emoji"] = BaseCheckSource.get_emoji(result["pure_score"])
    elif ip_version == 6:
        result["score_status"] = SCORE_IPV6_UNSUPPORTED
        result["pure_score"] = "IPv6无评分"
        result["pure_emoji"] = "⚠️"
        result["error"] = "IPPure does not provide a risk score for this IPv6 address"
    else:
        result["score_status"] = SCORE_UNAVAILABLE
        result["pure_score"] = "暂无评分"
        result["pure_emoji"] = "⚠️"
        result["error"] = "IPPure did not provide fraudScore for this IPv4 address"

    result["full_string"] = _full_string(result)
    return result


class IPPureSource(BaseCheckSource):
    def _check_sync(
        self,
        proxy: Optional[str] = None,
        expected_ip: Optional[str] = None,
    ) -> Dict[str, object]:
        try:
            proxies = {"http": proxy, "https": proxy} if proxy else None
            with Session(
                proxies=proxies,
                impersonate="chrome110",
                timeout=5,
                curl_options={CurlOpt.IPRESOLVE: CurlIpResolve.V4},
            ) as session:
                response = session.get(IPPURE_INFO_URL)
                if response.status_code == 200:
                    return parse_ippure_payload(response.json(), expected_ip=expected_ip)

                result = _empty_result()
                result["error"] = f"API Error {response.status_code}"
                result["full_string"] = "【❌ IPPure接口异常】"
                return result
        except Exception as error:
            print(f"     [ippure] curl_cffi error: {error}")
            result = _empty_result()
            result["error"] = str(error)
            result["full_string"] = "【❌ IPPure请求失败】"
            return result

    async def check(
        self,
        proxy: Optional[str] = None,
        expected_ip: Optional[str] = None,
    ) -> Dict[str, object]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._check_sync, proxy, expected_ip)


def _empty_result() -> Dict[str, object]:
    return {
        "pure_emoji": "❓",
        "shared_emoji": "❓",
        "ip_attr": "❓",
        "ip_src": "❓",
        "pure_score": "❓",
        "shared_users": "N/A",
        "full_string": "",
        "ip": "❓",
        "expected_ip": "",
        "ip_version": "unknown",
        "score_status": SCORE_FAILED,
        "error": None,
        "source": "ippure",
    }


def _classification(value: object, true_label: str, false_label: str) -> str:
    if value is True:
        return true_label
    if value is False:
        return false_label
    return "❓"


def _ip_version(value: str) -> Optional[int]:
    try:
        return ipaddress.ip_address(value).version
    except ValueError:
        return None


def _same_ip(left: str, right: str) -> bool:
    try:
        return ipaddress.ip_address(left) == ipaddress.ip_address(right)
    except ValueError:
        return False


def _score(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if 0 <= score <= 100 else None


def _full_string(result: Dict[str, object]) -> str:
    attr = result["ip_attr"] if result["ip_attr"] != "❓" else ""
    source = result["ip_src"] if result["ip_src"] != "❓" else ""
    info = "|".join(value for value in (str(attr), str(source)) if value) or "未知"
    score_status = result.get("score_status")
    if score_status == SCORE_AVAILABLE:
        prefix = str(result["pure_emoji"])
    elif score_status == SCORE_IPV6_UNSUPPORTED:
        prefix = "⚠️ IPv6无评分"
    elif score_status == SCORE_IP_MISMATCH:
        prefix = "⚠️ 出口不一致"
    else:
        prefix = "⚠️ 暂无评分"
    return f"【{prefix} {info}】"
