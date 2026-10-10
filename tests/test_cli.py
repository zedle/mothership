import io
import unittest
from contextlib import redirect_stderr

from mothership import cli


def req(*argv):
    return cli.to_request(cli.parser().parse_args(list(argv)))


class CliTest(unittest.TestCase):
    def test_keyboard(self):
        self.assertEqual(req("kb", "effect", "wave", "-c", "FF0000", "--speed", "2"),
                         ("keyboard.effect", {"name": "wave", "on": "static", "colors": ["ff0000"], "speed": 2}))
        self.assertEqual(req("kb", "reactive", "00ff00", "--release"),
                         ("keyboard.reactive", {"color": "00ff00", "on": "release"}))
        self.assertEqual(req("kb", "key", "0=ff0000", "61=#00FF00"),
                         ("keyboard.keys", {"keys": {0: "ff0000", 61: "00ff00"}}))
        self.assertEqual(req("kb", "fire"), ("keyboard.effect", {"name": "fire"}))

    def test_chassis_and_power(self):
        self.assertEqual(req("chassis", "color", "head", "00ff00"), ("chassis.color", {"zone": "head", "color": "00ff00"}))
        self.assertEqual(req("power", "set", "dc-on", "ff8800", "--write-flash")[1]["write_flash"], True)

    def test_thermal(self):
        self.assertEqual(req("fans"), ("thermal.status", {}))
        self.assertEqual(req("fans", "boost", "off"), ("thermal.boost", {"value": None, "fan": None}))
        self.assertEqual(req("gmode"), ("thermal.gmode", {"on": "toggle"}))

    def test_rejects_bad_input(self):
        for argv in (["kb", "brightness", "140"], ["kb", "static", "red"], ["kb", "effect", "disco"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.parser().parse_args(argv)

    def test_power_needs_flag(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["power", "set", "all", "00ff00"]), 2)


if __name__ == "__main__":
    unittest.main()
