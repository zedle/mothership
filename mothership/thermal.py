"""Thermal control for Alienware laptops through the kernel's alienware-wmi driver.

Port of the dotfiles' gage-fans. Everything goes through sysfs (all paths joined under `root`, so tests run
on a fake tree): the platform profile (`/sys/class/platform-profile/*` named `alienware-wmi`) picks the
firmware's thermal mode, and the `alienware_wmi` hwmon's `fanN_boost` adds fan speed on top of the EC's own
curve. The firmware keeps its own thermal protection; nothing here can turn it off.

G-Mode: the x17 R2 BIOS lists thermal mode 0xAB (G-Mode), but Linux's driver skips it and maps
"performance" to 0xA4, which is what this module treats as the hot profile. The stock driver's G-Mode
override (force_gmode) breaks every profile switch on that BIOS, so it is never used here. mothership's
extended driver (kernel/, DKMS) adds a `gmode` file on the WMAX WMI device (the hwmon's and the platform
profile's `device`): 1 activates 0xAB, 0 restores the previous profile. It also adds read-only
`power_info/adapter_{count,watts,status}` there. Without that driver `gmode_available()` is False,
`set_gmode()` raises ENODEV and `power_info()` returns None.

Fan boost is a percentage at this API (0-100) and is mapped onto the driver's raw range with one scale
(`DEFAULTS["boost_scale"]`, 255 until a hardware measurement says the EC tops out at 100).

The dGPU is only queried while it is already awake: `power/runtime_status` is read first and `nvidia-smi`
runs only when it says `active` (nvidia-smi would wake a suspended RTX).
"""
import errno
import glob
import os
import subprocess

DEFAULTS = {
    # Profile while nothing is hot. The EC runs its own fan curve inside it.
    "ac": "balanced",
    "battery": "quiet",
    # Linux's "performance" (thermal mode 0xA4): fans high, power limits up.
    "hot_profile": "performance",
    "hot_cpu": 95,        # package °C that calls for it (for hot_seconds)
    "hot_gpu": 80,        # dGPU °C
    "hot_gpu_util": 60,   # dGPU % busy (games, renders)
    "hot_seconds": 8,
    "cool_cpu": 80,       # back to normal below these for cool_seconds
    "cool_gpu": 66,
    "cool_seconds": 45,
    # Extra fan on top of the profile, ramped with the package temperature. boost_max is in driver units
    # (0..boost_scale).
    "boost_from_cpu": 78,
    "boost_to_cpu": 94,
    "boost_max": 190,
    "interval": 3,
    # Raw driver value that 100 % maps to.
    "boost_scale": 255,
}

# Auto ramp steps per decision, in driver units: up fast, down slowly, so the fans don't hunt.
BOOST_UP = 60
BOOST_DOWN = 8

TCC_MAX = 15                 # the x17 R2 BIOS allows 0-15 °C
POWER_MIN_W, POWER_MAX_W = 15, 250
PROFILE_NAME = "alienware-wmi"
HWMON_NAME = "alienware_wmi"
NVIDIA = "0x10de"


def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _int(path, default=0):
    v = _read(path)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _write(path, value, what):
    try:
        with open(path, "w") as f:
            f.write(str(value))
    except PermissionError as e:
        raise PermissionError(
            e.errno, f"cannot set {what}: permission denied on {path} (is mothership's udev rule installed "
                     f"and are you in its group?)", path) from e
    except OSError as e:
        raise OSError(e.errno, f"cannot set {what}: {path}: {e.strerror}", path) from e


def _pct_to_raw(pct, scale):
    return int(pct * scale / 100 + 0.5)


def _raw_to_pct(raw, scale):
    if scale <= 0:
        return 0
    return max(0, min(100, int(raw * 100 / scale + 0.5)))


class TccLocked(PermissionError):
    """The BIOS locked the TCC offset; it can't be changed from the OS."""


class Thermal:
    def __init__(self, root="/", boost_scale=None):
        self.root = root
        self.boost_scale = int(boost_scale or DEFAULTS["boost_scale"])
        self._run = subprocess.run  # replaced in tests

    # ---- discovery ----

    def _p(self, rel):
        return os.path.join(self.root, rel.lstrip("/"))

    def _profile_dir(self):
        for d in sorted(glob.glob(self._p("sys/class/platform-profile/*"))):
            if _read(d + "/name") == PROFILE_NAME:
                return d
        return None

    def _hwmon(self, name=HWMON_NAME):
        return [d for d in sorted(glob.glob(self._p("sys/class/hwmon/hwmon*"))) if _read(d + "/name") == name]

    def _fan_hwmon(self):
        h = self._hwmon()
        return h[0] if h else None

    def available(self):
        return self._profile_dir() is not None or self._fan_hwmon() is not None

    def _wmax_dirs(self):
        """Candidate directories of the WMAX WMI device (the extended driver's files live there)."""
        dirs = []
        for d in (self._fan_hwmon(), self._profile_dir()):
            if d:
                dirs.append(os.path.join(d, "device"))
        dirs.append(self._p("sys/devices/platform/alienware-wmi"))
        return dirs

    def _gmode_file(self):
        for d in self._wmax_dirs():
            f = os.path.join(d, "gmode")
            if os.path.isfile(f):
                return f
        return None

    def gmode_available(self):
        """True only if the (extended) driver exposes a dedicated `gmode` file."""
        return self._gmode_file() is not None

    def gmode(self):
        """True/False from the driver's `gmode` file, None without one (or if it can't be read)."""
        f = self._gmode_file()
        v = _read(f) if f else None
        return None if v not in ("0", "1") else v == "1"

    def set_gmode(self, on):
        """G-Mode on (thermal mode 0xAB) or off (the driver restores the previous mode)."""
        f = self._gmode_file()
        if f is None:
            raise OSError(errno.ENODEV, "no G-Mode control (needs mothership's alienware-wmi driver)")
        _write(f, "1" if on else "0", "G-Mode")

    def power_info(self):
        """AC adapters from the extended driver's power_info group, or None without it.

        {"adapters": count, "watts": [W per present adapter], "status": "ok" | "undersized" |
        "unsupported" | raw number as a string}. Unreadable values are None (or [] for watts).
        """
        for d in self._wmax_dirs():
            p = os.path.join(d, "power_info")
            if not os.path.isdir(p):
                continue
            count = _read(p + "/adapter_count")
            watts = (_read(p + "/adapter_watts") or "").split()
            return {
                "adapters": int(count) if count and count.isdigit() else None,
                "watts": [int(w) for w in watts if w.isdigit()],
                "status": _read(p + "/adapter_status"),
            }
        return None

    # ---- profile ----

    def modes(self):
        d = self._profile_dir()
        return (_read(d + "/choices") or "").split() if d else []

    def mode(self):
        d = self._profile_dir()
        return _read(d + "/profile") if d else None

    def set_mode(self, name):
        d = self._profile_dir()
        if d is None:
            raise OSError(errno.ENODEV, "no alienware-wmi platform profile (driver not loaded?)")
        choices = self.modes()
        if name not in choices:
            raise ValueError(f"unknown thermal mode {name!r}; choose from: {' '.join(choices)}")
        if _read(d + "/profile") != name:
            _write(d + "/profile", name, f"thermal mode {name}")

    # ---- fans ----

    def _fan_ids(self, h):
        ids = []
        i = 1
        while os.path.exists(f"{h}/fan{i}_input") or os.path.exists(f"{h}/fan{i}_boost"):
            ids.append(i)
            i += 1
        return ids

    def fans(self):
        h = self._fan_hwmon()
        if h is None:
            return []
        out = []
        for i in self._fan_ids(h):
            boost = _int(f"{h}/fan{i}_boost")
            out.append({
                "id": i,
                "label": _read(f"{h}/fan{i}_label", f"Fan {i}"),
                "rpm": _int(f"{h}/fan{i}_input"),
                "boost": boost,
                "boost_pct": _raw_to_pct(boost, self.boost_scale),
                "max": _int(f"{h}/fan{i}_max"),
            })
        return out

    def set_boost(self, pct, fan=None, scale=None):
        """Fan boost in percent (None or "off" = 0) for every fan, or one fan id."""
        scale = int(scale or self.boost_scale)
        if pct is None or pct == "off":
            pct = 0
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            raise ValueError(f"boost must be 0-100 or off, not {pct!r}") from None
        if not 0 <= pct <= 100:
            raise ValueError(f"boost must be 0-100 %, not {pct:g}")
        h = self._fan_hwmon()
        if h is None:
            raise OSError(errno.ENODEV, "no alienware_wmi fans (driver not loaded?)")
        ids = self._fan_ids(h)
        if fan not in (None, "all"):
            try:
                fan = int(fan)
            except (TypeError, ValueError):
                raise ValueError(f"unknown fan {fan!r}") from None
            if fan not in ids:
                raise ValueError(f"unknown fan {fan}; fans: {' '.join(map(str, ids))}")
            ids = [fan]
        raw = max(0, min(scale, _pct_to_raw(pct, scale)))
        for i in ids:
            p = f"{h}/fan{i}_boost"
            if os.path.exists(p) and _int(p, -1) != raw:
                _write(p, raw, f"fan {i} boost")

    # ---- sensors ----

    def temps(self):
        out = {}
        for h in self._hwmon():
            for t in sorted(glob.glob(h + "/temp*_input")):
                label = (_read(t[: -len("_input")] + "_label") or "").lower()
                v = _read(t)
                if label in ("cpu", "gpu") and v and v.lstrip("-").isdigit():
                    out.setdefault(label, int(v) / 1000)
        pkg = None
        for h in self._hwmon("coretemp"):
            for t in glob.glob(h + "/temp*_input"):
                if _read(t[: -len("_input")] + "_label") != "Package id 0":
                    continue
                v = _read(t)
                if v and v.lstrip("-").isdigit():
                    v = int(v) / 1000
                    pkg = v if pkg is None else max(pkg, v)
        if pkg is not None:
            out["package"] = pkg
        return out

    def on_ac(self):
        for p in sorted(glob.glob(self._p("sys/class/power_supply/*"))):
            if _read(p + "/type") == "Mains":
                return _read(p + "/online") == "1"
        return None

    def _dgpu_dir(self):
        for d in sorted(glob.glob(self._p("sys/bus/pci/devices/*"))):
            if _read(d + "/vendor") == NVIDIA and (_read(d + "/class") or "").startswith("0x03"):
                return d
        return None

    def dgpu(self):
        """NVIDIA dGPU state without waking it: nvidia-smi only while it is already awake."""
        d = self._dgpu_dir()
        if d is None:
            return None
        g = {"state": _read(d + "/power/runtime_status", "unknown"), "temp": None, "util": None, "watts": None}
        if g["state"] == "active":
            try:
                out = self._run(
                    ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,power.draw",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=4).stdout.strip().split(",")
                g["temp"], g["util"], g["watts"] = (float(x) for x in out[:3])
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        return g

    # -- CPU temperature limit (Intel TCC offset, int340x processor thermal device)
    def _tcc_file(self):
        found = sorted(glob.glob(self._p("sys/bus/pci/devices/*/tcc_offset_degree_celsius")))
        return found[0] if found else None

    def tcc_offset(self):
        f = self._tcc_file()
        return _int(f, None) if f else None

    def set_tcc_offset(self, degrees):
        f = self._tcc_file()
        if not f:
            raise OSError(errno.ENODEV, "no CPU temperature limit control (int340x processor thermal driver)")
        if not isinstance(degrees, int) or not 0 <= degrees <= TCC_MAX:
            raise ValueError(f"temperature limit offset must be 0-{TCC_MAX} °C")
        try:
            with open(f, "w") as fh:
                fh.write(str(degrees))
        except PermissionError as e:
            if e.errno == errno.EPERM:          # the kernel refuses when the BIOS set the TCC lock bit
                raise TccLocked(errno.EPERM, "the CPU temperature limit is locked by the BIOS on this machine") from e
            raise PermissionError(e.errno, f"cannot set the CPU temperature limit: permission denied on {f} "
                                           "(is mothership's udev rule installed and are you in its group?)") from e

    # -- CPU package power limits (intel-rapl)
    def _rapl(self):
        for d in sorted(glob.glob(self._p("sys/class/powercap/intel-rapl:*"))):
            if _read(os.path.join(d, "name")) == "package-0":
                return d
        return None

    def power_limits(self):
        d = self._rapl()
        if not d:
            return None
        out = {}
        for i in (0, 1):
            name = _read(os.path.join(d, f"constraint_{i}_name"))
            uw = _int(os.path.join(d, f"constraint_{i}_power_limit_uw"), None)
            if name and uw is not None:
                out[name] = round(uw / 1e6)
        return out

    def set_power_limit(self, watts):
        """Long- and short-term package power limit in watts (both set to the same value)."""
        d = self._rapl()
        if not d:
            raise OSError(errno.ENODEV, "no CPU power limit control (intel-rapl)")
        if not isinstance(watts, int) or not POWER_MIN_W <= watts <= POWER_MAX_W:
            raise ValueError(f"power limit must be {POWER_MIN_W}-{POWER_MAX_W} W")
        for i in (0, 1):
            f = os.path.join(d, f"constraint_{i}_power_limit_uw")
            if os.path.exists(f):
                _write(f, watts * 1_000_000, "the CPU power limit")

    def adapter_status(self):
        info = self.power_info()
        return info.get("status") if info else None

    def status(self):
        avail = self.available()
        return {
            "available": avail,
            "mode": self.mode(),
            "modes": self.modes(),
            "gmode_available": self.gmode_available() if avail else False,
            "gmode": (self.gmode() if self.gmode_available() else None) if avail else None,
            "fans": self.fans(),
            "temps": self.temps(),
            "ac": self.on_ac(),
            "dgpu": self.dgpu(),
            "tcc_offset": self.tcc_offset(),
            "power_limits": self.power_limits(),
            "power_info": self.power_info(),
        }


class Auto:
    """gage-fans' auto rules: AC/battery profile, hot -> hot_profile with hysteresis, boost ramp by package °C."""

    def __init__(self, config=None):
        self.config = dict(DEFAULTS)
        self.config.update(config or {})
        self.hot = False
        self.hot_since = None
        self.cool_since = None
        self.boost = 0  # raw driver units

    def decide(self, snap, now):
        c = self.config
        temps = snap.get("temps") or {}
        cpu = temps.get("package")
        if cpu is None:
            cpu = temps.get("cpu")
        cpu = cpu or 0
        g = snap.get("dgpu") or {}
        gpu_t = g.get("temp") or 0
        gpu_u = g.get("util") or 0
        is_hot = cpu >= c["hot_cpu"] or gpu_t >= c["hot_gpu"] or gpu_u >= c["hot_gpu_util"]
        is_cool = cpu <= c["cool_cpu"] and gpu_t <= c["cool_gpu"] and gpu_u < c["hot_gpu_util"] / 2
        if not is_hot:
            self.hot_since = None
        elif self.hot_since is None:
            self.hot_since = now
        if not is_cool:
            self.cool_since = None
        elif self.cool_since is None:
            self.cool_since = now
        if not self.hot and self.hot_since is not None and now - self.hot_since >= c["hot_seconds"]:
            self.hot = True
        elif self.hot and self.cool_since is not None and now - self.cool_since >= c["cool_seconds"]:
            self.hot = False

        if self.hot:
            mode = c["hot_profile"]
        else:
            mode = c["battery"] if snap.get("ac") is False else c["ac"]

        span = max(1, c["boost_to_cpu"] - c["boost_from_cpu"])
        target = int(c["boost_max"] * min(1, max(0, (cpu - c["boost_from_cpu"]) / span)))
        if target > self.boost:
            self.boost = min(target, self.boost + BOOST_UP)
        else:
            self.boost = max(target, self.boost - BOOST_DOWN)
        return {"mode": mode, "boost_pct": _raw_to_pct(self.boost, int(c["boost_scale"]))}


def curve_boost(temp, a, b, c):
    """AWCC-style fan curve: clamp(a*T^2 + b*T + c, 0, 100), rounded."""
    return int(max(0, min(100, round(a * temp * temp + b * temp + c))))
