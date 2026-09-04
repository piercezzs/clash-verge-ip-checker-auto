"""Device-local port selection for the Clash checker web service."""

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional


DEFAULT_PORT = 8080
FALLBACK_PORTS = tuple(range(18080, 18121))
STATE_VERSION = 1


class PortSelectionError(ValueError):
    """Raised when no safe port can be selected."""


@dataclass(frozen=True)
class PortPreference:
    port: int
    explicit: bool
    source: str


def _validated_port(value: object, label: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as error:
        raise PortSelectionError(f"{label}必须是 1-65535 之间的整数。") from error
    if not 1 <= port <= 65535:
        raise PortSelectionError(f"{label}必须是 1-65535 之间的整数。")
    return port


def load_port_preference(
    state_path: Path,
    environ: Optional[Mapping[str, str]] = None,
) -> PortPreference:
    environment = os.environ if environ is None else environ
    configured = str(environment.get("CLASH_CHECKER_PORT") or "").strip()
    if configured:
        return PortPreference(
            port=_validated_port(configured, "CLASH_CHECKER_PORT"),
            explicit=True,
            source="environment",
        )

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        stored = payload.get("port") if isinstance(payload, dict) else None
        if stored is not None:
            return PortPreference(
                port=_validated_port(stored, "已保存端口"),
                explicit=False,
                source="persisted",
            )
    except (OSError, ValueError, PortSelectionError):
        pass

    return PortPreference(port=DEFAULT_PORT, explicit=False, source="default")


def port_is_available(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind((host, port))
        except OSError:
            return False
    return True


def select_available_port(
    preference: PortPreference,
    is_available: Callable[[int], bool] = port_is_available,
) -> PortPreference:
    if is_available(preference.port):
        return preference
    if preference.explicit:
        raise PortSelectionError(
            f"显式指定的端口 {preference.port} 已被占用；不会自动改用其他端口。"
        )

    candidates = dict.fromkeys((DEFAULT_PORT, *FALLBACK_PORTS))
    for port in candidates:
        if port != preference.port and is_available(port):
            return PortPreference(port=port, explicit=False, source="automatic")
    raise PortSelectionError(
        f"默认端口 {DEFAULT_PORT} 及自动端口范围 "
        f"{FALLBACK_PORTS[0]}-{FALLBACK_PORTS[-1]} 均不可用。"
    )


def save_port_preference(state_path: Path, port: int) -> None:
    selected = _validated_port(port, "端口")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_name(f"{state_path.name}.tmp-{os.getpid()}")
    try:
        temp_path.write_text(
            json.dumps(
                {"version": STATE_VERSION, "port": selected},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(str(temp_path), str(state_path))
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
