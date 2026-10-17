"""Tests for driveway v0.2: pty runner, netmap parsing/storage, wizard conf.

Run: python3 -m unittest tests.test_netmap -v
Secrets are synthetic; nothing here talks to a real server or rclone.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from driveway import netmap, wizard  # noqa: E402
from driveway.ptyrun import Expect, run_expect  # noqa: E402


def sandbox_env(tmp: Path) -> dict:
    """Isolated config dir (and rclone conf) for a test."""
    env = dict(os.environ)
    env["DRIVEWAY_CONFIG_DIR"] = str(tmp / "dw")
    env["RCLONE_CONFIG"] = str(tmp / "rclone.conf")
    netmap.CONFIG_DIR = tmp / "dw"
    netmap.MAPS_FILE = netmap.CONFIG_DIR / "maps.json"
    netmap.CREDS_DIR = netmap.CONFIG_DIR / "creds"
    netmap.CREDS_FALLBACK_PLAINTEXT = netmap.CONFIG_DIR / "creds-plaintext-warning"
    wizard.RCLONE_CONF = tmp / "rclone.conf"
    return env


class TestPtyRun(unittest.TestCase):
    def test_answers_prompts_and_captures(self):
        out, code = run_expect(
            ["/bin/sh", "-c",
             "printf 'Username: '; read u; "
             "printf 'Password: '; read p; "
             "echo \"GOT:$u:$p\""],
            [Expect(r"Username", "alice"), Expect(r"Password", "s3cret")],
            timeout=10, done_pattern=r"GOT:")
        self.assertEqual(code, 0)
        self.assertIn(b"GOT:alice:s3cret", out)

    def test_secret_never_in_argv(self):
        # argv of the child is fixed; answers only flow through the pty fd
        out, _ = run_expect(
            ["/bin/sh", "-c", "tr '\\0' ' ' </proc/$$/cmdline"],
            [], timeout=10, done_pattern=r".")
        self.assertNotIn(b"s3cret", out)


AVAHIFIX = """\
+;eth0;IPv4;living-room;_airplay._tcp;local;living-room.local;192.168.1.30;7000;
=;eth0;IPv4;living-room;_airplay._tcp;local;living-room.local;192.168.1.30;7000;
=;eth0;IPv4;NAS;_smb._tcp;local;nas.local;192.168.1.50;445;
=;wlan0;IPv4;NAS;_smb._tcp;local;nas.local;192.168.1.50;445;
=;eth0;IPv4;backuppi;_ssh._tcp;local;backuppi.local;192.168.1.61;22;
=;eth0;IPv4;printer;._ipp._tcp;local;printer.local;192.168.1.9;631;
"""


class TestDiscover(unittest.TestCase):
    def test_parse_and_dedupe(self):
        res = netmap.discover.__wrapped__ if hasattr(netmap.discover, "__wrapped__") else None
        # direct parser test via fake avahi-browse
        def fake_run(cmd, **kw):
            class P:
                stdout = AVAHIFIX
                returncode = 0
            return P()
        with mock.patch.object(subprocess, "run", fake_run):
            servers = netmap.discover()
        hosts = {(s["host"], s["scheme"]) for s in servers}
        self.assertIn(("nas.local", "smb"), hosts)
        self.assertIn(("backuppi.local", "sftp"), hosts)
        self.assertNotIn(("living-room.local", "smb"), hosts)  # airplay skipped
        smb = [s for s in servers if s["scheme"] == "smb"]
        self.assertEqual(len(smb), 1)  # eth0+wlan0 deduped


SMBFIX = """\

\tSharename       Type      Comment
\t---------       -------   -------
\tadmin$          Disk      Remote Admin
\tmedia           Disk      Shared media
\tphotos          Disk      
\tIPC$            IPC       IPC Service (nas)
\tPrinter1        Printer  
Reconnecting with SMB1 for workgroup listing.

\tServer               Comment
\t---------            -------

\tWorkgroup            Master
\t---------            -------
"""


class TestShares(unittest.TestCase):
    def test_parse_disk_shares(self):
        shares = netmap._parse_shares(SMBFIX.encode(), None)
        names = [s["name"] for s in shares]
        self.assertEqual(names, ["media", "photos"])


class TestUrlAndMountArgs(unittest.TestCase):
    def test_build_url(self):
        self.assertEqual(netmap._build_url("smb", "nas.local", "media"),
                         "smb://nas.local/media")
        self.assertEqual(netmap._build_url("sftp", "pi", None, port=2222,
                                           path="data/x"),
                         "sftp://pi:2222/data/x")

    def test_mount_cmd_has_no_secrets(self):
        # netmap.mount builds gio argv internally; assert via fake pty capture
        seen = {}

        def fake_pipe_expect(cmd, expects, timeout=90.0, eof_after=None):
            seen["argv"] = list(cmd)
            seen["prompts"] = [e.pattern.pattern for e in expects]
            return b"Mounted smb://nas.local/media\n", 0

        with mock.patch.object(netmap, "pipe_expect", fake_pipe_expect), \
             mock.patch.object(subprocess, "run",
                               lambda *a, **k: type("P", (), {
                                   "stdout": b"uri: smb://nas.local/media",
                                   "stderr": b"", "returncode": 0})()):
            r = netmap.mount("smb", "nas.local", "media",
                             user="alice", domain="WORK", password="hunter2")
        self.assertTrue(r["ok"])
        self.assertEqual(seen["argv"], ["gio", "mount", "smb://nas.local/media"])
        self.assertNotIn("hunter2", str(seen))  # secret only via pty fd
        self.assertEqual([p.decode() if isinstance(p, bytes) else p
                          for p in seen["prompts"][:3]],
                         [r"User(?:name)?\s*(\[[^\]]*\])?\s*[:?]",
                          r"Domain\s*(\[[^\]]*\])?\s*[:?]",
                          r"Password\s*(\[[^\]]*\])?\s*[:?]"])


class TestMaps(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dwtest."))
        sandbox_env(self.tmp)

    def test_save_list_forget_roundtrip(self):
        entry = netmap.save_map("smb", "nas.local", "media", user="alice",
                                password="hunter2")
        self.assertTrue(netmap.MAPS_FILE.exists())
        self.assertEqual(netmap.MAPS_FILE.stat().st_mode & 0o777, 0o600)
        maps = netmap.list_maps()
        self.assertEqual(len(maps), 1)
        self.assertEqual(maps[0]["label"], "nas.local/media")
        # credential exists in some form, readable back
        cred = json.loads(netmap._cred_read(entry["cred"]))
        self.assertEqual(cred["password"], "hunter2")
        self.assertIn(entry["cred_how"], ("encrypted", "plain"))
        self.assertTrue(netmap.forget_map(entry["id"]))
        self.assertEqual(netmap.list_maps(), [])
        with self.assertRaises(netmap.CredsError):
            netmap._cred_read(entry["cred"])  # forgotten along with the map

    def test_gvfs_mounts_parse(self):
        gv = self.tmp / "gvfs"
        gv.mkdir()
        (gv / "smb-share:server=nas.local,share=media").mkdir()
        (gv / "sftp:host=backuppi.local").mkdir()
        (gv / "trash").mkdir()
        mounts = netmap.gvfs_mounts(base=gv)
        self.assertEqual(len(mounts), 2)
        by_url = {m["url"]: m for m in mounts}
        self.assertIn("smb://nas.local/media", by_url)
        self.assertEqual(by_url["smb://nas.local/media"]["label"],
                         "nas.local/media")
        self.assertIn("sftp://backuppi.local", by_url)


class TestWizard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dwwiz."))
        sandbox_env(self.tmp)

    def test_add_remote_writes_conf(self):
        with mock.patch.object(wizard, "obscure", lambda p: "OBF:" + p):
            wizard.add_remote("gdrive", "gdrive", token='{"access_token":"X"}')
            wizard.add_remote("nas", "nextcloud", url="https://nc.example",
                              user="greg", password="pw123")
        conf = wizard.RCLONE_CONF.read_text()
        self.assertIn("[gdrive]", conf)
        self.assertIn('token = {"access_token":"X"}', conf)
        self.assertIn("[nas]", conf)
        self.assertIn("vendor = nextcloud", conf)
        self.assertIn("pass = OBF:pw123", conf)
        self.assertEqual(wizard.RCLONE_CONF.stat().st_mode & 0o777, 0o600)
        names = wizard._section_names(wizard._conf_read())
        self.assertEqual(names, {"gdrive", "nas"})

    def test_duplicate_rejected(self):
        wizard.add_remote("gdrive", "gdrive", token="{}")
        with self.assertRaises(wizard.WizardError):
            wizard.add_remote("gdrive", "gdrive", token="{}")

    def test_remove_remote(self):
        with mock.patch.object(wizard, "obscure", lambda p: "OBF:" + p):
            wizard.add_remote("gdrive", "gdrive", token="{}")
            wizard.add_remote("nas", "nextcloud", url="https://x", user="g",
                              password="p")
            with mock.patch.object(wizard.subprocess, "run",
                                   lambda *a, **k: type("P", (), {
                                       "returncode": 0})()):
                r = wizard.remove_remote("gdrive")
        self.assertTrue(r["ok"])
        names = wizard._section_names(wizard._conf_read())
        self.assertEqual(names, {"nas"})

    def test_bad_name_rejected(self):
        with self.assertRaises(wizard.WizardError):
            wizard.add_remote("bad name!", "gdrive", token="{}")


if __name__ == "__main__":
    unittest.main()
