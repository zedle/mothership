# mothership

A replacement for Alienware Command Center, for Alienware laptops on Linux: keyboard and
chassis lighting, thermal modes and fans, G-Mode, macro keys, per-app profiles and
lighting-controller firmware updates.

First fully supported machine: **Alienware x17 R2** (and the x15 R2, which shares its
lighting controller). Other Alienware laptops with the same controllers (per-key keyboards
from Darfon, `0d62:*`; AW-ELC chassis lights, `187c:0550`/`0551`; the `alienware-wmi` thermal
interface) are detected and get every feature their hardware reports.

## What it does

| | |
|---|---|
| Keyboard | Firmware effects (static, breathing, wave, spectrum, scanner, aurora, gradient), hardware brightness, per-key colours, firmware key-press lighting, and **Fire**: animated flames where the keys you press flare up |
| Lid, rear and touchpad lights | Colours per zone (alien head, rear loop, touchpad), effects (breathing, pulse, morph, spectrum, wave), brightness |
| Power button | Its own colour in each power state (AC, charging, battery, low battery, asleep) |
| Thermal | Thermal modes, real **G-Mode**, fan boost, automatic rules (cool and quiet until something is hot), live fan speeds and temperatures |
| Macro keys | Firmware macros on F2-F6 |
| Profiles | Lighting and thermal mode switch while a matching app is focused (Hyprland) |
| Firmware | Validated, backed-up updates of the AW-ELC lighting controller |
| Desktop | An Omarchy bar widget with a live mirror of the machine's lights, plus a full window for painting keys |

### Your model isn't fully supported yet?

Thermal control works on any laptop Linux's `alienware-wmi` driver supports. Lighting works on the
per-key keyboards and AW-ELC lighting controllers, but individual chassis zones (lid logo, rear,
touchpad) are only named for models someone has mapped. Run `mothership probe`: it lights one LED
at a time and asks what lit up, saves the map for your machine, and prints it so you can contribute
it in an issue or pull request.

## Install (Arch Linux)

```sh
git clone https://github.com/zedle/mothership && cd mothership/packaging/arch
makepkg -si                      # builds mothership and mothership-dkms
sudo usermod -aG mothership "$USER"   # then log out and in
systemctl --user enable --now mothershipd
sudo systemctl enable --now mothership-fire   # only needed for the Fire effect
```

Other distributions: `sudo make install`, then the same group and service steps. The kernel
module in `kernel/` is optional (see below) and installs with DKMS.

## Use

```sh
mothership status                 # the machine at a glance
mothership tui                    # full-screen control panel with a live mirror
mothership kb effect wave --speed 2
mothership kb effect breathing -c ff0040 -c 0040ff
mothership kb fire
mothership kb brightness 60
mothership chassis color head 00ff88
mothership chassis effect spectrum
mothership fans mode quiet
mothership gmode toggle
mothership profile add wow --match '^wow' --kb spectrum --mode gmode
mothership macro set F2 "ctrl+shift+t" --write-flash
mothership --json status          # for scripts and agents
```

### Without a desktop

Everything above works from a console or over SSH; the bar widget is just another client of the
same daemon. To have lighting and the fan rules applied from boot even when nobody logs in, run
`loginctl enable-linger "$USER"` once. Without a graphical session, per-app profiles (they follow
Hyprland's focused window) are inactive and adapter warnings go to `journalctl --user -u
mothershipd` instead of a notification.

Settings live in `~/.config/mothership/config.json`. The daemon re-applies them at start,
after suspend and whenever a device comes back.

## Safety

The lighting controllers keep some settings in flash. mothership never writes flash on its
own: power-button colours and macros are written only when you pass `--write-flash`, and the
command that erases a controller's whole flash is not implemented at all.

Keystrokes are read by one process only, the sandboxed `mothership-fire` service (no
network, no home directory, read-only system), and only while the Fire effect is selected.
The keyboard's lighting interface is opened write-only because it also carries what you type.

Firmware updates (`mothership firmware elc check|backup|update|restore`) refuse any image that
reaches outside the controller's application area, isn't built for the connected controller or
isn't newer, and require AC power. They read the controller's whole flash to a backup file
first, verify what they write, and never touch its bootloader, so a failed update can be
retried or rolled back. mothership doesn't ship firmware: point it at the `.hex` from Dell's
own AWCC package; it stays Dell's.

**Flashing is at your own risk.** mothership is not Dell software. A failed or interrupted
update, a power loss or a wrong image can leave the lighting controller unusable, and a repair
can need a new motherboard. In the US, a manufacturer can't void a warranty just because other
software was used (Magnuson-Moss Warranty Act, 15 U.S.C. §2302(c)), but it can refuse to cover
damage it shows the flash caused. See LICENSE: no warranty.

## Kernel module (optional)

`kernel/` is Linux's `alienware-wmi` driver (v7.2) with additions this BIOS supports but the
stock driver doesn't use: real G-Mode (thermal mode 0xAB) as a `gmode` file, power adapter
information, the default thermal profile and the cooling type. It also stops the driver's
`force_gmode` option from breaking every profile change on BIOSes without the GameShift
method. Install it with the `mothership-dkms` package or `dkms install`. Details in
`kernel/README.md`.

## How it was made

The protocols were reverse engineered from Dell's AWCC for interoperability and written down
as notes; this code was written from those notes. No Dell code, firmware or data files are
included.

## License

MIT, except `kernel/`, which is GPL-2.0 like the Linux driver it extends. Third-party
notices are in `NOTICE`.

Not affiliated with or endorsed by Dell. Alienware, Alienware Command Center (AWCC) and the
alien head logo are trademarks of Dell Inc., named here only to say which hardware and software
mothership works with or replaces.
