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

"""Provision debian rootfs + wine + mimalloc.

the rootfs is Desbian trixie-slim OCI layer fetched from Docker Hub. Wine
dependencies & libmimalloc are installed inside bwrap by apt. Kron4ek wine
goes to /opt/wine. mimalloc preloaded via /etc/ld.so.preload
"""

from __future__ import annotations

import socket
import subprocess
import tarfile
from pathlib import Path

from .assets import Asset
from .result import Err, LogFn, Ok, Result

# Debian trixie-slim amd64 OCI digest docker.io
ROOTFS_DIGEST = "ecc510c1e359bdc007b39802570bb7e4dec7d6ebccf357c3201a74299113e05e"

APT_PACKAGES = (
    "libx11-6",
    "libxext6",
    "libxcb1",
    "libgl1",
    "libegl1",
    "libfreetype6",
    "libfontconfig1",
    "libgnutls30",
    "libpulse0",
    "libxcomposite1",
    "libxcursor1",
    "libxi6",
    "libxinerama1",
    "libxrandr2",
    "libxrender1",
    "libmimalloc3",
)

RESOLV_CONF = """nameserver 1.1.1.1
nameserver 9.9.9.9
"""

MIMALLOC_SO = "/usr/lib/x86_64-linux-gnu/libmimalloc.so.3"


def _docker_blob(repo_name: str, digest: str, dest: Path) -> Result[Path]:
    """fetch debian image from dockerhub"""
    import json
    import urllib.request

    if dest.exists():
        match Asset(dest.name, "", sha256=digest).verify(dest):
            case Ok():
                return Ok(dest)
            case Err():
                dest.unlink()
    try:
        with urllib.request.urlopen(
            f"https://auth.docker.io/token?service=registry.docker.io"
            f"&scope=repository:{repo_name}:pull"
        ) as r:
            token = json.load(r)["token"]
        req = urllib.request.Request(
            f"https://registry-1.docker.io/v2/{repo_name}/blobs/sha256:{digest}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as r, dest.open("wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    except (OSError, KeyError, json.JSONDecodeError) as e:
        return Err(f"docker blob fetch: {e}")
    return Asset(dest.name, "", sha256=digest).verify(dest)


def build_rootfs(
    repo: Path, downloads: Path, wine_tarball: Path, log: LogFn = print
) -> Result[Path]:
    """build the rootfs. this is idempotent"""
    rootfs = repo / "rootfs"
    if (rootfs / "opt" / "wine" / "bin" / "wine").exists():
        log("[skip] rootfs already provisioned")
        return Ok(rootfs)
    match _docker_blob("library/debian", ROOTFS_DIGEST, downloads / "rootfs.tar.gz"):
        case Err() as e:
            return e
        case Ok(tarball):
            rootfs.mkdir(parents=True, exist_ok=True)
            try:
                with tarfile.open(tarball) as tar:
                    tar.extractall(rootfs, filter="tar")
            except (tarfile.TarError, OSError) as e:
                return Err(f"extract rootfs: {e}")

    (rootfs / "etc" / "resolv.conf").write_text(RESOLV_CONF)
    # wine wants local hostname to resolve.
    # battle.net doesnt like getaddrinfo(hostname) failing
    (rootfs / "etc" / "hosts").write_text(
        f"127.0.0.1 localhost\n127.0.1.1 {socket.gethostname()}\n"
    )
    (rootfs / "etc" / "ld.so.preload").write_text(MIMALLOC_SO + "\n")

    bwrap = [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--uid",
        "0",
        "--gid",
        "0",
        "--bind",
        str(rootfs),
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--setenv",
        "HOME",
        "/tmp",
        "--",
    ]
    log("[rootfs] installing debian packages")
    proc = subprocess.run(
        bwrap + ["/usr/bin/apt-get", "-o", "APT::Sandbox::User=root", "update"],
        check=False,
    )
    if proc.returncode != 0:
        return Err("apt-get update failed")
    proc = subprocess.run(
        bwrap
        + [
            "/usr/bin/apt-get",
            "-o",
            "APT::Sandbox::User=root",
            "install",
            "-y",
            "--no-install-recommends",
            *APT_PACKAGES,
        ],
        check=False,
    )
    if proc.returncode != 0:
        return Err("apt-get install failed")

    log("[rootfs] installing wine")
    wine_dest = rootfs / "opt" / "wine"
    wine_dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(wine_tarball) as tar:
            tar.extractall(rootfs / "opt", filter="data")
        inner = next((rootfs / "opt").glob("wine-*"))
        inner.rename(wine_dest)
    except (tarfile.TarError, OSError, StopIteration) as e:
        return Err(f"wine install into rootfs: {e}")
    if not (wine_dest / "bin" / "wine").exists():
        return Err("wine missing after install")
    log("[ok] rootfs provisioned")
    return Ok(rootfs)
