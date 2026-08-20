from __future__ import annotations

import asyncio
import copy
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from desktop.verge_profiles import VergeProfile
from routers.api import export_yaml
from schemas import ExportRequest
from state import state


def request_for_local_server() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/export",
            "raw_path": b"/api/export",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("test", 1234),
            "server": ("127.0.0.1", 8080),
        }
    )


def checked_profile(url: str, uid: str = "checked-profile") -> VergeProfile:
    return VergeProfile(
        uid=uid,
        name="Example_checked",
        profile_type="remote",
        file=f"{uid}.yaml",
        path=f"/profiles/{uid}.yaml",
        url=url,
        is_current=False,
        supported=True,
        reason="",
    )


class ExportImportFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_cwd = Path.cwd()
        self.original_state = {
            key: copy.deepcopy(getattr(state, key))
            for key in (
                "nodes",
                "original_yaml",
                "app_home",
                "profile_uid",
                "profile_name",
                "profile_path",
                "runtime_path",
                "is_running",
            )
        }
        self.temp_dir = tempfile.TemporaryDirectory()
        os.chdir(self.temp_dir.name)
        proxy = {
            "name": "Node A",
            "type": "ss",
            "server": "203.0.113.8",
            "port": 443,
            "cipher": "aes-128-gcm",
            "password": "test-only",
        }
        state.nodes = [
            {
                "id": 0,
                "original_name": "Node A",
                "name": "Node A",
                "proxy_config": proxy,
            }
        ]
        state.original_yaml = {"proxies": [proxy], "proxy-groups": [], "rules": []}
        state.app_home = "/fake/clash-verge"
        state.profile_uid = "source-profile"
        state.profile_name = "Example"
        state.is_running = False

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        for key, value in self.original_state.items():
            setattr(state, key, value)
        self.temp_dir.cleanup()

    def run_export(self) -> dict[str, object]:
        return asyncio.run(
            export_yaml(
                ExportRequest(node_ids=[0], output_suffix="_checked"),
                request_for_local_server(),
            )
        )

    def test_existing_profile_prevents_duplicate_import(self) -> None:
        existing_url = (
            "http://localhost:8080/exports/Example_checked.yaml"
            "?name=Example_checked&v=123"
        )
        context = SimpleNamespace(profiles=[checked_profile(existing_url)])

        with patch("routers.api.discover_verge", return_value=context):
            payload = self.run_export()

        self.assertEqual(payload["import_status"], "existing")
        self.assertEqual(payload["import_url"], "")
        self.assertEqual(payload["existing_profile_count"], 1)
        self.assertTrue(Path("exports/Example_checked.yaml").exists())

    def test_first_export_still_offers_one_time_import(self) -> None:
        context = SimpleNamespace(profiles=[])

        with patch("routers.api.discover_verge", return_value=context):
            payload = self.run_export()

        self.assertEqual(payload["import_status"], "new")
        self.assertTrue(str(payload["import_url"]).startswith("clash://install-config?"))

    def test_duplicate_existing_profiles_are_reported_without_another_import(self) -> None:
        existing_url = "http://127.0.0.1:8080/exports/Example_checked.yaml"
        context = SimpleNamespace(
            profiles=[
                checked_profile(existing_url, uid="checked-one"),
                checked_profile(f"{existing_url}?v=456", uid="checked-two"),
            ]
        )

        with patch("routers.api.discover_verge", return_value=context):
            payload = self.run_export()

        self.assertEqual(payload["import_status"], "existing")
        self.assertEqual(payload["existing_profile_count"], 2)
        self.assertEqual(payload["import_url"], "")

    def test_lookup_failure_preserves_export_but_disables_import(self) -> None:
        with patch("routers.api.discover_verge", side_effect=PermissionError("blocked")):
            payload = self.run_export()

        self.assertEqual(payload["import_status"], "unknown")
        self.assertEqual(payload["import_url"], "")
        self.assertTrue(payload["import_lookup_warning"])
        self.assertTrue(Path("exports/Example_checked.yaml").exists())

    def test_running_check_rejects_export_without_writing_file(self) -> None:
        state.is_running = True

        with self.assertRaises(HTTPException) as raised:
            self.run_export()

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("检测任务执行中", str(raised.exception.detail))
        self.assertFalse(Path("exports/Example_checked.yaml").exists())


if __name__ == "__main__":
    unittest.main()
