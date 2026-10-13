# Copyright (C) 2026  wormt <209373679+wormt@users.noreply.github.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""CLI entry point: python -m sc_installer [install|launch]."""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from .install import install, launch


def main() -> int:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet exit on | head
    parser = argparse.ArgumentParser(prog="sc_installer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser("install")
    p_install.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    p_install.add_argument(
        "--discs",
        type=Path,
        help="directory with the sc.bin and bw.bin disc dumps (default: downloads/)",
    )

    p_launch = sub.add_parser("launch")
    p_launch.add_argument("--repo", type=Path, default=Path.cwd())
    p_launch.add_argument("--prefix", type=Path, required=True)

    p_gw = sub.add_parser("gateway", help="configure gateways from track.pvpgn.pro")
    p_gw.add_argument("--repo", type=Path, default=Path.cwd())
    p_gw.add_argument("--list", action="store_true", help="list tracker servers")
    p_gw.add_argument("--pick", help="comma-separated server numbers, e.g. 1,4,9")
    p_gw.add_argument("--all", action="store_true", help="add every tracked server")

    args = parser.parse_args()
    match args.command:
        case "install":
            install(args.repo, args.discs).expect("install failed")
        case "launch":
            result = launch(args.repo, args.prefix)
            return result.unwrap_or(1)
        case "gateway":
            from .gateway import fetch_servers, set_gateways

            servers = fetch_servers().expect("tracker fetch")
            for i, s in enumerate(servers, 1):
                print(f"{i:3}. {s.address:16} {s.users:>4} users {s.games:>4} games  {s.title}")
            if args.list:
                return 0
            if args.all:
                picked = servers
            elif args.pick:
                try:
                    picked = [servers[int(n) - 1] for n in args.pick.split(",")]
                except (ValueError, IndexError):
                    parser.error("--pick numbers must match the list")
            else:
                raw = input("pick servers (comma-separated numbers): ")
                try:
                    picked = [servers[int(n) - 1] for n in raw.split(",") if n.strip()]
                except (ValueError, IndexError):
                    parser.error("selection must match the list")
            set_gateways(
                repo=args.repo,
                prefix=args.repo / "prefix",
                servers=picked,
            ).expect("gateway setup")
        case _:
            parser.error(f"unknown command {args.command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
