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

from core.clash_api import ClashController, proxy_endpoints_from_configs
from desktop.importer import build_clash_import_url, find_matching_profiles
from desktop.verge_profiles import discover_verge, load_profile_config, sanitize_name
from schemas import ExportRequest, StartProfileRequest
from state import state
from storage.ip_cache import (
    IP_CACHE_TTL_DAYS,
    load_combined_ip_cache,
    save_shared_ip_cache,
)
from storage.results_store import get_recent_profile_ip_results, node_key, save_node_result

router = APIRouter(prefix="/api")
yaml = YAML()
yaml.preserve_quotes = True


@router.get("/verge/discover")
async def discover(app_home: str = ""):
    """Find local Clash Verge profiles and controller defaults."""
    context = discover_verge(app_home or None)
    payload = context.to_dict()
    controller = ClashController(context.controller_url, context.controller_secret)
    configs = await controller.get_configs()
    payload.update(
        {
            "controller_connected": configs is not None,
            "controller_mode": str((configs or {}).get("mode") or ""),
            "active_task": _active_task_payload(),
        }
    )
    return payload


@router.post("/preflight-profile")
async def preflight_profile_check(request: StartProfileRequest):
    """Validate the planned check and describe its live Clash impact."""
    if state.is_running:
        raise HTTPException(status_code=409, detail="已有检测任务正在运行或恢复网络状态")

    try:
        refresh_remote = bool(request.config.get("refresh_remote", False))
        config_data, profile, source_refreshed = await load_profile_config(
            request.app_home,
            request.profile_uid,
            refresh_remote=refresh_remote,
        )
        context = discover_verge(request.app_home or None)
        active_proxies = _active_profile_proxies(config_data, request.config)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    controller = _controller_for_config(request.config, context)
    configs = await controller.get_configs()
    if not configs:
        raise HTTPException(
            status_code=400,
            detail="无法连接 Clash External Controller，请先确认 Clash Verge 内核、External Controller 和密钥均可用",
        )

    all_proxies = await controller.get_proxies()
    if all_proxies is None:
        raise HTTPException(status_code=400, detail="无法读取 Clash 代理组，请检查 Controller 权限")

    will_temp_load = source_refreshed or (
        bool(request.config.get("temp_load_profile", False)) and not profile.is_current
    )
    requested_selector = str(request.config.get("selector_name", "auto"))
    selector = _resolve_selector_from_map(requested_selector, active_proxies, all_proxies)
    if not selector and will_temp_load:
        selector = _resolve_selector_from_profile(requested_selector, active_proxies, config_data)
    if not selector:
        raise HTTPException(
            status_code=400,
            detail="无法识别可切换的代理组；非当前订阅请启用“临时加载非当前订阅”，或手动填写有效代理组",
        )

    current_proxy = _selector_current(all_proxies.get(selector))
    warnings = [
        "检测期间会临时切换为 Clash 全局模式，并逐个切换代理节点。",
        "所有经本机 Clash 联网的下载、同步、SSH、浏览器和 API 任务都可能换 IP 或短暂中断。",
    ]
    if will_temp_load:
        warnings.append("本次还会临时加载所选订阅到 Clash 内核，完成后再恢复原运行时配置。")
    if not context.running:
        warnings.append("未检测到 Clash Verge 图形进程，但当前 External Controller 可以连接。")

    return {
        "profile": profile.to_dict(),
        "node_count": len(active_proxies),
        "selector": selector,
        "current_mode": str(configs.get("mode") or "unknown"),
        "current_proxy": current_proxy or "未知",
        "will_temp_load": will_temp_load,
        "source_refreshed": source_refreshed,
        "warnings": warnings,
    }


@router.post("/start-profile")
async def start_profile_check(request: StartProfileRequest):
    """Start checking a selected Clash Verge profile."""
    if not bool(request.config.get("impact_confirmed", False)):
        raise HTTPException(status_code=400, detail="请先完成网络影响确认")
    if state.is_running:
        raise HTTPException(status_code=409, detail="任务正在运行或恢复 Clash 网络状态")

    state.task_id = str(uuid.uuid4())
    state.is_running = True
    state.phase = "preparing"
    state.stop_requested = False
    state.run_task = None
    state.profile_uid = request.profile_uid
    state.events = []
    try:
        refresh_remote = bool(request.config.get("refresh_remote", False))
        config_data, profile, source_refreshed = await load_profile_config(
            request.app_home,
            request.profile_uid,
            refresh_remote=refresh_remote,
        )
        context = discover_verge(request.app_home or None)
        active_proxies = _active_profile_proxies(config_data, request.config)
    except Exception as error:
        state.is_running = False
        state.phase = "idle"
        state.stop_requested = False
        raise HTTPException(status_code=400, detail=str(error)) from error

    nodes, pending_items = _build_nodes(active_proxies, {})

    state.original_yaml = config_data
    state.app_home = context.app_home
    state.profile_uid = profile.uid
    state.profile_name = profile.name
    state.profile_path = profile.path
    state.runtime_path = context.runtime_path
    state.nodes = nodes
    state.progress = 0
    state.total = len(active_proxies)
    state.current_node = ""
    state.phase = "stopping" if state.stop_requested else "running"

    run_config = dict(request.config)
    if not run_config.get("clash_api_url"):
        run_config["clash_api_url"] = context.controller_url
    if not run_config.get("clash_api_secret"):
        run_config["clash_api_secret"] = context.controller_secret
    run_config["profile_is_current"] = profile.is_current
    run_config["force_load_profile"] = False
    run_config["temp_generated_profile_path"] = ""

    if source_refreshed:
        try:
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
        except Exception as error:
            state.is_running = False
            state.phase = "idle"
            state.stop_requested = False
            raise HTTPException(status_code=500, detail=f"准备临时订阅失败：{error}") from error

    if pending_items:
        state.run_task = asyncio.create_task(_run_check(pending_items, run_config))
    else:
        state.is_running = False
        state.phase = "idle"
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
    """Load fresh IP results through the profile's last known node-to-IP observations."""
    if state.is_running:
        return {
            "profile": {"uid": state.profile_uid, "name": state.profile_name},
            "nodes": state.nodes,
            "cached": 0,
            "total": state.total,
            "checked_date": "",
            "checked_at": "",
            "cache_ttl_days": IP_CACHE_TTL_DAYS,
            "cache_warning": "",
            "is_running": True,
            "phase": state.phase,
            "progress": state.progress,
            "current_node": state.current_node,
            "task_id": state.task_id,
        }

    try:
        config_data, profile, _ = await load_profile_config(
            request.app_home,
            request.profile_uid,
            refresh_remote=False,
        )
        context = discover_verge(request.app_home or None)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    active_proxies = _active_profile_proxies(config_data, request.config)
    cache_snapshot = load_combined_ip_cache()
    mode = "fast" if bool(request.config.get("fast_mode", True)) else "browser"
    checked_at, cached_results = get_recent_profile_ip_results(
        profile.uid,
        active_proxies,
        cache_snapshot.entries,
        mode=mode,
    )
    nodes, _ = _build_nodes(active_proxies, cached_results)

    state.task_id = ""
    state.is_running = False
    state.phase = "idle"
    state.stop_requested = False
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
        "checked_date": checked_at[:10] if checked_at else "",
        "checked_at": checked_at,
        "cache_ttl_days": IP_CACHE_TTL_DAYS,
        "cache_warning": cache_snapshot.warning,
        "is_running": False,
        "phase": "idle",
    }


class _CheckStopped(Exception):
    """Internal cooperative-stop signal that still runs Clash restoration."""


async def _run_check(pending_items: list[tuple[int, dict[str, object]]], config: dict[str, object]):
    controller = ClashController(
        config.get("clash_api_url", "http://127.0.0.1:9097"),
        config.get("clash_api_secret", ""),
    )
    state.checker.headless = bool(config.get("headless", True))
    original_mode: str | None = None
    original_selections: dict[str, str] = {}
    modified_selector: str | None = None
    restore_runtime_config = False
    temp_generated_profile_path = str(config.get("temp_generated_profile_path") or "")
    cache_hits = 0
    fresh_queries = 0
    partial_results = 0
    failures = 0
    task_error = ""
    recovery_errors: list[str] = []

    cache_snapshot = load_combined_ip_cache()
    cache_warning = cache_snapshot.warning
    state.checker.configure_cache(cache_snapshot)
    if cache_snapshot.warning:
        state.events.append({"type": "message", "message": cache_snapshot.warning})

    try:
        configs = await controller.get_configs()
        if not configs:
            raise RuntimeError("无法连接 Clash External Controller")
        original_mode = str(configs.get("mode") or "") or None
        original_proxy_map = await controller.get_proxies()
        if original_proxy_map is None:
            raise RuntimeError("无法读取 Clash 代理组")
        original_selections = _selector_selections(original_proxy_map)

        if state.stop_requested:
            raise _CheckStopped()

        should_load_profile = bool(config.get("force_load_profile", False)) or (
            config.get("temp_load_profile", False) and not config.get("profile_is_current", False)
        )
        if should_load_profile:
            state.events.append({"type": "message", "message": "临时加载所选订阅到 Clash 内核"})
            restore_runtime_config = True
            loaded = await controller.reload_config_path(state.profile_path, force=True)
            if not loaded:
                raise RuntimeError("临时加载所选订阅失败，请先在 Clash Verge 中手动使用该订阅")
            await asyncio.sleep(1)

        if state.stop_requested:
            raise _CheckStopped()

        pending_proxies = [proxy for _, proxy in pending_items]
        runtime_proxy_map = await controller.get_proxies()
        if runtime_proxy_map is None:
            raise RuntimeError("无法读取 Clash 代理组")
        selector = _resolve_selector_from_map(
            str(config.get("selector_name", "auto")),
            pending_proxies,
            runtime_proxy_map,
        )
        if not selector:
            raise RuntimeError("无法自动识别可切换的代理组，请手动填写 selector")
        modified_selector = selector

        if state.stop_requested:
            raise _CheckStopped()
        if not await controller.set_mode("global"):
            raise RuntimeError("无法将 Clash 临时切换为 global 模式")
        proxy_endpoints = proxy_endpoints_from_configs(configs)
        proxy_url = proxy_endpoints.request_url
        ipv4_proxy_url = proxy_endpoints.ipv4_lookup_url
        fast_mode = bool(config.get("fast_mode", True))
        if fast_mode and not proxy_endpoints.ipv4_lookup_forced:
            state.events.append(
                {
                    "type": "message",
                    "message": "Clash 当前只有 HTTP 代理端口，无法在客户端强制 IPPure 使用 IPv4；结果仍会校验出口 IP，不一致时不会作为有效评分。",
                }
            )
        source = "ippure"
        fallback = False

        for idx, proxy in pending_items:
            if state.stop_requested:
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
                ipv4_proxy_url=ipv4_proxy_url,
                fast_mode=fast_mode,
                source=source,
                fallback=fallback,
                force_refresh_ip_cache=bool(config.get("force_refresh_ip_cache", False)),
            )
            state.nodes[idx] = node_data
            save_node_result(state.profile_uid, state.profile_name, proxy, node_data)
            if node_data.get("cache_hit"):
                cache_hits += 1
            elif node_data.get("source") == "ippure":
                fresh_queries += 1
                if node_data.get("score_status") not in {"", "available"}:
                    partial_results += 1
            else:
                failures += 1
            state.progress += 1
            state.events.append(
                {
                    "type": "progress",
                    "progress": state.progress,
                    "total": state.total,
                    "node": node_data,
                }
            )

    except _CheckStopped:
        pass
    except Exception as error:
        task_error = str(error)
    finally:
        was_stopped = state.stop_requested
        state.phase = "restoring"
        if original_mode or modified_selector or restore_runtime_config:
            state.events.append({"type": "restoring", "message": "正在恢复 Clash 网络状态"})
            try:
                recovery_errors = await _restore_clash_state(
                    controller=controller,
                    original_mode=original_mode,
                    original_selections=original_selections,
                    modified_selector=modified_selector,
                    restore_runtime_config=restore_runtime_config,
                    runtime_path=state.runtime_path,
                )
            except Exception as error:
                recovery_errors = [f"恢复过程异常：{error}"]
        if temp_generated_profile_path:
            Path(temp_generated_profile_path).unlink(missing_ok=True)
        if state.checker.cache_writable and state.checker.cache_dirty:
            try:
                save_shared_ip_cache(state.checker.cache_entries())
                state.checker.mark_cache_saved()
            except OSError as error:
                cache_warning = f"共享 IP 缓存保存失败，节点检测结果仍保存在本机 SQLite：{error}"
                state.events.append(
                    {
                        "type": "message",
                        "message": cache_warning,
                    }
                )
        state.is_running = False
        state.phase = "idle"
        state.current_node = ""
        state.checker.clear_cache()
        state.stop_requested = False
        state.run_task = None

        if recovery_errors:
            detail = "；".join(recovery_errors)
            prefix = f"检测失败：{task_error}；" if task_error else ""
            state.events.append(
                {
                    "type": "error",
                    "node_name": "任务",
                    "error": f"{prefix}Clash 网络状态恢复不完整：{detail}。请立即在 Clash Verge 中核对模式和当前节点。",
                }
            )
        elif task_error:
            state.events.append({"type": "error", "node_name": "任务", "error": task_error})
        elif was_stopped:
            state.events.append({"type": "stopped", "message": "检测已停止，Clash 网络状态已恢复"})
        else:
            state.events.append(
                {
                    "type": "complete",
                    "total": len(state.nodes),
                    "cache_hits": cache_hits,
                    "fresh_queries": fresh_queries,
                    "partial_results": partial_results,
                    "failures": failures,
                    "cache_warning": cache_warning,
                }
            )


async def _check_node(
    idx: int,
    proxy: dict[str, object],
    name: str,
    selector: str,
    controller: ClashController,
    proxy_url: str,
    ipv4_proxy_url: str,
    fast_mode: bool,
    source: str,
    fallback: bool,
    force_refresh_ip_cache: bool,
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
            result = await state.checker.check_fast(
                proxy_url,
                ipv4_proxy=ipv4_proxy_url,
                source=source,
                fallback=fallback,
                force_refresh=force_refresh_ip_cache,
            )
        else:
            result = await state.checker.check_browser(
                proxy=proxy_url,
                force_refresh=force_refresh_ip_cache,
            )

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
            "cache_hit": bool(result.get("cache_hit", False)),
            "cache_scope": result.get("cache_scope", ""),
            "cached_at": result.get("cached_at", ""),
            "score_status": result.get("score_status", ""),
            "ip_version": result.get("ip_version", ""),
            "expected_ip": result.get("expected_ip", ""),
            "detail": result.get("error", ""),
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
    if state.stop_requested:
        return {"status": "stopping", "phase": state.phase}
    state.stop_requested = True
    state.phase = "stopping"
    state.events.append({"type": "stopping", "message": "正在停止检测，随后恢复 Clash 网络状态"})
    return {"status": "stopping", "phase": state.phase}


@router.get("/nodes")
async def get_nodes():
    return {
        "nodes": state.nodes,
        "is_running": state.is_running,
        "phase": state.phase,
        "task_id": state.task_id,
        "profile_name": state.profile_name,
        "profile_uid": state.profile_uid,
        "progress": state.progress,
        "total": state.total,
        "current_node": state.current_node,
    }


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
    if state.is_running:
        raise HTTPException(status_code=409, detail="检测任务执行中，完成或停止后再导出")
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
    import_payload = _export_import_payload(
        str(file_payload["absolute_url"]),
        import_name,
    )
    return {
        "yaml": yaml_content,
        **file_payload,
        **import_payload,
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


def _export_import_payload(file_url: str, import_name: str) -> dict[str, object]:
    if not state.app_home:
        return {
            "import_status": "unknown",
            "import_url": "",
            "existing_profile_count": 0,
            "existing_profile_names": [],
            "import_lookup_warning": "未记录 Clash Verge 数据目录，无法确认是否已有对应订阅",
        }

    try:
        context = discover_verge(state.app_home)
    except Exception:
        return {
            "import_status": "unknown",
            "import_url": "",
            "existing_profile_count": 0,
            "existing_profile_names": [],
            "import_lookup_warning": "无法读取 Clash Verge 订阅列表，为避免重复，本次不提供一键导入",
        }

    matches = find_matching_profiles(file_url, context.profiles)
    if matches:
        return {
            "import_status": "existing",
            "import_url": "",
            "existing_profile_count": len(matches),
            "existing_profile_names": [profile.name for profile in matches],
            "import_lookup_warning": "",
        }

    return {
        "import_status": "new",
        "import_url": build_clash_import_url(file_url, import_name),
        "existing_profile_count": 0,
        "existing_profile_names": [],
        "import_lookup_warning": "",
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
    all_proxies = await controller.get_proxies() or {}
    return _resolve_selector_from_map(requested, proxies, all_proxies)


def _resolve_selector_from_map(
    requested: str,
    proxies: list[dict[str, object]],
    all_proxies: dict[str, object],
) -> str | None:
    requested = (requested or "auto").strip()
    proxy_names = {proxy.get("name") for proxy in proxies if proxy.get("name")}
    if requested.lower() != "auto":
        return requested if _selector_contains(all_proxies.get(requested), proxy_names) else None

    preferred = ["GLOBAL", "Proxy", "PROXY", "节点选择", "🚀 节点选择"]

    for name in preferred:
        group = all_proxies.get(name)
        if _selector_contains(group, proxy_names):
            return name

    for name, group in all_proxies.items():
        if _selector_contains(group, proxy_names):
            return name
    return None


def _resolve_selector_from_profile(
    requested: str,
    proxies: list[dict[str, object]],
    config_data: dict[str, object],
) -> str | None:
    groups: dict[str, object] = {}
    for group in config_data.get("proxy-groups") or []:
        if not isinstance(group, dict) or not group.get("name"):
            continue
        groups[str(group["name"])] = {
            "type": group.get("type", ""),
            "all": group.get("proxies") or [],
        }
    return _resolve_selector_from_map(requested, proxies, groups)


def _selector_current(group: object) -> str:
    if not isinstance(group, dict):
        return ""
    return str(group.get("now") or "")


def _selector_selections(all_proxies: dict[str, object]) -> dict[str, str]:
    selections: dict[str, str] = {}
    for name, group in all_proxies.items():
        if not isinstance(group, dict) or "selector" not in str(group.get("type", "")).lower():
            continue
        current = _selector_current(group)
        if current:
            selections[name] = current
    return selections


async def _restore_clash_state(
    controller: ClashController,
    original_mode: str | None,
    original_selections: dict[str, str],
    modified_selector: str | None,
    restore_runtime_config: bool,
    runtime_path: str,
) -> list[str]:
    errors: list[str] = []

    if restore_runtime_config:
        if not runtime_path or not Path(runtime_path).exists():
            errors.append("找不到原运行时配置")
        elif not await controller.reload_config_path(runtime_path, force=True):
            errors.append("原运行时配置加载失败")
        else:
            await asyncio.sleep(0.5)

    targets = original_selections if restore_runtime_config else {
        name: original_selections[name]
        for name in [modified_selector]
        if name and name in original_selections
    }
    if targets:
        current_proxy_map = await controller.get_proxies()
        if current_proxy_map is None:
            errors.append("无法读取恢复后的代理组")
        else:
            for selector, proxy_name in targets.items():
                group = current_proxy_map.get(selector)
                if not isinstance(group, dict):
                    errors.append(f"原代理组 {selector} 不存在")
                    continue
                if _selector_current(group) == proxy_name:
                    continue
                if not await controller.switch_proxy(selector, proxy_name):
                    errors.append(f"代理组 {selector} 未能恢复到 {proxy_name}")

    if original_mode and not await controller.set_mode(original_mode):
        errors.append(f"Clash 模式未能恢复到 {original_mode}")
    return errors


def _selector_contains(group: object, proxy_names: set[str]) -> bool:
    if not isinstance(group, dict):
        return False
    group_type = str(group.get("type", "")).lower()
    if group_type not in {"select", "selector"} and "selector" not in group_type:
        return False
    names = set(group.get("all") or [])
    return bool(names & proxy_names)


def _controller_for_config(config: dict[str, object], context: object) -> ClashController:
    api_url = str(config.get("clash_api_url") or getattr(context, "controller_url", ""))
    secret = str(config.get("clash_api_secret") or getattr(context, "controller_secret", ""))
    return ClashController(api_url, secret)


def _active_profile_proxies(
    config_data: dict[str, object],
    config: dict[str, object],
) -> list[dict[str, object]]:
    proxies = config_data.get("proxies", [])
    if not isinstance(proxies, list) or not proxies:
        raise ValueError("订阅 YAML 未找到 proxies")
    skip_keywords = _parse_skip_keywords(str(config.get("skip_keywords_str", "")))
    active_proxies = [
        proxy
        for proxy in proxies
        if isinstance(proxy, dict) and not _should_skip(str(proxy.get("name", "")), skip_keywords)
    ]
    if not active_proxies:
        raise ValueError("过滤后没有可检测节点")
    return active_proxies


def _active_task_payload() -> dict[str, object]:
    return {
        "is_running": state.is_running,
        "phase": state.phase,
        "task_id": state.task_id,
        "profile_uid": state.profile_uid,
        "profile_name": state.profile_name,
        "progress": state.progress,
        "total": state.total,
        "current_node": state.current_node,
    }


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
    if result.get("cache_hit"):
        return "♻️ IP缓存"
    source = result.get("source")
    if source == "ippure":
        score_status = result.get("score_status")
        if score_status == "ipv6_unsupported":
            return "⚠️ IPv6无评分"
        if score_status == "ip_mismatch":
            return "⚠️ 出口不一致"
        if score_status in {"unavailable", "failed"}:
            return "⚠️ IPPure无评分"
        risk = str(result.get("pure_score") or "").strip()
        if score_status == "available" or risk.endswith("%"):
            return "✅ IPPure"
        return "⚠️ IPPure无评分"
    if source in {"timeout", "failed"}:
        return "❌"
    return "⚠️"
