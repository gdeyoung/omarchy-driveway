"""Cache-cap settings: global default + per-remote overrides (v0.4).

Covers size validation, settings/env-file round-trips, precedence
(override > global > template), and the template's EnvironmentFile hooks.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from driveway import cloud  # noqa: E402


def _sandbox():
    d = tempfile.mkdtemp(prefix="dw-cache-test.")
    return d, mock.patch.dict(os.environ, {"DRIVEWAY_CONFIG_DIR": d})


class TestNormalizeSize(unittest.TestCase):
    def test_suffixes_and_off(self):
        for ok in ("10G", "500M", "1.5T", "64k", "2Gi", "0", "1073741824", "32B"):
            self.assertEqual(cloud.normalize_size(ok), ok, ok)
        self.assertEqual(cloud.normalize_size("off"), "0")
        self.assertEqual(cloud.normalize_size(" UNLIMITED "), "0")

    def test_invalid(self):
        for bad in ("", "10X", "G", "ten gigs", "-5G", "1..2G", None):
            self.assertIsNone(cloud.normalize_size(bad), repr(bad))


class TestCacheGet(unittest.TestCase):
    def test_defaults_and_override(self):
        d, p = _sandbox()
        with p:
            with mock.patch.object(cloud, "remotes",
                                   return_value=[{"name": "a"}, {"name": "b"}]):
                got = cloud.cache_get()
            self.assertEqual(got["global"], cloud.TEMPLATE_CACHE_DEFAULT)
            self.assertFalse(got["globalIsCustom"])
            self.assertEqual(got["remotes"]["a"]["limit"], "10G")
            # set a global + one override
            with mock.patch.object(cloud, "remotes",
                                   return_value=[{"name": "a"}, {"name": "b"}]), \
                    mock.patch.object(cloud, "unit_state", return_value=None):
                self.assertTrue(cloud.cache_set("global", "25G")["ok"])
                self.assertTrue(cloud.cache_set("a", "2G")["ok"])
                cloud.cache_set("a", "off")     # off reverts to global below
                self.assertTrue(cloud.cache_set("a", "2G")["ok"])
            with mock.patch.object(cloud, "remotes",
                                   return_value=[{"name": "a"}, {"name": "b"}]):
                got = cloud.cache_get()
            self.assertTrue(got["globalIsCustom"])
            self.assertEqual(got["remotes"]["a"]["limit"], "2G")
            self.assertTrue(got["remotes"]["a"]["isOverride"])
            self.assertEqual(got["remotes"]["b"]["limit"], "25G")
            self.assertFalse(got["remotes"]["b"]["isOverride"])
        # env files written with 0600
        self.assertEqual((Path(d) / "cloud-defaults.env").read_text(),
                         "RCLONE_VFS_CACHE_MAX_SIZE=25G\n")
        self.assertEqual((Path(d) / "a.env").read_text(),
                         "RCLONE_VFS_CACHE_MAX_SIZE=2G\n")
        self.assertEqual((Path(d) / "cloud-defaults.env").stat().st_mode & 0o777, 0o600)

    def test_revert_to_global_removes_override(self):
        d, p = _sandbox()
        with p:
            with mock.patch.object(cloud, "remotes",
                                   return_value=[{"name": "a"}]), \
                    mock.patch.object(cloud, "unit_state", return_value=None):
                cloud.cache_set("a", "2G")
                self.assertTrue((Path(d) / "a.env").exists())
                cloud.cache_set("a", "off")     # off = 0 = no cap override
            self.assertFalse((Path(d) / "a.env").exists())
            with mock.patch.object(cloud, "remotes", return_value=[{"name": "a"}]):
                self.assertFalse(cloud.cache_get()["remotes"]["a"]["isOverride"])


class TestCacheSet(unittest.TestCase):
    def test_invalid_size_and_unknown_remote(self):
        _d, p = _sandbox()
        with p:
            r = cloud.cache_set("global", "10X")
            self.assertFalse(r["ok"])
            with mock.patch.object(cloud, "remotes", return_value=[{"name": "a"}]):
                r = cloud.cache_set("nope", "1G")
                self.assertFalse(r["ok"])

    def test_restart_of_running_units(self):
        d, p = _sandbox()
        with p:
            calls = []
            with mock.patch.object(cloud, "remotes",
                                   return_value=[{"name": "a"}]), \
                    mock.patch.object(cloud, "unit_state",
                                      side_effect=lambda n: "active" if n == "a" else None), \
                    mock.patch.object(cloud, "_run",
                                      side_effect=lambda c, timeout=10:
                                      calls.append(c) or (0, "")):
                r = cloud.cache_set("a", "3G")
            self.assertTrue(r["ok"])
            self.assertEqual(r["restarted"], ["a"])
            self.assertTrue(any("restart" in " ".join(c) and "a" in " ".join(c)
                                for c in calls))


class TestTemplateHooks(unittest.TestCase):
    def test_template_has_env_file_chain_and_default(self):
        body = cloud.unit_source().read_text()
        self.assertIn("Environment=RCLONE_VFS_CACHE_MAX_SIZE="
                      + cloud.TEMPLATE_CACHE_DEFAULT, body)
        # precedence chain: defaults file must be read BEFORE per-remote file
        di = body.index("cloud-defaults.env")
        ri = body.index("%i.env")
        self.assertLess(di, ri)


if __name__ == "__main__":
    unittest.main()
