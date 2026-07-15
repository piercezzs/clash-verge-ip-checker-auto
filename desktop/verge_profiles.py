from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path

import aiohttp

try:
    import psutil
except Exception:  # pragma: no cover - optional runtime dependency fallback
    psutil = None

from ruamel.yaml import YAML

APP_ID = "io.github.clash-verge-rev.clash-verge-rev"
DEFAULT_EXTERNAL_CONTROLLER = "127.0.0.1:9097"
DEFAULT_SECRET = "set-your-secret"
RUNTIME_CONFIG = "clash-verge.yaml"

yaml = YAML()
yaml.preserve_quotes = True


@dataclass(frozen=True)
class VergeProfile:
    uid: str
    name: str
    profile_type: str
    file: str
    path: str
    url: str | None
    is_current: bool
    supported: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "uid": self.uid,
            "name": self.name,
            "type": self.profile_type,
            "file": self.file,
            "path": self.path,
            "has_url": bool(self.url),
            "is_current": self.is_current,
            "supported": self.supported,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class VergeContext:
    app_home: str
    profiles_path: str
    profiles_dir: str
    runtime_path: str
    running: bool
    process_names: list[str]
    controller_url: str
    controller_secret: str
    external_controller_enabled: bool | None
    current_uid: str | None
    profiles: list[VergeProfile]
    issues: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "app_home": self.app_home,
            "profiles_path": self.profiles_path,
            "profiles_dir": self.profiles_dir,
            "runtime_path": self.runtime_path,
            "running": self.running,
            "process_names": self.process_names,
            "controller_url": self.controller_url,
            "controller_secret": "",
            "has_controller_secret": bool(self.controller_secret),
            "external_controller_enabled": self.external_controller_enabled,
            "current_uid": self.current_uid,
            "profiles": [profile.to_dict() for profile in self.profiles],
            "issues": self.issues,
        }


def discover_verge(app_home_override: str | None = None) -> VergeContext:
    app_home = find_app_home(app_home_override)
    if not app_home:
        return VergeContext(
            app_home="",
            profiles_path="",
            profiles_dir="",
            runtime_path="",
            running=is_verge_running()[0],
            process_names=is_verge_running()[1],
            controller_url=f"http://{DEFAULT_EXTERNAL_CONTROLLER}",
            controller_secret="",
            external_controller_enabled=None,
            current_uid=None,
            profiles=[],
            issues=["未找到 Clash Verge Rev 数据目录"],
        )

    profiles_path = app_home / "profiles.yaml"
    profiles_dir = app_home / "profiles"
    runtime_path = app_home / RUNTIME_CONFIG
    running, process_names = is_verge_running()
    profiles_data = _load_yaml(profiles_path) or {}
    current_uid = profiles_data.get("current")
    raw_items = profiles_data.get("items") or []
    profiles = [_profile_from_item(item, current_uid, profiles_dir) for item in raw_items]
    clash_settings = read_clash_settings(app_home)
    verge_settings = _load_yaml(app_home / "verge.yaml") or {}
    external_enabled = verge_settings.get("enable_external_controller")
    issues: list[str] = []

    if not profiles_path.exists():
        issues.append("未找到 profiles.yaml")
    if not profiles_dir.exists():
        issues.append("未找到 profiles 目录")
    if external_enabled is False:
        issues.append("Clash Verge Rev 当前未启用 External Controller，HTTP 控制可能不可用")

    return VergeContext(
        app_home=str(app_home),
        profiles_path=str(profiles_path),
        profiles_dir=str(profiles_dir),
        runtime_path=str(runtime_path),
        running=running,
        process_names=process_names,
        controller_url=clash_settings["controller_url"],
        controller_secret=clash_settings["secret"],
        external_controller_enabled=external_enabled,
        current_uid=current_uid,
        profiles=profiles,
        issues=issues,
    )


def find_app_home(app_home_override: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if app_home_override:
        candidates.append(Path(app_home_override).expanduser())

    env_home = os.environ.get("CLASH_VERGE_HOME")
    if env_home:
        candidates.append(Path(env_home).expanduser())

    home = Path.home()
    system = platform.system().lower()
    if system == "darwin":
        candidates.extend(
            [
                home / "Library" / "Application Support" / APP_ID,
                home / "Library" / "Application Support" / f"{APP_ID}.dev",
            ]
        )
    elif system == "windows":
        roaming = os.environ.get("APPDATA")
        local = os.environ.get("LOCALAPPDATA")
        if roaming:
            candidates.append(Path(roaming) / APP_ID)
            candidates.append(Path(roaming) / f"{APP_ID}.dev")
        if local:
            candidates.append(Path(local) / APP_ID)
            candidates.append(Path(local) / f"{APP_ID}.dev")
    else:
        candidates.extend(
            [
                home / ".local" / "share" / APP_ID,
                home / ".config" / APP_ID,
            ]
        )

    for candidate in candidates:
        if (candidate / "profiles.yaml").exists():
            return candidate
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


async def load_profile_config(
    app_home: str,
    uid: str,
    refresh_remote: bool = False,
) -> tuple[dict[str, object], VergeProfile, bool]:
    context = discover_verge(app_home)
    profile = next((item for item in context.profiles if item.uid == uid), None)
    if not profile:
        raise ValueError(f"未找到订阅: {uid}")
    if not profile.supported:
        raise ValueError(profile.reason)

    if refresh_remote:
        if profile.profile_type != "remote" or not profile.url:
            raise ValueError("只有远程订阅可以刷新原订阅内容")
        data = await _fetch_remote_profile(profile.url)
        refreshed = True
    else:
        data = _load_yaml(Path(profile.path))
        refreshed = False

    if not isinstance(data, dict):
        raise ValueError("订阅 YAML 内容不是对象")
    if not data.get("proxies"):
        raise ValueError("订阅 YAML 未找到 proxies")
    return data, profile, refreshed


def read_profile_config(app_home: str, uid: str) -> tuple[dict[str, object], VergeProfile]:
    context = discover_verge(app_home)
    profile = next((item for item in context.profiles if item.uid == uid), None)
    if not profile:
        raise ValueError(f"未找到订阅: {uid}")
    if not profile.supported:
        raise ValueError(profile.reason)
    data = _load_yaml(Path(profile.path))
    if not isinstance(data, dict):
        raise ValueError("订阅 YAML 内容不是对象")
    if not data.get("proxies"):
        raise ValueError("订阅 YAML 未找到 proxies")
    return data, profile


def read_clash_settings(app_home: Path) -> dict[str, str]:
    data = _load_yaml(app_home / "config.yaml") or {}
    external_controller = data.get("external-controller") or DEFAULT_EXTERNAL_CONTROLLER
    controller_url = _normalize_controller_url(str(external_controller))
    secret = data.get("secret") or ""
    if secret == DEFAULT_SECRET:
        secret = DEFAULT_SECRET
    return {"controller_url": controller_url, "secret": str(secret)}


def is_verge_running() -> tuple[bool, list[str]]:
    expected = ("clash verge", "clash-verge", "clash verge rev")
    seen: list[str] = []

    if psutil:
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info.get("name") or ""
            except Exception:
                continue
            lower = name.lower()
            if any(item in lower for item in expected):
                seen.append(name)
        return bool(seen), sorted(set(seen))

    return False, []


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value, flags=re.UNICODE).strip("._")
    return cleaned or "clash_verge_profile"


def _profile_from_item(item: dict[str, object], current_uid: str | None, profiles_dir: Path) -> VergeProfile:
    uid = str(item.get("uid") or "")
    profile_type = str(item.get("type") or "")
    name = str(item.get("name") or uid or "未命名订阅")
    file_name = str(item.get("file") or "")
    path = profiles_dir / file_name if file_name else profiles_dir
    is_main = profile_type in {"remote", "local"}
    is_yaml = file_name.lower().endswith((".yaml", ".yml"))
    exists = path.exists()
    supported = bool(uid and is_main and is_yaml and exists)
    reason = ""
    if not uid:
        reason = "缺少 uid"
    elif not is_main:
        reason = "只支持 Remote / Local 主订阅"
    elif not is_yaml:
        reason = "不是 YAML 订阅文件"
    elif not exists:
        reason = "订阅文件不存在"

    return VergeProfile(
        uid=uid,
        name=name,
        profile_type=profile_type,
        file=file_name,
        path=str(path),
        url=item.get("url"),
        is_current=uid == current_uid,
        supported=supported,
        reason=reason,
    )


async def _fetch_remote_profile(url: str) -> dict[str, object]:
    headers = {
        "User-Agent": "Clash Verge IP Checker Auto/1.0",
        "Accept": "text/yaml, application/yaml, text/plain, */*",
    }
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise ValueError(f"远程订阅请求失败: HTTP {response.status}")
                text = (await response.text()).lstrip("\ufeff")
    except aiohttp.ClientError as error:
        raise ValueError(f"远程订阅请求失败: {error}") from error

    data = yaml.load(text)
    if not isinstance(data, dict):
        raise ValueError("远程订阅返回内容不是 YAML 对象")
    return data


def _normalize_controller_url(value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return value.rstrip("/")
    return f"http://{value}".rstrip("/")


def _load_yaml(path: Path) -> object:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        return yaml.load(file)
