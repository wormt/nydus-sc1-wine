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

"""run wine inside a bubblewfap sandbox

everything is at /, so behavior is identical across distros. The
repo and prefix are bound at their real host paths so symlinks resolve
the same inside and outside the sandbox.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .result import Err, LogFn, Ok, Result


@dataclass(frozen=True)
class Sandbox:
    prefix: Path
    repo: Path
    share_net: bool = True

    @property
    def rootfs(self) -> Path:
        return self.repo / "rootfs"

    def __post_init__(self) -> None:
        # wineserver keys prefixes by absolute path STRING
        for field in ("prefix", "repo"):
            object.__setattr__(self, field, getattr(self, field).resolve())

    def _bwrap_base(self) -> list[str]:
        self.prefix.mkdir(parents=True, exist_ok=True)
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "")
        wayland = os.environ.get("WAYLAND_DISPLAY", "")
        xauth = os.environ.get(
            "XAUTHORITY", str(Path(os.environ.get("HOME", "/tmp")) / ".Xauthority")
        )
        cmd = [
            "bwrap",
            "--die-with-parent",
            "--new-session",
            "--bind",
            str(self.rootfs),
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--dev-bind-try",
            "/dev/dri",
            "/dev/dri",
            # need this for mesa to see gpuwu
            "--ro-bind-try",
            "/sys/dev",
            "/sys/dev",
            "--ro-bind-try",
            "/sys/devices",
            "/sys/devices",
            "--bind",
            str(self.repo),
            str(self.repo),
            "--bind",
            str(self.prefix),
            str(self.prefix),
            "--tmpfs",
            "/tmp",
            "--ro-bind-try",
            "/tmp/.X11-unix",
            "/tmp/.X11-unix",
            "--ro-bind-try",
            xauth,
            xauth,
        ]
        if xdg_runtime:
            for sock in (wayland, "pulse", "pipewire-0"):
                if sock:
                    cmd += [
                        "--ro-bind-try",
                        f"{xdg_runtime}/{sock}",
                        f"{xdg_runtime}/{sock}",
                    ]
        if not self.share_net:
            cmd.append("--unshare-net")
        cmd += [
            "--setenv",
            "WINEPREFIX",
            str(self.prefix),
            "--setenv",
            "WINEDEBUG",
            os.environ.get("WINEDEBUG", "-all"),
            # in-process futex_waitv syncing. if off wineserver uses its own locks which are slow
            "--setenv",
            "WINEFSYNC",
            os.environ.get("WINEFSYNC", "1"),
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "PATH",
            "/opt/wine/bin:/usr/bin",
            "--setenv",
            "DISPLAY",
            os.environ.get("DISPLAY", ":0"),
            "--setenv",
            "XAUTHORITY",
            xauth,
            "--setenv",
            "XDG_RUNTIME_DIR",
            xdg_runtime,
            "--chdir",
            str(self.repo),
        ]
        if wayland:
            cmd += ["--setenv", "WAYLAND_DISPLAY", wayland]
        for var in ("WINEDLLOVERRIDES",):
            if val := os.environ.get(var):
                cmd += ["--setenv", var, val]
        return cmd

    def run(self, args: list[str], log: LogFn = print) -> Result[int]:
        cmd = self._bwrap_base() + ["--"] + args
        log(f"[bwrap] {' '.join(args)}")
        try:
            proc = subprocess.run(cmd, check=False)
        except OSError as e:
            return Err(f"bwrap exec failed: {e}")
        if proc.returncode != 0:
            return Err(f"command exited with code {proc.returncode}")
        return Ok(proc.returncode)

    def wine(self, *args: str, log: LogFn = print) -> Result[int]:
        return self.run(["/opt/wine/bin/wine", *args], log=log)

    def wine_and_wait(self, *args: str, log: LogFn = print) -> Result[int]:
        """Run wine and wait until all wine processes exit."""
        script = (
            "/opt/wine/bin/wine "
            + " ".join(shlex.quote(a) for a in args)
            + "; rc=$?; wineserver -w; wineserver -k; exit $rc"
        )
        return self.run(["/bin/sh", "-c", script], log=log)

    def reg_query(self, key: str, value: str) -> Result[str]:
        proc = subprocess.run(
            self._bwrap_base() + ["--", "/opt/wine/bin/wine", "reg", "query", key, "/v", value],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return Err(f"reg query {key}\\{value} failed ({proc.returncode})")
        return Ok(proc.stdout)


def find_bwrap() -> Result[Path]:
    match shutil.which("bwrap"):
        case None:
            return Err("bwrap not found in PATH (install bubblewrap)")
        case path:
            return Ok(Path(path))
