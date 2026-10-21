"""Driveway network mapping: browse, map, and persist network locations.

Protocols: SMB (samba), SFTP (ssh), FTP, NFS, WebDAV — all mounted
user-space via gio/gvfs.  No root, no kernel mounts.

Credentials never appear in argv.  They are fed to `gio mount` prompts
under a pty (see ptyrun) and stored encrypted at rest via
`systemd-creds --user encrypt` (fallback: 0600 plaintext with a warning in
the JSON status, because a locked-down laptop user key may be absent).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from .ptyrun import Expect, PtyError, pipe_expect

__all__ = ["SVC_KINDS", "discover", "shares", "mount", "unmount",
           "save_map", "forget_map", "list_maps", "replay",
           "gvfs_mounts", "CredsError"]

CONFIG_DIR = Path(os.environ.get("DRIVEWAY_CONFIG_DIR",
                                 Path.home() / ".config/driveway"))
MAPS_FILE = CONFIG_DIR / "maps.json"
CREDS_DIR = CONFIG_DIR / "creds"
CREDS_FALLBACK_PLAINTEXT = CONFIG_DIR / "creds-plaintext-warning"
# The GTK bookmarks file is the one list every file manager on the box reads (flea's NETWORK
# section, Nautilus' sidebar); a map that does not land here stays invisible outside driveway.
BOOKMARKS_FILE = Path(os.environ.get("DRIVEWAY_BOOKMARKS",
                                     Path.home() / ".config/gtk-3.0/bookmarks"))

# avahi service type -> (scheme, label)
SVC_KINDS = {
    "_smb._tcp": ("smb", "SMB"),
    "_ssh._tcp": ("sftp", "SSH"),
    "_ftp._tcp": ("ftp", "FTP"),
    "_nfs._tcp": ("nfs", "NFS"),
    "_webdav._tcp": ("dav", "WebDAV"),
}

SCHEMES = ("smb", "sftp", "ftp", "nfs", "dav", "davs")


class CredsError(RuntimeError):
    pass


# ---------------------------------------------------------------- discover

def _unescape_mdns(s: str) -> str:
    """avahi -p escapes non-ASCII as \\NNN octal (e.g. \\032 = space).

    Some devices advertise control bytes; map those to spaces for display.
    """
    out = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)
    return re.sub(r"[\x00-\x1f\x7f]", " ", out).strip()


def discover(timeout: float = 4.0) -> list[dict]:
    """List network servers on the LAN via avahi.

    Returns [{"name","host","ip","kind","scheme"}] deduped per host, sorted.
    """
    try:
        # -k = no service-type db lookup: keeps raw types (_smb._tcp) instead
        # of friendly names ("Microsoft Windows Network") so SVC_KINDS matches
        p = subprocess.run(["avahi-browse", "-artpk"], capture_output=True,
                           text=True, timeout=timeout)
        lines = p.stdout.splitlines()
    except subprocess.TimeoutExpired as e:
        # a full browse+resolve cycle can outlive our window; keep partials
        partial = e.stdout if isinstance(e.stdout, str) else (
            e.stdout.decode("utf-8", "replace") if e.stdout else "")
        lines = partial.splitlines()
    except FileNotFoundError:
        return []

    seen: dict[tuple, dict] = {}
    for ln in lines:
        f = ln.split(";")
        if len(f) < 8 or f[0] != "=":
            continue
        # avahi -p resolved line: =;iface;family;name;service;domain;host;address;port
        name, svc, _domain, host, ip = f[3], f[4], f[5], f[6], f[7]
        kind = SVC_KINDS.get(svc)
        if not kind:
            continue
        scheme, label = kind
        # dedupe by hostname: same server answers on v4 and v6
        key = (host.rstrip(".") or ip, scheme)
        if key not in seen:
            seen[key] = {"name": _unescape_mdns(name),
                         "host": host.rstrip(".") if host else ip,
                         "ip": ip, "kind": label, "scheme": scheme}
    out = sorted(seen.values(), key=lambda d: (d["kind"], d["name"].lower()))
    return out


# ---------------------------------------------------------------- shares

def _ensure_smb_client_conf() -> str:
    """Arch ships no /etc/samba/smb.conf, which blocks smbclient entirely;
    point it at our own minimal client config instead (no root needed)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    conf = CONFIG_DIR / "smb-client.conf"
    if not conf.exists():
        conf.write_text("[global]\nclient min protocol = SMB2\n\n")
        os.chmod(conf, 0o644)
    return str(conf)


def shares(server: str, user: str | None = None, domain: str | None = None,
           password: str | None = None, timeout: float = 25.0) -> list[dict]:
    """List SMB shares on a server via smbclient.

    Guest first; with credentials via a 0600 temp auth file (never argv).
    Returns [{"name","comment"}].
    """
    sconf = _ensure_smb_client_conf()
    cmd = ["smbclient", "-s", sconf, "-L", f"//{server}", "-N", "-t", "4"]
    env = dict(os.environ)
    if user or password or domain:
        auth = tempfile.NamedTemporaryFile("w", prefix="dw.", delete=False)
        auth.write(f"username = {user or 'guest'}\n")
        if domain:
            auth.write(f"domain = {domain}\n")
        if password:
            auth.write(f"password = {password}\n")
        auth.close()
        os.chmod(auth.name, 0o600)
        cmd = ["smbclient", "-s", sconf, "-L", f"//{server}", "-A", auth.name,
               "-t", "4"]
        env["HOME"] = env.get("HOME", str(Path.home()))
        try:
            return _parse_shares(_run(cmd, env, timeout), auth.name)
        finally:
            try:
                os.unlink(auth.name)
            except OSError:
                pass
    out = _run(cmd, env, timeout)
    if b"NT_STATUS_ACCESS_DENIED" in out or b"password" in out.lower():
        raise CredsError("server requires credentials")
    return _parse_shares(out, None)


def _run(cmd, env, timeout):
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
        return p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return b""


def _parse_shares(out: bytes, authfile: str | None) -> list[dict]:
    txt = out.decode("utf-8", "replace")
    shares = []
    in_section = False
    for ln in txt.splitlines():
        if re.match(r"^\s*Sharename\s+Type\s+Comment", ln):
            in_section = True
            continue
        if not in_section:
            continue
        if not ln.strip() or ln.strip().startswith("---"):
            continue
        m = re.match(r"^\s*(\S+)\s+(Disk|IPC|Printer)\s*(.*)$", ln)
        if not m:
            # any other line (Server/Workgroup headers) ends the share list
            if shares or re.match(r"^\s*\S+\s+\S+\s+\S+", ln):
                in_section = False
            continue
        name, typ, comment = m.groups()
        if typ == "Disk" and not name.endswith("$"):
            shares.append({"name": name, "comment": comment.strip()})
    return shares


# ---------------------------------------------------------------- creds

def _cred_write(cred_id: str, data: str) -> str:
    """Store credential encrypted; returns 'encrypted'|'plain'."""
    CREDS_DIR.mkdir(parents=True, exist_ok=True)
    # try systemd-creds user encryption
    try:
        enc = CREDS_DIR / f"{cred_id}.cred"
        with tempfile.NamedTemporaryFile("w", prefix="dw.cred.", delete=False) as tf:
            tf.write(data)
            tf.flush()
            os.chmod(tf.name, 0o600)
            tmp = tf.name
        r = subprocess.run(["systemd-creds", "encrypt", "--user", tmp,
                            str(enc)], capture_output=True, timeout=10)
        os.unlink(tmp)
        if r.returncode == 0:
            os.chmod(enc, 0o600)
            return "encrypted"
    except (OSError, subprocess.SubprocessError):
        pass
    # fallback plaintext 0600
    plain = CREDS_DIR / f"{cred_id}.txt"
    plain.write_text(data)
    os.chmod(plain, 0o600)
    CREDS_FALLBACK_PLAINTEXT.write_text(
        "Some credentials stored plaintext 0600 (systemd-creds --user unavailable).\n")
    return "plain"


def _cred_read(cred_id: str) -> str:
    enc = CREDS_DIR / f"{cred_id}.cred"
    if enc.exists():
        r = subprocess.run(["systemd-creds", "decrypt", "--user", str(enc), "-"],
                           capture_output=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.decode()
        raise CredsError(f"decrypt failed for {cred_id}")
    plain = CREDS_DIR / f"{cred_id}.txt"
    if plain.exists():
        return plain.read_text()
    raise CredsError(f"no stored credential for {cred_id}")


def _cred_path(cred_id: str) -> Path:
    for suffix in (".cred", ".txt"):
        p = CREDS_DIR / f"{cred_id}{suffix}"
        if p.exists():
            return p
    raise CredsError(f"no stored credential for {cred_id}")


def _cred_remove(cred_id: str) -> None:
    for suffix in (".cred", ".txt"):
        p = CREDS_DIR / f"{cred_id}{suffix}"
        if p.exists():
            p.unlink()


# ---------------------------------------------------------------- mount

def _build_url(scheme: str, server: str, share: str | None,
               port: int | None = None, path: str | None = None) -> str:
    host = server
    if port:
        host = f"{host}:{port}"
    url = f"{scheme}://{host}"
    if share:
        url += f"/{share}"
    elif path:
        url += "/" + path.strip("/")
    return url


def mount(scheme: str, server: str, share: str | None = None,
          user: str | None = None, domain: str | None = None,
          password: str | None = None, port: int | None = None,
          path: str | None = None, timeout: float = 90.0) -> dict:
    """Mount a network location via gio, answering prompts under a pty.

    Returns {"ok", "url", "error", "mounted_path"}.
    """
    if scheme not in SCHEMES:
        return {"ok": False, "error": f"unsupported scheme {scheme}"}
    url = _build_url(scheme, server, share, port, path)
    expects: list[Expect] = []
    if user:  # non-empty answers only; empty answers get read as rejection
        expects.append(Expect(r"User(?:name)?\s*(\[[^\]]*\])?\s*[:?]", user))
    if domain:
        expects.append(Expect(r"Domain\s*(\[[^\]]*\])?\s*[:?]", domain))
    if password:
        expects.append(Expect(r"Password\s*(\[[^\]]*\])?\s*[:?]", password))
    # guest/no-credential mounts: EOF makes gio take the bracketed defaults
    # or anonymous, where an empty typed answer would be rejected
    eof_after = 1.0 if not expects else None
    # gio may also ask about keyring storage ("Remember...?/forever/session/never")
    expects.append(Expect(r"(?i)remember|forever|session", "never", optional=True))
    # certificate trust prompts (self-signed https/davs)
    expects.append(Expect(r"(?i)accept|trust|fingerprint|reject.*permanently", "accept",
                          optional=True))
    try:
        out, code = pipe_expect(["gio", "mount", url], expects,
                                timeout=timeout, eof_after=eof_after)
    except PtyError as e:
        return {"ok": False, "url": url, "error": str(e)}

    ok = _gio_mounted_ok(url, out, code)
    if not ok:
        # repeated auth prompts = rejected credentials, not a hang
        n_auth = len(re.findall(rb"Authentication Required", out))
        if n_auth >= 2:
            return {"ok": False, "url": url,
                    "error": "authentication rejected by server"}
        err = _extract_gio_error(out, code)
        return {"ok": False, "url": url, "error": err}
    return {"ok": True, "url": url, "mounted_path": _gvfs_path_for(url),
            "error": None}


def _gio_mounted_ok(url: str, out: bytes, code: int) -> bool:
    if b"mounted" in out.lower() and code == 0:
        return True
    if code != 0:
        return False
    # exit 0 with no explicit "already mounted"/error text → verify via gio info
    r = subprocess.run(["gio", "info", url], capture_output=True, timeout=10)
    return b"not mounted" not in (r.stdout + r.stderr)


def _extract_gio_error(out: bytes, code: int) -> str:
    txt = out.decode("utf-8", "replace").strip()
    for pat in ("specified location is not mounted",
                "Location is already mounted",
                "already mounted"):
        if pat.lower() in txt.lower():
            # already mounted is success-ish; others reported verbatim
            if "already" in pat:
                return "already mounted"
    tail = txt.splitlines()[-1] if txt else f"exit {code}"
    return tail[:300]


def _gvfs_path_for(url: str) -> str:
    """Best-effort local path of a gvfs mount (for opening in files)."""
    uid = os.getuid()
    gvfs = Path(f"/run/user/{uid}/gvfs")
    if not gvfs.exists():
        return url
    from urllib.parse import urlparse, unquote
    u = urlparse(url)
    scheme = u.scheme
    host = u.hostname or ""
    share = (u.path or "/").strip("/")
    if scheme == "smb":
        # smb-share:server=host,share=share
        want = f"smb-share:server={host},share={share}"
        for d in gvfs.iterdir():
            if d.name.lower() == want.lower():
                return str(d)
        # server-level mount: smb-server:server=host
        want2 = f"smb-server:server={host}"
        for d in gvfs.iterdir():
            if d.name.lower() == want2.lower():
                return str(d)
        return url
    # sftp:host / ftp:host / nfs:host etc: "sftp:host=example.com"
    for d in gvfs.iterdir():
        if d.name.startswith(f"{scheme}:") and host in d.name:
            return str(d)
    return url


# ------------------------------------------------------------ bookmarks

def _bookmark_lines() -> list[str]:
    try:
        return BOOKMARKS_FILE.read_text().splitlines()
    except OSError:
        return []


def _bookmark_add(url: str, label: str) -> None:
    """Append the map's line to the GTK bookmarks file, idempotently by URL."""
    lines = _bookmark_lines()
    if any(l.split(" ")[0] == url for l in lines):
        return
    lines.append(f"{url} {label}".rstrip())
    BOOKMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    BOOKMARKS_FILE.write_text("\n".join(lines) + "\n")


def _bookmark_remove(url: str) -> None:
    """Drop every line for this URL; an absent file is already clean."""
    lines = _bookmark_lines()
    kept = [l for l in lines if l.split(" ")[0] != url]
    if kept == lines:
        return
    BOOKMARKS_FILE.write_text("\n".join(kept) + ("\n" if kept else ""))


# ---------------------------------------------------------------- maps

def _load_maps() -> dict:
    if MAPS_FILE.exists():
        try:
            return json.loads(MAPS_FILE.read_text())
        except (OSError, ValueError):
            return {}
    return {}


def _save_maps(maps: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    MAPS_FILE.write_text(json.dumps(maps, indent=1) + "\n")
    os.chmod(MAPS_FILE, 0o600)


def save_map(scheme: str, server: str, share: str | None = None,
             user: str | None = None, domain: str | None = None,
             password: str | None = None, port: int | None = None,
             path: str | None = None, label: str | None = None) -> dict:
    """Persist a mapped location (and its credential if given)."""
    maps = _load_maps()
    cred_id = None
    if password or user:
        cred_id = secrets.token_hex(6)
        cred = {"user": user or "", "domain": domain or "",
                "password": password or ""}
        how = _cred_write(cred_id, json.dumps(cred))
    else:
        how = None
    mid = f"{scheme}-{secrets.token_hex(4)}"
    url = _build_url(scheme, server, share, port, path)
    entry = {
        "id": mid, "scheme": scheme, "server": server, "share": share,
        "path": path, "port": port, "url": url,
        "user": user, "domain": domain, "cred": cred_id,
        "label": label or (f"{server}/{share}" if share else server),
        "cred_how": how,
    }
    maps[mid] = entry
    _save_maps(maps)
    _bookmark_add(entry["url"], entry["label"])
    return entry


def forget_map(mid: str) -> bool:
    maps = _load_maps()
    entry = maps.pop(mid, None)
    if not entry:
        return False
    if entry.get("cred"):
        _cred_remove(entry["cred"])
    _save_maps(maps)
    _bookmark_remove(entry["url"])
    return True


def list_maps() -> list[dict]:
    return sorted(_load_maps().values(), key=lambda m: m.get("label", ""))


def unmount(url_or_id: str) -> dict:
    """Unmount by map id or gio URL."""
    url = url_or_id
    for m in _load_maps().values():
        if m["id"] == url_or_id:
            url = m["url"]
            break
    try:
        p = subprocess.run(["gio", "mount", "-u", url], capture_output=True,
                           timeout=15)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    return {"ok": p.returncode == 0, "error":
            (p.stderr or p.stdout).decode()[:200] if p.returncode else None}


def replay(timeout_each: float = 45.0) -> list[dict]:
    """Re-mount every saved map that is not currently mounted (login hook)."""
    results = []
    mounted = {m["url"] for m in gvfs_mounts()}
    for m in list_maps():
        if m["url"] in mounted:
            results.append({"id": m["id"], "ok": True, "skipped": True})
            continue
        cred = {}
        if m.get("cred"):
            try:
                cred = json.loads(_cred_read(m["cred"]))
            except (CredsError, ValueError) as e:
                results.append({"id": m["id"], "ok": False,
                                "error": f"credential unreadable: {e}"})
                continue
        r = mount(m["scheme"], m["server"], m.get("share"),
                  user=cred.get("user") or m.get("user"),
                  domain=cred.get("domain") or m.get("domain"),
                  password=cred.get("password"),
                  port=m.get("port"), path=m.get("path"),
                  timeout=timeout_each)
        r["id"] = m["id"]
        results.append(r)
    return results


# ---------------------------------------------------------------- listing

def gvfs_mounts(base: Path | None = None) -> list[dict]:
    """Current gvfs network mounts, for panel display.

    Returns [{"url","scheme","server","share","label","path"}].
    """
    uid = os.getuid()
    gvfs = base if base is not None else Path(f"/run/user/{uid}/gvfs")
    out = []
    if not gvfs.is_dir():
        return out
    name_re = re.compile(r"^(?P<prefix>[a-z0-9]+)(?:-(?:share|server|host))?:")
    for d in sorted(gvfs.iterdir()):
        if not d.is_dir():
            continue
        m = name_re.match(d.name)
        if not m:
            continue
        typ = m.group("prefix")
        rest = d.name[m.end():]
        if typ not in ("smb", "sftp", "ftp", "nfs", "dav", "davs", "afc"):
            continue
        parts = dict(kv.split("=", 1) for kv in rest.split(",") if "=" in kv)
        server = parts.get("server") or parts.get("host") or ""
        share = parts.get("share", "")
        from urllib.parse import unquote
        server = unquote(server)
        share = unquote(share)
        scheme = {"smb": "smb", "sftp": "sftp", "ftp": "ftp",
                  "nfs": "nfs", "dav": "dav", "davs": "davs"}.get(typ, typ)
        url = f"{scheme}://{server}" + (f"/{share}" if share else "")
        label = f"{server}/{share}" if share else server
        out.append({"url": url, "scheme": scheme, "server": server,
                    "share": share, "label": label, "path": str(d)})
    return out
