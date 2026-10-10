---
name: mothership
description: Control and inspect an Alienware laptop on Linux through mothership (the Alienware Command Center replacement) - keyboard and chassis lighting (colours, rainbow/wave/breathing effects, per-key colours, the Fire effect, brightness, lid logo, rear and touchpad lights), thermal modes, fans, fan boost, G-Mode, CPU temperature and power limits, power adapter checks, power-button colours, macro keys, per-app profiles, graphics mode (hybrid vs dGPU only) and lighting-controller firmware updates. Use whenever the person asks things like "make my keyboard red", "rainbow lights", "turn the lid logo green", "fans to quiet", "G-Mode on", "why is the laptop hot / loud", "lower the CPU power limit", "is my adapter big enough", "switch to dGPU only", "update the lighting controller firmware", or any Alienware/AWCC lighting, fan or thermal question, even if they don't say "mothership".
---

# mothership (Alienware lighting, thermal, firmware)

`mothership` is a CLI client of the user daemon `mothershipd`, which owns the
devices and keeps the desired state in `~/.config/mothership/config.json`
(re-applied at start, after suspend and when a device comes back). Every change
goes through the daemon, so the bar widget and the config stay in sync. It works
the same from a desktop, a console or SSH.

## 1. Look before you change

```sh
mothership --json status        # --json goes BEFORE the subcommand
```

| Field | Meaning |
|---|---|
| `devices` | Detected keyboard / chassis controllers (`null` = not present) |
| `config` | The desired state: `keyboard`, `chassis`, `thermal` (`auto`, `power_limits`, `tcc_offset`, `gmode`), `power_button`, `profiles`, `macros` |
| `errors` | Per part (`keyboard`, `chassis`, `thermal`, `tcc`, `power_limit`...). Report them; see Troubleshooting |
| `keyboard` | Live read from the keyboard: `firmware`, `layout`, `mode`, `brightness`; `unlit` = LED ids with no LED (on the x17 R2 the space bar, 106/107, is unlit) |
| `chassis.zones` | Chassis zones this machine has. Only offer `touchpad` if it is listed |
| `thermal` | `mode`, `modes` (valid names), `gmode_available`, `fans[]` (`rpm`, `boost_pct`), `temps` (`package`, `cpu`, `gpu` in °C), `ac`, `dgpu` (`state`; `temp/util/watts` only while it is awake), `tcc_offset`, `power_limits` (W), `power_info` (adapter, see below) |
| `graphics` | `mode`: `hybrid`, `discrete` or `unknown` |

Missing keys mean the hardware or driver isn't there: say so instead of guessing.
Only parse `--json` output: the plain output is for people and its format
changes. The commands below are shown without `--json` for readability; add it
(before the subcommand) whenever you read the reply. A change returns the new
state of that part; an `error` field in it, or a non-zero exit, means it didn't
land.

## 2. Lighting

Colours are `RRGGBB` hex (a leading `#` is fine). Translate names yourself:
red `ff0000`, green `00ff00`, blue `0000ff`, white `ffffff`, purple `8000ff`,
pink `ff0080`, orange `ff6000`, yellow `ffd000`, cyan `00ffff`, teal
`00ffb0`. LEDs are not paint: pure, saturated colours look best.

**Keyboard** (`kb`):

```sh
mothership kb static ff0000                       # one colour
mothership kb effect spectrum --speed 2           # rainbow, whole board cycles
mothership kb effect wave --dir left              # rainbow rolling across the keys
mothership kb effect breathing -c ff0040 -c 0040ff
mothership kb brightness 60                       # 0-100
mothership kb fire                                # flames; pressed keys flare
mothership kb off
```

Effects: `static`, `breathing` (1-2 colours), `wave` (rainbow), `spectrum`
(rainbow), `scanner` (colour), `aurora` (fixed greens/blues), `gradient`
(2 colours), `static-blue` (firmware cyan), `fire`, `perkey`, `off`.
Options: `--speed 0|1|2`, `--dir left|right|up|down|bounce|bounce-v`,
`--on static|press|release` (light keys on press). `kb reactive RRGGBB
[--release]` lights only the keys you press. Per-key colours: `kb key LED=RRGGBB
...` (LED ids, not key names: see [reference.md](reference.md#keyboard-led-ids));
unnamed keys take the keyboard's base colour. Fire needs the system service
`mothership-fire` (`sudo systemctl enable --now mothership-fire`): suggest it
to the person if Fire does nothing.

**Chassis lights** (`chassis`, alias `lights`): zones `all`, `head` (the lid's
alien head, "lid logo"), `rear` (= `rear_left` + `rear_right`), `touchpad`
(only if `chassis.zones` lists it).

```sh
mothership chassis color head 00ff00              # one zone, static
mothership chassis color all ff0000               # every zone (clears per-zone colours)
mothership chassis effect spectrum                # all chassis lights
mothership chassis effect morph -c ff0000 -c 0000ff --duration 4000
mothership chassis brightness 50
mothership chassis off
```

Chassis effects: `static`, `breathing`, `pulse`, `morph` (cycles through each
`-c`), `spectrum` (rainbow), `wave` (rainbow travelling), `off`; they apply to
all chassis lights at once. "Rainbow everything" = `kb effect spectrum` +
`chassis effect spectrum`. The power button is not a chassis zone: it has its
own flash-stored colours (Safety).

`mothership reapply` re-sends the configured lighting if the hardware lost it.

## 3. Thermal and fans

```sh
mothership fans mode quiet            # any name from thermal.modes; turns auto off
mothership fans auto on               # back to the automatic rules
mothership fans boost 40 [--fan N]    # 0-100 % on top of the EC curve, or off; turns auto off
mothership gmode on|off|toggle        # G-Mode
mothership fans tcc 5                 # throttle 0-15 °C earlier (cooler, quieter, slower)
mothership fans power-limit 45 [--mode quiet]   # CPU package watts (15-250), all modes by default; "off" drops it
```

- Modes on the x17 R2: `low-power quiet balanced balanced-performance
  performance custom`. Always pick from `thermal.modes`.
- **Auto rules** (`config.thermal.auto`, on by default): `balanced` on AC,
  `quiet` on battery; `performance` while the CPU package is ≥ 95 °C, the dGPU
  ≥ 80 °C or ≥ 60 % busy for 8 s, back below 80 °C / 66 °C for 45 s; fan boost
  ramps from 78 to 94 °C. A manual mode or boost turns auto off until
  `fans auto on`; so does `gmode on` (`gmode off` restores the previous mode
  but not auto: turn it back on if the person wants it).
- **G-Mode** on the x17 R2: the firmware treats `performance` as G-Mode (fans
  pinned high, F1 lights white). With mothership's kernel module
  (`gmode_available: true`) `gmode on` selects the real G-Mode profile and the
  mode then reads `performance`; without it, `gmode on` switches to
  `performance`.
- **Don't spam thermal changes.** On the x17 R2 every mode or boost change makes
  the BIOS rewrite its settings in flash. Set what was asked once; never loop,
  sweep or "try each mode" to compare.
- The BIOS resets CPU power limits on every mode change; the daemon puts the
  person's back. `power-limit off` forgets the setting (the current value stays
  until the next mode change).

**"Why is it hot / loud?"** Read `status`: `temps`, `fans[].rpm`, `mode`,
`config.thermal.auto`, `ac`, `dgpu` (`state: active` + `util` = something is
using the GPU), `power_limits`. Then find the load (`ps -eo pid,comm,%cpu
--sort=-%cpu | head`). Explain, and offer remedies (quiet mode, a power limit,
a TCC offset, closing the busy app) instead of applying them unasked. Don't run
`nvidia-smi` when `dgpu.state` is `suspended`: it wakes the GPU.

**"Is my adapter big enough?"** `thermal.power_info` (needs mothership's kernel
module): `adapters`, `watts` per adapter, `status` `ok` / `undersized` (below
what this model needs; 330 W for the x17 R2 with its bigger GPU/panel, 240 W
otherwise) / `unsupported` (non-Dell). On battery the BIOS reports `ok`. If
`power_info` is missing, say it can't be read here and suggest checking the
adapter's label.

## 4. Profiles, macros, graphics, firmware

```sh
mothership profile list                                   # and which one is active
mothership profile add wow --match '^wow' --kb spectrum --mode gmode
mothership profile remove wow
mothership macro keys                                     # F2-F6 and saved macros
mothership graphics                                       # status (read-only)
mothership firmware check ~/Downloads/elc-....hex         # read-only validation
```

Profiles apply while a window whose class (`--match`) or title (`--title`)
regex matches is focused (Hyprland only); options `--kb`, `--kb-color`,
`--chassis`, `--chassis-color`, `--mode <mode|gmode>`. Adding a profile with an
existing name replaces it. Macros, graphics changes and firmware writes are in
Safety. Full syntax: [reference.md](reference.md).

## Safety

These are persistent or disruptive. Run them only when the person explicitly
asked for that change in this conversation, and say what will happen first.

- **Controller flash:** `power set <state> RRGGBB --write-flash` (power-button
  colour per power state: `all ac-full ac-charging ac-sleep dc-on dc-low
  dc-sleep`) and `macro set <F2-F6> "<keys>" --write-flash` / `macro clear <key>
  --write-flash`. Flash wears and these survive reboots: one write per request,
  never in a loop, never "to test". Without `--write-flash` they refuse; don't
  add the flag on your own initiative. `power show` is read-only.
- **Firmware** (`firmware update|restore|backup`): only on an explicit request.
  Run `mothership firmware check <image>` first and show its result. Update
  needs sudo and AC power, takes the image from Dell's AWCC package (mothership
  ships none), backs up the controller to `/var/lib/mothership/firmware` first
  and verifies the write. Tell the person the risk plainly: an interrupted or
  wrong flash can leave the lighting controller unusable (a repair can mean a
  new motherboard); it's at their own risk. Prefer handing them the command
  (`sudo mothership firmware update <image>`, which asks them to type
  `update`); use `--yes` only if they asked you to run it after that warning.
- **Graphics mode:** `graphics change` restarts the computer into the firmware
  setup screen, where the person switches hybrid/discrete themselves. Only on
  an explicit request, after warning that open work will be lost and asking
  them to save; it needs `--yes` when not run from a terminal.
- Never send raw HID reports or WMI calls, write to `/sys` or `/dev/hidraw*`
  yourself, or edit udev rules, groups or permissions to get around an error.
  mothership exists so that nothing else touches these devices.

## Troubleshooting

- Exit code 3 = the daemon isn't running (or didn't answer): tell the person, and start it with
  `systemctl --user start mothershipd` (`journalctl --user -u mothershipd` for
  why it stopped). Don't work around it.
- `Permission denied` in `errors`: the udev rules or the `mothership` group
  aren't in effect (`sudo usermod -aG mothership "$USER"`, then log out and
  in). Tell the person; don't change permissions yourself.
- On an Omarchy desktop the bar widget can also be driven, and it is the way to
  *show* the person something: `quickshell ipc -p /usr/share/omarchy/shell call
  mothership showTab thermal` (`keyboard|chassis|thermal|power`), `openWindow`
  (full key-painting window). More in [reference.md](reference.md#omarchy-bar-widget).
  `mothership tui` is an interactive terminal UI for the person; suggest it,
  don't drive it.
