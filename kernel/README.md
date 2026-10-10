# alienware-wmi (mothership)

An extended `alienware-wmi` kernel module, packaged for DKMS (mothership sub-project 4). It is the upstream
driver (Linux v7.2, `drivers/platform/x86/dell/alienware-wmi*`) plus a few WMAX methods the upstream driver does not
use. It builds one module with the same name, objects, aliases and dependencies as the in-tree one
(`alienware-wmi-base.o`, `-legacy.o`, `-wmax.o`; `wmi:A70591CE-…`, `wmi:A90597CE-…`; depends `wmi`), so DKMS
installs it under `updates/dkms` and depmod picks it over the kernel's copy. `modinfo -F version alienware-wmi`
prints `mothership-1` when ours is the one installed; the in-tree module has no version line.

All changes are in [`patches/0001-alienware-wmi-wmax-gmode-power-thermal-info.patch`](patches/), a commit-style
diff against upstream for submitting later (it needs a `Signed-off-by:` from whoever submits it; the
`MODULE_VERSION` hunk is for this out-of-tree build only).

## What it adds

All files live on the WMAX WMI device, which is also the `device` of the driver's hwmon and platform profile:

```
/sys/bus/wmi/devices/A70591CE-A997-11DA-B012-B622A1EF5492-<n>/
/sys/class/hwmon/hwmonN/device/                     (name = alienware_wmi)
/sys/class/platform-profile/platform-profile-N/device/  (name = alienware-wmi)
```

| File | Mode | WMAX call | Shown when |
|---|---|---|---|
| `gmode` | 0664 | read: Thermal_Information (0x14) op 0x0B; write: Thermal_Control (0x15) op 1 | 0xAB is in the thermal profile list (0x14 op 3) and G-Mode isn't already handled through GameShiftStatus |
| `default_profile` | 0444 | 0x14 op 0x0A | the call works at probe |
| `cooling_type` | 0444 | 0x14 op 1 | the call works at probe |
| `power_info/adapter_count` | 0444 | PowerInformation (0x1C) op 1 | 0x1C op 1 works at probe |
| `power_info/adapter_watts` | 0444 | 0x1C op 2, arg 0 and 1 | (same) |
| `power_info/adapter_status` | 0444 | 0x1C op 4 | (same) |

- **`gmode`**: `1` activates thermal profile 0xAB (G-Mode) and remembers the profile that was active; `0` restores
  that profile, or the BIOS default profile (0x14 op 0x0A) if none was remembered. Reads `1` while the current
  profile (0x14 op 0x0B) is 0xAB. Writing the value it already has does nothing. Platform profile listeners
  (`platform_profile` sysfs pollers, `/sys/firmware/acpi/platform_profile`) are notified on every change. While
  G-Mode is on, `platform_profile` reads `performance` (upstream maps 0xAB there); selecting any platform profile
  replaces G-Mode and `gmode` then reads `0` (pollers of `gmode` are notified). Never calls GameShiftStatus (0x25).
- **`default_profile`**: the platform profile name of the BIOS default (`balanced` on the x17 R2: 0xA0), or the raw
  id as hex if it has no name.
- **`cooling_type`**: `air`, `liquid`, or the raw number.
- **`power_info/adapter_count`**: AC adapters plugged in (0-2).
- **`power_info/adapter_watts`**: rated watts of each plugged-in adapter, space separated (slots 0..count-1; an
  empty line on battery).
- **`power_info/adapter_status`**: `ok`, `undersized` (below the wattage this model needs), `unsupported`
  (non-Dell adapter), or the raw number. On battery the BIOS reports `ok`.

### force_gmode fix

With the `gmode` quirk (G-series models) or `force_gmode=1`, upstream calls GameShiftStatus (0x25) before every
platform profile change and fails the change if the call fails. This driver calls 0x25 once at probe: if the BIOS
rejects it, it logs one warning (`GameShiftStatus is not supported …`) and carries on as if the quirk were off:
`performance` stays the listed performance profile, profile changes work, and the `gmode` file appears instead
(when 0xAB is listed). Models where 0x25 works behave exactly as upstream.

## Alienware x17 R2 (what this was written for)

From the BIOS's ACPI tables and WMI MOF (static reading, nothing was called):

- WMAX has no GameShiftStatus (0x25): it returns 0xFFFFFFFF. **Never load the stock (unpatched) driver with
  `force_gmode=1` on this model**: every platform profile change then fails with -EBADRQC.
- The thermal profile list (0x14 op 3) is A3 A0 A1 A4 A5 **AB**: quiet, balanced, balanced-performance,
  performance, low-power, and G-Mode. Upstream skips AB, so `performance` is 0xA4 and G-Mode is unreachable; with
  this driver it is the `gmode` file. In ACPI and NVPCF, AB and A4 look identical (GPU 150 W + 25 W boost); whether
  the EC treats them differently (fan speed, CPU PL1/PL2) still has to be measured.
- Default profile 0xA0 (balanced), cooling type 1 (air).
- PowerInformation: op 1 counts adapters from two EC flags, op 2 reads the EC's watts for adapter 0/1, op 4 returns
  1 ok, 2 when the adapter is below 330 W (this GPU/panel combination; 240 W otherwise), 9 for a non-Dell adapter.

## Build

Needs the headers for the target kernel (`linux-omarchy-headers` here).

```sh
make                 # against the running kernel: /usr/lib/modules/$(uname -r)/build
make W=1             # with extra warnings (builds clean)
make KVER=<release>  # another installed kernel
make clean
```

Or directly: `make -C /usr/lib/modules/$(uname -r)/build M=$PWD/alienware-wmi modules`.

## Try it without installing

```sh
sudo modprobe -r alienware_wmi
sudo insmod alienware-wmi/alienware-wmi.ko      # wmi is already loaded on these machines
cat /sys/module/alienware_wmi/version                # mothership-1
d=$(readlink -f /sys/class/platform-profile/*/device | head -1)   # the WMAX device
cat $d/gmode $d/default_profile $d/cooling_type $d/power_info/*
echo 1 | sudo tee $d/gmode; cat /sys/firmware/acpi/platform_profile; echo 0 | sudo tee $d/gmode
journalctl -k -b | grep -i alienware
```

Back to the stock driver: `sudo rmmod alienware_wmi && sudo modprobe alienware_wmi`.

The module is unsigned unless DKMS signs it with a machine owner key; a kernel that enforces signatures
(Secure Boot lockdown, `module.sig_enforce=1`) refuses it. This kernel doesn't enforce them (it only taints).

## Install with DKMS

```sh
sudo cp -r . /usr/src/alienware-wmi-mothership-1        # from this kernel/ directory
sudo dkms install alienware-wmi-mothership/1             # builds, installs to updates/dkms, runs depmod
sudo modprobe -r alienware_wmi && sudo modprobe alienware_wmi
modinfo -F version alienware-wmi                          # mothership-1
```

`AUTOINSTALL=yes`: DKMS rebuilds it for every new kernel (the headers package must be installed).

## Remove

```sh
sudo dkms remove alienware-wmi-mothership/1 --all
sudo rm -rf /usr/src/alienware-wmi-mothership-1
sudo depmod -a
sudo modprobe -r alienware_wmi && sudo modprobe alienware_wmi   # back to the in-tree module
```

## Permissions

sysfs files belong to root; `gmode` is created 0664, so a udev rule can give it to mothership's group. The
attribute exists by the time the WMI device's `bind` uevent fires, e.g.:

```
ACTION=="bind", SUBSYSTEM=="wmi", DRIVER=="alienware-wmi-wmax", RUN+="/bin/sh -c 'f=/sys%p/gmode; [ -e $$f ] && chgrp mothership $$f'"
```

## License

GPL-2.0-only for this directory; see [LICENSE](LICENSE). The driver files keep their upstream SPDX tags
(GPL-2.0-or-later).
