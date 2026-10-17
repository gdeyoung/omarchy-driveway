"""Backend smoke tests (no root, no side effects on real mounts).

Run: python3 tests/test_driveway.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = [str(ROOT / "bin" / "driveway")]


def run_cli(*args, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(CLI + list(args), capture_output=True, text=True,
                          timeout=60, env=env)


class TestList(unittest.TestCase):
    def test_list_shape(self):
        out = run_cli("list")
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertIn("drives", data)
        self.assertIn("error", data)
        for d in data["drives"]:
            for key in ("key", "kind", "mounted", "size", "used", "pct", "eject"):
                self.assertIn(key, d)

    def test_system_row(self):
        data = json.loads(run_cli("list").stdout)
        system = [d for d in data["drives"] if d["kind"] == "system"]
        self.assertEqual(len(system), 1)
        self.assertEqual(system[0]["mountpoint"], "/")
        self.assertGreater(system[0]["size"], 0)
        self.assertFalse(system[0]["removable"])

    def test_no_root_flag(self):
        data = json.loads(run_cli("list", "--no-root").stdout)
        self.assertEqual([d for d in data["drives"] if d["kind"] == "system"], [])


class TestCloud(unittest.TestCase):
    def test_status_shape_without_rclone(self):
        out = run_cli("cloud", "status")
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        for key in ("rclone", "unit", "mountRoot", "drives"):
            self.assertIn(key, data)
        self.assertIsInstance(data["drives"], list)

    def test_install_unit_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_cli("cloud", "install-unit",
                          env_extra={"DRIVEWAY_UNIT_DIR": tmp})
            data = json.loads(out.stdout)
            self.assertTrue(data["changed"], data)
            unit = Path(tmp) / "driveway-cloud@.service"
            self.assertTrue(unit.is_file())
            # idempotent: second run is a no-op
            out2 = run_cli("cloud", "install-unit",
                           env_extra={"DRIVEWAY_UNIT_DIR": tmp})
            self.assertFalse(json.loads(out2.stdout)["changed"])


class TestVersion(unittest.TestCase):
    def test_version(self):
        data = json.loads(run_cli("version").stdout)
        self.assertEqual(data["id"], "gdeyoung.driveway")
        self.assertTrue(data["version"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
