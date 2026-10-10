import os
import tempfile
import unittest

from mothership import firmware as fw


def ihex(records):
    """[(addr, bytes)] with 32-bit addresses -> Intel HEX text."""
    lines, upper = [], None
    for addr, data in records:
        for off in range(0, len(data), 16):
            a = addr + off
            if a >> 16 != upper:
                upper = a >> 16
                rec = bytes([2, 0, 0, 4, upper >> 8, upper & 0xFF])
                lines.append(":" + (rec + bytes([-sum(rec) & 0xFF])).hex().upper())
            chunk = data[off : off + 16]
            rec = bytes([len(chunk), (a >> 8) & 0xFF, a & 0xFF, 0]) + chunk
            lines.append(":" + (rec + bytes([-sum(rec) & 0xFF])).hex().upper())
    lines.append(":00000001FF")
    return "\n".join(lines) + "\n"


def app_image(pid=0x0550, start=fw.APP_START, size=0x400, sp=0x20004000):
    blob = bytearray(b"\x00" * size)
    blob[0:4] = sp.to_bytes(4, "little")
    blob[4:8] = (start + 0x101).to_bytes(4, "little")
    desc = bytes([0x12, 0x01, 0x10, 0x02, 0, 0, 0, 0x40, 0x7C, 0x18]) + pid.to_bytes(2, "little")
    blob[0x200 : 0x200 + len(desc)] = desc
    return bytes(blob)


class FirmwareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        p = os.path.join(self.tmp.name, name)
        with open(p, "w") as f:
            f.write(text)
        return p

    def test_good_image(self):
        p = self.write("elc-gcc-v1.1.12.hex", ihex([(fw.APP_START, app_image())]))
        img = fw.inspect_image(p)
        self.assertEqual(img["version"], (1, 1, 12))
        self.assertEqual(img["pids"], [0x0550])
        self.assertEqual(len(img["binary"]), 0x400)

    def test_rejects_bootloader_and_factory_pages(self):
        for start in (fw.FLASH_BASE, fw.BOOT_END, fw.APP_END - 0x200):
            p = self.write("elc-gcc-v9.9.9.hex", ihex([(start, app_image(start=start))]))
            with self.assertRaises(fw.FirmwareError):
                fw.inspect_image(p)
        p = self.write("elc-gcc-v9.9.9.hex", ihex([(fw.APP_START, app_image()), (0x0801F000, b"\x51\x15")]))
        with self.assertRaisesRegex(fw.FirmwareError, "outside the application area"):
            fw.inspect_image(p)

    def test_rejects_bad_checksum_and_vectors(self):
        good = ihex([(fw.APP_START, app_image())]).splitlines()
        good[1] = good[1][:-2] + ("00" if good[1][-2:] != "00" else "01")
        with self.assertRaisesRegex(fw.FirmwareError, "checksum"):
            fw.inspect_image(self.write("elc-gcc-v1.1.12.hex", "\n".join(good)))
        with self.assertRaisesRegex(fw.FirmwareError, "vector table"):
            fw.inspect_image(self.write("elc-gcc-v1.1.12.hex", ihex([(fw.APP_START, app_image(sp=0x12345678))])))

    def test_checks(self):
        img = fw.inspect_image(self.write("elc-gcc-v1.1.12.hex", ihex([(fw.APP_START, app_image())])))
        self.assertEqual(fw.check(img, {"pid": 0x0550, "firmware": "1.1.7"}, ac=True), [])
        self.assertTrue(fw.check(img, {"pid": 0x0550, "firmware": "1.1.12"}, ac=True))         # not newer
        self.assertEqual(fw.check(img, {"pid": 0x0550, "firmware": "1.1.12"}, allow_downgrade=True, ac=True), [])
        self.assertTrue(fw.check(img, {"pid": 0x0551, "firmware": "1.1.7"}, ac=True))         # wrong target
        self.assertIn("connect the power adapter first", fw.check(img, {"pid": 0x0550, "firmware": "1.1.7"}, ac=False))

    def test_dry_run_touches_nothing(self):
        p = self.write("elc-gcc-v1.1.12.hex", ihex([(fw.APP_START, app_image())]))
        fw_on_ac = fw.on_ac
        fw.on_ac = lambda root="/": True
        try:
            r = fw.update(p, self.tmp.name + "/b", {"pid": 0x0550, "firmware": "1.1.7"}, dry_run=True, log=lambda *_: None)
        finally:
            fw.on_ac = fw_on_ac
        self.assertTrue(r["dry_run"])
        self.assertFalse(os.path.exists(self.tmp.name + "/b"))


if __name__ == "__main__":
    unittest.main()
