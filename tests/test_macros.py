import unittest

from mothership import keyboard as kb_mod
from mothership import macros
from tests.fakes import FakeHid, hexb


class MacroTest(unittest.TestCase):
    def test_parse_chord_and_delay(self):
        ev = macros.parse("ctrl+c 200ms ctrl+v")
        self.assertEqual(ev[:4], [[0xE0, 0, 25], [0x06, 0, 25], [0x06, 1, 25], [0xE0, 1, 200]])
        self.assertEqual(ev[-1], [0xE0, 1, 25])

    def test_encode_terminator(self):
        data = macros.encode(macros.parse("a"))
        self.assertEqual(data, hexb("04 00 00 19 04 01 00 19 ff 01 00 25"))

    def test_bad_input(self):
        for spec in ("", "hyper+x", "100ms a"):
            with self.assertRaises(ValueError):
                macros.encode(macros.parse(spec))
        with self.assertRaises(ValueError):
            macros.slot_of("F7")

    def test_chunks(self):
        data = bytes(100)
        ps = macros.chunks(3, data)
        self.assertEqual([p[1] for p in ps], [0x73, 0x74])
        self.assertEqual(bytes(ps[0][1:4]), hexb("73 18 64"))     # slot 3 << 3, length 100

    def test_store_requires_flag_and_waits_ready(self):
        ready = bytes([0xCC, 0x96, 1])
        h = FakeHid(replies=[ready] * 5)
        k = kb_mod.Keyboard(h)
        with self.assertRaises(PermissionError):
            macros.store(k, "F2", "a")
        self.assertFalse(h.sent)
        r = macros.store(k, "F2", "a", write_flash=True)
        self.assertEqual(r["slot"], 1)
        self.assertEqual(h.packets("feature")[-1][1:4], hexb("73 08 0c"))

    def test_clear(self):
        h = FakeHid(replies=[bytes([0xCC, 0x96, 1])])
        macros.clear(kb_mod.Keyboard(h), "f6", write_flash=True)
        self.assertEqual(h.packets("feature")[-1][1:4], hexb("73 28 00"))


if __name__ == "__main__":
    unittest.main()
