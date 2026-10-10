import unittest

from mothership import elc
from tests.fakes import FakeHid, hexb


class PacketTest(unittest.TestCase):
    def test_dim_example(self):
        (p,) = elc.dim_packets(50, range(1, 20))
        self.assertEqual(bytes(p[:24]), hexb("03 26 32 00 13") + bytes(range(1, 20)))

    def test_color_split(self):
        ps = elc.color_packets((1, 2, 3), range(30))
        self.assertEqual(len(ps), 2)
        self.assertEqual(bytes(ps[0][:7]), hexb("03 27 01 02 03 00 1a"))
        self.assertEqual(ps[1][6], 4)

    def test_anim_cmd_and_guard(self):
        self.assertEqual(bytes(elc.anim_cmd(elc.BEGIN, 0xFFFF)[:8]), hexb("03 21 00 01 ff ff 00 00"))
        self.assertEqual(bytes(elc.anim_cmd(elc.RUN_FROM_RAM, 0xFFFF)[:8]), hexb("03 21 00 03 ff ff 00 00"))
        for sub in (elc.COMMIT_TO_FLASH, elc.DELETE, elc.MAKE_DEFAULT, elc.MAKE_STARTUP):
            with self.assertRaises(PermissionError):
                elc.anim_cmd(sub, 97)
        p = elc.anim_cmd(elc.COMMIT_TO_FLASH, 91, power=True, write_flash=True)
        self.assertEqual(bytes(p[:8]), hexb("03 22 00 02 00 5b 00 00"))

    def test_no_erase_builder(self):
        self.assertFalse(any("erase" in n.lower() for n in dir(elc)))

    def test_actions_three_per_packet(self):
        acts = [(elc.MORPH, 1500, 100, (0, 240, 240))] * 4
        ps = elc.action_packets(acts)
        self.assertEqual(len(ps), 2)
        self.assertEqual(bytes(ps[0][:10]), hexb("03 24 02 05 dc 00 64 00 f0 f0"))

    def test_zone_bounds(self):
        with self.assertRaises(ValueError):
            elc.color_packets((1, 1, 1), [25], count=20)

    def test_recipes(self):
        s = elc.recipe("breathing", [1, 2], ["ff0000"] and [(255, 0, 0)], duration_ms=3000)
        self.assertEqual(s[0][1][1][3], (0, 0, 0))
        w = elc.recipe("wave", [], columns=[[1], [2], [3]])
        self.assertEqual(w[1][1][0][3], elc.RAINBOW[1])
        with self.assertRaises(ValueError):
            elc.recipe("disco", [1])


class ElcTest(unittest.TestCase):
    def test_static_sequence(self):
        h = FakeHid()
        e = elc.Elc(h, led_count=20)
        e.static({(0, 255, 0): [1], (255, 0, 0): [10, 11]})
        w = [p[1:] for p in h.packets("write")]
        self.assertTrue(all(len(p) == 33 for p in w))
        self.assertEqual(bytes(w[0][:6]), hexb("03 21 00 01 ff ff"))
        self.assertEqual(bytes(w[1][:7]), hexb("03 27 00 ff 00 00 01"))
        self.assertEqual(bytes(w[-1][:6]), hexb("03 21 00 03 ff ff"))

    def test_info(self):
        v = bytearray(34); v[4:7] = bytes([1, 1, 7])
        c = bytearray(34); c[4:7] = bytes([0x03, 0x06, 20])
        h = FakeHid(replies=[bytes(v), bytes(c)])
        e = elc.Elc(h)
        self.assertEqual(e.info(), {"firmware": "1.1.7", "platform": "0x0306", "leds": 20})
        self.assertEqual(e.led_count, 20)

    def test_power_state_guard(self):
        h = FakeHid()
        e = elc.Elc(h, led_count=20)
        with self.assertRaises(PermissionError):
            e.save_power_state("dc-on", elc.recipe("static", [0]))
        self.assertFalse(h.packets("write"))
        e.save_power_state("dc-on", elc.recipe("static", [0], [(255, 0, 0)]), write_flash=True)
        w = [bytes(p[1:9]) for p in h.packets("write")]
        self.assertEqual(w[0], hexb("03 22 00 04 00 5f 00 00"))
        self.assertEqual(w[-1], hexb("03 22 00 02 00 5f 00 00"))


if __name__ == "__main__":
    unittest.main()
