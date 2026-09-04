import json
import tempfile
import unittest
from pathlib import Path

from runtime_port import (
    DEFAULT_PORT,
    PortPreference,
    PortSelectionError,
    load_port_preference,
    save_port_preference,
    select_available_port,
)


class RuntimePortTests(unittest.TestCase):
    def test_explicit_environment_port_has_priority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "port.json"
            save_port_preference(state_path, 18080)

            preference = load_port_preference(
                state_path,
                {"CLASH_CHECKER_PORT": "19090"},
            )

        self.assertEqual(preference.port, 19090)
        self.assertTrue(preference.explicit)
        self.assertEqual(preference.source, "environment")

    def test_persisted_port_is_reused_without_environment_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "port.json"
            save_port_preference(state_path, 18081)

            preference = load_port_preference(state_path, {})

        self.assertEqual(preference.port, 18081)
        self.assertFalse(preference.explicit)
        self.assertEqual(preference.source, "persisted")

    def test_missing_or_invalid_state_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "port.json"
            state_path.write_text(json.dumps({"port": 70000}), encoding="utf-8")

            preference = load_port_preference(state_path, {})

        self.assertEqual(preference.port, DEFAULT_PORT)
        self.assertEqual(preference.source, "default")

    def test_occupied_automatic_port_selects_first_available_fallback(self):
        availability = {8080: False, 18080: False, 18081: True}

        selected = select_available_port(
            PortPreference(8080, explicit=False, source="default"),
            lambda port: availability.get(port, False),
        )

        self.assertEqual(selected.port, 18081)
        self.assertEqual(selected.source, "automatic")

    def test_occupied_explicit_port_never_falls_back(self):
        with self.assertRaisesRegex(PortSelectionError, "不会自动改用"):
            select_available_port(
                PortPreference(8080, explicit=True, source="environment"),
                lambda _port: False,
            )


if __name__ == "__main__":
    unittest.main()
