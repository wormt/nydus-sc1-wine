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

"""configure StarCraft BNet gateways from the PvPGN tracker

Fetches https://track.pvpgn.pro/, parses html table, writes the selection
to HKCU\\Software\\Battle.net\\Configuration\\Battle.net Gateways (REG_MULTI_SZ),
preserving existing entries. Existing Blizzard defaults use the format:
["1000", <selected>, <address>, <timezone>, <title>, ...]
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from ipaddress import ip_address
from pathlib import Path

from .result import Err, LogFn, Ok, Result
from .sandbox import Sandbox

TRACKER_URL = "https://track.pvpgn.pro/"
REG_KEY = r"HKCU\Software\Battle.net\Configuration"
REG_VALUE = "Battle.net Gateways"


@dataclass(frozen=True)
class Server:
    address: str
    location: str
    description: str
    users: str
    games: str

    @property
    def title(self) -> str:
        text = self.description or self.location or self.address
        return re.sub(r"[^ -~]", "", text).strip()[:40]


class _TrackerParser(HTMLParser):
    """Extract table rows"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag == "td":
            self._cell = ""
        elif tag == "br" and self._cell:
            self._cell += " "

    def handle_data(self, data: str) -> None:
        self._cell += data.replace("\xa0", " ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self._row.append(self._cell.strip())
        elif tag == "tr" and self._row:
            self.rows.append(self._row)


def fetch_servers(url: str = TRACKER_URL) -> Result[list[Server]]:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except OSError as e:
        return Err(f"tracker fetch failed: {e}")
    parser = _TrackerParser()
    parser.feed(html)
    servers: list[Server] = []
    for row in parser.rows:
        if len(row) < 10 or not re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", row[0]):
            continue
        try:
            if ip_address(row[0]).is_private:
                continue  # if we hit loopback
        except ValueError:
            continue
        users = re.sub(r"\s.*", "", row[7])
        games = re.sub(r"\s.*", "", row[9])
        if any(s.address == row[0] for s in servers):
            continue
        servers.append(Server(row[0], row[1], row[2], users, games))
    if not servers:
        return Err("no servers parsed from tracker page")
    return Ok(servers)


def _reg_hex7(strings: list[str]) -> str:
    """Encode strings as REG_MULTI_SZ hex(7) for the .reg file.

    wine's reg.exe double-encodes UTF-16LE input. Instead we need to
    encode plain ASCII bytes with NUL separators"""
    data = "".join(s + "\0" for s in strings) + "\0"
    raw = data.encode("ascii")
    hexed = ",".join(f"{b:02x}" for b in raw)
    return "hex(7):" + hexed


def set_gateways(
    repo: Path,
    prefix: Path,
    servers: list[Server],
    log: LogFn = print,
) -> Result[Path]:
    """write the gateway list with both builtin+custom & import it."""
    if not servers:
        return Err("no servers selected")
    tz = {
        "uswest.battle.net": "8",
        "useast.battle.net": "6",
        "asia.battle.net": "-9",
        "europe.battle.net": "-1",
    }
    customs = list(dict.fromkeys(servers))  # deduplicate
    select = str(len(BUILTIN_SERVERS) + 1).zfill(2)
    entries = ["1001", select]
    for s in [*BUILTIN_SERVERS, *customs]:
        entries += [s.address, tz.get(s.address, "0"), s.title]
    reg_file = repo / "gateways.reg"
    reg_file.write_text(
        "Windows Registry Editor Version 5.00\n\n"
        f"[{REG_KEY.replace('HKCU', 'HKEY_CURRENT_USER')}]\n"
        f'"{REG_VALUE}"={_reg_hex7(entries)}\n'
    )
    sandbox = Sandbox(repo=repo, prefix=prefix)
    return sandbox.wine_and_wait("reg", "import", str(reg_file), log=log).map(lambda _: prefix)


# Blizzard's gateways are dead but the game expects them to be listed.
BUILTIN_SERVERS: tuple[Server, ...] = (
    Server("uswest.battle.net", "", "U.S. West", "", ""),
    Server("useast.battle.net", "", "U.S. East", "", ""),
    Server("asia.battle.net", "", "Asia", "", ""),
    Server("europe.battle.net", "", "Europe", "", ""),
)
