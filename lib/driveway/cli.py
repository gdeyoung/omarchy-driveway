"""driveway CLI dispatcher (lib/driveway/cli.py).

Every subcommand prints one JSON object on stdout (matching the QML
Service contract) and exits non-zero only on hard failure.
"""

import argparse
import json
import sys

from . import __version__
from . import actions, cloud, lister, netmap, wizard


def _stdin_json() -> dict:
    """Read a single-line JSON spec from stdin if present (secret-carrying
    requests arrive here, never via argv; callers write one line + \\n)."""
    try:
        line = sys.stdin.readline()
    except (OSError, ValueError):
        return {}
    line = line.strip()
    if not line:
        return {}
    try:
        return json.loads(line)
    except ValueError:
        return {}


def cmd_list(args):
    print(json.dumps(lister.collect(
        network=args.network, unmounted=args.unmounted,
        min_unmounted_mb=args.min_unmounted_mb,
        thumb_max_gb=args.thumb_max_gb, include_root=args.include_root)))


def cmd_action(args):
    # actions' handlers print their own JSON line and exit.
    actions.HANDLERS[args.action](args)


def cmd_cloud(args):
    if args.cloud_cmd == "status":
        print(json.dumps(cloud.status()))
    elif args.cloud_cmd == "mount":
        print(json.dumps(cloud.mount(args.remote)))
    elif args.cloud_cmd == "unmount":
        print(json.dumps(cloud.unmount(args.remote)))
    elif args.cloud_cmd == "install-unit":
        print(json.dumps(cloud.install_unit()))
    elif args.cloud_cmd == "providers":
        print(json.dumps({"providers": wizard.providers()}))
    elif args.cloud_cmd == "add-oauth":
        # long-running: opens browser, waits for sign-in; token never printed
        rtype = args.type or wizard.PROVIDERS[args.provider][0]
        try:
            res = wizard.authorize_oauth(rtype)
        except wizard.WizardError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return
        spec = _stdin_json()
        try:
            res.update(wizard.add_remote(args.name, args.provider,
                                         token=res["token"], **{
                                             k: v for k, v in spec.items()
                                             if k in ("url", "user", "password",
                                                      "host", "extra")}))
            unit = cloud.mount(args.name)
            res.update({"unit": unit})
        except wizard.WizardError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return
        print(json.dumps(res))
    elif args.cloud_cmd == "add":
        spec = _stdin_json()
        try:
            res = wizard.add_remote(args.name, args.provider, **{
                k: v for k, v in spec.items()
                if k in ("token", "url", "user", "password", "host", "extra")})
            if spec.get("start", True):
                res.update({"unit": cloud.mount(args.name)})
        except wizard.WizardError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return
        print(json.dumps(res))
    elif args.cloud_cmd == "remove":
        print(json.dumps(wizard.remove_remote(args.remote)))


def cmd_netmap(args):
    if args.netmap_cmd == "discover":
        print(json.dumps({"servers": netmap.discover()}))
    elif args.netmap_cmd == "shares":
        spec = _stdin_json()
        try:
            res = {"shares": netmap.shares(
                args.server, user=spec.get("user"),
                domain=spec.get("domain"), password=spec.get("password"))}
        except netmap.CredsError as e:
            res = {"ok": False, "error": str(e), "needs_creds": True}
        print(json.dumps(res))
    elif args.netmap_cmd == "mount":
        spec = _stdin_json()
        res = netmap.mount(spec.get("scheme", "smb"), spec.get("server"),
                           share=spec.get("share"), user=spec.get("user"),
                           domain=spec.get("domain"),
                           password=spec.get("password"),
                           port=spec.get("port"), path=spec.get("path"))
        if res.get("ok") and spec.get("save", True):
            entry = netmap.save_map(
                spec.get("scheme", "smb"), spec.get("server"),
                share=spec.get("share"), user=spec.get("user"),
                domain=spec.get("domain"), password=spec.get("password"),
                port=spec.get("port"), path=spec.get("path"))
            res["map"] = entry
        print(json.dumps(res))
    elif args.netmap_cmd == "unmount":
        print(json.dumps(netmap.unmount(args.target)))
    elif args.netmap_cmd == "list":
        print(json.dumps({"maps": netmap.list_maps(),
                          "mounted": netmap.gvfs_mounts()}))
    elif args.netmap_cmd == "forget":
        print(json.dumps({"ok": netmap.forget_map(args.map_id)}))
    elif args.netmap_cmd == "replay":
        print(json.dumps({"results": netmap.replay()}))
    elif args.netmap_cmd == "gvfs":
        print(json.dumps({"mounted": netmap.gvfs_mounts()}))



def cmd_version(_args):
    print(json.dumps({"version": __version__, "id": "gdeyoung.driveway"}))


def build_parser():
    parser = argparse.ArgumentParser(prog="driveway",
                                     description="gdeyoung.driveway backend")
    parser.add_argument("--version", action="version",
                        version="gdeyoung.driveway %s" % __version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="enumerate drives as JSON")
    p.add_argument("--network", action="store_true", default=True,
                   help="include network shares and cloud drives")
    p.add_argument("--no-network", dest="network", action="store_false")
    p.add_argument("--unmounted", action="store_true", default=True,
                   help="include plugged-in but unmounted filesystems")
    p.add_argument("--no-unmounted", dest="unmounted", action="store_false")
    p.add_argument("--min-unmounted-mb", type=float, default=64)
    p.add_argument("--thumb-max-gb", type=float, default=256)
    p.add_argument("--include-root", action="store_true", default=True,
                   help="include the read-only System row")
    p.add_argument("--no-root", dest="include_root", action="store_false")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("action", help="mount/unlock/lock/eject/busy (JSON line out)")
    p.add_argument("action", choices=list(actions.HANDLERS))
    p.add_argument("--mode", default="udisks")
    p.add_argument("--dev", default="")
    p.add_argument("--disk", default="")
    p.add_argument("--luks", default="")
    p.add_argument("--mount", default="")
    p.add_argument("--name", default="drive")
    p.add_argument("--removable", action="store_true")
    p.add_argument("--kill", action="store_true")
    p.set_defaults(func=cmd_action)

    p = sub.add_parser("cloud", help="rclone remote management")
    sub2 = p.add_subparsers(dest="cloud_cmd", required=True)
    sub2.add_parser("status")
    pm = sub2.add_parser("mount")
    pm.add_argument("remote")
    pu = sub2.add_parser("unmount")
    pu.add_argument("remote")
    sub2.add_parser("install-unit")
    pp = sub2.add_parser("providers")
    pao = sub2.add_parser("add-oauth")
    pao.add_argument("name")
    pao.add_argument("provider")
    pao.add_argument("--type", default=None,
                     help="rclone type override (defaults to provider's)")
    pad = sub2.add_parser("add")
    pad.add_argument("name")
    pad.add_argument("provider")
    prm = sub2.add_parser("remove")
    prm.add_argument("remote")

    p = sub.add_parser("netmap", help="network drive mapping")
    sub3 = p.add_subparsers(dest="netmap_cmd", required=True)
    sub3.add_parser("discover")
    psh = sub3.add_parser("shares")
    psh.add_argument("server")
    sub3.add_parser("mount")
    pum = sub3.add_parser("unmount")
    pum.add_argument("target")
    sub3.add_parser("list")
    pfg = sub3.add_parser("forget")
    pfg.add_argument("map_id")
    sub3.add_parser("replay")
    sub3.add_parser("gvfs")

    p = sub.add_parser("version")
    p.set_defaults(func=cmd_version)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "action":
        cmd_action(args)
    elif args.cmd == "cloud":
        cmd_cloud(args)
    elif args.cmd == "netmap":
        cmd_netmap(args)
    else:
        args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
