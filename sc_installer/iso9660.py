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

"""ISO9660 extraction from raw MODE1/2352 bin images. I don't understand how this slop works"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .result import Err, Ok, Result

SECTOR_RAW = 2352
SECTOR_DATA = 2048
DATA_OFFSET = 16


def strip_bin(bin_path: Path, iso_path: Path) -> Result[Path]:
    """Convert MODE1/2352 .bin to a plain 2048B-sector image."""
    try:
        with bin_path.open("rb") as src, iso_path.open("wb") as dst:
            while sector := src.read(SECTOR_RAW):
                if len(sector) != SECTOR_RAW:
                    return Err(f"{bin_path}: truncated sector ({len(sector)} bytes)")
                dst.write(sector[DATA_OFFSET : DATA_OFFSET + SECTOR_DATA])
    except OSError as e:
        return Err(f"strip {bin_path}: {e}")
    return Ok(iso_path)


@dataclass(frozen=True)
class DirRecord:
    extent_lba: int
    data_length: int
    is_dir: bool
    name: str


class IsoImage:
    def __init__(self, path: Path) -> None:
        self._path = path
        # Volume descriptors start at sector 16; prefer a Joliet supplementary
        # descriptor (type 2, escape sequences %/@ %/C %/E = UCS-2 levels 1-3)
        # so long Unicode filenames are preserved.
        self._utf16 = False
        pvd: bytes | None = None
        with path.open("rb") as f:
            sector = 16
            while True:
                desc = _read_sectors(f, sector, 1)
                if len(desc) < SECTOR_DATA or desc[1:6] != b"CD001":
                    raise ValueError(f"{path}: not an ISO9660 image")
                match desc[0]:
                    case 255:
                        break
                    case 2 if desc[88:120][:3] in (b"%/@", b"%/C", b"%/E"):
                        pvd = desc
                        self._utf16 = True
                    case 1 if pvd is None:
                        pvd = desc
                    case _:
                        pass
                sector += 1
        if pvd is None:
            raise ValueError(f"{path}: no volume descriptor found")
        root = self._parse_record(pvd, 156)
        if root is None:
            raise ValueError(f"{path}: missing root directory record")
        self._root = root[0]

    def _parse_record(self, buf: bytes, offset: int) -> tuple[DirRecord, int] | None:
        length = buf[offset]
        if length == 0:
            return None
        extent = struct.unpack_from("<I", buf, offset + 2)[0]
        data_len = struct.unpack_from("<I", buf, offset + 10)[0]
        flags = buf[offset + 25]
        name_len = buf[offset + 32]
        name_raw = buf[offset + 33 : offset + 33 + name_len]
        if name_raw == b"\x00":
            name = "."
        elif name_raw == b"\x01":
            name = ".."
        elif self._utf16:
            name = name_raw.decode("utf-16-be", errors="replace")
        else:
            name = name_raw.decode("ascii", errors="replace").split(";")[0].rstrip(".")
        return DirRecord(extent, data_len, bool(flags & 0x02), name), offset + length

    def _read_extent(self, extent_lba: int, length: int) -> bytes:
        with self._path.open("rb") as f:
            f.seek(extent_lba * SECTOR_DATA)
            return f.read(length)

    def _list_dir(self, record: DirRecord) -> list[DirRecord]:
        buf = self._read_extent(record.extent_lba, record.data_length)
        records: list[DirRecord] = []
        offset = 0
        while offset < len(buf):
            if buf[offset] == 0:
                # move to next sector boundary
                offset = (offset // SECTOR_DATA + 1) * SECTOR_DATA
                continue
            parsed = self._parse_record(buf, offset)
            if parsed is None:
                break
            rec, offset = parsed
            if rec.name not in (".", ".."):
                records.append(rec)
        return records

    def extract_to(self, dest_dir: Path) -> Result[Path]:
        try:
            self._extract_dir(self._root, dest_dir)
        except (OSError, ValueError) as e:
            return Err(f"extract {self._path}: {e}")
        return Ok(dest_dir)

    def _extract_dir(self, record: DirRecord, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        for rec in self._list_dir(record):
            target = dest / rec.name
            if rec.is_dir:
                self._extract_dir(rec, target)
            else:
                target.write_bytes(self._read_extent(rec.extent_lba, rec.data_length))


def _read_sectors(f: BinaryIO, lba: int, count: int) -> bytes:
    f.seek(lba * SECTOR_DATA)
    return f.read(count * SECTOR_DATA)


def bin_to_dir(bin_path: Path, iso_path: Path, dest_dir: Path) -> Result[Path]:
    """Full pipeline: strip raw bin, parse ISO9660, extract files."""
    iso_path.parent.mkdir(parents=True, exist_ok=True)
    dest_dir.mkdir(parents=True, exist_ok=True)
    match strip_bin(bin_path, iso_path):
        case Err() as e:
            return e
        case Ok(iso):
            match _try_image(iso):
                case Err() as e:
                    return e
                case Ok(img):
                    return img.extract_to(dest_dir)


def _try_image(iso: Path) -> Result[IsoImage]:
    try:
        return Ok(IsoImage(iso))
    except ValueError as e:
        return Err(str(e))
