import io
import unittest

from mothership import effects as fx
from mothership import layout, tty, tui

STATUS = {
    "devices": {"keyboard": "/dev/hidraw1", "chassis": "/dev/hidraw4", "chassis_pid": "0550"},
    "config": {
        "keyboard": {"effect": "wave", "colors": ["ff0000"], "speed": 2, "direction": "left", "brightness": 80},
        "chassis": {"effect": "static", "colors": ["00ff00"], "zones": {"head": "00ff00", "rear": "ff0000"},
                    "brightness": 100},
        "thermal": {"auto": True},
        "power_button": {"ac-full": "00ff00"},
    },
    "errors": {"chassis": "[Errno 13] Permission denied: '/dev/hidraw4'"},
    "keyboard": {"firmware": "3326", "unlit": [106, 107]},
    "chassis": {"firmware": "1.1.12", "platform": "0x0306", "zones": ["head", "power", "rear_left", "rear_right"]},
    "graphics": {"mode": "hybrid"},
    "thermal": {"available": True, "mode": "balanced", "modes": ["quiet", "balanced", "performance"],
                "fans": [{"id": 1, "label": "CPU Fan", "rpm": 2400, "boost_pct": 0, "max": 4200},
                         {"id": 2, "label": "GPU Fan", "rpm": 2100, "boost_pct": 30, "max": 4100}],
                "temps": {"cpu": 61.0, "package": 92.0, "gpu": 50.0}, "ac": True,
                "tcc_offset": 5, "power_limits": {"long_term": 90, "short_term": 120},
                "power_info": {"adapters": 1, "watts": [330], "status": "ok"}},
}


class Tty:
    def __init__(self, tty=True):
        self._tty = tty
        self.encoding = "utf-8"

    def isatty(self):
        return self._tty

    def fileno(self):
        raise OSError("no fd")


def has_sgr(s):
    return "\x1b[" in s


class DetectTest(unittest.TestCase):
    def test_no_color_and_pipes_are_plain(self):
        self.assertEqual(tty.Term.detect(Tty(), {"NO_COLOR": "1", "COLORTERM": "truecolor"}).mode, "plain")
        self.assertEqual(tty.Term.detect(Tty(False), {"COLORTERM": "truecolor"}).mode, "plain")
        self.assertEqual(tty.Term.detect(Tty(), {"TERM": "dumb"}).mode, "plain")

    def test_truecolor_and_256(self):
        self.assertEqual(tty.Term.detect(Tty(), {"COLORTERM": "truecolor", "TERM": "xterm-ghostty"}).mode, "truecolor")
        self.assertEqual(tty.Term.detect(Tty(), {"COLORTERM": "24bit"}).mode, "truecolor")
        self.assertEqual(tty.Term.detect(Tty(), {"TERM": "xterm-256color"}).mode, "256")

    def test_width_from_columns(self):
        self.assertEqual(tty.Term.detect(Tty(False), {"COLUMNS": "132"}).width, 132)

    def test_plain_has_no_escapes(self):
        t = tty.Term("plain", 80)
        self.assertEqual(t.paint("x", bold=True, fg=(1, 2, 3)), "x")
        self.assertEqual(tty.swatch(t, "ff0000"), "#ff0000")

    def test_256_colour(self):
        self.assertEqual(tty.rgb256((255, 0, 0)), 196)
        self.assertEqual(tty.rgb256((0, 0, 0)), 16)
        self.assertIn("38;5;196", tty.Term("256").paint("x", fg=(255, 0, 0)))


class KeyboardTest(unittest.TestCase):
    def colors(self, kb=None):
        return tty.key_colors(kb or {"effect": "static", "colors": ["00ff00"]}, 0.0, still=True)

    def test_fits_width(self):
        for mode in ("truecolor", "256", "plain"):
            term = tty.Term(mode, 200)
            for w in (40, 60, 79, 95, 120):
                for ln in tty.keyboard(term, self.colors(), w, unlit=[106, 107]):
                    self.assertLessEqual(tty.vlen(ln), w, (mode, w, ln))

    def test_plain_has_no_colour_codes(self):
        lines = tty.keyboard(tty.Term("plain", 100), self.colors(), 95, unlit=[106, 107])
        self.assertEqual(len(lines), 6)
        self.assertFalse(any(has_sgr(ln) for ln in lines))
        self.assertIn("[Esc]", lines[0])
        self.assertIn("·" * 10, lines[5])       # unlit space bar

    def test_unlit_keys_are_dim_outlines(self):
        term = tty.Term("truecolor", 100)
        lines = tty.keyboard(term, self.colors(), 95, unlit=[106, 107])
        self.assertEqual(len(lines), 12)
        self.assertIn("\x1b[0;2m╭", lines[10])
        self.assertIn("\x1b[0;2m╰", lines[11])
        lit = tty.keyboard(term, self.colors(), 95, unlit=[])
        self.assertNotIn("╭", lit[10])
        self.assertIn("48;2;0;255;0", lit[10])  # the space bar is painted green instead

    def test_spans_keep_gaps_and_order(self):
        for w in (32, 47, 95):
            for row in tty.key_spans(w):
                for (_, a, b), (_, c, _) in zip(row, row[1:]):
                    self.assertLess(a, b)
                    self.assertLess(b, c)
                self.assertLessEqual(row[-1][2], w)

    def test_every_key_drawn(self):
        drawn = {led for row in tty.key_spans(95) for led, _, _ in row}
        self.assertEqual(drawn | {107}, set(layout.KEYS))

    def test_fire_frame_is_warm(self):
        cols = tty.key_colors({"effect": "fire"}, 1.7, still=True)
        rgb, i = cols[107]
        self.assertGreater(rgb[0], rgb[2])
        self.assertGreater(i, 0.3)

    def test_breathing_still_frame_is_bright(self):
        kb = {"effect": "breathing", "colors": ["0000ff"], "speed": 1}
        _, i = fx.key_color(kb, 50, 0.5, 0.5, fx.still_time(kb), still=True)
        self.assertGreater(i, 0.95)


class StatusTest(unittest.TestCase):
    def test_full_status(self):
        out = tty.render_status(tty.Term("truecolor", 100), STATUS)
        plain = tty.strip(out)
        for s in ("mothership", "keyboard fw 3326", "lighting fw 1.1.12", "hybrid", "Wave", "speed 2",
                  "left", "80%", "lid", "rear", "balanced", "2400", "rpm", "+30%", "92°C", "PL1 90 W",
                  "TCC −5 °C", "330 W", "chassis: Permission denied"):
            self.assertIn(s, plain)
        self.assertNotIn("touchpad", plain)       # zones don't list it
        self.assertNotIn("G-MODE", plain)
        self.assertLessEqual(max(tty.vlen(ln) for ln in out.split("\n")), 100)

    def test_touchpad_only_when_listed(self):
        st = dict(STATUS, chassis=dict(STATUS["chassis"], zones=["head", "touchpad", "rear_left"]))
        self.assertIn("touchpad", tty.strip(tty.render_status(tty.Term("truecolor", 100), st)))

    def test_minimal_and_partial(self):
        for st in ({}, {"config": {}}, {"devices": {"keyboard": None, "chassis": None}},
                   {"keyboard": {"firmware": "1"}, "config": {"keyboard": {"effect": "fire"}}},
                   {"thermal": {"error": "boom"}}, {"thermal": {"available": False}},
                   {"thermal": {"mode": "quiet"}}, {"chassis": {"zones": []}, "config": {"chassis": {}}}):
            for mode in ("truecolor", "plain"):
                out = tty.render_status(tty.Term(mode, 80, tty=mode != "plain"), st)
                self.assertIn("mothership", out)
        out = tty.render_status(tty.Term("plain", 80, tty=False), {"thermal": {"error": "[Errno 13] boom"}})
        self.assertIn("boom", out)
        self.assertNotIn("Errno", out)

    def test_old_daemon_without_new_fields(self):
        st = {k: v for k, v in STATUS.items() if k != "graphics"}
        st["thermal"] = {k: v for k, v in STATUS["thermal"].items() if k not in ("tcc_offset", "power_limits", "power_info")}
        plain = tty.strip(tty.render_status(tty.Term("truecolor", 100), st))
        self.assertNotIn("Limits", plain)
        self.assertNotIn("graphics", plain)

    def test_plain_and_piped(self):
        out = tty.render_status(tty.Term("plain", 80, tty=False), STATUS)
        self.assertFalse(has_sgr(out))
        self.assertNotIn("[Esc]", out)            # no keyboard drawing in a pipe
        self.assertIn("Keyboard  Wave", out)

    def test_gmode_badge(self):
        st = dict(STATUS, thermal=dict(STATUS["thermal"], mode="performance"))
        self.assertIn("G-MODE", tty.strip(tty.render_status(tty.Term("truecolor", 100), st)))


class ResultTest(unittest.TestCase):
    term = tty.Term("plain", 80, tty=False)

    def r(self, cmd, args, result, **ctx):
        return tty.render_result(self.term, cmd, args, result, ctx)

    def test_keyboard_confirmation(self):
        out = self.r("keyboard.effect", {"name": "wave"}, {"keyboard": {"effect": "wave", "speed": 2, "brightness": 100}})
        self.assertEqual(out, "ok Keyboard  Wave - speed 2 - 100%" if not self.term.unicode else "✓ Keyboard  Wave · speed 2 · 100%")
        out = self.r("keyboard.effect", {}, {"keyboard": {"effect": "static", "colors": ["ff0000"], "brightness": 60}})
        self.assertIn("#ff0000", out)
        self.assertIn("60%", out)

    def test_colour_confirmation_has_swatch(self):
        out = tty.render_result(tty.Term("truecolor", 80), "keyboard.effect", {},
                                {"keyboard": {"effect": "static", "colors": ["ff0000"]}})
        self.assertIn("38;2;255;0;0", out)
        self.assertIn("✓", out)
        self.assertEqual(out.count("\n"), 0)

    def test_other_confirmations(self):
        self.assertIn("Lights", self.r("chassis.color", {"zone": "head", "color": "00ff00"},
                                      {"chassis": {"effect": "static", "zones": {"head": "00ff00"}}}))
        self.assertIn("G-Mode  on", self.r("thermal.gmode", {"on": True}, {"mode": "performance"}))
        self.assertIn("Fan boost  50%", self.r("thermal.boost", {"value": 50}, {}))
        self.assertIn("Fan rules  manual", self.r("thermal.auto", {"on": False}, {}))
        self.assertIn("−5 °C", self.r("thermal.tcc", {"value": 5}, {}))
        self.assertIn("65 W", self.r("thermal.power_limit", {"value": 65, "mode": None}, {}))
        self.assertIn("re-applied", self.r("reapply", {}, "ok"))
        self.assertIn("Profile removed", self.r("profiles.set", {}, {"profiles": []}, verb="remove", name="wow"))
        out = self.r("profiles.set", {}, {"profiles": [{"name": "wow", "match": "^wow", "thermal": {"mode": "gmode"}}]},
                     verb="add", name="wow")
        self.assertIn("wow", out)
        self.assertIn("gmode", out)
        self.assertIn("not set by mothership", self.r("power.show", {}, {"states": ["ac-full"], "saved": {}}))
        self.assertIn("hybrid", self.r("graphics", {}, {"mode": "hybrid"}))

    def test_warnings(self):
        self.assertEqual(tty.warnings(self.term, "keyboard.effect", {"error": "[Errno 5] I/O error"}), "! keyboard: I/O error")
        self.assertEqual(tty.warnings(self.term, "keyboard.effect", {"error": None}), "")


class CliTest(unittest.TestCase):
    def test_json_unchanged(self):
        from contextlib import redirect_stdout
        from unittest import mock
        from mothership import cli
        buf = io.StringIO()
        with mock.patch.object(cli.ipc, "request", return_value={"a": 1}), redirect_stdout(buf):
            self.assertEqual(cli.main(["--json", "devices"]), 0)
        self.assertEqual(buf.getvalue(), '{"a": 1}\n')

    def test_human_default(self):
        from contextlib import redirect_stdout
        from unittest import mock
        from mothership import cli
        buf = io.StringIO()
        with mock.patch.object(cli.ipc, "request", return_value={"keyboard": {"effect": "fire"}, "error": None}), \
                redirect_stdout(buf):
            self.assertEqual(cli.main(["kb", "fire"]), 0)
        self.assertIn("Keyboard", buf.getvalue())
        self.assertIn("Fire", buf.getvalue())


class TuiStateTest(unittest.TestCase):
    def state(self):
        s = tui.State()
        s.set_status(STATUS)
        return s

    def test_parse_keys(self):
        self.assertEqual(tui.parse_keys("\x1b[A\x1b[B\x1bOC\x1b[D\t\x1b[Z\r[]gq\x1b"),
                         ["up", "down", "right", "left", "tab", "backtab", "enter", "[", "]", "g", "q", "esc"])
        self.assertEqual(tui.parse_keys("\x03"), ["ctrl-c"])

    def test_tabs(self):
        s = self.state()
        s.key("tab")
        self.assertEqual(s.tab, 1)
        s.key("backtab")
        s.key("backtab")
        self.assertEqual(s.tab, 3)
        s.key("3")
        self.assertEqual(s.tab, 2)
        for k in ("q", "esc", "ctrl-c"):
            self.assertEqual(s.key(k), [("quit",)])

    def test_keyboard_effect_and_apply(self):
        s = self.state()
        self.assertEqual(s.value("effect"), "wave")
        s.key("left")                               # wave -> breathing
        self.assertEqual(s.value("effect"), "breathing")
        self.assertIn(0, s.dirty)
        kb, _ = s.preview()
        self.assertEqual(kb["effect"], "breathing")
        s.key("down")                               # colour row (enabled for breathing)
        self.assertEqual(s.current_row().key, "color")
        s.key("right")
        col = s.value("color")
        acts = s.key("enter")
        self.assertEqual(acts, [("request", "keyboard.effect",
                                 {"name": "breathing", "on": "static", "colors": [col], "speed": 2})])
        self.assertNotIn(0, s.dirty)

    def test_disabled_rows_are_skipped(self):
        s = self.state()
        s.draft[(0, "effect")] = "spectrum"         # no colours, no direction
        s.key("down")
        self.assertEqual(s.current_row().key, "speed")
        s.key("down")
        self.assertEqual(s.current_row().key, "effect")
        s.draft[(0, "effect")] = "fire"
        self.assertEqual(s.key("enter"), [("request", "keyboard.effect", {"name": "fire"})])

    def test_wave_sends_direction(self):
        s = self.state()
        args = s.key("enter")[0][2]
        self.assertEqual(args, {"name": "wave", "on": "static", "speed": 2, "direction": "left"})

    def test_brightness_and_gmode(self):
        s = self.state()
        self.assertEqual(s.key("]"), [("request", "keyboard.brightness", {"value": 90})])
        self.assertEqual(s.key("["), [("request", "keyboard.brightness", {"value": 70})])
        s.key("2")
        self.assertEqual(s.key("]"), [("request", "chassis.brightness", {"value": 100})])
        self.assertEqual(s.key("g"), [("request", "thermal.gmode", {"on": "toggle"})])

    def test_lights(self):
        s = self.state()
        s.key("2")
        self.assertEqual([r.key for r in s.rows()], ["effect", "zone", "color", "duration"])
        zones = [v for v, _ in s.rows()[1].options]
        self.assertNotIn("touchpad", zones)
        self.assertEqual(s.key("enter"), [("request", "chassis.color", {"zone": "head", "color": "00ff00"})])
        s.key("right")                              # breathing
        s.key("enter")
        s.set_status(STATUS)
        s.draft[(1, "effect")] = "spectrum"
        self.assertEqual(s.key("enter"), [("request", "chassis.effect", {"name": "spectrum", "duration_ms": 3000})])

    def test_thermal(self):
        s = self.state()
        s.key("3")
        self.assertEqual([r.key for r in s.rows()], ["mode", "auto", "boost", "tcc"])
        s.key("right")
        self.assertEqual(s.key("enter"), [("request", "thermal.mode", {"name": "performance"})])
        s.key("down")
        s.key("right")
        self.assertEqual(s.key("enter"), [("request", "thermal.auto", {"on": False})])
        s.key("down")
        self.assertEqual(s.value("boost"), 25)      # nearest step to the 30% boost
        s.key("left")
        self.assertEqual(s.key("enter"), [("request", "thermal.boost", {"value": None, "fan": None})])

    def test_power_tab_is_read_only(self):
        s = self.state()
        s.key("4")
        self.assertEqual(s.rows(), [])
        for k in ("enter", "left", "right", "up", "down"):
            self.assertEqual(s.key(k), [])

    def test_status_refresh_keeps_edits(self):
        s = self.state()
        s.key("right")
        s.set_status(STATUS)
        self.assertEqual(s.value("effect"), "spectrum")
        s.key("r")
        self.assertEqual(s.value("effect"), "wave")

    def test_no_status(self):
        s = tui.State()
        s.set_status({})
        for k in ("3", "enter", "down", "4", "1", "right", "enter"):
            s.key(k)

    def test_frame_fits(self):
        for mode in ("truecolor", "plain"):
            term = tty.Term(mode, 100)
            for w, h in ((100, 40), (60, 20), (200, 60), (40, 12)):
                for tab in "1234":
                    s = self.state()
                    s.key(tab)
                    lines = tui.frame(term, s, w, h, 1.0, toast="hello")
                    self.assertEqual(len(lines), h)
                    self.assertTrue(all(tty.vlen(ln) <= w for ln in lines))
        lines = tui.frame(tty.Term("truecolor", 100), tui.State(), 80, 24, 0.0, live=False)
        self.assertIn("offline", tty.strip(lines[0]))


if __name__ == "__main__":
    unittest.main()
