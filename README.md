# Nydus Launcher

StarCraft BW 1.16.1 with cnc-ddraw (sharp integer-scaled rendering),
BWAPI, and online play via public PvPGN gateways. Everything runs in
a bubblewrap sandbox rooted at a self-contained, hash-pinned Debian
closure with wine. The only host packages needed are Python and
bubblewrap.

## Requirements

- Python ≥ 3.12 (only needs stdlib)
- `bwrap` (bubblewrap)

## A note on legality

This project installs StarCraft: Brood War 1.16.1. Blizzard no longer
sells or distributes 1.16.1. It's free release is the 1.18+ client,
which does not work with BWAPI. The disc images circulate on archive.org.
This repository hosts nothing copyrighted by Blizzard and downloads no
game files: you must supply your own disc images and your own CD key.

This project circumvents no technological protection measure. The
1.16.1 installer's CD-key prompt is satisfied by a key the user
supplies, not bypassed. Blizzard removed the play-time disc check in
patch 1.15.2 (2007), so 1.16.1 has none. The combined-disc construction
only avoids the 2008 installer's disc-swap prompt when both discs' data
is already in hand. The project is GPLv3, whose section 3 declares the
covered work is not part of an "effective technological measure" and
waives DMCA section 1201 claims against modifiers.

## Install and play

You need sc.bin and bw.bin, cue/bin dumps of the 2008 Blizzard
StarCraft and Brood War CDs, plus a CD key. This repo provides neither.
Drop the disc images into `downloads/` (or pass `--discs DIR`). The
installer verifies them against known retail hashes and stops with an
error if they are absent or do not match.

```sh
git clone <this repo> && cd nydus-sc1-wine
./install.py # verifies your discs, downloads the free patches and tools, installs
./launch.sh
```

During the Blizzard installer you'll be asked for your CD key. Keep
default paths and don't launch the game at its end.

You get the game in a virtual desktop. Battle.net is not configured by
default, see below.

## Gateways

Official Blizzard gateways are dead for 1.16.1. To play on public
PvPGN servers, pick some yourself from the live tracker:

```sh
python3 -m sc_installer gateway --list # live list from track.pvpgn.pro
python3 -m sc_installer gateway --pick 3,18
```

This writes `gateways.reg` and imports it into the prefix. `launch.sh`
imports it on every start. Pick a gateway in the dropdown at the login screen.

## Tweaks

Files live in `prefix/drive_c/Program Files (x86)/StarCraft/` and next
to `launch.sh` in the repo root.

### Resolution and scaling

Edit `ddraw.ini` in the game directory: `width` and `height` plus the
`shader=` line. Also update the `/desktop=sc,WxH` argument in
`sc_installer/install.py` to match. Use integer multiples of 640×480
for sharp pixels (see table below).

| Scale | Resolution | Fits display |
| ----- | ---------- | ------------ |
| 1×    | 640×480    | any          |
| 2×    | 1280×960   | 1080p        |
| 3×    | 1920×1440  | 1440p        |
| 4×    | 2560×1920  | 4K           |
| 5×    | 3200×2400  | 5K           |

### Mouse

- Edit `adjmouse` in `ddraw.ini` for cnc-ddraw's automatic sensitivity
  scaling. Off by default because it made the cursor too slow on my
  display. You may prefer turning it back on rather than adjusting
  your desktop settings.
- Wine's MouseSensitivity registry values do nothing for this game.
  Fine-tuned control comes from adjusting desktop settings. On GNOME:
  `gsettings set org.gnome.desktop.peripherals.mouse speed -0.15` and
  `accel-profile 'flat'`.

## License

GPLv3 or later. See `COPYING`. Wine is LGPL, and the Debian packages
in the rootfs are mixed free licenses.
