import unittest

from mothership import models


class ModelsTest(unittest.TestCase):
    def test_x17_map_via_same_as(self):
        m = models.chassis_map("0x0406")
        self.assertEqual(m["zones"]["head"], [1])
        self.assertEqual(m, models.chassis_map("0x0306"))
        self.assertIsNone(models.chassis_map("0x9999"))

    def test_zone_leds(self):
        m = models.chassis_map("0x0306")
        self.assertEqual(models.zone_leds(m, "rear"), list(range(10, 20)))
        self.assertNotIn(0, models.zone_leds(m, "all"))           # power LED never in "all"
        self.assertEqual(models.zone_leds(m, ["head", "power"]), [0, 1])
        with self.assertRaises(ValueError):
            models.zone_leds(m, "trunk")

    def test_generic_map(self):
        g = models.generic_map(4)
        self.assertEqual(models.zone_leds(g, "all"), [0, 1, 2, 3])
        self.assertFalse(g["power_states"])



class FitTest(unittest.TestCase):
    def test_touchpad_dropped_unless_present(self):
        m = models.chassis_map("0x0306")
        fitted = models.fit_map(m, {"touchpad_lighting": None})
        self.assertNotIn("touchpad", fitted["zones"])
        self.assertNotIn(2, models.zone_leds(fitted, "all"))
        self.assertTrue(all(2 not in c for c in fitted["columns"]))
        self.assertIn("touchpad", models.fit_map(m, {"touchpad_lighting": True})["zones"])

    def test_unlit_space(self):
        self.assertEqual(models.unlit_keys(0xCABC), {106, 107})
        self.assertEqual(models.unlit_keys(0x1234), set())


if __name__ == "__main__":
    unittest.main()
