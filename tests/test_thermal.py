import errno
import os
import subprocess
import unittest

from mothership import thermal
from mothership.thermal import Auto, Thermal, curve_boost
from tests.fakes import FakeSysfs


class ThermalTest(unittest.TestCase):
    def setUp(self):
        self.fs = FakeSysfs()
        self.addCleanup(self.fs.cleanup)
        self.t = Thermal(self.fs.root)

    def test_available_and_modes(self):
        self.assertTrue(self.t.available())
        self.assertEqual(self.t.modes(),
                         ["low-power", "quiet", "balanced", "balanced-performance", "performance", "custom"])
        self.assertEqual(self.t.mode(), "balanced")

    def test_set_mode(self):
        self.t.set_mode("performance")
        self.assertEqual(self.fs.get("sys/class/platform-profile/platform-profile-0/profile"), "performance")
        self.assertEqual(self.t.mode(), "performance")

    def test_invalid_mode(self):
        with self.assertRaises(ValueError):
            self.t.set_mode("turbo")
        self.assertEqual(self.t.mode(), "balanced")

    def test_set_mode_permission_message(self):
        p = os.path.join(self.fs.root, "sys/class/platform-profile/platform-profile-0/profile")
        os.chmod(p, 0o444)
        if os.access(p, os.W_OK):  # running as root
            self.skipTest("root ignores file modes")
        with self.assertRaises(PermissionError) as cm:
            self.t.set_mode("quiet")
        self.assertIn("udev rule", str(cm.exception))

    def test_fans(self):
        fans = self.t.fans()
        self.assertEqual(len(fans), 4)
        self.assertEqual(fans[0], {"id": 1, "label": "Fan 1", "rpm": 1000, "boost": 0, "boost_pct": 0, "max": 5000})
        self.assertEqual(fans[3]["rpm"], 4000)

    def test_boost_all_fans(self):
        self.t.set_boost(50)
        for i in range(1, 5):
            self.assertEqual(self.fs.get(f"sys/class/hwmon/hwmon5/fan{i}_boost"), "128")
        self.assertEqual([f["boost_pct"] for f in self.t.fans()], [50] * 4)
        self.t.set_boost(100)
        self.assertEqual(self.fs.get("sys/class/hwmon/hwmon5/fan2_boost"), "255")
        self.t.set_boost("off")
        self.assertEqual(self.fs.get("sys/class/hwmon/hwmon5/fan2_boost"), "0")
        self.t.set_boost(40)
        self.t.set_boost(None)
        self.assertEqual(self.fs.get("sys/class/hwmon/hwmon5/fan3_boost"), "0")

    def test_boost_one_fan(self):
        self.t.set_boost(50, fan=2)
        self.assertEqual(self.fs.get("sys/class/hwmon/hwmon5/fan2_boost"), "128")
        for i in (1, 3, 4):
            self.assertEqual(self.fs.get(f"sys/class/hwmon/hwmon5/fan{i}_boost"), "0")
        with self.assertRaises(ValueError):
            self.t.set_boost(50, fan=9)

    def test_boost_scale(self):
        self.t.set_boost(50, scale=100)
        self.assertEqual(self.fs.get("sys/class/hwmon/hwmon5/fan1_boost"), "50")
        self.assertEqual(Thermal(self.fs.root, boost_scale=100).fans()[0]["boost_pct"], 50)

    def test_boost_out_of_range(self):
        for bad in (-1, 101, 255, "max"):
            with self.assertRaises(ValueError):
                self.t.set_boost(bad)
        self.assertEqual(self.fs.get("sys/class/hwmon/hwmon5/fan1_boost"), "0")

    def test_temps(self):
        self.assertEqual(self.t.temps(), {"cpu": 55.0, "gpu": 48.0, "package": 61.0})

    def test_on_ac(self):
        self.assertIs(self.t.on_ac(), True)
        FakeSysfs.put(os.path.join(self.fs.root, "sys/class/power_supply/AC"), "online", "0")
        self.assertIs(self.t.on_ac(), False)

    def test_gmode_not_available(self):
        self.assertFalse(self.t.gmode_available())
        d = self.fs.mk("sys/devices/platform/alienware-wmi")
        FakeSysfs.put(d, "gmode", "0")
        self.assertTrue(self.t.gmode_available())

    def test_status(self):
        s = self.t.status()
        self.assertTrue(s["available"])
        self.assertEqual(s["mode"], "balanced")
        self.assertEqual(len(s["modes"]), 6)
        self.assertEqual(len(s["fans"]), 4)
        self.assertEqual(s["temps"]["package"], 61.0)
        self.assertIs(s["ac"], True)
        self.assertIsNone(s["dgpu"])
        self.assertFalse(s["gmode_available"])


class ExtendedDriverTest(unittest.TestCase):
    """The files mothership's alienware-wmi (kernel/) adds on the WMAX WMI device."""

    def setUp(self):
        self.fs = FakeSysfs()
        self.addCleanup(self.fs.cleanup)
        self.t = Thermal(self.fs.root)

    def test_stock_driver(self):
        self.assertFalse(self.t.gmode_available())
        self.assertIsNone(self.t.gmode())
        self.assertIsNone(self.t.power_info())
        with self.assertRaises(OSError) as cm:
            self.t.set_gmode(True)
        self.assertEqual(cm.exception.errno, errno.ENODEV)

    def test_gmode_through_hwmon_device(self):
        self.fs.add_wmax(gmode="0")
        self.assertTrue(self.t.gmode_available())
        self.assertIs(self.t.gmode(), False)
        self.t.set_gmode(True)
        self.assertEqual(self.fs.get(FakeSysfs.WMAX + "/gmode"), "1")
        self.assertIs(self.t.gmode(), True)
        self.t.set_gmode(False)
        self.assertEqual(self.fs.get(FakeSysfs.WMAX + "/gmode"), "0")
        self.assertTrue(self.t.status()["gmode_available"])

    def test_gmode_through_platform_profile_device(self):
        fs = FakeSysfs(hwmon=False)
        self.addCleanup(fs.cleanup)
        fs.add_wmax(gmode="1")
        t = Thermal(fs.root)
        self.assertTrue(t.gmode_available())
        self.assertIs(t.gmode(), True)
        t.set_gmode(False)
        self.assertEqual(fs.get(FakeSysfs.WMAX + "/gmode"), "0")

    def test_gmode_hidden_by_driver(self):
        # The extended driver hides gmode where AB isn't listed or GameShiftStatus handles it.
        self.fs.add_wmax(gmode=None, power=(1, "330", "ok"))
        self.assertFalse(self.t.gmode_available())
        self.assertIsNone(self.t.gmode())
        with self.assertRaises(OSError):
            self.t.set_gmode(True)
        self.assertIsNotNone(self.t.power_info())

    def test_gmode_write_error(self):
        self.fs.add_wmax(gmode="0")
        p = os.path.join(self.fs.root, FakeSysfs.WMAX, "gmode")
        os.chmod(p, 0o444)
        if os.access(p, os.W_OK):
            self.skipTest("root ignores file modes")
        with self.assertRaises(PermissionError) as cm:
            self.t.set_gmode(True)
        self.assertIn("G-Mode", str(cm.exception))

    def test_power_info(self):
        self.fs.add_wmax(power=(1, "330", "ok"))
        self.assertEqual(self.t.power_info(), {"adapters": 1, "watts": [330], "status": "ok"})

    def test_power_info_two_adapters_undersized(self):
        self.fs.add_wmax(power=(2, "240 130", "undersized"))
        self.assertEqual(self.t.power_info(), {"adapters": 2, "watts": [240, 130], "status": "undersized"})

    def test_power_info_on_battery_and_raw_status(self):
        self.fs.add_wmax(power=(0, "", "7"))
        self.assertEqual(self.t.power_info(), {"adapters": 0, "watts": [], "status": "7"})

    def test_power_info_unreadable(self):
        self.fs.add_wmax(power=(1, "330", "ok"))
        os.remove(os.path.join(self.fs.root, FakeSysfs.WMAX, "power_info", "adapter_count"))
        self.assertEqual(self.t.power_info(), {"adapters": None, "watts": [330], "status": "ok"})


class DgpuTest(unittest.TestCase):
    def setUp(self):
        self.fs = FakeSysfs()
        self.addCleanup(self.fs.cleanup)
        d = self.fs.mk("sys/bus/pci/devices/0000:01:00.0")
        FakeSysfs.put(d, "vendor", "0x10de")
        FakeSysfs.put(d, "class", "0x030000")
        self.pm = self.fs.mk("sys/bus/pci/devices/0000:01:00.0/power")
        self.t = Thermal(self.fs.root)
        self.calls = []

        def run(cmd, **kw):
            self.calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="71, 85, 120.5\n", stderr="")

        self.t._run = run

    def test_suspended_never_queried(self):
        FakeSysfs.put(self.pm, "runtime_status", "suspended")
        self.assertEqual(self.t.dgpu(), {"state": "suspended", "temp": None, "util": None, "watts": None})
        self.assertEqual(self.calls, [])

    def test_active_queried(self):
        FakeSysfs.put(self.pm, "runtime_status", "active")
        self.assertEqual(self.t.dgpu(), {"state": "active", "temp": 71.0, "util": 85.0, "watts": 120.5})
        self.assertEqual(self.calls[0][0], "nvidia-smi")

    def test_no_nvidia(self):
        fs = FakeSysfs()
        self.addCleanup(fs.cleanup)
        self.assertIsNone(Thermal(fs.root).dgpu())


class MissingHardwareTest(unittest.TestCase):
    def test_no_hwmon(self):
        fs = FakeSysfs(hwmon=False)
        self.addCleanup(fs.cleanup)
        t = Thermal(fs.root)
        self.assertTrue(t.available())
        self.assertEqual(t.fans(), [])
        self.assertEqual(t.temps(), {"package": 61.0})
        with self.assertRaises(OSError):
            t.set_boost(50)
        s = t.status()
        self.assertTrue(s["available"])
        self.assertEqual(s["fans"], [])
        self.assertEqual(s["mode"], "balanced")
        t.set_mode("quiet")
        self.assertEqual(t.mode(), "quiet")

    def test_nothing(self):
        fs = FakeSysfs(profile=False, hwmon=False)
        self.addCleanup(fs.cleanup)
        t = Thermal(fs.root)
        self.assertFalse(t.available())
        self.assertEqual(t.modes(), [])
        self.assertIsNone(t.mode())
        with self.assertRaises(OSError):
            t.set_mode("quiet")
        s = t.status()
        self.assertFalse(s["available"])
        self.assertEqual(s["fans"], [])

    def test_empty_root(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            t = Thermal(d)
            self.assertFalse(t.available())
            self.assertIsNone(t.on_ac())
            self.assertIsNone(t.dgpu())
            self.assertEqual(t.status()["temps"], {})


def snap(pkg=60, ac=True, gpu_t=None, gpu_u=None):
    return {"temps": {"package": pkg, "cpu": pkg}, "ac": ac,
            "dgpu": {"state": "active" if gpu_t else "suspended", "temp": gpu_t, "util": gpu_u, "watts": None}}


class AutoTest(unittest.TestCase):
    def test_defaults_merged(self):
        a = Auto({"hot_cpu": 90})
        self.assertEqual(a.config["hot_cpu"], 90)
        self.assertEqual(a.config["cool_seconds"], thermal.DEFAULTS["cool_seconds"])
        self.assertEqual(thermal.DEFAULTS["boost_scale"], 255)

    def test_ac_and_battery(self):
        a = Auto({})
        self.assertEqual(a.decide(snap(ac=True), 0)["mode"], "balanced")
        self.assertEqual(a.decide(snap(ac=False), 1)["mode"], "quiet")
        self.assertEqual(a.decide(snap(ac=None), 2)["mode"], "balanced")

    def test_hot_after_hot_seconds_then_cool_hysteresis(self):
        a = Auto({})
        self.assertEqual(a.decide(snap(96), 0)["mode"], "balanced")
        self.assertEqual(a.decide(snap(96), 7)["mode"], "balanced")
        self.assertEqual(a.decide(snap(96), 8)["mode"], "performance")
        # Between cool and hot: stays hot.
        self.assertEqual(a.decide(snap(85), 100)["mode"], "performance")
        # Cool, but not for cool_seconds yet.
        self.assertEqual(a.decide(snap(75), 110)["mode"], "performance")
        self.assertEqual(a.decide(snap(75), 154)["mode"], "performance")
        self.assertEqual(a.decide(snap(75, ac=False), 155)["mode"], "quiet")

    def test_hot_interrupted_resets(self):
        a = Auto({})
        a.decide(snap(96), 0)
        a.decide(snap(90), 5)
        self.assertEqual(a.decide(snap(96), 10)["mode"], "balanced")
        self.assertEqual(a.decide(snap(96), 18)["mode"], "performance")

    def test_gpu_triggers_hot(self):
        a = Auto({})
        a.decide(snap(60, gpu_t=50, gpu_u=70), 0)
        self.assertEqual(a.decide(snap(60, gpu_t=50, gpu_u=70), 8)["mode"], "performance")
        b = Auto({})
        b.decide(snap(60, gpu_t=82, gpu_u=10), 0)
        self.assertEqual(b.decide(snap(60, gpu_t=82, gpu_u=10), 8)["mode"], "performance")

    def test_cpu_fallback_when_no_package(self):
        a = Auto({"hot_seconds": 0})
        self.assertEqual(a.decide({"temps": {"cpu": 99}, "ac": True, "dgpu": None}, 0)["mode"], "performance")

    def test_boost_ramp(self):
        a = Auto({})
        self.assertEqual(a.decide(snap(78), 0)["boost_pct"], 0)
        # Halfway (86 °C): target 95 raw; up at most 60 per step.
        self.assertEqual(a.boost, 0)
        a.decide(snap(86), 1)
        self.assertEqual(a.boost, 60)
        a.decide(snap(86), 2)
        self.assertEqual(a.boost, 95)
        # Full (94 °C and above): boost_max 190 raw = 75 %.
        a.decide(snap(94), 3)
        a.decide(snap(99), 4)
        self.assertEqual(a.boost, 190)
        self.assertEqual(a.decide(snap(99), 5)["boost_pct"], 75)
        # Down slowly: 8 raw per step.
        a.decide(snap(60), 6)
        self.assertEqual(a.boost, 182)
        for i in range(30):
            out = a.decide(snap(60), 7 + i)
        self.assertEqual(out["boost_pct"], 0)

    def test_boost_pct_capped(self):
        a = Auto({"boost_max": 255, "boost_scale": 100})
        for i in range(10):
            out = a.decide(snap(99), i)
        self.assertEqual(out["boost_pct"], 100)


class CurveTest(unittest.TestCase):
    def test_curve(self):
        self.assertEqual(curve_boost(50, 0, 1, -40), 10)
        self.assertEqual(curve_boost(80, 0.01, 0, 0), 64)
        self.assertEqual(curve_boost(30, 0, 1, -40), 0)
        self.assertEqual(curve_boost(100, 0.05, 0, 0), 100)
        self.assertIsInstance(curve_boost(70.4, 0, 1, 0), int)


if __name__ == "__main__":
    unittest.main()


class TccLockTest(unittest.TestCase):
    def test_eperm_means_locked(self):
        import errno, os
        from unittest import mock
        from tests.fakes import FakeSysfs
        fs = FakeSysfs()
        try:
            d = fs.mk("sys/bus/pci/devices/0000:00:04.0")
            fs.put(d, "tcc_offset_degree_celsius", "0")
            t = thermal.Thermal(root=fs.root)
            real_open = open

            def fake_open(path, mode="r", *a, **k):
                if str(path).endswith("tcc_offset_degree_celsius") and "w" in mode:
                    raise PermissionError(errno.EPERM, "Operation not permitted")
                return real_open(path, mode, *a, **k)

            with mock.patch("builtins.open", fake_open):
                with self.assertRaises(thermal.TccLocked):
                    t.set_tcc_offset(3)
        finally:
            fs.cleanup()
