"""Cloud drives for gdeyoung.driveway (lib/driveway/cloud.py).

rclone remotes, mounted by supervised systemd user units (template
systemd/driveway-cloud@.service, adapted from bmaltais/StartDrive's unit —
see NOTICE.md). One unit instance per remote; the restart loop is the
network gate (no bogus user-manager network-online.target, per
jonspinks/omarchy-rclone). All state is read, never guessed: remotes from
`rclone listremotes --long`, mounts from findmnt, unit health from
`systemctl --user show`, upload activity from the unit's private rc socket.

Prints/returns JSON only; secrets never appear (credentials stay in
rclone's own config, which this module never writes).
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import lister

UNIT_NAME = "driveway-cloud@.service"

# rclone backend type -> display kind (single source of truth: lister).
KINDS = lister.RCLONE_KINDS


def _run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc) or type(exc).__name__


def rclone_installed():
    return shutil.which("rclone") is not None


def config_path():
    return Path(os.environ.get("DRIVEWAY_CONFIG",
                               os.path.expanduser("~/.config/omarchy/driveway.json")))


def load_config():
    cfg = {"mountRoot": os.path.expanduser("~/Cloud")}
    try:
        with open(config_path()) as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            root = loaded.get("mountRoot")
            if root:
                cfg["mountRoot"] = os.path.expanduser(root)
    except (OSError, ValueError):
        pass
    return cfg


def unit_dir():
    return Path(os.environ.get("DRIVEWAY_UNIT_DIR",
                               os.path.expanduser("~/.config/systemd/user")))


def unit_source():
    return Path(__file__).resolve().parents[2] / "systemd" / UNIT_NAME


def unit_installed():
    return (unit_dir() / UNIT_NAME).exists()


def install_unit():
    """Copy the template into the user unit dir if missing or changed.
    Returns {"changed": bool, "message": str}."""
    src, dst = unit_source(), unit_dir() / UNIT_NAME
    if not src.is_file():
        return {"changed": False, "message": "template %s not found in plugin" % src}
    body = src.read_text()
    if dst.is_file() and dst.read_text() == body:
        return {"changed": False, "message": "already installed"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Atomic-ish: tempfile in the same dir, then rename over.
    fd, tmp = tempfile.mkstemp(dir=str(dst.parent), prefix=".driveway-unit-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(body)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    code, out = _run(["systemctl", "--user", "daemon-reload"])
    if code != 0:
        return {"changed": True, "message": "installed, daemon-reload failed: " + out}
    return {"changed": True, "message": "installed"}


def remotes():
    """[{name, type}] or None when rclone is not installed."""
    if not rclone_installed():
        return None
    code, out = _run(["rclone", "listremotes", "--long"])
    if code != 0:
        return []
    found = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(":"):
            found.append({"name": parts[0].rstrip(":"), "type": parts[1]})
    return found


def mounted_rclone():
    """{remote name: mountpoint} for every fuse.rclone mount."""
    mounted = {}
    for fs in lister.findmnt("fuse.rclone"):
        source = fs.get("source") or ""
        remote = source.split(":", 1)[0]
        if remote:
            mounted[remote] = fs.get("target") or ""
    return mounted


def unit_state(name):
    """ActiveState/SubState/Result/NRestarts for our unit, or None if absent."""
    code, out = _run(["systemctl", "--user", "show", "driveway-cloud@%s" % name,
                      "-p", "LoadState", "-p", "ActiveState", "-p", "SubState",
                      "-p", "Result", "-p", "NRestarts"])
    if code != 0:
        return None
    state = {}
    for line in out.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            state[key] = value
    if state.get("LoadState") == "not-found":
        return None
    return state


def rc_socket(name):
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    return os.path.join(runtime, "driveway-cloud", name, "rc.sock")


def status():
    """Full cloud snapshot for the panel."""
    result = {"rclone": rclone_installed(), "unit": unit_installed(),
              "mountRoot": load_config()["mountRoot"], "drives": []}
    rems = remotes()
    if rems is None:
        return result
    mounted = mounted_rclone()
    rows = []
    for remote in rems:
        name = remote["name"]
        unit = unit_state(name)
        mp = mounted.get(name, "")
        if mp:
            state = "mounted" if unit else "external"
        elif unit is None:
            state = "idle"
        else:
            active = unit.get("ActiveState", "")
            if active == "active":
                state = "starting"
            elif active == "failed" or unit.get("Result") == "exit-code":
                state = "failed"
            elif active in ("inactive", "deactivating"):
                state = "stopped"
            else:
                state = "unknown"
        row = {
            "name": name,
            "type": remote["type"],
            "kind": KINDS.get(remote["type"], "cloud"),
            "state": state,
            "mountpoint": mp,
            "unit": unit is not None,
            "nrestarts": int(unit.get("NRestarts", "0") or 0) if unit else 0,
            "pending": -1,
            "size": 0, "used": 0, "pct": 0,
        }
        if mp:
            # Bounded statvfs: a wedged FUSE mount must not hang the poller.
            use = lister.bounded_usage([mp]).get(mp, (0, 0, False))
            row["size"], row["used"], _ro = use
            row["pct"] = lister.pct(row["used"], row["size"])
            sock = rc_socket(name)
            if os.path.exists(sock):
                row["pending"] = lister.rclone_pending(("unix", sock), name + ":")
        rows.append(row)
    result["drives"] = rows
    return result


def mount_point_for(name):
    return Path(load_config()["mountRoot"]) / name


def mount(name):
    """Start the unit for `name` (installs the template first if needed)."""
    install = install_unit()
    target = mount_point_for(name)
    try:
        target.mkdir(parents=True, exist_ok=True)
        os.chmod(target, 0o700)
    except OSError as exc:
        return {"ok": False, "message": str(exc)}
    code, out = _run(["systemctl", "--user", "start", "driveway-cloud@%s" % name],
                     timeout=30)
    message = out or ("ok" if code == 0 else "systemctl failed")
    if install["changed"]:
        message = install["message"] + "; " + message
    return {"ok": code == 0, "message": message}


def unmount(name):
    """Stop the unit; lazy-unmount the FUSE mount if it survives (or is not
    ours at all — an `rclone mount` started outside Driveway)."""
    if unit_state(name) is not None:
        code, out = _run(["systemctl", "--user", "stop", "driveway-cloud@%s" % name],
                         timeout=30)
    else:
        code, out = 0, "no unit"
    if code == 0 and name in mounted_rclone():
        mp = mounted_rclone()[name]
        code2, out2 = _run(["fusermount3", "-u", mp], timeout=10)
        if code2 != 0:
            _run(["fusermount3", "-uz", mp], timeout=10)
    return {"ok": code == 0, "message": out or "ok"}
