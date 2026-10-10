import unittest

from mothership import keyboard as kb
from tests.fakes import FakeHid, hexb


def head(b, n=18):
    return bytes(b[:n])


class PacketTest(unittest.TestCase):
    def test_breathing(self):
        p = kb.effect_packet("breathing", ["ff0000"], speed=0)
        self.assertEqual(len(p), 64)
        self.assertEqual(head(p), hexb("cc 80 02 01 00 00 02 01 01 00 ff 00 00 ff 00 00 02 00"))

    def test_spectrum_two_colors_left(self):
        p = kb.effect_packet("spectrum", [(1, 2, 3), (4, 5, 6)], speed=2, direction="left")
        self.assertEqual(head(p), hexb("cc 80 0e 07 00 00 01 01 01 01 01 02 03 04 05 06 02 00"))

    def test_reactive_press(self):
        p = kb.effect_packet("static", ["00ff00"], play="press")
        self.assertEqual(p[7], 2)
        self.assertEqual(kb.effect_packet("static", ["00ff00"], play="release")[7], 3)

    def test_aurora_block_and_gradient(self):
        p = kb.effect_packet("aurora")
        self.assertEqual(bytes(p[10:22]), kb.AURORA_BLOCK)
        self.assertEqual(kb.effect_packet("gradient", ["ff0000", "0000ff"])[17], 2)

    def test_bad_input(self):
        for args in [("fire",), ("static", ["red"]), ("static", ["ff0000"], 3)]:
            with self.assertRaises(ValueError):
                kb.effect_packet(*args)
        with self.assertRaises(ValueError):
            kb.brightness_packet(140)

    def test_brightness(self):
        self.assertEqual(head(kb.brightness_packet(100), 4), hexb("cc 8b 01 ff"))
        self.assertEqual(head(kb.brightness_packet(50), 4), hexb("cc 8b 01 80"))
        self.assertEqual(head(kb.level_packet(100), 5), hexb("cc 83 38 9c fe"))

    def test_perkey_enter_sequence(self):
        ps = kb.perkey_packets({0: (255, 0, 0), 61: (0, 0, 255)})
        cmds = [bytes(p[1:3]) for p in ps]
        self.assertEqual(cmds[0], hexb("8c 10"))
        self.assertEqual([p[3] for p in ps[1:7]], list(kb.SLOTS))
        self.assertEqual(cmds[7:10], [hexb("8c 05"), hexb("8c 06"), hexb("8c 07")])
        self.assertEqual(ps[7][4 + 0], 1)            # LED 0 mapped to slot 1
        self.assertEqual(ps[8][4 + 1], 1)            # LED 61 -> second map packet, index 1
        self.assertEqual(head(ps[10], 18), hexb("cc 8c 01 01 01 00 00 01 01 01 00 00 00 00 00 00 00 01"))
        self.assertEqual(head(ps[11], 12), hexb("cc 8c 02 00 01 ff 00 00 3e 00 00 ff"))
        self.assertEqual(bytes(ps[-1][1:3]), hexb("8c 13"))

    def test_perkey_frames_split_at_15(self):
        ps = kb.perkey_packets({i: (1, 1, 1) for i in range(20)}, enter=False)
        self.assertEqual(len(ps), 3)                 # 15 + 5 records, then 8c 13

    def test_status_parse(self):
        r91 = b"\xcc3326"
        r93 = bytes([0xCC, 0x93, 0, 0x11, 33, 0x00])
        r94 = bytearray(64)
        r94[2], r94[19], r94[21] = 0x8C, 0, 255
        r94[22:25] = bytes([0x30, 0x20, 0x10])
        st = kb.parse_status(r91, r93, bytes(r94))
        self.assertEqual(st["firmware"], "3326")
        self.assertEqual(st["layout"], "ansi")
        self.assertEqual(st["mode"], "perkey")
        self.assertEqual(st["brightness"], 100)
        self.assertEqual(st["color"], "102030")


class KeyboardTest(unittest.TestCase):
    def test_effect_sends_effect_then_brightness(self):
        h = FakeHid()
        k = kb.Keyboard(h)
        k.effect("wave", ["ff0000"], brightness=40)
        feats = h.packets("feature")
        self.assertEqual(feats[-2][1:3], hexb("80 03"))
        self.assertEqual(feats[-1][1:4], hexb("8b 01 66"))

    def test_set_keys_enters_once(self):
        h = FakeHid()
        k = kb.Keyboard(h, keys={0: None, 1: None})
        k.static("ff0000")
        n1 = sum(1 for p in h.packets("feature") if p[1:3] == hexb("8c 10"))
        k.static("00ff00")
        n2 = sum(1 for p in h.packets("feature") if p[1:3] == hexb("8c 10"))
        self.assertEqual((n1, n2), (1, 1))

    def test_flash_guard(self):
        h = FakeHid()
        k = kb.Keyboard(h)
        with self.assertRaises(PermissionError):
            k.save_as_power_on()
        self.assertFalse(h.sent)
        k.save_as_power_on(write_flash=True)
        self.assertEqual(h.packets("feature")[-1][1:4], hexb("84 03 00"))

    def test_device_gone(self):
        k = kb.Keyboard(FakeHid(fail=True))
        with self.assertRaises(OSError):
            k.effect("static", ["ffffff"])


if __name__ == "__main__":
    unittest.main()
