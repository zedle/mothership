import os
import random
import tempfile
import time
import unittest
from unittest import mock

from mothership import fire
from mothership import keyboard as kb
from mothership.layout import ALL_KEYS, CAPS_LED, KEYCODES, KEYS, MICMUTE_LED, MUTE_LED
from tests.fakes import FakeHid, hexb

G = KEYCODES[34]            # KEY_G -> LED 66, row 3


class FakeInputs:
    """Stands in for KeyInputs: hands out scripted LED presses, honouring accept()."""

    def __init__(self, presses=()):
        self.presses = list(presses)
        self.fds = []
        self.opened = 0
        self.closed = 0

    def open(self):
        self.opened += 1
        self.fds = [99]
        return True

    def close(self):
        self.closed += 1
        self.fds = []

    def wait(self, timeout, accept):
        out, self.presses = self.presses, []
        return out if accept() else []


class RecordingSim(fire.FireSim):
    def __init__(self):
        super().__init__(rng=random.Random(1))
        self.pressed = []

    def step(self, dt=1 / fire.FPS, pressed=()):
        self.pressed.append(list(pressed))
        return super().step(dt, pressed)


class SimTest(unittest.TestCase):
    def test_every_key_gets_a_color(self):
        sim = fire.FireSim(rng=random.Random(0))
        for _ in range(5):
            cols = sim.step()
        self.assertEqual(sorted(cols), ALL_KEYS)
        for rgb in cols.values():
            self.assertEqual(len(rgb), 3)
            self.assertTrue(all(isinstance(v, int) and 0 <= v <= 255 for v in rgb))
        kb.perkey_packets(cols)     # valid input for the keyboard protocol

    def test_pressed_key_flares(self):
        a, b = fire.FireSim(rng=random.Random(7)), fire.FireSim(rng=random.Random(7))
        for _ in range(10):
            a.step()
            b.step()
        a.step(pressed=[G])
        b.step()
        self.assertGreater(a.key_heat(G), b.key_heat(G) + 0.4)
        # hotter than its row neighbours two keys away on either side
        self.assertGreater(a.key_heat(G), a.key_heat(64))
        self.assertGreater(a.key_heat(G), a.key_heat(68))
        self.assertGreater(sum(a.colors()[G]), sum(b.colors()[G]))

    def test_flare_fades(self):
        sim = fire.FireSim(rng=random.Random(3))
        sim.step(pressed=[G])
        for _ in range(15):
            sim.step()
        self.assertEqual(sim.sparks, [])

    def test_unknown_led_ignored(self):
        fire.FireSim(rng=random.Random(0)).step(pressed=[999])

    def test_palette_bounds(self):
        self.assertEqual(fire.palette(-1), (40, 0, 0))
        self.assertEqual(fire.palette(5), (255, 255, 200))


class EffectFileTest(unittest.TestCase):
    def test_parse(self):
        self.assertIsNone(fire.parse_effect("none"))
        self.assertIsNone(fire.parse_effect(""))
        self.assertIsNone(fire.parse_effect("static"))
        self.assertEqual(fire.parse_effect("fire\n"), {"brightness": 100, "chassis": None})
        e = fire.parse_effect("fire brightness=40 chassis")
        self.assertEqual(e["brightness"], 40)
        self.assertEqual(e["chassis"], (fire.HEAD_COLOR, fire.REST_COLOR))
        self.assertEqual(fire.parse_effect("fire chassis=0000ff,ffffff")["chassis"], ((0, 0, 255), (255, 255, 255)))
        self.assertEqual(fire.parse_effect("fire chassis=bogus brightness=x")["chassis"], None)


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = os.path.join(self.tmp.name, "run")
        self.sys = os.path.join(self.tmp.name, "sys")
        os.makedirs(self.run)
        os.makedirs(self.sys)
        self.hid = FakeHid()
        self.inputs = FakeInputs()
        self.sim = RecordingSim()
        self.opened = 0

    def tearDown(self):
        self.tmp.cleanup()

    def open_keyboard(self):
        self.opened += 1
        return kb.Keyboard(self.hid, keys=KEYS)

    def service(self, **kw):
        with mock.patch.dict(os.environ, {"MOTHERSHIP_RUN": self.run}):
            return fire.FireService(self.open_keyboard, inputs=self.inputs, sim=self.sim,
                                    sys_root=self.sys, **kw)

    def put(self, name, text="1", age=0.0):
        p = os.path.join(self.run, name)
        with open(p, "w") as f:
            f.write(text)
        t = time.time() - age
        os.utime(p, (t, t))

    def frames(self):
        return [p for p in self.hid.packets("feature") if p[1:3] == hexb("8c 02")]

    def test_run_dir_from_env(self):
        self.assertEqual(self.service().run_dir, self.run)

    def test_idle_without_fire(self):
        svc = self.service()
        self.assertFalse(svc.tick())                # no effect file
        self.put("effect", "none")
        self.assertFalse(svc.tick())
        self.assertEqual(self.hid.sent, [])
        self.assertEqual(self.opened, 0)
        self.assertEqual(self.inputs.opened, 0)
        self.assertEqual(self.sim.pressed, [])

    def test_renders_while_fire(self):
        svc = self.service()
        self.put("effect", "fire")
        self.assertTrue(svc.tick())
        feats = self.hid.packets("feature")
        self.assertEqual(sum(1 for p in feats if p[1:3] == hexb("8c 10")), 1)   # entered per-key mode
        self.assertTrue(self.frames())
        self.assertTrue(os.path.exists(os.path.join(self.run, fire.ACTIVE_MARK)))
        self.assertEqual(self.inputs.opened, 1)
        n = len(feats)
        self.assertTrue(svc.tick())
        later = self.hid.packets("feature")[n:]
        self.assertFalse(any(p[1:3] == hexb("8c 10") for p in later))         # enter only once
        self.assertTrue(any(p[1:3] == hexb("8c 02") for p in later))

    def test_effect_off_stops_and_closes_inputs(self):
        svc = self.service()
        self.put("effect", "fire")
        svc.tick()
        self.put("effect", "none")
        n = len(self.hid.sent)
        self.assertFalse(svc.tick())
        self.assertEqual(len(self.hid.sent), n)       # nothing more sent
        self.assertEqual(self.inputs.closed, 1)
        self.assertEqual(self.inputs.fds, [])
        self.assertFalse(os.path.exists(os.path.join(self.run, fire.ACTIVE_MARK)))
        self.put("effect", "fire")                     # back on: per-key mode again
        svc.tick()
        later = self.hid.packets("feature")[n:]
        self.assertTrue(any(p[1:3] == hexb("8c 10") for p in later))

    def test_flares_only_when_unlocked_fresh(self):
        svc = self.service()
        self.put("effect", "fire")
        self.inputs.presses = [G]
        svc.tick()                                     # no unlocked flag at all
        self.put("unlocked", age=30)                   # stale
        self.inputs.presses = [G]
        svc.tick()
        self.put("unlocked", age=1)                    # fresh
        self.inputs.presses = [G]
        svc.tick()
        self.assertEqual(self.sim.pressed, [[], [], [G]])

    def test_stale_flag_with_injected_clock(self):
        self.put("effect", "fire")
        self.put("unlocked")
        svc = self.service(clock=lambda: time.time() + 13)
        self.inputs.presses = [G]
        svc.tick()
        self.assertEqual(self.sim.pressed, [[]])

    def test_indicators(self):
        self.put("effect", "fire")
        self.put("mute")
        led = os.path.join(self.sys, "class/leds/input3::capslock")
        os.makedirs(led)
        with open(os.path.join(led, "brightness"), "w") as f:
            f.write("1\n")
        svc = self.service()
        cols = svc.indicators(self.sim.step())
        self.assertEqual(cols[CAPS_LED], fire.WHITE)
        self.assertEqual(cols[MUTE_LED], fire.WHITE)
        self.assertNotEqual(cols[MICMUTE_LED], fire.WHITE)

    def test_brightness_option(self):
        self.put("effect", "fire brightness=50")
        self.service().tick()
        self.assertIn(hexb("cc 8b 01 80"), [p[:4] for p in self.hid.packets("feature")])

    def test_keyboard_gone_then_back(self):
        self.put("effect", "fire")
        svc = self.service()
        self.hid.fail = True
        with mock.patch.object(fire, "log"):
            self.assertFalse(svc.tick())
        self.assertIsNone(svc.kb)
        self.hid.fail = False
        self.assertTrue(svc.tick())
        self.assertEqual(self.opened, 2)
        self.assertTrue(any(p[1:3] == hexb("8c 10") for p in self.hid.packets("feature")))

    def test_no_keyboard_idles(self):
        self.put("effect", "fire")
        svc = self.service()
        svc.open_keyboard = lambda: None
        self.assertFalse(svc.tick())
        self.assertEqual(self.inputs.opened, 0)

    def test_chassis_only_when_asked(self):
        ch_hid = FakeHid()
        from mothership import elc
        svc = self.service(open_chassis=lambda: elc.Elc(ch_hid))
        self.put("effect", "fire")
        svc.tick()
        self.assertEqual(ch_hid.packets("write"), [])
        self.put("effect", "fire chassis")
        with mock.patch("time.sleep"):
            svc.tick()
            svc.tick()                                 # applied once, not every frame
        writes = ch_hid.packets("write")
        colors = [w for w in writes if w[1:3] == bytes([0x03, elc.OP_COLOR])]
        self.assertEqual(len(colors), 1)               # unknown platform: every LED in the rest colour
        self.assertEqual(colors[0][3:6], bytes(fire.REST_COLOR))

    def test_leave_embers(self):
        self.put("effect", "fire")
        svc = self.service()
        svc.tick()
        n = len(self.hid.sent)
        svc.leave_embers()
        svc.stop()
        frames = [p for p in self.hid.packets("feature")[n:] if p[1:3] == hexb("8c 02")]
        self.assertTrue(frames)
        self.assertEqual(bytes(frames[0][5:8]), bytes(fire.palette(fire.EMBER_HEAT)))


class KeyInputsTest(unittest.TestCase):
    def test_finds_keyboards_and_reads_presses(self):
        with tempfile.TemporaryDirectory() as tmp:
            sysd, dev = os.path.join(tmp, "sys"), os.path.join(tmp, "dev")
            os.makedirs(dev)
            for name, caps in (("event3", 1 << 30 | 1 << 57), ("event4", 1 << 1)):
                d = os.path.join(sysd, "class/input", name, "device/capabilities")
                os.makedirs(d)
                with open(os.path.join(d, "key"), "w") as f:
                    f.write(f"{caps:x}\n")
            r, w = os.pipe()
            # stand the pipe's read end in for /dev/input/event3
            os.symlink(f"/proc/self/fd/{r}", os.path.join(dev, "event3"))
            ki = fire.KeyInputs(sysd, dev)
            self.assertTrue(ki.open())
            self.assertEqual(len(ki.fds), 1)
            os.write(w, fire.EVENT.pack(0, 0, fire.EV_KEY, 34, 1) + fire.EVENT.pack(0, 0, fire.EV_KEY, 34, 0))
            self.assertEqual(ki.wait(0.2, lambda: True), [G])
            os.write(w, fire.EVENT.pack(0, 0, fire.EV_KEY, 34, 1))
            self.assertEqual(ki.wait(0.2, lambda: False), [])   # locked: discarded
            ki.close()
            os.close(r)
            os.close(w)


if __name__ == "__main__":
    unittest.main()
