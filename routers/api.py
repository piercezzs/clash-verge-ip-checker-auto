from __future__ import annotations

import asyncio
import copy
import io
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from ruamel.yaml import YAML
import segno

from core.clash_api import ClashController
from desktop.importer import build_clash_import_url
from desktop.verge_profiles import discover_verge, load_profile_config, sanitize_name
from schemas import ExportRequest, StartProfileRequest, UpdateNodeRequest
from state import state
from storage.results_store import get_latest_profile_results, node_key, save_node_result

router = APIRouter(prefix="/api")
yaml = YAML()
yaml.preserve_quotes = True


@router.get("/verge/discover")
async def discover(app_home: str = ""):
    """Find local Clash Verge profiles and controller defaults."""
    return discover_verge(app_home or None).to_dict()


@router.post("/start-profile")
async def start_profile_check(request: StartProfileRequest):
    """Start checking a selected Clash Verge profile."""
    if state.is_running:
        raise HTTPException(status_code=409, detail="任务正在运行中")

    try:
        refresh_remote = bool(request.config.get("refresh_remote", False))
        config_data, profile, source_refreshed = await load_profile_config(
            request.app_home,
            request.profile_uid,
            refresh_remote=refresh_remote,
        )
        context = discover_verge(request.app_home or None)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    proxies = config_data.get("proxies", [])
    if not proxies:
        raise HTTPException(status_code=400, detail="订阅 YAML 未找到 proxies")

    skip_keywords = _parse_skip_keywords(request.config.get("skip_keywords_str", ""))
    active_proxies = [proxy for proxy in proxies if not _should_skip(proxy.get("name", ""), skip_keywords)]
    if not active_proxies:
        raise HTTPException(status_code=400, detail="过滤后没有可检测节点")

    nodes, pending_items = _build_nodes(active_proxies, {})

    state.task_id = str(uuid.uuid4())
    state.is_running = True
    state.original_yaml = config_data
    state.app_home = context.app_home
    state.profile_uid = profile.uid
    state.profile_name = profile.name
    state.profile_path = profile.path
    state.runtime_path = context.runtime_path
    state.nodes = nodes
    state.events = []
    state.progress = 0
    state.total = len(active_proxies)
    state.current_node = ""

    run_config = dict(request.config)
    if not run_config.get("clash_api_url"):
        run_config["clash_api_url"] = context.controller_url
    if not run_config.get("clash_api_secret"):
        run_config["clash_api_secret"] = context.controller_secret
    run_config["profile_is_current"] = profile.is_current
    run_config["force_load_profile"] = False
    run_config["temp_generated_profile_path"] = ""

    if source_refreshed:
        temp_profile_path = _write_temp_profile(config_data, profile.uid)
        state.profile_path = str(temp_profile_path)
        run_config["force_load_profile"] = True
        run_config["temp_generated_profile_path"] = str(temp_profile_path)
        state.events.append(
            {
                "type": "message",
                "message": "已拉取远程订阅最新内容；本次检测不会改动 Clash Verge 原订阅文件",
            }
        )

    if pending_items:
        asyncio.create_task(_run_check(pending_items, run_config))
    else:
        state.is_running = False
        state.events.append({"type": "complete", "total": len(state.nodes)})
    return {
        "task_id": state.task_id,
        "total": state.total,
        "profile": profile.to_dict(),
        "source_refreshed": source_refreshed,
        "pending": len(pending_items),
    }


@router.post("/load-profile-results")
async def load_profile_results(request: StartProfileRequest):
    """Load same-day cached node results for the selected profile without checking."""
    try:
        config_data, profile, _ = await load_profile_config(
            request.app_home,
            request.profile_uid,
            refresh_remote=False,
        )
        context = discover_verge(request.app_home or None)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    skip_keywords = _parse_skip_keywords(request.config.get("skip_keywords_str", ""))
    proxies = config_data.get("proxies", [])
    active_proxies = [proxy for proxy in proxies if not _should_skip(proxy.get("name", ""), skip_keywords)]
    checked_date, checked_at, cached_results = get_latest_profile_results(profile.uid, active_proxies)
    nodes, _ = _build_nodes(active_proxies, cached_results)

    state.task_id = ""
    state.is_running = False
    state.original_yaml = config_data
    state.app_home = context.app_home
    state.profile_uid = profile.uid
    state.profile_name = profile.name
    state.profile_path = profile.path
    state.runtime_path = context.runtime_path
    state.nodes = nodes
    state.events = []
    state.progress = 0
    state.total = len(active_proxies)
    state.current_node = ""

    return {
        "profile": profile.to_dict(),
        "nodes": nodes,
        "cached": len(cached_results),
        "total": len(active_proxies),
        "checked_date": checked_date,
        "checked_at": checked_at,
    }


async def _run_check(pending_items: list[tuple[int, dict[str, object]]], config: dict[str, object]):
    controller = ClashController(
        config.get("clash_api_url", "http://127.0.0.1:9097"),
        config.get("clash_api_secret", ""),
    )
    state.checker.headless = bool(config.get("headless", True))
    original_mode: str | None = None
    temp_loaded = False
    temp_generated_profile_path = str(config.get("temp_generated_profile_path") or "")

    try:
        configs = await controller.get_configs()
        if not configs:
            raise RuntimeError("无法连接 Clash External Controller")
        original_mode = configs.get("mode")

        should_load_profile = bool(config.get("force_load_profile", False)) or (
            config.get("temp_load_profile", False) and not config.get("profile_is_current", False)
        )
        if should_load_profile:
            state.events.append({"type": "message", "message": "临时加载所选订阅到 Clash 内核"})
            loaded = await controller.reload_config_path(state.profile_path, force=True)
            if not loaded:
                raise RuntimeError("临时加载所选订阅失败，请先在 Clash Verge 中手动使用该订阅")
            temp_loaded = True
            await asyncio.sleep(1)

        pending_proxies = [proxy for _, proxy in pending_items]
        selector = await _resolve_selector(controller, config.get("selector_name", "auto"), pending_proxies)
        if not selector:
            raise RuntimeError("无法自动识别可切换的代理组，请手动填写 selector")

        await controller.set_mode("global")
        port = await controller.get_running_port()
        proxy_url = f"http://127.0.0.1:{port}"
        fast_mode = bool(config.get("fast_mode", True))
        source = "ippure"
        fallback = False

        for idx, proxy in pending_items:
            if not state.is_running:
                break
            name = proxy.get("name", f"Node {idx}")
            state.current_node = name
            node_data = await _check_node(
                idx=idx,
                proxy=proxy,
                name=name,
                selector=selector,
                controller=controller,
                proxy_url=proxy_url,
                fast_mode=fast_mode,
                source=source,
                fallback=fallback,
            )
            state.nodes[idx] = node_data
            save_node_result(state.profile_uid, state.profile_name, proxy, node_data)
            state.progress += 1
            state.events.append(
                {
                    "type": "progress",
                    "progress": state.progress,
                    "total": state.total,
                    "node": node_data,
                }
            )

    except Exception as error:
        state.events.append({"type": "error", "node_name": "任务", "error": str(error)})
    finally:
        if original_mode:
            await controller.set_mode(original_mode)
        if temp_loaded and state.runtime_path and Path(state.runtime_path).exists():
            state.events.append({"type": "message", "message": "恢复 Clash Verge 运行时配置"})
            await controller.reload_config_path(state.runtime_path, force=True)
        if temp_generated_profile_path:
            Path(temp_generated_profile_path).unlink(missing_ok=True)
        state.is_running = False
        state.current_node = ""
        state.checker.clear_cache()
        state.events.append({"type": "complete", "total": len(state.nodes)})


async def _check_node(
    idx: int,
    proxy: dict[str, object],
    name: str,
    selector: str,
    controller: ClashController,
    proxy_url: str,
    fast_mode: bool,
    source: str,
    fallback: bool,
) -> dict[str, object]:
    try:
        switched = await controller.switch_proxy(selector, name)
        if not switched:
            return {
                "id": idx,
                "original_name": name,
                "name": f"{name}【❌ 切换失败】",
                "ip": "❓",
                "status": "❌ 切换失败",
                "proxy_config": proxy,
            }

        await asyncio.sleep(1)
        if fast_mode:
            result = await state.checker.check_fast(proxy_url, source=source, fallback=fallback)
        else:
            result = await state.checker.check_browser(proxy=proxy_url)

        status = _status_from_result(result)
        return {
            "id": idx,
            "original_name": name,
            "name": f"{name}{result.get('full_string', '')}",
            "ip": result.get("ip", "❓"),
            "risk": result.get("pure_score", "❓"),
            "bot": result.get("bot_score", "N/A"),
            "shared": result.get("shared_users", "N/A"),
            "type": result.get("ip_attr", "❓"),
            "native": result.get("ip_src", "❓"),
            "source": result.get("source", "unknown"),
            "status": status,
            "proxy_config": proxy,
        }
    except Exception as error:
        return {
            "id": idx,
            "original_name": name,
            "name": f"{name}【❌ Error】",
            "ip": "❓",
            "status": "❌ 失败",
            "error": str(error),
            "proxy_config": proxy,
        }


@router.get("/progress")
async def progress_stream():
    async def event_generator():
        last_sent = 0
        while True:
            while last_sent < len(state.events):
                event = state.events[last_sent]
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                last_sent += 1
            if not state.is_running and last_sent >= len(state.events):
                break
            await asyncio.sleep(0.1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/stop")
async def stop_check():
    if not state.is_running:
        raise HTTPException(status_code=400, detail="没有正在运行的任务")
    state.is_running = False
    state.events.append({"type": "stopped"})
    return {"status": "stopped"}


@router.get("/nodes")
async def get_nodes():
    return {
        "nodes": state.nodes,
        "is_running": state.is_running,
        "profile_name": state.profile_name,
    }


@router.put("/nodes/{node_id}")
async def update_node(node_id: int, request: UpdateNodeRequest):
    for node in state.nodes:
        if node["id"] == node_id:
            node["name"] = request.name
            return {"status": "updated", "node": node}
    raise HTTPException(status_code=404, detail="节点不存在")


@router.delete("/nodes/{node_id}")
async def delete_node(node_id: int):
    for idx, node in enumerate(state.nodes):
        if node["id"] == node_id:
            state.nodes.pop(idx)
            return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="节点不存在")


@router.get("/exports")
async def list_exports(http_request: Request):
    exports_dir = Path("exports")
    if not exports_dir.exists():
        return {"files": []}

    files = [
        _export_file_payload(path, http_request)
        for path in exports_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}
    ]
    files.sort(key=lambda item: item["modified_ts"], reverse=True)
    return {"files": files}


@router.post("/export")
async def export_yaml(request: ExportRequest, http_request: Request):
    selected_nodes = [node for node in state.nodes if node["id"] in request.node_ids]
    if not selected_nodes:
        raise HTTPException(status_code=400, detail="请选择要导出的节点")
    if not state.original_yaml:
        raise HTTPException(status_code=400, detail="没有可导出的原始 YAML")

    name_map = {node["original_name"]: node["name"] for node in selected_nodes}
    selected_proxy_names = [node["name"] for node in selected_nodes]
    deleted_names = {node["original_name"] for node in state.nodes if node["id"] not in request.node_ids}
    export_data = copy.deepcopy(state.original_yaml)
    export_data["proxies"] = []

    for node in selected_nodes:
        proxy = copy.deepcopy(node["proxy_config"])
        proxy["name"] = node["name"]
        export_data["proxies"].append(proxy)

    clean_export_groups(export_data, selected_proxy_names, name_map, deleted_names)

    stream = io.StringIO()
    yaml.dump(export_data, stream)
    yaml_content = stream.getvalue()

    suffix = request.output_suffix or "_checked"
    base_name = sanitize_name(state.profile_name or "clash_verge_profile")
    filename = f"{base_name}{suffix}.yaml"
    exports_dir = Path("exports")
    exports_dir.mkdir(parents=True, exist_ok=True)
    filepath = exports_dir / filename
    filepath.write_text(yaml_content, encoding="utf-8")

    file_payload = _export_file_payload(filepath, http_request)
    import_name = f"{state.profile_name or base_name}{suffix}"
    return {
        "yaml": yaml_content,
        **file_payload,
        "import_url": build_clash_import_url(str(file_payload["absolute_url"]), import_name),
    }


@router.get("/qr")
async def qr_code(text: str):
    if not text.strip():
        raise HTTPException(status_code=400, detail="二维码内容不能为空")
    if len(text) > 2048:
        raise HTTPException(status_code=400, detail="二维码内容过长")

    stream = io.BytesIO()
    qr = segno.make(text, error="m")
    qr.save(stream, kind="svg", scale=7, border=2, xmldecl=False)
    return Response(
        content=stream.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


def _public_base_url(http_request: Request) -> str:
    configured = os.environ.get("CLASH_CHECKER_PUBLIC_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    return str(http_request.base_url).rstrip("/")


def _mobile_base_url(http_request: Request) -> str:
    configured = os.environ.get("CLASH_CHECKER_PUBLIC_BASE_URL", "").strip()
    candidate = configured.rstrip("/") if configured else str(http_request.base_url).rstrip("/")
    return candidate if _is_mobile_reachable_base_url(candidate) else ""


def _is_mobile_reachable_base_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host in {"localhost", "0.0.0.0", "::1", "0:0:0:0:0:0:0:1"}:
        return False
    if host.startswith("127."):
        return False
    return True


def _export_file_payload(path: Path, http_request: Request) -> dict[str, object]:
    stat = path.stat()
    file_url = f"/exports/{quote(path.name)}"
    absolute_file_url = _public_base_url(http_request) + file_url
    mobile_base_url = _mobile_base_url(http_request)
    mobile_subscription_url = f"{mobile_base_url}{file_url}?v={int(stat.st_mtime)}" if mobile_base_url else ""
    return {
        "filename": path.name,
        "url": file_url,
        "absolute_url": absolute_file_url,
        "mobile_subscription_url": mobile_subscription_url,
        "mobile_available": bool(mobile_subscription_url),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "modified_ts": stat.st_mtime,
    }


def clean_export_groups(
    export_data: dict[str, object],
    selected_proxy_names: list[str],
    name_map: dict[str, str] | None = None,
    deleted_names: set[str] | None = None,
) -> None:
    original_group_names = _proxy_group_names(export_data)
    export_data["proxy-groups"] = [
        {
            "name": "节点选择",
            "type": "select",
            "proxies": _dedupe(selected_proxy_names),
        }
    ]
    _rewrite_rule_targets(
        export_data=export_data,
        original_group_names=original_group_names,
        name_map=name_map or {},
        deleted_names=deleted_names or set(),
        selected_proxy_names=set(selected_proxy_names),
    )


def _proxy_group_names(export_data: dict[str, object]) -> set[str]:
    return {
        str(group.get("name"))
        for group in export_data.get("proxy-groups", [])
        if isinstance(group, dict) and group.get("name")
    }


def _rewrite_rule_targets(
    export_data: dict[str, object],
    original_group_names: set[str],
    name_map: dict[str, str],
    deleted_names: set[str],
    selected_proxy_names: set[str],
) -> None:
    rules = export_data.get("rules")
    if not isinstance(rules, list):
        return

    rewritten_rules: list[object] = []
    for rule in rules:
        if not isinstance(rule, str) or "," not in rule:
            rewritten_rules.append(rule)
            continue

        parts = [part.strip() for part in rule.split(",")]
        target_index = -2 if len(parts) >= 3 and parts[-1].lower() == "no-resolve" else -1
        target = parts[target_index]
        normalized_target = _clean_rule_target(
            target=target,
            original_group_names=original_group_names,
            name_map=name_map,
            deleted_names=deleted_names,
            selected_proxy_names=selected_proxy_names,
        )
        parts[target_index] = normalized_target
        rewritten_rules.append(",".join(parts))
    export_data["rules"] = rewritten_rules


def _clean_rule_target(
    target: str,
    original_group_names: set[str],
    name_map: dict[str, str],
    deleted_names: set[str],
    selected_proxy_names: set[str],
) -> str:
    if target in _builtin_proxy_names() or target == "节点选择":
        return target
    if target in selected_proxy_names:
        return target
    if target == "全球直连":
        return "DIRECT"
    if target == "广告拦截":
        return "REJECT"
    if target in name_map:
        return name_map[target]
    if target in deleted_names:
        return "节点选择"
    if target in original_group_names:
        return "节点选择"
    return "节点选择"


async def _resolve_selector(controller: ClashController, requested: str, proxies: list[dict[str, object]]) -> str | None:
    requested = (requested or "auto").strip()
    if requested.lower() != "auto":
        return requested

    proxy_names = {proxy.get("name") for proxy in proxies if proxy.get("name")}
    all_proxies = await controller.get_proxies() or {}
    preferred = ["GLOBAL", "Proxy", "PROXY", "节点选择", "🚀 节点选择"]

    for name in preferred:
        group = all_proxies.get(name)
        if _selector_contains(group, proxy_names):
            return name

    for name, group in all_proxies.items():
        if _selector_contains(group, proxy_names):
            return name
    return None


def _selector_contains(group: object, proxy_names: set[str]) -> bool:
    if not isinstance(group, dict):
        return False
    group_type = str(group.get("type", "")).lower()
    if "selector" not in group_type:
        return False
    names = set(group.get("all") or [])
    return bool(names & proxy_names)


def _parse_skip_keywords(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _should_skip(name: str, skip_keywords: list[str]) -> bool:
    return any(keyword in name for keyword in skip_keywords)


def _build_nodes(
    proxies: list[dict[str, object]],
    cached_results: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], list[tuple[int, dict[str, object]]]]:
    nodes: list[dict[str, object]] = []
    pending_items: list[tuple[int, dict[str, object]]] = []
    for idx, proxy in enumerate(proxies):
        name = proxy.get("name", f"Node {idx}")
        cached = cached_results.get(node_key(proxy))
        if cached:
            node = {
                **cached,
                "id": idx,
                "original_name": name,
                "proxy_config": proxy,
                "status": cached.get("status", "cached"),
            }
        else:
            node = {
                "id": idx,
                "original_name": name,
                "name": name,
                "ip": "...",
                "risk": "",
                "shared": "",
                "bot": "",
                "type": "",
                "native": "",
                "source": "",
                "status": "pending",
                "proxy_config": proxy,
            }
            pending_items.append((idx, proxy))
        nodes.append(node)
    return nodes, pending_items


def _write_temp_profile(config_data: dict[str, object], profile_uid: str) -> Path:
    temp_dir = Path(".runtime")
    temp_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{profile_uid or 'profile'}_{uuid.uuid4().hex}.yaml"
    temp_path = temp_dir / filename
    stream = io.StringIO()
    yaml.dump(config_data, stream)
    temp_path.write_text(stream.getvalue(), encoding="utf-8")
    return temp_path


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _builtin_proxy_names() -> set[str]:
    return {
        "DIRECT",
        "REJECT",
        "REJECT-DROP",
        "PASS",
        "COMPATIBLE",
        "GLOBAL",
    }


def _status_from_result(result: dict[str, object]) -> str:
    source = result.get("source")
    if source == "ippure":
        return "✅ IPPure"
    if source in {"timeout", "failed"}:
        return "❌"
    return "⚠️"
