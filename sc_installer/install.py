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

"""StarCraft 1.16.1 + cnc-ddraw + BWAPI installer

Downloads the free patches and tools, verifies hashes, extracts user-supplied
retail disc dumps, sets up a Wine prefix (Kron4ek wow64) under bubblewrap,
installs StarCraft Brood War, patches to 1.16.1, and installs cnc-ddraw and BWAPI
"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

from .assets import DISC_IMAGES, download_all
from .iso9660 import bin_to_dir
from .result import Err, LogFn, Ok, Result
from .rootfs import build_rootfs
from .sandbox import Sandbox, find_bwrap

GAME_EXE = "StarCraft.exe"
DDWAR_INI = """[ddraw]
fullscreen=true
windowed=true
maintas=true
adjmouse=false
renderer=opengl
vsync=false
width=1280
height=960
shader=Shaders/nearest-neighbor.glsl
savesettings=0
"""


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.unlink(missing_ok=True)
    try:
        dst.hardlink_to(src)
    except OSError:
        dst.write_bytes(src.read_bytes())


def _build_combined_disc(sc_dir: Path, bw_dir: Path, combined: Path) -> Result[Path]:
    """One disc containing both CDs so the 2008 installer never asks for a disc swap."""
    try:
        combined.mkdir(parents=True, exist_ok=True)
        for src_dir in (sc_dir, bw_dir):
            for entry in src_dir.iterdir():
                _link_or_copy(entry, combined / entry.name)
    except OSError as e:
        return Err(f"build combined disc: {e}")
    return Ok(combined)


def _map_cdrom(prefix: Path, disc_dir: Path) -> Result[Path]:
    dosdevices = prefix / "dosdevices"
    if not dosdevices.is_dir():
        return Err(f"prefix not initialized (no {dosdevices})")
    link = dosdevices / "d:"
    link.unlink(missing_ok=True)
    try:
        link.symlink_to(disc_dir)
    except OSError as e:
        return Err(f"map d: -> {disc_dir}: {e}")
    return Ok(disc_dir)


def _find_game_dir(prefix: Path) -> Result[Path]:
    drive_c = prefix / "drive_c"
    for exe in drive_c.rglob(GAME_EXE):
        return Ok(exe.parent)
    return Err(f"{GAME_EXE} not found under {drive_c} (did the installer finish?)")


def _install_cnc_ddraw(zip_path: Path, game_dir: Path) -> Result[Path]:
    ini = game_dir / "ddraw.ini"
    had_ini = ini.exists()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                # never clobber a modified ddraw.ini
                if member.filename == "ddraw.ini":
                    continue
                zf.extract(member, game_dir)
    except (zipfile.BadZipFile, OSError) as e:
        return Err(f"extract cnc-ddraw: {e}")
    if not had_ini:
        ini.write_text(DDWAR_INI)
    return Ok(game_dir)


def _write_launcher(repo: Path, prefix: Path) -> Result[Path]:
    script = repo / "launch.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"cd {repo} && "
        f"exec python3 -m sc_installer launch "
        f"--prefix {prefix} --repo {repo}\n"
    )
    script.chmod(0o755, follow_symlinks=False)
    return Ok(script)


def _supply_discs(discs_dir: Path, log: LogFn) -> Result[None]:
    """Verify the user-supplied disc images against the pinned retail hashes."""
    for image in DISC_IMAGES:
        path = discs_dir / image.name
        if not path.exists():
            return Err(
                f"{path} not found: supply your own retail disc dumps "
                f"(sc.bin and bw.bin cue/bin images of the 2008 CDs) "
                f"in {discs_dir}, or pass --discs DIR"
            )
        match image.verify(path):
            case Err() as e:
                return Err(f"{e}\n  {path} does not match the known retail dump. check the image")
            case Ok():
                log(f"[ok] {image.name} matches the retail dump hash")
    return Ok(None)


def install(repo: Path, discs_dir: Path | None = None, log: LogFn = print) -> Result[Path]:
    prefix = repo / "prefix"
    downloads = repo / "downloads"
    discs = repo / "discs"

    find_bwrap().expect("sandbox prerequisite")
    log("[keys] the installer will ask for a CD key. Have one ready.")

    downloads.mkdir(exist_ok=True)
    _supply_discs(discs_dir or downloads, log).expect("disc images")
    asyncio.run(download_all(downloads, log)).expect("downloads")

    build_rootfs(repo, downloads, downloads / "wine.tar.xz", log).expect("rootfs setup")

    for name, out in (("sc.bin", "sc_cd"), ("bw.bin", "bw_cd")):
        dest = discs / out
        if not dest.exists():
            bin_to_dir((discs_dir or downloads) / name, discs / f"{out}.iso", dest).expect(
                f"extracting {name}"
            )
            log(f"[ok] extracted {name} -> {dest}")

    combined = _build_combined_disc(discs / "sc_cd", discs / "bw_cd", discs / "disc").expect(
        "combined disc"
    )

    sandbox = Sandbox(repo=repo, prefix=prefix)
    sandbox.wine("wineboot", "--init", log=log).expect("wine prefix creation")
    _map_cdrom(prefix, combined).expect("cdrom mapping")

    match _find_game_dir(prefix):
        case Ok(game_dir):
            log(f"[skip] game already installed at {game_dir}")
        case Err():
            log(
                "[install] running StarCraft installer. Use default paths, do NOT launch at the end"
            )
            sandbox.wine_and_wait("D:\\StarCraft (Windows).exe", log=log).expect("SC installer")
            game_dir = _find_game_dir(prefix).expect("locating game")
            log(f"[ok] game installed to {game_dir}")

    if not (game_dir / "BWAPI.dll").exists():
        log("[install] patching to 1.16.1, click through the patcher")
        sandbox.wine_and_wait(str(downloads / "SC-1161.exe"), log=log).expect("1.16.1 patch")
        z_game_dir = "Z:" + str(game_dir).replace("/", "\\")
        sandbox.wine(str(downloads / "BWAPI_Setup.exe"), "/S", f"/D={z_game_dir}", log=log).expect(
            "BWAPI setup"
        )

    _install_cnc_ddraw(downloads / "cnc-ddraw.zip", game_dir).expect("cnc-ddraw")
    sandbox.wine_and_wait(
        "reg",
        "add",
        r"HKCU\Software\Wine\DllOverrides",
        "/v",
        "ddraw",
        "/d",
        "native,builtin",
        "/f",
        log=log,
    ).expect("ddraw override")

    launcher = _write_launcher(repo, prefix).expect("launcher")
    log(f"[done] game ready at {game_dir}. run with {launcher}")
    return Ok(game_dir)


def launch(repo: Path, prefix: Path, log: LogFn = print) -> Result[int]:
    game_dir = _find_game_dir(prefix).expect("locating game")
    if not (repo / "rootfs" / "opt" / "wine" / "bin" / "wine").exists():
        return Err("rootfs not provisioned (run install first)")
    sandbox = Sandbox(repo=repo, prefix=prefix)
    # the game rewrites the gateway list on exit and drops custom servers.
    # so we have to reimport list every launch
    reg_file = repo / "gateways.reg"
    if reg_file.exists():
        sandbox.wine_and_wait("reg", "import", str(reg_file), log=lambda *a: None)
    # virtual desktop
    return sandbox.wine_and_wait(
        "explorer", "/desktop=sc,1280x960", str(game_dir / GAME_EXE), log=log
    )
