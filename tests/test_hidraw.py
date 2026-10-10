import os
import tempfile
import unittest

from mothership import hidraw

# Vendor page 0xff89 with report id 0xcc (the keyboard's lighting interface) and a
# plain keyboard descriptor (Generic Desktop page 0x01).
LIGHTING_DESC = bytes([0x06, 0x89, 0xFF, 0x09, 0xCC, 0xA1, 0x01, 0x85, 0xCC, 0xC0])
KEYBOARD_DESC = bytes([0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, 0x01, 0xC0])


def node(root, name, hid_id, desc):
    d = os.path.join(root, name, "device")
    os.makedirs(d)
    with open(os.path.join(d, "uevent"), "w") as f:
        f.write(f"DRIVER=hid-generic\nHID_ID={hid_id}\nHID_NAME=x\n")
    with open(os.path.join(d, "report_descriptor"), "wb") as f:
        f.write(desc)


class HidrawTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = self.tmp.name
        node(r, "hidraw2", "0003:00000D62:0000CABC", KEYBOARD_DESC)
        node(r, "hidraw10", "0003:00000D62:0000CABC", LIGHTING_DESC)
        node(r, "hidraw3", "0003:0000187C:00000550", bytes([0x06, 0x00, 0xFF]))
        self.root = r

    def tearDown(self):
        self.tmp.cleanup()

    def test_usage_pages_and_report_ids(self):
        self.assertEqual(hidraw.usage_pages(LIGHTING_DESC), [0xFF89])
        self.assertEqual(hidraw.report_ids(LIGHTING_DESC), [0xCC])

    def test_find_by_vendor_page(self):
        found = hidraw.find(0x0D62, usage_page=0xFF89, root=self.root)
        self.assertEqual(found, ["/dev/hidraw10"])

    def test_find_by_pid(self):
        self.assertEqual(hidraw.find(0x187C, {0x0550, 0x0551}, root=self.root), ["/dev/hidraw3"])
        self.assertEqual(hidraw.find(0x187C, {0x0551}, root=self.root), [])

    def test_natural_order(self):
        self.assertEqual(hidraw.find(0x0D62, root=self.root), ["/dev/hidraw2", "/dev/hidraw10"])

    def test_product_id(self):
        self.assertEqual(hidraw.product_id("/dev/hidraw3", root=self.root), 0x0550)
        self.assertIsNone(hidraw.product_id("/dev/hidraw99", root=self.root))

    def test_ioctl_numbers(self):
        # HIDIOCSFEATURE(64) as computed by the kernel headers
        self.assertEqual(hidraw.hidiocsfeature(64), 0xC0404806)
        self.assertEqual(hidraw.hidiocgfeature(64), 0xC0404807)


if __name__ == "__main__":
    unittest.main()
