"""Driveway cloud account wizard: add/remove cloud remotes from the panel.

Sign-in uses `rclone authorize` under a pty: rclone opens the browser,
the user signs in, and the OAuth token lands on stdout — captured, never
logged, never in argv.  Remote configuration is appended directly to
rclone.conf (0600) instead of `rclone config create` so tokens/passwords
never appear in a process command line.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .ptyrun import PtyError, run_capture, run_expect

__all__ = ["PROVIDERS", "providers", "authorize_oauth", "obscure",
           "add_remote", "remove_remote", "WizardError"]

RCLONE_CONF = Path(os.environ.get("RCLONE_CONFIG",
                                  Path.home() / ".config/rclone/rclone.conf"))

# key -> (rclone type, display, needs_oauth, hint)
PROVIDERS = {
    "gdrive":    ("drive",     "Google Drive", True,  ""),
    "onedrive":  ("onedrive",  "OneDrive",     True,  ""),
    "dropbox":   ("dropbox",   "Dropbox",      True,  ""),
    "box":       ("box",       "Box",          True,  ""),
    "pcloud":    ("pcloud",    "pCloud",       True,  ""),
    "nextcloud": ("webdav",    "Nextcloud",    False, "needs URL + login"),
    "webdav":    ("webdav",    "WebDAV",       False, "needs URL + login"),
    "sftp":      ("sftp",      "SFTP host",    False, "host + login"),
    "ftp":       ("ftp",       "FTP host",     False, "host + login"),
    "s3":        ("s3",        "S3 / MinIO / R2", False, "access key + secret"),
}


class WizardError(RuntimeError):
    pass


def providers() -> list[dict]:
    out = []
    for key, (rtype, label, oauth, hint) in PROVIDERS.items():
        out.append({"key": key, "type": rtype, "label": label,
                    "oauth": oauth, "hint": hint})
    return out


# ---------------------------------------------------------------- oauth

def authorize_oauth(rtype: str, timeout: float = 300.0) -> dict:
    """Run `rclone authorize <rtype>` and capture the token JSON.

    Returns {"token": "<json string>"} — caller must not log this.
    Raises WizardError on failure/timeout.

    NOTE: rclone's first-run banner says `Config file ... not found - using
    defaults` — a bare "not found" match is NOT a missing-binary signal
    (that bit us on a fresh machine).  Only explicit shell/command failures
    count as not-installed.
    """
    out, code = run_expect(
        ["rclone", "authorize", rtype, ""],
        expects=[], timeout=timeout,
        done_pattern=r"(Success|Got code|Failed|[Ee]rror)")
    txt = out.decode("utf-8", "replace")
    if "command not found" in txt or "rclone: command" in txt:
        raise WizardError("rclone is not installed")
    m = re.search(r"-{2,4}>\s*(\{.*?\})\s*<-{2,4}", txt, re.S)
    if not m:
        m = re.search(r"(\{\"access_token\".*?\})", txt, re.S)
    if not m:
        tail = txt.strip().splitlines()[-1] if txt.strip() else f"exit {code}"
        raise WizardError(f"authorization did not complete: {tail[:200]}")
    return {"token": m.group(1)}


# ---------------------------------------------------------------- obscure

def obscure(password: str) -> str:
    """rclone-obscure a password without argv exposure.

    Tries stdin first (`rclone obscure` reads stdin when no arg given in
    recent versions); falls back to a pty.  Never logs.
    """
    try:
        r = subprocess.run(["rclone", "obscure"], input=password.encode(),
                           capture_output=True, timeout=10)
    except FileNotFoundError:
        raise WizardError("rclone is not installed")
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.decode().strip()
    out, code = run_expect(["rclone", "obscure"], expects=[], timeout=10,
                           done_pattern=r"\S")
    cand = out.decode().strip()
    if cand and code == 0:
        return cand
    raise WizardError("rclone obscure failed")


# ---------------------------------------------------------------- config

def _conf_read() -> str:
    try:
        return RCLONE_CONF.read_text()
    except OSError:
        return ""


def _section_names(conf: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r"^\[([^\]]+)\]\s*$", conf, re.M)}


def _append_section(name: str, fields: list[tuple[str, str]]) -> None:
    RCLONE_CONF.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(RCLONE_CONF.parent, 0o700)
    except OSError:
        pass
    conf = _conf_read()
    if name in _section_names(conf):
        raise WizardError(f"remote '{name}' already exists in rclone.conf")
    block = f"\n[{name}]\n" + "".join(f"{k} = {v}\n" for k, v in fields)
    if conf and not conf.endswith("\n"):
        conf += "\n"
    # atomic-ish: write temp then rename, keeping 0600
    fd, tmp = tempfile.mkstemp(dir=str(RCLONE_CONF.parent), prefix=".conf.")
    with os.fdopen(fd, "w") as fh:
        fh.write(conf + block)
    os.chmod(tmp, 0o600)
    os.replace(tmp, RCLONE_CONF)


def add_remote(name: str, provider_key: str, token: str | None = None,
               url: str | None = None, user: str | None = None,
               password: str | None = None, host: str | None = None,
               extra: dict | None = None) -> dict:
    """Create a remote in rclone.conf. Secrets never touch argv."""
    if not re.match(r"^[A-Za-z0-9_-]+$", name):
        raise WizardError("remote name must be alphanumeric/-/_")
    prov = PROVIDERS.get(provider_key)
    if not prov:
        raise WizardError(f"unknown provider {provider_key}")
    rtype, _label, oauth, _hint = prov
    fields: list[tuple[str, str]] = [("type", rtype)]
    if oauth:
        if not token:
            raise WizardError("oauth provider requires a token")
        fields.append(("token", token))
    if rtype == "webdav":
        if not url or not user:
            raise WizardError("webdav/nextcloud requires url and user")
        vendor = "nextcloud" if provider_key == "nextcloud" else "owncloud"
        if provider_key == "webdav":
            vendor = "webdav"
        fields += [("url", url), ("vendor", vendor), ("user", user)]
        if password:
            fields.append(("pass", obscure(password)))
    elif rtype in ("sftp", "ftp"):
        if not host:
            raise WizardError("sftp/ftp requires host")
        fields.append(("host", host))
        if user:
            fields.append(("user", user))
        if password:
            fields.append(("pass", obscure(password)))
    elif rtype == "s3":
        # keys arrive via stdin JSON (Service.runWithStdin) — never argv;
        # written straight into rclone.conf, secret kept plain like rclone
        # itself does (rclone stores s3 keys unobscured).
        if not user:                      # user == access_key_id here
            raise WizardError("s3 requires access key id")
        if not password:                  # password == secret_access_key
            raise WizardError("s3 requires secret access key")
        fields += [("access_key_id", user), ("secret_access_key", password)]
        if url:                           # endpoint for MinIO/R2/other
            fields.append(("endpoint", url))
        if extra and extra.get("region"):
            fields.append(("region", str(extra["region"])))
    if extra:
        for k, v in extra.items():
            if k not in ("type", "token", "pass"):
                fields.append((k, str(v)))
    _append_section(name, fields)
    return {"ok": True, "name": name, "type": rtype}


def remove_remote(name: str) -> dict:
    """Stop any unit, then delete the remote section from rclone.conf."""
    subprocess.run(["systemctl", "--user", "stop", f"driveway-cloud@{name}.service"],
                   capture_output=True, timeout=15)
    conf = _conf_read()
    if name not in _section_names(conf):
        return {"ok": False, "error": f"no remote named '{name}'"}
    conf = re.sub(rf"\n?\[{re.escape(name)}\]\n.*?(?=\n\[|\Z)", "\n",
                  conf, flags=re.S)
    RCLONE_CONF.write_text(conf.lstrip("\n"))
    # clean per-remote env file and runtime dir
    envf = Path.home() / f".config/driveway/{name}.env"
    if envf.exists():
        envf.unlink()
    return {"ok": True}
