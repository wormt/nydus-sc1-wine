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

"""
HTTP/1.1 client built on asyncio.open_connection. All of the downloadable
assets fetched concurrently. Disc images must be provided by user. Checks
hashes of all provided files and downloaded files to ensure safety.
"""

from __future__ import annotations

import asyncio
import hashlib
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

from .result import Err, LogFn, Ok, Result, collect

ARCHIVE_ORG = "https://archive.org/download"
CHUNK = 1 << 16
MAX_REDIRECTS = 8


@dataclass(frozen=True)
class Asset:
    name: str
    url: str | None = None
    md5: str | None = None
    sha256: str | None = None
    size: int | None = None

    def verify(self, path: Path) -> Result[Path]:
        if not path.exists():
            return Err(f"{path} does not exist")
        if self.size is not None and path.stat().st_size != self.size:
            return Err(f"{self.name}: size {path.stat().st_size} != expected {self.size}")
        if self.md5 is not None:
            digest = _hash(path, "md5")
            if digest != self.md5:
                return Err(f"{self.name}: md5 {digest} != expected {self.md5}")
        if self.sha256 is not None:
            digest = _hash(path, "sha256")
            if digest != self.sha256:
                return Err(f"{self.name}: sha256 {digest} != expected {self.sha256}")
        return Ok(path)


def _hash(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# DISC_IMAGES are not automatically fetched.
# Find them yourself >:c
DISC_IMAGES: tuple[Asset, ...] = (
    Asset(
        name="sc.bin",
        md5="e64bc4b83f92d18a1d0b3c73d8631a5f",
        size=789197136,
    ),
    Asset(
        name="bw.bin",
        md5="f7711c39565d9828749d311c4ea918cb",
        size=721798224,
    ),
)

ASSETS: tuple[Asset, ...] = (
    Asset(
        name="SC-1161.exe",
        url=f"{ARCHIVE_ORG}/StarCraftPatches/patches/PC/SC-1161.exe",
        md5="d2561b3caeb2a89ecc1aec382d87197f",
        size=10696135,
    ),
    Asset(
        name="cnc-ddraw.zip",
        url="https://github.com/FunkyFr3sh/cnc-ddraw/releases/download/v7.1.0.0/cnc-ddraw.zip",
        sha256="0b13ab89a64c9918189b1dadd449ef6ed3cb3b7b19cabd96d8adbd95505bb908",
    ),
    Asset(
        name="BWAPI_Setup.exe",
        url="https://github.com/bwapi/bwapi/releases/download/v4.4.0/BWAPI_Setup.exe",
        sha256="27c0e1d1d6d33256132620ee1091df587aeb4dffa34c1b4b174b6e95cc590f74",
    ),
    Asset(
        name="wine.tar.xz",
        url="https://github.com/Kron4ek/Wine-Builds/releases/download/11.19/wine-11.19-staging-tkg-amd64-wow64.tar.xz",
        sha256="c6a67b5c4629a72a340d6507e4ab5250ffd96eecb924ecfe4806e8f559160944",
    ),
)


async def _read_headers(reader: asyncio.StreamReader) -> Result[tuple[int, dict[str, str]]]:
    try:
        status_line = await asyncio.wait_for(reader.readline(), timeout=30)
    except TimeoutError:
        return Err("timed out waiting for status")
    parts = status_line.decode("latin-1").split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        return Err(f"malformed status: {status_line!r}")
    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        key, _, value = line.decode("latin-1").partition(":")
        headers[key.strip().lower()] = value.strip()
    return Ok((int(parts[1]), headers))


async def _fetch(url: str, dest: Path, redirects: int = 0) -> Result[Path]:
    """One HTTP GET, following redirects recursively. Streams body to dest."""
    if redirects > MAX_REDIRECTS:
        return Err(f"too many redirects for {url}")
    parts = urlsplit(url)
    host = parts.hostname
    if host is None:
        return Err(f"bad url: {url}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    target = parts.path or "/"
    if parts.query:
        target += f"?{parts.query}"
    try:
        reader, writer = await asyncio.open_connection(
            host, port, ssl=parts.scheme == "https" or None
        )
    except (OSError, ssl.SSLError) as e:
        return Err(f"connect {host}:{port}: {e}")
    try:
        writer.write(
            f"GET {target} HTTP/1.1\r\nHost: {host}\r\n"
            "User-Agent: sc-installer\r\nAccept: */*\r\nConnection: close\r\n\r\n".encode("ascii")
        )
        await writer.drain()
        match await _read_headers(reader):
            case Err() as e:
                return e
            case Ok((status, headers)):
                if status in (301, 302, 303, 307, 308):
                    location = headers.get("location")
                    if location is None:
                        return Err(f"{url}: redirect with no location header")
                    writer.close()
                    return await _fetch(location, dest, redirects + 1)
                if status != 200:
                    return Err(f"{url}: HTTP {status}")
                with dest.open("wb") as out:
                    await _stream_body(reader, headers, out)
    except OSError as e:
        return Err(f"fetch {url}: {e}")
    finally:
        writer.close()
    return Ok(dest)


async def _stream_body(
    reader: asyncio.StreamReader, headers: dict[str, str], out: BinaryIO
) -> None:
    if headers.get("transfer-encoding") == "chunked":
        while True:
            size_line = await reader.readline()
            size = int(size_line.strip().split(b";")[0], 16)
            if size == 0:
                await reader.readline()  # break early on trailing CRLF
                break
            out.write(await reader.readexactly(size))
            await reader.readexactly(2)  # oops... all CLRF!
    else:
        while chunk := await reader.read(CHUNK):
            out.write(chunk)


async def download(asset: Asset, dest_dir: Path, log: LogFn = print) -> Result[Path]:
    """check if already downloaded, check if url exists, download, else raise error."""
    dest = dest_dir / asset.name
    if dest.exists():
        match asset.verify(dest):
            case Ok():
                log(f"[skip] {asset.name} already downloaded and verified")
                return Ok(dest)
            case Err():
                log(f"[redo] {asset.name} failed verification, re-downloading")
                dest.unlink()
    tmp = dest.with_suffix(dest.suffix + ".part")
    if asset.url is not None:
        match await _fetch(asset.url, tmp):
            case Err() as e:
                tmp.unlink(missing_ok=True)
                return e
            case Ok():
                tmp.rename(dest)
    else:
        return Err(
            f"{asset.name}: failed download. if this is for an sc disc, you must find it yourself."
        )

    match asset.verify(dest):
        case Err() as e:
            return e
        case Ok(p):
            log(f"[ok] {p.name} verified")
            return Ok(p)


async def download_all(
    dest_dir: Path, log: LogFn = print, assets: tuple[Asset, ...] = ASSETS
) -> Result[list[Path]]:
    """Download URLs concurrently."""
    results = await asyncio.gather(*(download(a, dest_dir, log) for a in assets))
    return collect(list(results))
