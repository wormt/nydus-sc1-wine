# FAQ and troubleshooting

## How do I change the server list?

Nothing is preconfigured: generate the file from the tracker with
`python3 -m sc_installer gateway --pick <n>` (see `--list` for live
options), then edit further by hand if you like.

## The gateway list lost my servers or reset to Blizzard defaults

The game rewrites that registry value on exit and drops custom servers.
`launch.sh` re-imports `gateways.reg` on every start, so custom servers
always come back. If you launched the game some other way, run
`python3 -m sc_installer gateway --pick <n>` and relaunch.

## The mouse feels wrong

The game reads raw mouse deltas, and wine's MouseSensitivity registry
values do nothing. You have to change the host pointer instead. On GNOME:

```sh
gsettings set org.gnome.desktop.peripherals.mouse speed -0.15
gsettings set org.gnome.desktop.peripherals.mouse accel-profile 'flat'
```

cnc-ddraw's `adjmouse` is off in our defaults. You can also try changing
it if you want to avoid changing your desktop settings.

## Low FPS

Check that `ddraw.ini` has `renderer=opengl`, and that the wine registry
has `ddraw=native,builtin`. Without that override, wine uses the built-in
ddraw which uses CPU.

## Pixels look blurry or uneven

Use integer scaling. Set `width` and `height` in `ddraw.ini` to exact
multiples of 640×480 and leave `shader=` empty (or set it to
`Shaders/nearest-neighbor.glsl`). Shaders such as fsr or catmull-rom give
even scaling at non-integer ratios and 16:9 aspect, at the cost of
sharpness.

## Battle.net bounces me back to the multiplayer menu

The TCP connection failed. Check that the server is alive with
`python3 -m sc_installer gateway --list`, which shows live user counts,
and that the dropdown at the login screen has the intended gateway
selected. Blizzard's own gateways are dead for 1.16.1 and always bounce.
