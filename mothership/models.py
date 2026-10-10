"""Which supported hardware this machine has (data/devices.json), and opening it."""
import json
import os
from dataclasses import dataclass, field

from . import elc as elc_mod
from . import hidraw
from . import keyboard as kb_mod

DATA = os.path.join(os.path.dirname(__file__), "data", "devices.json")


def load_devices(path=DATA):
    with open(path) as f:
        return json.load(f)


def chassis_map(platform, devices=None, user=True):
    """Zone map for an AW-ELC platform id ('0x0306'): a probed map in the user's config wins,
    then devices.json (following same_as links); None if unknown."""
    if user:
        from . import probe
        m = probe.load_user_map(platform)
        if m:
            return m
    maps = (devices or load_devices())["chassis_maps"]
    seen = set()
    while platform in maps and platform not in seen:
        seen.add(platform)
        m = maps[platform]
        if "same_as" not in m:
            return m
        platform = m["same_as"]
    return None


def generic_map(led_count):
    """Unknown platform: every LED is one 'lights' zone; the power LED is not guessed."""
    return {"zones": {"all": list(range(led_count))}, "groups": {"lights": ["all"]},
            "columns": [[z] for z in range(led_count)], "power_states": False}


def platform_flag(name, root="/"):
    """A flag file from the extended alienware-wmi driver (on its WMAX device), as bool; None if absent."""
    import glob as _glob
    for hw in _glob.glob(os.path.join(root, "sys/class/hwmon/*/name")):
        try:
            with open(hw) as f:
                if f.read().strip() != "alienware_wmi":
                    continue
            with open(os.path.join(os.path.dirname(hw), "device", name)) as f:
                return f.read().strip() == "1"
        except OSError:
            continue
    return None


def fit_map(cmap, flags):
    """Drop optional zones whose hardware isn't there. flags: {flag name: bool or None}."""
    drop = {z for z, flag in cmap.get("optional_zones", {}).items() if flags.get(flag) is not True}
    if not drop:
        return cmap
    m = dict(cmap)
    gone = {led for z in drop for led in cmap["zones"].get(z, [])}
    m["zones"] = {k: v for k, v in cmap["zones"].items() if k not in drop}
    m["groups"] = {g: [z for z in zs if z not in drop] for g, zs in cmap.get("groups", {}).items()}
    m["columns"] = [c for c in ([l for l in col if l not in gone] for col in cmap.get("columns", [])) if c]
    return m


def unlit_keys(pid, devices=None):
    for k in (devices or load_devices())["keyboards"]:
        u = k.get("unlit", {})
        if f"{pid:04x}" in u:
            return set(u[f"{pid:04x}"])
    return set()


def zone_leds(cmap, names):
    """Zone/group names (or 'all') -> sorted LED ids."""
    out = set()
    for n in names if isinstance(names, (list, tuple)) else [names]:
        if n == "all":
            for leds in cmap["zones"].values():
                out.update(leds)
            out.difference_update(cmap["zones"].get("power", []))
        elif n in cmap["zones"]:
            out.update(cmap["zones"][n])
        elif n in cmap.get("groups", {}):
            out.update(zone_leds(cmap, cmap["groups"][n]))
        else:
            raise ValueError(f"unknown zone {n!r}; one of {', '.join(['all', *cmap['zones'], *cmap.get('groups', {})])}")
    return sorted(out)


@dataclass
class Machine:
    keyboard_path: str | None = None
    keyboard_pid: int | None = None
    chassis_path: str | None = None
    chassis_pid: int | None = None
    devices: dict = field(default_factory=load_devices)

    def open_keyboard(self, keys=None):
        if not self.keyboard_path:
            return None
        return kb_mod.Keyboard(hidraw.Hid(self.keyboard_path, write_only=True), keys=keys)

    def open_chassis(self):
        if not self.chassis_path:
            return None
        return elc_mod.Elc(hidraw.Hid(self.chassis_path))

    def summary(self):
        return {"keyboard": self.keyboard_path, "chassis": self.chassis_path,
                "chassis_pid": f"{self.chassis_pid:04x}" if self.chassis_pid else None}


def detect(root="/sys/class/hidraw", devices=None):
    devices = devices or load_devices()
    m = Machine(devices=devices)
    for k in devices["keyboards"]:
        found = hidraw.find(int(k["vid"], 16), report_id=k["report_id"], root=root)
        if found:
            m.keyboard_path = found[0]
            m.keyboard_pid = hidraw.product_id(found[0], root=root)
            break
    for c in devices["chassis"]:
        found = hidraw.find(int(c["vid"], 16), {int(p, 16) for p in c["pids"]}, root=root)
        if found:
            m.chassis_path = found[0]
            m.chassis_pid = hidraw.product_id(found[0], root=root)
            break
    return m
