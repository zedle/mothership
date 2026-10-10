import os
import tempfile
import unittest

from mothership import graphics


class GraphicsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, card, name, status, driver):
        cdir = os.path.join(self.root, "sys/class/drm", card)
        conn = os.path.join(cdir, f"{card}-{name}")
        os.makedirs(conn, exist_ok=True)
        drv = os.path.join(self.root, "sys/bus/pci/drivers", driver)
        os.makedirs(drv, exist_ok=True)
        os.makedirs(os.path.join(cdir, "device"), exist_ok=True)
        if not os.path.islink(os.path.join(cdir, "device", "driver")):
            os.symlink(drv, os.path.join(cdir, "device", "driver"))
        with open(os.path.join(conn, "status"), "w") as f:
            f.write(status + "\n")
        flat = os.path.join(self.root, "sys/class/drm", f"{card}-{name}")
        if not os.path.exists(flat):
            os.symlink(conn, flat)

    def test_hybrid(self):
        self.make("card0", "eDP-2", "disconnected", "nvidia")
        self.make("card1", "eDP-1", "connected", "i915")
        self.assertEqual(graphics.mode(self.root)["mode"], "hybrid")

    def test_discrete(self):
        self.make("card0", "eDP-2", "connected", "nvidia")
        self.make("card1", "eDP-1", "disconnected", "i915")
        self.assertEqual(graphics.mode(self.root)["mode"], "discrete")

    def test_no_panel(self):
        self.assertEqual(graphics.mode(self.root), {"mode": "unknown"})

    def test_reboot_needs_confirm(self):
        with self.assertRaises(PermissionError):
            graphics.reboot_to_firmware_setup()


if __name__ == "__main__":
    unittest.main()
