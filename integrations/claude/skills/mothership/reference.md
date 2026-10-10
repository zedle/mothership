# mothership reference

Contents: [Commands](#commands) · [Keyboard LED ids](#keyboard-led-ids) ·
[Macro syntax](#macro-syntax) · [Daemon socket](#daemon-socket) ·
[Omarchy bar widget](#omarchy-bar-widget)

## Commands

`--json` is a global flag: `mothership --json <command>`. Parse only `--json`
output. Aliases: `kb` = `keyboard`, `chassis` = `lights`, `fans` = `thermal`.
**Bold** rows need an explicit request (SKILL.md, Safety).

| Command | Does |
|---|---|
| `status` | Devices, desired config, live keyboard/chassis/thermal/graphics state, errors |
| `devices` | Detected controllers |
| `reapply` | Re-send the configured lighting |
| `kb effect <name> [-c RRGGBB]... [--speed 0\|1\|2] [--dir left\|right\|up\|down\|bounce\|bounce-v] [--on static\|press\|release]` | Firmware effect: `static breathing wave scanner spectrum aurora gradient static-blue fire perkey off` |
| `kb static RRGGBB` | One colour |
| `kb brightness 0-100` | Hardware brightness |
| `kb reactive RRGGBB [--release]` | Keys light as pressed (or released) |
| `kb key LED=RRGGBB [LED=RRGGBB ...]` | Per-key colours (switches to `perkey`; stored keys accumulate, others take the base colour) |
| `kb fire` | Fire effect (needs the `mothership-fire` system service) |
| `kb off` | Keyboard dark |
| `chassis color <zone> RRGGBB` | Static colour for `all`, `head`, `rear`, `rear_left`, `rear_right`, `touchpad` |
| `chassis effect <name> [-c RRGGBB]... [--duration MS]` | `static breathing pulse morph spectrum wave off`, all chassis lights |
| `chassis brightness 0-100` | |
| `chassis off` | |
| `power show` | Power states and saved power-button colours (read-only) |
| **`power set <state> RRGGBB --write-flash`** | Power-button colour, saved in controller flash. States: `all ac-sleep ac-full ac-charging dc-sleep dc-on dc-low` (sleep states breathe, `ac-charging` breathes slowly, `dc-low` pulses, the rest are static) |
| `fans` / `fans status` | Thermal state only |
| `fans mode <name>` | Thermal mode from `thermal.modes`; auto off |
| `fans boost <0-100\|off> [--fan N]` | Extra fan speed on top of the EC curve, all fans or one id; auto off |
| `fans auto on\|off` | Automatic rules |
| `fans tcc 0-15` | CPU throttle temperature lowered by that many °C |
| `fans power-limit <watts\|off> [--mode <mode>]` | CPU package power limit 15-250 W (long and short term), for all modes or one |
| `gmode [on\|off\|toggle]` | G-Mode (default toggle) |
| `profile list` | Profiles and the active one |
| `profile add <name> --match <regex> [--title <regex>] [--kb <effect>] [--kb-color RRGGBB] [--chassis <effect>] [--chassis-color RRGGBB] [--mode <mode\|gmode>]` | Per-app profile (Hyprland focus); replaces a same-named one |
| `profile remove <name>` | |
| `macro keys` | Macro keys (F2-F6) and saved macros (read-only) |
| **`macro set <F2-F6> "<keys>" --write-flash`** | Firmware macro, saved in keyboard flash |
| **`macro clear <F2-F6> --write-flash`** | |
| `graphics` / `graphics status` | `hybrid`, `discrete` or `unknown`, and the panel's connector/driver |
| **`graphics change [--yes]`** | Restarts into firmware setup to switch the mode there |
| `firmware check <image.hex> [--allow-downgrade]` | Validate a Dell `elc-*-vX.Y.Z.hex` against this controller; changes nothing |
| **`firmware backup [--dir DIR]`** | Root. Read the controller's whole flash to a file (default dir `/var/lib/mothership/firmware`) |
| **`firmware update <image.hex> [--dir DIR] [--allow-downgrade] [--yes]`** | Root, AC power. Back up, write, verify |
| **`firmware restore <backup> [--dir DIR] [--yes]`** | Root. Write a backup's application area back |
| `tui` | Interactive terminal UI for the person (newer versions) |

Exit codes: 0 ok, 1 error (message on stderr), 2 `power set` without
`--write-flash`, 3 daemon not running or not answering.

## Keyboard LED ids

US layout of the x15/x17 R2 per-key keyboards (`kb key` takes these ids).
Check `status.keyboard.unlit`: those ids have no LED (x17 R2: 106, 107, the
space bar).

| Row | Keys → LED id |
|---|---|
| F row | Esc 0, F1-F10 1-10, F11 11, F12 12, Home 13, End 14, Delete 15 |
| Numbers | \` 20, 1-9 21-29, 0 30, - 31, = 32, Backspace 35 |
| Q row | Tab 40, Q 42, W 43, E 44, R 45, T 46, Y 47, U 48, I 49, O 50, P 51, [ 52, ] 53, \\ 55 |
| A row | Caps Lock 61, A 62, S 63, D 64, F 65, G 66, H 67, J 68, K 69, L 70, ; 71, ' 72, Enter 74 |
| Z row | Left Shift 81, Z 83, X 84, C 85, V 86, B 87, N 88, M 89, , 90, . 91, / 92, Right Shift 94, Up 114 |
| Bottom | Left Ctrl 100, Fn 101, Super 103, Left Alt 104, Space 106 + 107, Right Alt 111, Menu 109, Right Ctrl 112, Left 133, Down 134, Right 135 |
| Right column | Mic mute 19, Mute 16, Volume up 18, Volume down 17 |

Example, WASD red on a dim white board: `mothership kb static 404040` then
`mothership kb key 43=ff0000 62=ff0000 63=ff0000 64=ff0000`.

## Macro syntax

Steps separated by spaces; keys in a step joined with `+` (pressed in order,
released in reverse); `200ms` sets the delay after the previous step. Keys:
`a-z`, `0-9`, `f1-f24`, `enter esc backspace tab space minus equal leftbrace
rightbrace backslash semicolon apostrophe grave comma dot slash capslock print
scrolllock pause insert home pageup delete end pagedown right left down up mute
volumeup volumedown ctrl shift alt super rctrl rshift ralt rsuper` (aliases:
`return escape del control win meta pgup pgdn` and the punctuation itself).
Max 800 bytes encoded.

```sh
mothership macro set F2 "ctrl+shift+t" --write-flash
mothership macro set F3 "ctrl+c 200ms ctrl+v" --write-flash
```

## Daemon socket

The CLI talks to `$XDG_RUNTIME_DIR/mothership.sock` (fallback
`/tmp/mothership-<uid>.sock`): one JSON object per line, request
`{"cmd": "...", "args": {...}}`, reply `{"ok": true, "result": ...}` or
`{"ok": false, "error": "..."}`. The CLI is simpler; use the socket only if a
program needs it.

```sh
printf '%s\n' '{"cmd":"thermal.status"}' | socat - UNIX-CONNECT:"$XDG_RUNTIME_DIR/mothership.sock"
```

Commands: `ping`, `status`, `devices`, `reapply`, `config.get`,
`profiles.get`, `profiles.set {profiles: [...]}` (replaces the whole list),
`keyboard.effect {name, colors?, speed?, direction?, on?}`,
`keyboard.brightness {value}`, `keyboard.keys {keys: {led: hex}}`,
`keyboard.reactive {color, on: press|release}`,
`chassis.effect {name, colors?, duration_ms?}`, `chassis.color {zone, color}`,
`chassis.brightness {value}`, `power.show`, `power.set {state, color,
write_flash: true}`, `thermal.status`, `thermal.mode {name}`,
`thermal.boost {value, fan?}`, `thermal.auto {on}`, `thermal.tcc {value}`,
`thermal.power_limit {value, mode?}`, `thermal.gmode {on: true|false|"toggle"}`,
`macro.keys`, `macro.set {key, keys, write_flash: true}`,
`macro.clear {key, write_flash: true}`, `graphics.change {confirm: true}`.
The Safety rules apply here exactly as to the CLI.

## Omarchy bar widget

Only on an Omarchy desktop with the widget enabled:
`quickshell ipc -p /usr/share/omarchy/shell call mothership <fn> [args]`.
It calls the same CLI, so prefer the CLI for changes; use the widget to show
the person something.

| Function | Does |
|---|---|
| `state` | JSON snapshot: daemon up, problems, keyboard, chassis, thermal (mode, auto, gmode, temps, fans), power button |
| `effect <name>` | Keyboard effect |
| `color <RRGGBB>` | Keyboard colour (keeps a colour effect, else static) |
| `brightness <0-100>` | Keyboard brightness |
| `mode <name>` | Thermal mode |
| `gmode` | Toggle G-Mode |
| `tcc <0-15>` | TCC offset |
| `powerLimit <watts>` | For the current mode; `0` clears it |
| `showTab keyboard\|chassis\|thermal\|power` | Open the popup on that tab |
| `toggle` / `openWindow` / `closeWindow` | Popup / full key-painting window |

## Unknown models: `mothership probe`

Interactive (the person answers what lit up for each LED; it lights one LED at a time from RAM,
never flash). Suggest it when `chassis.zones` only lists `all` (an unmapped controller); the
person runs it themselves in a terminal. It saves `~/.config/mothership/zones/<platform>.json`.
