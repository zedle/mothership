import os
import tempfile
import unittest
from unittest import mock

from mothership import elc, models, probe
from tests.fakes import FakeHid


def info_replies(leds=6, platform=(0x09, 0x99)):
    v = bytearray(34); v[4:7] = bytes([1, 1, 12])
    c = bytearray(34); c[4], c[5], c[6] = platform[0], platform[1], leds
    return [bytes(v), bytes(c)]


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_probe_builds_and_saves_map(self):
        answers = iter(["", "l", "rl", "rr", "t", "bogus", "o"])
        e = elc.Elc(FakeHid(replies=info_replies()))
        m = probe.run(e, ask=lambda _: next(answers), say=lambda *_: None)
        self.assertEqual(m["zones"], {"head": [1], "rear_left": [2], "rear_right": [3], "touchpad": [4],
                                      "other": [5], "power": [0]})
        self.assertEqual(m["groups"]["rear"], ["rear_left", "rear_right"])
        self.assertEqual(models.chassis_map("0x0999"), m)              # user map is picked up
        self.assertIsNotNone(models.chassis_map("0x0306"))              # built-ins still there

    def test_stop_early(self):
        answers = iter(["l", "q"])
        e = elc.Elc(FakeHid(replies=info_replies()))
        m = probe.run(e, ask=lambda _: next(answers), say=lambda *_: None)
        self.assertEqual(m["zones"]["head"], [0])

    def test_probe_never_writes_flash(self):
        h = FakeHid(replies=info_replies(3))
        answers = iter(["l", "n", "r"])
        probe.run(elc.Elc(h), ask=lambda _: next(answers), say=lambda *_: None)
        for p in h.packets("write"):
            if p[1] == 0x03 and p[2] in (0x21, 0x22):
                self.assertNotIn(p[4], elc.PERSISTENT_SUBS)


if __name__ == "__main__":
    unittest.main()
