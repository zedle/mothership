"""Test doubles: a fake hidraw device and a fake sysfs tree."""
import os
import tempfile


class FakeHid:
    """Records every packet; get_feature/get_input/read pop scripted replies."""

    def __init__(self, replies=None, fail=False):
        self.sent = []          # (kind, bytes)
        self.replies = list(replies or [])
        self.fail = fail
        self.path = "/dev/hidraw-fake"

    def _check(self):
        if self.fail:
            raise OSError(19, "No such device")

    def set_feature(self, buf):
        self._check()
        self.sent.append(("feature", bytes(buf)))

    def get_feature(self, buf):
        self._check()
        self.sent.append(("get", bytes(buf)))
        if self.replies:
            r = bytearray(self.replies.pop(0))
            r += bytes(max(0, len(buf) - len(r)))
            return bytes(r[: len(buf)])
        return bytes(buf)

    def get_input(self, buf):
        self._check()
        if self.replies:
            r = bytearray(self.replies.pop(0))
            r += bytes(max(0, len(buf) - len(r)))
            return bytes(r[: len(buf)])
        return bytes(len(buf))

    def write(self, buf):
        self._check()
        self.sent.append(("write", bytes(buf)))

    def read(self, n, timeout_ms=200):
        self._check()
        return self.replies.pop(0) if self.replies else None

    def close(self):
        pass

    def packets(self, kind=None):
        return [b for k, b in self.sent if kind is None or k == kind]


def hexb(s):
    """'cc 80 02' -> bytes."""
    return bytes(int(x, 16) for x in s.split())


class FakeSysfs:
    """A temp directory shaped like the parts of /sys mothership reads."""

    def __init__(self, fans=4, profile=True, hwmon=True, choices="low-power quiet balanced balanced-performance performance custom"):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        if profile:
            p = self.mk("sys/class/platform-profile/platform-profile-0")
            self.put(p, "name", "alienware-wmi")
            self.put(p, "choices", choices)
            self.put(p, "profile", "balanced")
        if hwmon:
            h = self.mk("sys/class/hwmon/hwmon5")
            self.put(h, "name", "alienware_wmi")
            for i in range(1, fans + 1):
                self.put(h, f"fan{i}_input", str(1000 * i))
                self.put(h, f"fan{i}_label", f"Fan {i}")
                self.put(h, f"fan{i}_boost", "0")
                self.put(h, f"fan{i}_min", "0")
                self.put(h, f"fan{i}_max", "5000")
            self.put(h, "temp1_input", "55000")
            self.put(h, "temp1_label", "CPU")
            self.put(h, "temp2_input", "48000")
            self.put(h, "temp2_label", "GPU")
        c = self.mk("sys/class/hwmon/hwmon2")
        self.put(c, "name", "coretemp")
        self.put(c, "temp1_input", "61000")
        self.put(c, "temp1_label", "Package id 0")
        ps = self.mk("sys/class/power_supply/AC")
        self.put(ps, "type", "Mains")
        self.put(ps, "online", "1")

    WMAX = "sys/devices/platform/PNP0C14:01/wmi_bus/wmi_bus-PNP0C14:01/A70591CE-A997-11DA-B012-B622A1EF5492"

    def add_wmax(self, gmode="0", power=None):
        """The WMAX WMI device with the extended driver's files, linked as the hwmon's and the platform
        profile's `device`. power: None (no power_info group) or (count, "watts", "status")."""
        w = self.mk(self.WMAX)
        if gmode is not None:
            self.put(w, "gmode", gmode)
        if power is not None:
            p = self.mk(self.WMAX + "/power_info")
            self.put(p, "adapter_count", str(power[0]))
            self.put(p, "adapter_watts", power[1])
            self.put(p, "adapter_status", power[2])
        for d in ("sys/class/hwmon/hwmon5", "sys/class/platform-profile/platform-profile-0"):
            d = os.path.join(self.root, d)
            if os.path.isdir(d) and not os.path.exists(d + "/device"):
                os.symlink(w, d + "/device")
        return w

    def mk(self, rel):
        p = os.path.join(self.root, rel)
        os.makedirs(p, exist_ok=True)
        return p

    @staticmethod
    def put(d, name, value):
        with open(os.path.join(d, name), "w") as f:
            f.write(value + "\n")

    def get(self, rel):
        with open(os.path.join(self.root, rel)) as f:
            return f.read().strip()

    def cleanup(self):
        self.tmp.cleanup()
