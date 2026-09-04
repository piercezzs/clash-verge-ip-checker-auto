from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from routers.api import (
    _restore_clash_state,
    _resolve_selector_from_profile,
    _run_check,
    start_profile_check,
    stop_check,
)
from schemas import StartProfileRequest
from state import state
from storage.ip_cache import IPCacheSnapshot


class FakeChecker:
    def __init__(self) -> None:
        self.headless = True
        self.cache_writable = True
        self.cache_dirty = False

    def configure_cache(self, _snapshot: IPCacheSnapshot) -> None:
        self.cache_dirty = False

    def clear_cache(self) -> None:
        self.cache_dirty = False

    async def check_fast(self, *_args, **_kwargs) -> dict[str, object]:
        return {
            "ip": "203.0.113.9",
            "pure_score": "12%",
            "shared_users": "1",
            "ip_attr": "住宅",
            "ip_src": "原生",
            "full_string": "",
            "source": "ippure",
            "score_status": "available",
        }


class FakeController:
    def __init__(self) -> None:
        self.mutations: list[tuple[str, ...]] = []
        self.current = "Original"

    async def get_configs(self) -> dict[str, object]:
        return {"mode": "rule", "mixed-port": 7897}

    async def get_proxies(self) -> dict[str, object]:
        return {
            "GLOBAL": {
                "type": "Selector",
                "all": ["Original", "Node A"],
                "now": self.current,
            }
        }

    async def set_mode(self, mode: str) -> bool:
        self.mutations.append(("mode", mode))
        return True

    async def switch_proxy(self, selector: str, proxy_name: str) -> bool:
        self.mutations.append(("switch", selector, proxy_name))
        self.current = proxy_name
        return True

    async def reload_config_path(self, path: str, force: bool = True) -> bool:
        self.mutations.append(("reload", path, str(force)))
        return True


class CheckLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.saved_state = {
            key: copy.copy(getattr(state, key))
            for key in (
                "checker",
                "task_id",
                "is_running",
                "phase",
                "stop_requested",
                "run_task",
                "nodes",
                "events",
                "profile_uid",
                "profile_name",
                "profile_path",
                "runtime_path",
                "progress",
                "total",
                "current_node",
            )
        }
        state.checker = FakeChecker()
        state.task_id = "test-task"
        state.is_running = False
        state.phase = "idle"
        state.stop_requested = False
        state.run_task = None
        state.nodes = []
        state.events = []
        state.profile_uid = "profile-a"
        state.profile_name = "Profile A"
        state.profile_path = "/profiles/profile-a.yaml"
        state.runtime_path = ""
        state.progress = 0
        state.total = 0
        state.current_node = ""

    def tearDown(self) -> None:
        for key, value in self.saved_state.items():
            setattr(state, key, value)

    async def test_start_requires_explicit_impact_confirmation(self) -> None:
        request = StartProfileRequest(profile_uid="profile-a", config={})

        with self.assertRaises(HTTPException) as raised:
            await start_profile_check(request)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("网络影响确认", str(raised.exception.detail))
        self.assertFalse(state.is_running)

    async def test_stop_keeps_run_locked_until_restoration_finishes(self) -> None:
        state.is_running = True
        state.phase = "running"

        response = await stop_check()

        self.assertEqual(response["status"], "stopping")
        self.assertTrue(state.is_running)
        self.assertTrue(state.stop_requested)
        self.assertEqual(state.phase, "stopping")
        self.assertEqual(state.events[-1]["type"], "stopping")

    async def test_successful_check_restores_original_proxy_then_mode(self) -> None:
        controller = FakeController()
        proxy = {"name": "Node A", "type": "ss", "server": "203.0.113.8", "port": 443}
        state.is_running = True
        state.phase = "running"
        state.nodes = [{"id": 0, "original_name": "Node A", "name": "Node A"}]
        state.total = 1

        with (
            patch("routers.api.ClashController", return_value=controller),
            patch("routers.api.load_combined_ip_cache", return_value=IPCacheSnapshot(entries={})),
            patch("routers.api.save_node_result"),
            patch("routers.api.asyncio.sleep", new=AsyncMock()),
        ):
            await _run_check([(0, proxy)], {"selector_name": "auto", "fast_mode": True})

        self.assertEqual(
            controller.mutations,
            [
                ("mode", "global"),
                ("switch", "GLOBAL", "Node A"),
                ("switch", "GLOBAL", "Original"),
                ("mode", "rule"),
            ],
        )
        self.assertFalse(state.is_running)
        self.assertEqual(state.phase, "idle")
        self.assertEqual(state.events[-1]["type"], "complete")

    async def test_temp_profile_restores_config_before_proxy_and_mode(self) -> None:
        controller = FakeController()
        controller.current = "Node A"
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_path = Path(temp_dir) / "clash-verge.yaml"
            runtime_path.write_text("mode: rule\n", encoding="utf-8")

            with patch("routers.api.asyncio.sleep", new=AsyncMock()):
                errors = await _restore_clash_state(
                    controller=controller,
                    original_mode="rule",
                    original_selections={"GLOBAL": "Original"},
                    modified_selector="GLOBAL",
                    restore_runtime_config=True,
                    runtime_path=str(runtime_path),
                )

        self.assertEqual(errors, [])
        self.assertEqual(controller.mutations[0][0], "reload")
        self.assertEqual(controller.mutations[1], ("switch", "GLOBAL", "Original"))
        self.assertEqual(controller.mutations[2], ("mode", "rule"))

    async def test_profile_selector_accepts_yaml_select_type(self) -> None:
        selector = _resolve_selector_from_profile(
            "auto",
            [{"name": "Node A"}],
            {
                "proxy-groups": [
                    {"name": "节点选择", "type": "select", "proxies": ["Node A"]},
                ]
            },
        )

        self.assertEqual(selector, "节点选择")


if __name__ == "__main__":
    unittest.main()
