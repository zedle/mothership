# mothership: design

Date: 2026-10-09. Status: design for the first release. This document covers the
whole system and specifies sub-project 1 (core daemon + CLI) in detail; sub-projects 3 (firmware updater) and
4 (kernel driver) get their own specs once their research is complete.

## Goal

Everything Alienware Command Center does on Windows, on Linux, for the person's Alienware x17 R2 first and any
model whose hardware the tool can recognise:

- Lighting: per-key keyboard (Darfon/ITE "API v5", 0d62:cabc and siblings) and the AW-ELC chassis controller
  (187c:0550/0551: alien head, rear "stadium" loop, touchpad zones, power button). Firmware effects, brightness,
  firmware key-press reactions, software effects (fire with key flares), power-button profiles per power state.
- Thermal: thermal modes (platform_profile), real G-Mode, fan boost, software fan curves, sensors, the G key.
- Extras the kernel exposes after sub-project 4: CPU TCC offset, MUX switch, Intel boost, adapter watts,
  touchpad backlight.
- Firmware: AW-ELC firmware update (sub-project 3).

Success: on this x17 R2, every AWCC lighting effect and thermal mode can be selected from the bar popup, the full
window and the CLI; settings survive reboot/suspend without writing controller flash; the old kbd-fire,
gage-fans and gage.fans are retired in its favour; on a machine without the hardware it installs and does nothing.

## Constraints

- Clean room: protocols are reimplemented from our own notes (the project's private protocol notes). No Dell code, binaries,
  firmware images or metadata files are copied into the repo. Facts (opcodes, zone numbers, effect ids) are written
  in our own words and data formats. The firmware updater asks the user for Dell's package; it never ships images.
- Python 3.11+, standard library only (the hardware tools here already are). No compiled extensions.
- Never write controller flash implicitly. Commands that persist (ELC COMMIT_TO_FLASH/REMOVE/SET_DEFAULT/
  SET_STARTUP, keyboard `84 03`, `85 ae`, macro writes, ELC `03 ff` erase, any firmware update) are refused
  unless the caller passes an explicit flag; `03 ff` and keyboard bootloader commands are never sent at all.
- Least privilege: the daemon runs as the user. Devices are reached through udev rules granting a `mothership`
  group (keyboard hidraw write-only 0620, ELC hidraw 0660, alienware_wmi sysfs files 0664). Keystrokes are read
  only by the sandboxed fire service (system unit, DynamicUser, groups input + mothership, no network/home), and
  only while the Fire effect is selected.
- Hardware-gated: every part detects its hardware (USB ids, sysfs names, DMI only as a hint, never a hostname)
  and is a no-op without it.

## Architecture

```
mothership CLI ─┐                      ┌─ keyboard (hidraw, feature reports 0xcc)
bar popup (QML) ├─ JSON over unix ─ mothershipd (user) ─┼─ AW-ELC (hidraw, 33-byte output/input reports)
full window     ┘  socket                │              ├─ thermal (/sys/class/platform-profile, hwmon alienware_wmi)
agents (CLI/IPC)                         │              └─ extras (sysfs from the extended driver, sub-project 4)
                                         └─ /run/mothership/{effect,unlocked,mute,micmute} ─ mothership-fire (system,
                                                                                            sandboxed, keystrokes)
```

Python package `mothership/` (one purpose per module):

| Module | Purpose | Depends on |
|---|---|---|
| `hidraw.py` | Find hidraw nodes by VID/PID/usage via sysfs uevent + report descriptor; feature/output/input ioctls | stdlib |
| `models.py` + `data/devices.json` | Known devices: USB ids, protocol, LED/zone maps, key layout id; model detection | data file |
| `keyboard.py` | Keyboard protocol: status reads (91/93/94/9c), firmware effects (80), stop (8c 10), per-key frames (8c 02/13), effect map (8c 05), slot config (8c 01), brightness (8b 01, 83 38 9c), calibration | hidraw |
| `elc.py` | AW-ELC protocol: reports (20 sub 0-5), SET_COLOR 27, SET_DIM 26, animations (21/23/24 with BEGIN/RUN_FROM_RAM/PLAY/stop), guarded saves (power states 91-96 via 22) | hidraw |
| `effects.py` | Effect catalogue: firmware effects (keyboard), ELC animation recipes (breathing, spectrum, rainbow wave, morph, pulse, color), software effects run by the daemon (none heavy; fire lives in the fire service) | keyboard, elc |
| `thermal.py` | Modes, G-Mode, fan boost (scale-aware), sensors, auto rules (ported from gage-fans), fan curves | sysfs |
| `extras.py` | TCC offset, MUX, Intel boost, adapter watts, touchpad backlight, when the extended driver exposes them | sysfs |
| `config.py` | `~/.config/mothership/config.json` (user settings) and `~/.local/state/mothership/state.json` | stdlib |
| `daemon.py` | Owns devices; applies config at start, after resume (logind PrepareForSleep via `busctl monitor`/`gdbus`, or a 2 s wall-clock jump check) and on hotplug; serves the socket; runs thermal auto rules | all |
| `ipc.py` | Line-delimited JSON request/response over `$XDG_RUNTIME_DIR/mothership.sock`; also used by the CLI | stdlib |
| `cli.py` | `mothership …` commands; talks to the daemon, falls back to direct device access for one-shot commands when no daemon runs | ipc, modules |
| `fire.py` | Fire effect + key flares (port of kbd-fire): run only by `mothership-fire.service` | keyboard, elc |

Front ends (sub-project 2): `ui/omarchy/` (a Quickshell plugin: bar widget + popup + full window using
gage-ui conventions and theme colours) and the CLI. All front ends only talk to the daemon.

## Sub-project 1: core daemon + CLI (detailed)

### Device layer

- `hidraw.find(vid, pids, usage_page=None)` walks `/sys/class/hidraw/*/device/uevent` (HID_ID) and parses the
  report descriptor (`device/report_descriptor`) for the vendor usage page, returning `/dev/hidrawN`.
- Keyboard: open `O_WRONLY` (the typing interface is the same device; never read input reports). Reads are
  SetFeature(request) then GetFeature(0xcc) into the same 64-byte buffer (ioctl works on a write-only fd).
- ELC: open `O_RDWR`; write 33-byte output reports (first byte 0x03); read the 33-byte input reply after 10 ms
  with a 200 ms poll timeout; a missing reply is tolerated for commands whose reply AWCC ignores.

### Keyboard

- `status()` -> {firmware (91), layout family/enum and chassis colour (93), mode, bank, brightness, colour (94)}.
- `effect(name, colors, speed 0-2, direction, play static|press|release)` builds the 0x80 packet per effect
  table (breathing 2, spectrum 14, rainbow wave 3, scanner 10, static 1, aurora 3+palette, gradient 3, static
  blue 1) and then sets brightness.
- `brightness(pct)` -> `8b 01 <pct*255/100>` (+ `83 38 9c <level>` below 100 in per-key mode).
- `per_key({led: rgb})` -> stop effect if mode != 0x8c, effect map (all slot 1), slot config, colour frames
  (15 per packet, calibration gains applied), `8c 13`, brightness.
- `reactive(color, on=press|release)` -> firmware key-press mode via 0x80 byte 7 (whole board) and, when the
  firmware accepts it, per-key slot 5. Must be verified on hardware; if the firmware ignores it, the feature is
  reported as unsupported for that model.
- Never sends: `84 03 00`, `85 ae`, `73/74/77/79` (macro/flash) without the explicit persist flag; bootloader
  (048d:89db) commands never.

### AW-ELC

- `info()` -> firmware version (20 00), platform id + LED count (20 02), animation count (20 03).
- `color({zones: rgb})` -> 0x27 packets (26 LEDs each). Volatile.
- `dim(pct, include_power=False)` -> 0x26. Volatile (unverified; checked on hardware before relying on it).
- `play(recipe)` -> BEGIN id 0xFFFF, series/actions, RUN_FROM_RAM (no flash). `stop()` -> PLAY id 0.
- `save_power_state(state, recipe, persist=True)` -> REMOVE id, 250 ms, BEGIN, series, COMMIT_TO_FLASH on
  opcode 0x22 for ids 91-96. Only from the CLI with `--write-flash`, never from the daemon loop.
- Zone map for model 0x0406/0x0306: 0 power, 1 alien head, 2-9 touchpad (lit-touchpad models), 10-14 rear left,
  15-19 rear right. Detected LED count (20 02) bounds every zone list.

### Thermal

- Modes come from `platform_profile_choices`; G-Mode is `performance` when the driver runs with `force_gmode`
  (or the extended driver's x17 quirk). `mothership gmode on|off|toggle` remembers the previous mode.
- Fan boost: written to `fanN_boost`; the UI shows 0-100 %, mapped onto the driver's range (verify on hardware
  whether 100 or 255 is the top; the scale lives in one constant).
- Auto rules: the gage-fans rules (AC/battery profile, hot -> G-Mode, boost ramp by package temperature) move
  into `thermal.Auto`; settings keep the same keys under `thermal` in config.json.
- Fan curves (AWCC style, optional): per fan `boost = clamp(a*T^2+b*T+c)` every 10 s, written on change > 10 %.

### Daemon, state and resume

- Config is the desired state: `{"keyboard": {...}, "chassis": {...}, "thermal": {...}}`. The daemon applies it at
  start, after resume (firmware forgets volatile lighting) and when a device reappears; CLI/UI changes update the
  config and apply immediately.
- Lock screen: while `/run/mothership/unlocked` is stale (>12 s) or absent, key flares are off (fire service);
  gage.lock's refresher writes that path (compat symlink from `/run/kbd-fire`).
- Indicators: mute/micmute flags under `/run/mothership/` (port of kbd-fire-mute into the daemon via
  `pactl subscribe`) light Mute/Mic Mute white in per-key modes; Caps Lock likewise from sysfs LEDs.

### IPC (socket, line-delimited JSON)

Request `{"cmd": "keyboard.effect", "args": {...}}` -> response `{"ok": true, "result": ...}` or
`{"ok": false, "error": "..."}`. Commands: `status`, `devices`, `keyboard.{effect,brightness,reactive,static,off,
per_key}`, `chassis.{color,dim,effect,off}`, `power.{show,set}` (set needs `write_flash: true`), `thermal.{mode,
gmode,boost,auto,curve}`, `extras.*`, `fire.{on,off}`, `config.{get,set}`.

### CLI

```
mothership status | devices
mothership kb effect <breathing|spectrum|rainbow|scanner|aurora|gradient|static|static-blue> [--color RRGGBB]...
              [--speed 0-2] [--dir left|right|up|down] [--on static|press|release]
mothership kb brightness <0-100> | kb static RRGGBB | kb off | kb fire | kb reactive RRGGBB [--release]
mothership chassis color <zones|all|head|rear|touchpad> RRGGBB | chassis effect <...> | chassis dim <0-100>
mothership power show | power set <ac-sleep|ac-full|ac-charging|dc-sleep|dc-on|dc-low> <effect> RRGGBB --write-flash
mothership fans [status] | fans mode <name> | fans boost <0-100|off> [fan] | fans auto on|off | gmode on|off|toggle
mothership daemon            (run by the user unit)
```
`--json` on every read command for agents.

### Packaging (this repo)

- `pyproject.toml` (console script `mothership`), `Makefile` (`make install PREFIX=… DESTDIR=…`),
  `packaging/arch/PKGBUILD`.
- `data/udev/70-mothership.rules`, `data/sysusers.d/mothership.conf`, `data/tmpfiles.d/mothership.conf`,
  `data/systemd/user/mothershipd.service`, `data/systemd/system/mothership-fire.service`.
- `docs/`: README with supported hardware, safety rules and the clean-room note.

### Testing

- Unit tests (`python3 -m unittest`) with a fake hidraw that records packets and replays scripted replies, and a
  fake sysfs tree in a temp dir: every packet builder is checked byte for byte against the findings tables;
  guards are tested (persisting commands refused without the flag; `03 ff` impossible to build).
- Hardware smoke tests (`tests/hw/`, run by hand on the machine, opt-in env var): status reads, each effect,
  brightness, chassis colours, thermal mode round trip. Volatile only.

### Migration on this machine (dotfiles)

The dotfiles' extras.sh installs mothership on machines with the hardware; kbd-fire.service, gage-fans.service and
gage.fans are disabled once mothership's equivalents work; AGENTS.md is updated (G-Mode correction included).

## Sub-projects 2-4 (summary; own specs follow)

2. Front ends: Omarchy plugin (bar widget with popup tabs Lighting / Thermal / Power / System, and a full window
   with a clickable key map, zone map and fan-curve editor), driven only through the socket.
3. Firmware updater: AW-ELC 1.1.x/2.1.x from a user-supplied Dell package; image + target validation,
   bootloader never written, AC required, explicit confirmation; dry-run mode parses everything without
   touching the device.
4. Kernel: an extended alienware-wmi (DKMS) with the missing WMAX methods as sysfs/firmware-attributes,
   upstreamable.
