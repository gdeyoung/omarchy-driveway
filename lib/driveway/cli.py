"""driveway CLI dispatcher (lib/driveway/cli.py).

Every subcommand prints one JSON object on stdout (matching the QML
Service contract) and exits non-zero only on hard failure.
"""

import argparse
import json
import sys

from . import __version__
from . import actions, cloud, lister


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
    else:
        args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
