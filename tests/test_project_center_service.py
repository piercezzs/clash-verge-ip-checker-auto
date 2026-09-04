import importlib.machinery
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_port import PortPreference


ROOT = Path(__file__).resolve().parents[1]


def _load_lifecycle_module():
    path = ROOT / "scripts" / "project_center_service"
    loader = importlib.machinery.SourceFileLoader("project_center_service_module", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


LIFECYCLE = _load_lifecycle_module()


def _status(port, state, managed=False, pid=None, detail=""):
    return {
        "app": LIFECYCLE.APP,
        "status": state,
        "pid": pid,
        "managed": managed,
        "detail": detail,
        "health": {},
        "port": port,
        "openUrl": f"http://127.0.0.1:{port}/",
    }


class ProjectCenterServiceTests(unittest.TestCase):
    def test_status_projects_free_fallback_without_persisting(self):
        preference = PortPreference(8080, explicit=False, source="default")
        with patch.object(LIFECYCLE, "_configured_port", return_value=preference), patch.object(
            LIFECYCLE,
            "_service_status_for_port",
            side_effect=[
                _status(8080, "conflict", pid=57771, detail="端口 8080 被占用。"),
                _status(18080, "stopped"),
            ],
        ), patch.object(
            LIFECYCLE,
            "_port_is_available",
            side_effect=lambda port: port == 18080,
        ), patch.object(LIFECYCLE, "save_port_preference") as save:
            result = LIFECYCLE.service_status()

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["port"], 18080)
        self.assertEqual(result["openUrl"], "http://127.0.0.1:18080/")
        self.assertIn("下次启动将自动使用", result["detail"])
        save.assert_not_called()

    def test_explicit_conflict_never_falls_back(self):
        preference = PortPreference(8080, explicit=True, source="environment")
        conflict = _status(8080, "conflict", pid=57771, detail="端口 8080 被占用。")
        with patch.object(LIFECYCLE, "_configured_port", return_value=preference), patch.object(
            LIFECYCLE,
            "_service_status_for_port",
            return_value=conflict,
        ), patch.object(LIFECYCLE, "select_available_port") as select:
            result = LIFECYCLE.service_status()

        self.assertEqual(result, conflict)
        select.assert_not_called()

    def test_stop_does_not_signal_foreign_listener(self):
        conflict = _status(8080, "conflict", pid=57771, detail="端口 8080 被占用。")
        with patch.object(
            LIFECYCLE,
            "_service_status_for_port",
            return_value=conflict,
        ), patch.object(LIFECYCLE, "_listener_pids", return_value=[57771]), patch.object(
            LIFECYCLE,
            "_verified_listener_pids",
            return_value=[],
        ), patch.object(LIFECYCLE, "_signal_pid") as signal:
            with self.assertRaisesRegex(LIFECYCLE.LifecycleError, "端口 8080 被占用"):
                LIFECYCLE._stop_service_on_port(8080)

        signal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
