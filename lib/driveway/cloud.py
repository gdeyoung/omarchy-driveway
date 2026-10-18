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

# State dir shared with netmap (DRIVEWAY_CONFIG_DIR override for tests).
STATE_DIR = Path(os.environ.get("DRIVEWAY_CONFIG_DIR",
                                os.path.expanduser("~/.config/driveway")))
ABOUT_CACHE = STATE_DIR / "about.json"
ABOUT_TTL = 300.0          # seconds a quota reading stays fresh
ABOUT_TIMEOUT = 6.0        # bounded so the poller never hangs on one remote

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


# ---------------------------------------------------------------- quotas

def _about_load():
    try:
        with open(ABOUT_CACHE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _about_save(cache):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_DIR / ".about.json.tmp"
        tmp.write_text(json.dumps(cache))
        os.replace(tmp, ABOUT_CACHE)
    except OSError:
        pass


def about(name, force=False, now=None):
    """Account quota via `rclone about <name>: --json`, cached.

    Returns {"used": int, "total": int, "error": str|None, "ts": float} or
    None when nothing is known.  Errors are cached too (short TTL) so a
    dead backend doesn't get hammered by the poller; auth errors feed
    diagnose().
    """
    import time
    now = now if now is not None else time.time()
    cache = _about_load()
    entry = cache.get(name)
    if entry and not force:
        ttl = ABOUT_TTL if not entry.get("error") else 60.0
        if now - entry.get("ts", 0) < ttl:
            return entry
    code, out = _run(["rclone", "about", name + ":", "--json"],
                     timeout=ABOUT_TIMEOUT)
    entry = {"ts": now, "error": None, "used": 0, "total": 0}
    if code != 0:
        entry["error"] = (out or "rclone about failed").strip().splitlines()[-1][:200]
    else:
        try:
            data = json.loads(out)
            entry["used"] = int(data.get("used") or 0)
            entry["total"] = int(data.get("total") or 0)
        except ValueError:
            entry["error"] = "bad rclone about output"
    cache[name] = entry
    _about_save(cache)
    return entry


def _about_warm_one(rems):
    """Refresh at most ONE stale cache entry (round-robin) per status call,
    so the 10s poll never pays for N slow `rclone about` runs."""
    import time
    cache = _about_load()
    now = time.time()
    stale = [r["name"] for r in rems
             if not cache.get(r["name"])
             or now - cache[r["name"]].get("ts", 0) >=
                 (ABOUT_TTL if not cache[r["name"]].get("error") else 60.0)]
    if stale:
        about(stale[0], force=True, now=now)


def clock_synced():
    """True/False/None(unknown) from timedatectl — OAuth token refresh
    fails when the clock is off (jonspinks/omarchy-rclone lesson)."""
    code, out = _run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                     timeout=5)
    if code != 0:
        return None
    return out.strip().lower() == "yes"


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
        abt = _about_load().get(name) or {"used": 0, "total": 0, "error": None}
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
            "about": {"used": abt.get("used", 0), "total": abt.get("total", 0),
                      "error": abt.get("error")},
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
    _about_warm_one(rems)
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


def mount_all():
    """Start every remote's unit in one systemctl call (systemd mounts them
    in parallel). Skips remotes that are already mounted."""
    rems = remotes()
    if not rems:
        return {"ok": True, "started": [], "message": "no remotes"}
    install_unit()
    mounted = mounted_rclone()
    todo = []
    for r in rems:
        if r["name"] not in mounted:
            try:
                target = mount_point_for(r["name"])
                target.mkdir(parents=True, exist_ok=True)
                os.chmod(target, 0o700)
            except OSError:
                continue
            todo.append("driveway-cloud@%s" % r["name"])
    if not todo:
        return {"ok": True, "started": [], "message": "all mounted"}
    code, out = _run(["systemctl", "--user", "start"] + todo, timeout=60)
    return {"ok": code == 0, "started": [t.split("@")[1] for t in todo],
            "message": out or "ok"}


def unmount_all():
    rems = remotes()
    if not rems:
        return {"ok": True, "stopped": [], "message": "no remotes"}
    names = [r["name"] for r in rems]
    units = ["driveway-cloud@%s" % n for n in names]
    code, out = _run(["systemctl", "--user", "stop"] + units, timeout=60)
    # sweep stragglers (external mounts / lazy stops)
    mounted = mounted_rclone()
    for n in names:
        if n in mounted:
            _run(["fusermount3", "-u", mounted[n]], timeout=10)
    return {"ok": code == 0, "stopped": names, "message": out or "ok"}


# ---------------------------------------------------------------- diagnose

_AUTH_MARKERS = ("invalid_grant", "invalid_request", "401", "unauthorized",
                 "expired", "refresh_token", "couldn't fetch token",
                 "token has been expired", "oauth")


def _looks_like_auth_error(text):
    t = (text or "").lower()
    return any(m in t for m in _AUTH_MARKERS)


def diagnose(name):
    """Why is this remote unhappy, and what fixes it?

    Returns {"state": ..., "problem": str|None, "remedy": str|None}.
    remedy values: "restart", "reconnect", "fix-clock", None.
    Never guesses: each verdict is backed by a command's output.
    """
    unit = unit_state(name)
    if unit is None:
        return {"state": "idle", "problem": None, "remedy": None}
    active = unit.get("ActiveState", "")
    result = unit.get("Result", "")
    nrestarts = int(unit.get("NRestarts", "0") or 0)
    mp = mounted_rclone().get(name, "")

    if active == "failed" or result == "exit-code":
        abt = about(name, force=True)
        err = (abt or {}).get("error") or ""
        if _looks_like_auth_error(err):
            if clock_synced() is False:
                return {"state": "failed",
                        "problem": "sign-in expired and the clock is unsynced — "
                                   "OAuth cannot refresh",
                        "remedy": "fix-clock"}
            return {"state": "failed",
                    "problem": "sign-in expired or revoked — rclone needs to "
                               "re-authorize in your browser",
                    "remedy": "reconnect"}
        if clock_synced() is False:
            return {"state": "failed",
                    "problem": "system clock is unsynced — OAuth token "
                               "refresh fails until NTP syncs",
                    "remedy": "fix-clock"}
        if nrestarts >= 3:
            return {"state": "failed",
                    "problem": "unit in a restart loop (%d restarts) — likely "
                               "network unreachable or backend down"
                               % nrestarts,
                    "remedy": "restart"}
        return {"state": "failed",
                "problem": "unit failed to start", "remedy": "restart"}

    if active == "active" and mp:
        # hung? active + mounted but rc socket dead to the world
        sock = rc_socket(name)
        if os.path.exists(sock):
            pending = lister.rclone_pending(("unix", sock), name + ":")
            if pending == -1:
                return {"state": "hung",
                        "problem": "rclone is running but not responding "
                                   "(rc socket silent)",
                        "remedy": "restart"}
        return {"state": "mounted", "problem": None, "remedy": None}

    if active == "active" and not mp:
        if nrestarts >= 3:
            return {"state": "starting",
                    "problem": "still connecting after %d restarts" % nrestarts,
                    "remedy": None}
        return {"state": "starting", "problem": None, "remedy": None}

    return {"state": active or "unknown", "problem": None, "remedy": None}


def remedy_restart(name):
    code, out = _run(["systemctl", "--user", "restart", "driveway-cloud@%s" % name],
                     timeout=30)
    return {"ok": code == 0, "message": out or "ok"}


def reconnect(name):
    """Expired OAuth fix: stop the unit first (rclone rewrites rclone.conf —
    jonspinks lesson: reconnect must not race a running mount), then
    re-authorize interactively. The browser opens; the token lands in
    rclone.conf directly. Secrets never cross argv.
    """
    if unit_state(name) is not None:
        _run(["systemctl", "--user", "stop", "driveway-cloud@%s" % name],
             timeout=30)
    from .ptyrun import run_expect
    out, code = run_expect(
        ["rclone", "config", "reconnect", name + ":"],
        expects=[], timeout=300.0,
        done_pattern=r"(Success|Already|Failed|error|not found)")
    txt = out.decode("utf-8", "replace")
    ok = code == 0 and ("success" in txt.lower() or "already" in txt.lower())
    return {"ok": ok,
            "message": "reauthorized" if ok else txt.strip().splitlines()[-1][:200]
            if txt.strip() else "exit %s" % code}


# ---------------------------------------------------------------- cache caps
# VFS disk-cache limits: global default + per-remote override.  Values ride
# EnvironmentFiles the unit template already reads (RCLONE_* env is rclone's
# own config surface — verified live via the rc socket: CacheMaxSize follows
# RCLONE_VFS_CACHE_MAX_SIZE).  Later EnvironmentFile lines override earlier
# Environment= directives, so precedence = template fallback < global < remote.

ENV_FILE_MODE = 0o600


def _state_dir() -> Path:
    """Resolved per call so tests (and exotic envs) never share one binding."""
    return Path(os.environ.get("DRIVEWAY_CONFIG_DIR",
                               os.path.expanduser("~/.config/driveway")))
TEMPLATE_CACHE_DEFAULT = "10G"
_SIZE_RE = None  # compiled lazily to keep import cost trivial


def _size_re():
    global _SIZE_RE
    import re
    if _SIZE_RE is None:
        _SIZE_RE = re.compile(
            r"^\d+(\.\d+)?([kKmMgGtTpP]|[kKmMgGtTpP][iI]|[bB])?$")
    return _SIZE_RE


def normalize_size(size: str):
    """'off'/'unlimited' -> '0' (rclone: 0 = no cap). Returns None if invalid."""
    s = (size or "").strip()
    if s.lower() in ("off", "unlimited", "none"):
        return "0"
    if _size_re().match(s):
        return s
    return None


def _settings_load() -> dict:
    try:
        with open(_settings_file()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _settings_save(data: dict) -> None:
    sd = _state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(sd), prefix=".settings-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, ENV_FILE_MODE)
        os.replace(tmp, _settings_file())
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_env_file(path: Path, var: str, value: str | None) -> bool:
    """Write/remove one RCLONE_*= line file. Returns True if disk changed."""
    if value is None:
        return path.exists() and (path.unlink() or True)
    line = "%s=%s\n" % (var, value)
    if path.is_file() and path.read_text() == line:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(line)
    os.chmod(path, ENV_FILE_MODE)
    return True


def _cloud_defaults_env() -> Path:
    return _state_dir() / "cloud-defaults.env"


def _remote_env(name: str) -> Path:
    return _state_dir() / ("%s.env" % name)


def _settings_file() -> Path:
    return _state_dir() / "settings.json"


def cache_get() -> dict:
    """Effective cache limits for panel display."""
    data = _settings_load()
    gmax = data.get("vfsCacheMax")
    overrides = data.get("remotes") or {}
    out = {"global": gmax or TEMPLATE_CACHE_DEFAULT,
           "globalIsCustom": bool(gmax),
           "remotes": {}}
    for r in remotes():
        name = r["name"]
        ov = overrides.get(name, {}).get("vfsCacheMax")
        out["remotes"][name] = {
            "limit": ov or out["global"],
            "isOverride": bool(ov),
        }
    return out


def cache_set(target: str, size: str) -> dict:
    """target='global' or a remote name. size: SizeSuffix or 'off'.
    Writes settings.json + the env file, restarts affected mounts."""
    val = normalize_size(size)
    if val is None:
        return {"ok": False, "error": "invalid size %r (use e.g. 10G, 500M, off)" % size}
    data = _settings_load()
    changed_units = []
    if target == "global":
        data["vfsCacheMax"] = val
        _settings_save(data)
        _write_env_file(_cloud_defaults_env(), "RCLONE_VFS_CACHE_MAX_SIZE", val)
        # every mount picks the new default up on restart
        for r in remotes():
            if unit_state(r["name"]) is not None:
                changed_units.append(r["name"])
    else:
        if not any(r["name"] == target for r in remotes()):
            return {"ok": False, "error": "unknown remote %r" % target}
        rem = data.setdefault("remotes", {})
        if val == "0" or val == (data.get("vfsCacheMax") or TEMPLATE_CACHE_DEFAULT):
            rem.pop(target, None)           # revert to global: no override file
            _write_env_file(_remote_env(target), "RCLONE_VFS_CACHE_MAX_SIZE", None)
        else:
            rem.setdefault(target, {})["vfsCacheMax"] = val
            _write_env_file(_remote_env(target), "RCLONE_VFS_CACHE_MAX_SIZE", val)
        _settings_save(data)
        if unit_state(target) is not None:
            changed_units.append(target)
    for name in changed_units:
        _run(["systemctl", "--user", "restart", "driveway-cloud@%s" % name],
             timeout=45)
    return {"ok": True, "restarted": changed_units,
            "effective": cache_get()}
