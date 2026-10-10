# mothership core (daemon + CLI) Implementation Plan

> For agentic workers: implement task by task; each task ends green (`python3 -m unittest -q`) and committed.

**Goal:** the device layer, protocols, thermal control, daemon, CLI, fire service and packaging of mothership.

**Architecture:** stdlib-only Python package `mothership/`; a user daemon owns the devices and serves JSON over a
unix socket; the CLI and UIs are clients; the sandboxed fire service is the only keystroke reader.

**Tech stack:** Python 3.11+ stdlib, unittest, systemd (user + system units), udev, sysusers/tmpfiles.

**Spec:** `docs/specs/2026-10-09-mothership-design.md`. Protocol references (not in the repo, clean-room notes):
the project's private protocol notes.

## Global constraints

- Standard library only; Python >= 3.11.
- No Dell code, binaries, firmware, metadata files or calibration tables in the repo; facts in our own format.
- Never send: ELC `03 ff`; keyboard bootloader (048d:89db) anything. Persisting commands (ELC 0x21/0x22 sub 2/4/6/7,
  keyboard `84 03`, `85 ae`, `73`, `74`, `77`, `79`) only through functions that require `write_flash=True`.
- Daemon runs as the user; keyboard hidraw opened O_WRONLY; ELC O_RDWR.
- Hardware absent -> every command reports "not present" and exits 0; the daemon idles.

## Review focus

1. Device unplugged/replugged or suspended mid-command (hidraw write raises OSError/ENODEV): daemon must reopen on
   the next apply, never crash the loop. Test: fake device raising OSError, then a new fake found -> apply succeeds.
2. A second client or a stale socket file: daemon removes a stale socket at start, refuses to start if another live
   daemon answers. Test in ipc tests.
3. Invalid user input (colour "red", brightness 140, unknown effect, zone 25 on a 20-LED controller): clear error,
   no packet sent. Tests in keyboard/elc/cli.
4. Config file corrupted or from an older version: fall back to defaults for the bad section, keep the rest, log once.
   Test in config tests.
5. Thermal sysfs missing or permission denied (driver not loaded, udev rule absent): thermal commands report the
   reason; daemon keeps lighting working. Test with a fake sysfs tree without hwmon.

---

### Task 1: scaffold + fake devices
Files: `pyproject.toml`, `mothership/__init__.py` (`__version__ = "0.1.0"`), `tests/__init__.py`,
`tests/fakes.py` (FakeHid: records `sent` list of bytes for feature/output writes, `replies` queue for
get_feature/read; FakeSysfs: builds a temp tree with platform-profile + hwmon alienware_wmi), `.gitignore`, `LICENSE` (MIT).
Test: `tests/test_fakes.py` round-trips a packet. Commit "scaffold".

### Task 2: hidraw discovery + transport (`mothership/hidraw.py`)
Produces: `find(vid:int, pids:set[int], usage_page:int|None=None, root="/sys/class/hidraw") -> list[str]` (dev paths),
`class Hid: __init__(path, write_only=False); set_feature(buf); get_feature(buf)->bytes; write(buf); read(n, timeout_ms)->bytes|None; close()`.
Ioctls: HIDIOCSFEATURE(len) = _IOC(3,'H',6,len), HIDIOCGFEATURE(len) = _IOC(3,'H',7,len).
Uevent parse: `HID_ID=0003:00000D62:0000CABC`. Usage page from report descriptor bytes `06 lo hi` (global usage page).
Tests: fake sysfs tree with two hidraw entries -> find picks the matching vid/pid and usage page 0xff89.

### Task 3: keyboard protocol (`mothership/keyboard.py`)
Produces: pure builders returning 64-byte `bytearray`s and a `Keyboard(hid)` class:
- `pkt(*b)`; `status_requests()`; `parse_status(r91, r93, r94) -> dict(firmware, layout_family, layout, chassis_dark,
  mode("perkey"|"effect"|"other"), bank, brightness(0-100), color(r,g,b))` (94 colour bytes 22..24 are B,G,R).
- `effect_packet(name, colors, speed=1, direction="right", play="static", loop=True) -> bytearray` with mode/byte
  tables: static(1) breathing(2) wave(3, flag 1) aurora(3 + fixed palette bytes) gradient(3, [17]=2) scanner(10)
  spectrum(14, flag 1); speed steps per effect (3 entries) for [3] and [16]; directions 1..6.
- `brightness_packet(pct) -> 8b 01 <round(pct*255/100)>`; `level_packet(pct) -> 83 38 9c <round(pct*254/100)>`.
- `perkey_packets(colors: dict[int,(r,g,b)], first=True) -> list[bytearray]`: if first: `8c 10`, clears for slots
  01 02 05 08 09 0e, map packets 05/06/07 with 1 for each coloured LED; slot config `8c 01 01 01 00 00 01 01 01 00 R G B R G B 01`;
  colour frames `8c 02 00 [led+1 r g b]*15`; `8c 13`.
- Keyboard methods: `status()`, `effect(...)`, `brightness(pct)`, `perkey(colors)`, `static(rgb)`, `off()`, `reactive(rgb, on)`.
- Persisting: `save_as_power_on(write_flash=False)` raises `PermissionError` unless True; sends `84 03 00`.
Tests: byte vectors, e.g. `effect_packet("breathing", [(255,0,0)], speed=0)` ==
`cc 80 02 01 00 00 01 01 01 00 ff 00 00 ff 00 00 02` + zeros; brightness(100) -> `cc 8b 01 ff`; invalid input raises ValueError.

### Task 4: AW-ELC protocol (`mothership/elc.py`)
Produces: builders returning 33-byte payloads (byte0 0x03) and `Elc(hid)`:
- `report(sub, arg=None)`; `parse_version(reply)`, `parse_config(reply) -> (platform, led_count)`.
- `color_packets(rgb, leds) -> list` (26 per packet: `03 27 R G B 00 n leds`).
- `dim_packets(pct_dim, leds) -> list` (28 per packet: `03 26 dim page n leds`).
- `anim_cmd(op, sub, anim_id, duration=0)` (`03 op subHi subLo idHi idLo durHi durLo`; finish quirk: id cast to byte).
- `series_packets(leds, loop=True)`; `action_packets(actions)` (3 per packet, `eff durHi durLo tempoHi tempoLo R G B`).
- Effects: COLOR 0, PULSE 1, MORPH 2. Recipes: `recipe(name, colors, duration_ms, tempo)` -> list[(leds, actions)].
- `Elc.play(recipe)` (BEGIN 0xFFFF ... RUN_FROM_RAM), `stop()`, `color()`, `dim()`, `info()`.
- `save_power_state(state, recipe, write_flash=False)` -> PermissionError unless True; op 0x22, REMOVE, 250 ms,
  BEGIN, series, COMMIT_TO_FLASH. States: ac-sleep 91, ac-full 92, ac-charging 93, dc-sleep 94, dc-on 95, dc-low 96.
- No builder exists for opcode 0xFF; `anim_cmd` refuses sub 2/4/6/7 unless `write_flash=True`.
Tests: protocol vectors (50 % dim on 19 LEDs = `03 26 32 00 13 01..13`), guards, zone bounds.

### Task 5: models (`mothership/models.py`, `mothership/data/devices.json`)
devices.json (our format): keyboards [{vid, pid, name, protocol "darfon-v5", report_len 64}], chassis [{vid, pids,
protocol "elc-v4"}], zone maps by ELC platform id ({"0x0306": {...}, "0x0406": {...}}: power [0], head [1],
touchpad [2..9], rear_left [10..14], rear_right [15..19]), keyboard layouts (LED geometry from kbd-fire's KEYS, MIT).
Produces: `detect() -> Machine(keyboard: Keyboard|None, chassis: Elc|None, zones: dict, keys: dict)`.

### Task 6: thermal (`mothership/thermal.py`)
Port gage-fans: `Thermal(root="/")` with `available()`, `status()`, `modes()`, `set_mode(name)`, `gmode(on)`,
`set_boost(pct, fan=None)` (scale constant BOOST_MAX read from config, default 255), `fans()`, `temps()`,
`Auto(config).decide(snapshot, now)` (same rules/keys as gage-fans DEFAULTS), `Curve(a,b,c)`.
Tests with FakeSysfs.

### Task 7: config + IPC (`mothership/config.py`, `mothership/ipc.py`)
Config: load/merge defaults per section, atomic save (tmp + rename), corrupted section -> default.
IPC: `serve(path, handler)` (threaded, line JSON), `request(cmd, args, path=None, timeout=5)`; stale socket handling.

### Task 8: daemon (`mothership/daemon.py`)
`Daemon(machine, config)`: `apply_all()`, handlers for every IPC command in the spec, thermal loop (interval from
config), resume detection (monotonic vs wall clock jump > 5 s, and `/sys/power` hooks not needed), device re-detect
on OSError, indicator flags under `/run/mothership` (mute/micmute via `pactl subscribe` subprocess, optional).
Writes `/run/mothership/effect` for the fire service.

### Task 9: CLI (`mothership/cli.py`, console script `mothership`)
argparse tree per spec; `--json`; uses ipc.request, falls back to direct device mode for one-shot commands.

### Task 10: fire service (`mothership/fire.py`)
Port kbd-fire's fire()/flares/caps/mute logic onto `keyboard.Keyboard`; runs only while `/run/mothership/effect`
contains `fire`; otherwise closes input devices and sleeps on inotify-free polling (1 s).

### Task 11: packaging
`data/udev/70-mothership.rules`, `data/sysusers.d/mothership.conf`, `data/tmpfiles.d/mothership.conf`,
`data/systemd/user/mothershipd.service`, `data/systemd/system/mothership-fire.service` (DynamicUser, groups input
mothership, sandboxing as kbd-fire.service), `Makefile` install/uninstall, `packaging/arch/PKGBUILD`, `README.md`.

### Task 12: hardware smoke test + migration (this machine)
`tests/hw/smoke.py` (opt-in). Run volatile checks on the x17 R2; then dotfiles: install via extras.sh behind a hardware
check, retire kbd-fire/gage-fans/gage.fans, update AGENTS.md.
