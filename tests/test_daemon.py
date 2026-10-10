import os
import tempfile
import unittest
from unittest import mock

from mothership import config as cfgmod
from mothership import daemon as dmod
from mothership import elc as elc_mod
from mothership import keyboard as kb_mod
from mothership import models, thermal
from tests.fakes import FakeHid, FakeSysfs, hexb


class FakeMachine(models.Machine):
    def __init__(self, kb_hid=None, ch_hid=None):
        super().__init__(keyboard_path="/dev/kb" if kb_hid else None, chassis_path="/dev/ch" if ch_hid else None,
                         chassis_pid=0x550 if ch_hid else None)
        self.kb_hid, self.ch_hid = kb_hid, ch_hid

    def open_keyboard(self, keys=None):
        return kb_mod.Keyboard(self.kb_hid, keys=keys) if self.kb_hid else None

    def open_chassis(self):
        return elc_mod.Elc(self.ch_hid) if self.ch_hid else None


def elc_info_replies():
    v = bytearray(34); v[4:7] = bytes([1, 1, 7])
    c = bytearray(34); c[4:7] = bytes([0x03, 0x06, 20])
    return [bytes(v), bytes(c)]


class DaemonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name + "/cfg",
                                                "XDG_STATE_HOME": self.tmp.name + "/state"})
        self.env.start()
        self.sys = FakeSysfs()
        self.kb = FakeHid()
        self.ch = FakeHid(replies=elc_info_replies())
        self.d = dmod.Daemon(machine=FakeMachine(self.kb, self.ch), cfg=cfgmod.load(),
                             thermal=thermal.Thermal(root=self.sys.root), run_dir=self.tmp.name + "/run",
                             keys={0: None, 1: None, 61: None})

    def tearDown(self):
        self.env.stop()
        self.sys.cleanup()
        self.tmp.cleanup()

    def run_file(self, name):
        with open(os.path.join(self.tmp.name, "run", name)) as f:
            return f.read()

    def test_apply_sends_keyboard_and_chassis(self):
        self.d.apply_lighting()
        self.assertTrue(self.kb.packets("feature"))
        self.assertTrue(any(p[1:3] == hexb("03 27") for p in self.ch.packets("write")))
        self.assertEqual(self.run_file("effect"), "none")

    def test_keyboard_effect_command_persists_config(self):
        self.d.apply_lighting()
        self.d.handle("keyboard.effect", {"name": "spectrum", "speed": 2})
        self.assertEqual(self.kb.packets("feature")[-2][1:3], hexb("80 0e"))
        self.assertEqual(cfgmod.load()["keyboard"]["effect"], "spectrum")

    def test_fire_hands_keyboard_to_fire_service(self):
        self.d.apply_lighting()
        n = len(self.kb.sent)
        self.d.handle("keyboard.effect", {"name": "fire"})
        self.assertEqual(self.run_file("effect"), "fire")
        self.assertEqual(len(self.kb.sent), n)          # daemon leaves the keyboard alone

    def test_bad_input_sends_nothing(self):
        self.d.apply_lighting()
        n = len(self.kb.sent)
        for cmd, args in [("keyboard.effect", {"name": "disco"}), ("keyboard.brightness", {"value": 140}),
                          ("chassis.color", {"zone": "trunk", "color": "ff0000"})]:
            with self.assertRaises(ValueError):
                self.d.handle(cmd, args)
        self.assertEqual(len(self.kb.sent), n)

    def test_power_set_requires_flag(self):
        self.d.apply_lighting()
        with self.assertRaises(PermissionError):
            self.d.handle("power.set", {"state": "dc-on", "color": "ff0000"})
        self.assertFalse(any(p[1:3] == hexb("03 22") for p in self.ch.packets("write")))
        self.d.handle("power.set", {"state": "dc-on", "color": "ff0000", "write_flash": True})
        self.assertTrue(any(p[1:5] == hexb("03 22 00 02") for p in self.ch.packets("write")))

    def test_never_persists_during_normal_apply(self):
        for eff in ("static", "breathing", "spectrum", "wave", "off"):
            self.d.cfg["chassis"]["effect"] = eff
            self.d.apply_lighting()
        for p in self.ch.packets("write"):
            self.assertFalse(p[1] == 0x03 and p[2] in (0x21, 0x22) and p[4] in elc_mod.PERSISTENT_SUBS, p.hex())
            self.assertNotEqual(p[2], 0xFF)

    def test_device_loss_is_survived(self):
        self.d.apply_lighting()
        self.kb.fail = True
        self.d.apply_keyboard()
        self.assertIn("keyboard", self.d.errors)
        self.assertIsNone(self.d.kb)
        self.kb.fail = False
        self.d.apply_lighting()                          # reopened
        self.assertIsNotNone(self.d.kb)

    def test_thermal_commands(self):
        self.d.handle("thermal.mode", {"name": "quiet"})
        self.assertEqual(self.sys.get("sys/class/platform-profile/platform-profile-0/profile"), "quiet")
        self.d.handle("thermal.gmode", {"on": True})
        self.assertEqual(self.sys.get("sys/class/platform-profile/platform-profile-0/profile"), "performance")
        self.d.handle("thermal.gmode", {"on": False})
        self.assertEqual(self.sys.get("sys/class/platform-profile/platform-profile-0/profile"), "quiet")

    def test_thermal_missing(self):
        d = dmod.Daemon(machine=FakeMachine(), cfg=cfgmod.load(), thermal=thermal.Thermal(root=self.tmp.name),
                        run_dir=self.tmp.name + "/run")
        with self.assertRaises(RuntimeError):
            d.handle("thermal.mode", {"name": "quiet"})
        self.assertIn("devices", d.status())

    def test_power_recipe(self):
        self.assertEqual(dmod.power_recipe("dc-low", (1, 2, 3), [0])[0][1][0][0], elc_mod.PULSE)



class ProfileTest(DaemonTest):
    def test_profile_overrides_and_reverts(self):
        self.d.apply_lighting()
        self.d.handle("profiles.set", {"profiles": [{"name": "WoW", "match": "^wow", "keyboard": {"effect": "spectrum"},
                                                     "thermal": {"mode": "performance"}}]})
        self.d.on_focus("wow.exe", "World of Warcraft")
        self.assertEqual(self.kb.packets("feature")[-2][1:3], hexb("80 0e"))
        self.assertEqual(self.sys.get("sys/class/platform-profile/platform-profile-0/profile"), "performance")
        self.d.on_focus("com.mitchellh.ghostty", "zsh")
        self.assertEqual(self.sys.get("sys/class/platform-profile/platform-profile-0/profile"), "balanced")
        self.assertEqual(self.kb.packets("feature")[-2][1:3], hexb("80 01"))      # back to static
        self.assertEqual(cfgmod.load()["keyboard"]["effect"], "static")           # never saved

    def test_bad_profiles_rejected(self):
        for profs in ([{"keyboard": {}}], [{"match": "("}], "x"):
            with self.assertRaises(Exception):
                self.d.handle("profiles.set", {"profiles": profs})


class ThermalWearTest(unittest.TestCase):
    """The BIOS writes flash on every Thermal_Control call: the auto rules must not chatter."""

    class FakeThermal:
        def __init__(self):
            self.mode_, self.writes = "balanced", []

        def available(self):
            return True

        def status(self):
            return {"mode": self.mode_}

        def set_mode(self, m):
            self.mode_ = m
            self.writes.append(("mode", m))

        def set_boost(self, pct, fan=None, scale=255):
            self.writes.append(("boost", pct))

        def adapter_status(self):
            return "ok"

        def mode(self):
            return self.mode_

        def set_power_limit(self, w):
            self.writes.append(("power", w))

    class FakeAuto:
        def __init__(self):
            self.want = {"mode": "balanced", "boost_pct": 0}

        def decide(self, snap, now):
            return dict(self.want)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.th = self.FakeThermal()
        self.d = dmod.Daemon(machine=FakeMachine(), cfg={"keyboard": {}, "chassis": {}, "thermal": {"auto": True}},
                             thermal=self.th, run_dir=self.tmp.name)
        self.d.auto = self.FakeAuto()

    def tearDown(self):
        self.tmp.cleanup()

    def test_small_boost_jitter_is_not_written(self):
        for i, pct in enumerate([0, 3, 7, 4, 12, 14, 9]):
            self.d.auto.want["boost_pct"] = pct
            self.d.thermal_tick(float(i))
        self.assertEqual([w for w in self.th.writes if w[0] == "boost"], [("boost", 0)])

    def test_boost_rate_limited_but_urgent_ramp_allowed(self):
        self.d.auto.want["boost_pct"] = 20
        self.d.thermal_tick(0.0)
        self.d.auto.want["boost_pct"] = 30
        self.d.thermal_tick(5.0)                # 10 % more, too soon
        self.d.thermal_tick(25.0)               # due
        self.d.auto.want["boost_pct"] = 70
        self.d.thermal_tick(26.0)               # +40 %: urgent
        self.assertEqual([w[1] for w in self.th.writes if w[0] == "boost"], [20, 30, 70])

    def test_mode_switch_rate_limited_and_boost_reapplied(self):
        self.d.auto.want.update(mode="performance", boost_pct=50)
        self.d.thermal_tick(100.0)
        self.d.auto.want["mode"] = "balanced"
        self.d.thermal_tick(110.0)              # within a minute: no switch
        self.d.thermal_tick(161.0)
        self.assertEqual(self.th.writes, [("mode", "performance"), ("boost", 50), ("mode", "balanced"), ("boost", 50)])



class PowerLimitTest(ThermalWearTest):
    def test_power_limit_reapplied_after_auto_mode_switch(self):
        self.d.cfg["thermal"]["power_limits"] = {"quiet": 45}
        self.d.auto.want.update(mode="quiet", boost_pct=0)
        self.d.thermal_tick(100.0)
        self.assertIn(("power", 45), self.th.writes)
        self.assertLess(self.th.writes.index(("mode", "quiet")), self.th.writes.index(("power", 45)))

    def test_adapter_warning_once(self):
        calls = []
        self.th.adapter_status = lambda: "undersized"
        with mock.patch.object(dmod.subprocess, "run", lambda *a, **k: calls.append(a)), \
                mock.patch.object(dmod.shutil, "which", lambda n: "/usr/bin/" + n):
            self.d.check_adapter(0.0)
            self.d.check_adapter(100.0)
        self.assertEqual(len(calls), 1)
        self.assertIn("too small", calls[0][0][-1])


if __name__ == "__main__":
    unittest.main()
