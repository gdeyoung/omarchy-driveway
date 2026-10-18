"""Tests for driveway v0.3 cloud features: quota cache, mount-all,
diagnose/remedy, provider expansion (box/pcloud/s3).

Run: python3 -m unittest tests.test_cloud_v03 -v
All rclone/systemctl calls are mocked; nothing hits the network.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from driveway import cloud, wizard  # noqa: E402


def sandbox(tmp: Path):
    cloud.STATE_DIR = tmp / "dw"
    cloud.ABOUT_CACHE = cloud.STATE_DIR / "about.json"


def fake_run(responses):
    """responses: dict prefix -> (code, out). Returns a _run stand-in."""
    def _fake(cmd, timeout=10):
        key = " ".join(cmd[:2])
        for prefix, resp in responses.items():
            if key.startswith(prefix) or " ".join(cmd).startswith(prefix):
                return resp
        return 0, ""
    return _fake


class TestAbout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        sandbox(Path(self.tmp.name))

    def test_parses_and_caches(self):
        calls = []
        resp = (0, json.dumps({"used": 11, "total": 2000}))

        def _run(cmd, timeout=10):
            calls.append(cmd)
            return resp
        with mock.patch.object(cloud, "_run", _run):
            e1 = cloud.about("gd", now=1000.0)
            e2 = cloud.about("gd", now=1000.0 + 10)
        self.assertEqual((e1["used"], e1["total"]), (11, 2000))
        self.assertIsNone(e1["error"])
        self.assertEqual(len(calls), 1)          # second call hit the cache
        self.assertEqual(e2["used"], 11)

    def test_error_cached_shorter(self):
        n = [0]

        def _run(cmd, timeout=10):
            n[0] += 1
            if n[0] == 1:
                return 1, "some failure text"
            return 0, json.dumps({"used": 5, "total": 10})
        with mock.patch.object(cloud, "_run", _run):
            e1 = cloud.about("gd", now=1000.0)
            self.assertIsNotNone(e1["error"])
            e2 = cloud.about("gd", now=1000.0 + 30)     # <60s: still cached
            self.assertIsNotNone(e2["error"])
            e3 = cloud.about("gd", now=1000.0 + 61)     # >60s: retried
            self.assertIsNone(e3["error"])
        self.assertEqual(n[0], 2)

    def test_status_rows_carry_about(self):
        rems = [{"name": "gd", "type": "drive"}]
        with mock.patch.object(cloud, "rclone_installed", lambda: True), \
             mock.patch.object(cloud, "remotes", lambda: rems), \
             mock.patch.object(cloud, "mounted_rclone", lambda: {}), \
             mock.patch.object(cloud, "unit_state", lambda n: None), \
             mock.patch.object(cloud, "_about_warm_one", lambda r: None), \
             mock.patch.object(cloud, "_about_load",
                               lambda: {"gd": {"used": 1, "total": 2,
                                               "error": None, "ts": 0}}):
            s = cloud.status()
        self.assertEqual(s["drives"][0]["about"]["total"], 2)

    def test_warm_one_refreshes_single_stale(self):
        rems = [{"name": "a", "type": "drive"}, {"name": "b", "type": "drive"}]
        refreshed = []
        with mock.patch.object(cloud, "_about_load", lambda: {}), \
             mock.patch.object(cloud, "about",
                               lambda n, force=False, now=None:
                               refreshed.append(n) or {}):
            cloud._about_warm_one(rems)
            cloud._about_warm_one(rems)
        self.assertEqual(len(refreshed), 2)      # one per call, not all at once


class TestMountAll(unittest.TestCase):
    def _patched(self, rems, mounted):
        return mock.patch.multiple(
            cloud, remotes=lambda: rems, mounted_rclone=lambda: mounted,
            install_unit=lambda: {"changed": False},
            mount_point_for=lambda n: Path("/tmp/mnt") / n)

    def test_starts_all_unmounted(self):
        rems = [{"name": "a", "type": "drive"}, {"name": "b", "type": "drive"},
                {"name": "c", "type": "drive"}]
        started = []

        def _run(cmd, timeout=10):
            if cmd[:3] == ["systemctl", "--user", "start"]:
                started.extend(cmd[3:])
                return 0, ""
            return 0, ""
        with self._patched(rems, {"c": "/x"}), \
             mock.patch.object(cloud, "_run", _run), \
             mock.patch.object(Path, "mkdir", lambda self, *a, **k: None), \
             mock.patch.object(cloud.os, "chmod", lambda *a: None):
            res = cloud.mount_all()
        self.assertTrue(res["ok"])
        self.assertEqual(sorted(res["started"]), ["a", "b"])
        self.assertEqual(len(started), 2)        # ONE systemctl call

    def test_unmount_all_stops_and_sweeps(self):
        rems = [{"name": "a", "type": "drive"}, {"name": "b", "type": "drive"}]
        cmds = []

        def _run(cmd, timeout=10):
            cmds.append(cmd)
            return 0, ""
        with self._patched(rems, {"a": "/mnt/a"}), \
             mock.patch.object(cloud, "_run", _run):
            res = cloud.unmount_all()
        self.assertTrue(res["ok"])
        self.assertTrue(any(c[0] == "fusermount3" for c in cmds))


class TestDiagnose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        sandbox(Path(self.tmp.name))

    def _unit(self, active="failed", result="exit-code", restarts=0):
        return {"ActiveState": active, "SubState": "dead", "Result": result,
                "NRestarts": str(restarts)}

    def test_expired_token_wants_reconnect(self):
        with mock.patch.object(cloud, "unit_state",
                               lambda n: self._unit()), \
             mock.patch.object(cloud, "mounted_rclone", lambda: {}), \
             mock.patch.object(cloud, "about",
                               lambda n, force=False:
                               {"error": "invalid_grant: refresh token "
                                         "expired", "used": 0, "total": 0}), \
             mock.patch.object(cloud, "clock_synced", lambda: True):
            d = cloud.diagnose("gd")
        self.assertEqual(d["remedy"], "reconnect")
        self.assertIn("sign-in", d["problem"])

    def test_auth_error_and_bad_clock_wants_clock_fix(self):
        with mock.patch.object(cloud, "unit_state",
                               lambda n: self._unit()), \
             mock.patch.object(cloud, "mounted_rclone", lambda: {}), \
             mock.patch.object(cloud, "about",
                               lambda n, force=False:
                               {"error": "401 unauthorized", "used": 0,
                                "total": 0}), \
             mock.patch.object(cloud, "clock_synced", lambda: False):
            d = cloud.diagnose("gd")
        self.assertEqual(d["remedy"], "fix-clock")

    def test_restart_loop(self):
        with mock.patch.object(cloud, "unit_state",
                               lambda n: self._unit(restarts=5)), \
             mock.patch.object(cloud, "mounted_rclone", lambda: {}), \
             mock.patch.object(cloud, "about",
                               lambda n, force=False:
                               {"error": "dial tcp: network unreachable",
                                "used": 0, "total": 0}), \
             mock.patch.object(cloud, "clock_synced", lambda: True):
            d = cloud.diagnose("gd")
        self.assertEqual(d["remedy"], "restart")
        self.assertIn("restart loop", d["problem"])

    def test_hung_mount(self):
        with mock.patch.object(cloud, "unit_state",
                               lambda n: self._unit(active="active",
                                                    result="success")), \
             mock.patch.object(cloud, "mounted_rclone",
                               lambda: {"gd": "/mnt/gd"}), \
             mock.patch.object(cloud.os.path, "exists", lambda p: True), \
             mock.patch.object(cloud.lister, "rclone_pending",
                               lambda url, fs, timeout=None: -1):
            d = cloud.diagnose("gd")
        self.assertEqual(d["state"], "hung")
        self.assertEqual(d["remedy"], "restart")

    def test_healthy(self):
        with mock.patch.object(cloud, "unit_state",
                               lambda n: self._unit(active="active",
                                                    result="success")), \
             mock.patch.object(cloud, "mounted_rclone",
                               lambda: {"gd": "/mnt/gd"}), \
             mock.patch.object(cloud.os.path, "exists", lambda p: False):
            d = cloud.diagnose("gd")
        self.assertEqual(d["state"], "mounted")
        self.assertIsNone(d["problem"])


class TestProviders(unittest.TestCase):
    def test_new_providers_listed(self):
        keys = {p["key"] for p in wizard.providers()}
        self.assertTrue({"box", "pcloud", "s3"} <= keys)

    def test_s3_remote_fields(self):
        with tempfile.TemporaryDirectory() as td:
            conf = Path(td) / "rclone.conf"
            with mock.patch.object(wizard, "RCLONE_CONF", conf):
                res = wizard.add_remote(
                    "mini", "s3", user="AKIAEXAMPLE", password="s3cr3tKEY",
                    url="http://minio.lan:9000", extra={"region": "us-east-1"})
                body = conf.read_text()
            self.assertTrue(res["ok"])
            self.assertIn("access_key_id = AKIAEXAMPLE", body)
            self.assertIn("secret_access_key = s3cr3tKEY", body)
            self.assertIn("endpoint = http://minio.lan:9000", body)
            self.assertIn("region = us-east-1", body)
            self.assertNotIn("obscured", body)

    def test_s3_requires_keys(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(wizard, "RCLONE_CONF",
                                   Path(td) / "rclone.conf"):
                with self.assertRaises(wizard.WizardError):
                    wizard.add_remote("nope", "s3")

class TestDebugLogRedaction(unittest.TestCase):
    """Tokens must never survive _debug_log, in either rclone output shape."""

    def test_pipe_and_pty_shapes_redacted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"DRIVEWAY_CONFIG_DIR": d}):
            pipe = ('stdout:\n{"access_token":"ABC.DEF.GHI","token_type":"Bearer",'
                    '"refresh_token":"REFR","expiry":"x"}\n')
            pty = ('Paste the following into your remote machine --->\n'
                   'eyJhbGciOiJSUzI1NiIsImtpZCI6IjFhMjM0NTY3ODlhYmNkZWYxMjM0NTY3ODlhYmNkZWYifQ\n'
                   '<---End paste\n')
            wizard._debug_log(pipe, 0, "pipes")
            wizard._debug_log(pty, 0, "pty")
            log = open(os.path.join(d, "authorize-debug.log")).read()
            for secret in ("ABC.DEF.GHI", "REFR",
                           "eyJhbGciOiJSUzI1NiIsImtpZCI6IjFh"):
                self.assertNotIn(secret, log)


class TestAuthorizePipes(unittest.TestCase):
    """authorize must run over PIPES: full JSON token on stdout, chatter on
    stderr (community/ODrive-verified; the pty path prints base64 instead)."""

    class _Proc:
        def __init__(self, out="", err="", code=0):
            import subprocess as sp
            self._out, self._err, self.returncode = out, err, code
            self._te = getattr(sp, "_TE", None)
        def communicate(self, timeout=None):
            import subprocess as sp
            if self._te:
                self._te = False
                raise sp.TimeoutExpired(cmd="rclone", timeout=timeout)
            return self._out, self._err
        def kill(self):
            pass

    def _auth(self, proc):
        with mock.patch.object(wizard.subprocess, "Popen", return_value=proc):
            return wizard.authorize_oauth("drive")

    def test_token_json_from_stdout(self):
        p = self._Proc(out='{"access_token":"A","token_type":"Bearer",'
                          '"refresh_token":"R","expiry":"2026"}',
                      err='NOTICE: Waiting for code...\nNOTICE: Got code\n')
        res = self._auth(p)
        self.assertIn("access_token", res["token"])

    def test_missing_binary(self):
        import subprocess as sp
        with mock.patch.object(wizard.subprocess, "Popen",
                               side_effect=FileNotFoundError()):
            with self.assertRaises(wizard.WizardError) as cm:
                wizard.authorize_oauth("drive")
        self.assertIn("not installed", str(cm.exception))

    def test_failure_reports_stderr_tail(self):
        p = self._Proc(out="", err="NOTICE: bad\nError: invalid_grant", code=1)
        with self.assertRaises(wizard.WizardError) as cm:
            self._auth(p)
        self.assertIn("invalid_grant", str(cm.exception))

    def test_timeout(self):
        import subprocess as sp
        p = self._Proc()
        p._te = True
        with self.assertRaises(wizard.WizardError) as cm:
            self._auth(p)
        self.assertIn("timed out", str(cm.exception))

    def test_no_token_is_error(self):
        p = self._Proc(out="nothing useful", err="")
        with self.assertRaises(wizard.WizardError):
            self._auth(p)


if __name__ == "__main__":
    unittest.main()
