import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from mothership import config


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "mothership", "config.json")

    def write(self, text):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            f.write(text)

    def test_defaults_without_file(self):
        cfg = config.load(self.path)
        self.assertEqual(cfg.pop("_warnings"), [])
        self.assertEqual(cfg, config.DEFAULTS)
        cfg["keyboard"]["colors"].append("000000")  # a deep copy: DEFAULTS untouched
        self.assertEqual(config.DEFAULTS["keyboard"]["colors"], ["ff2000"])

    def test_merge_keeps_user_keys(self):
        self.write(json.dumps({
            "keyboard": {"effect": "breathing", "custom": 7},
            "chassis": {"zones": {"head": "0000ff"}},
            "thermal": {"interval": 3},
            "future": {"x": 1},
        }))
        cfg = config.load(self.path)
        self.assertEqual(cfg["_warnings"], [])
        self.assertEqual(cfg["keyboard"]["effect"], "breathing")
        self.assertEqual(cfg["keyboard"]["custom"], 7)
        self.assertEqual(cfg["keyboard"]["brightness"], 100)
        self.assertEqual(cfg["chassis"]["zones"], {"head": "0000ff", "rear": "ff0000", "touchpad": "ff0000"})
        self.assertEqual(cfg["thermal"], {"auto": True, "interval": 3})
        self.assertEqual(cfg["future"], {"x": 1})

    def test_corrupted_json_gives_defaults_and_warning(self):
        self.write('{"keyboard": {"effect": "brea')
        cfg = config.load(self.path)
        warnings = cfg.pop("_warnings")
        self.assertEqual(len(warnings), 1)
        self.assertIn("not valid JSON", warnings[0])
        self.assertEqual(cfg, config.DEFAULTS)

    def test_top_level_not_object(self):
        self.write("[1, 2]")
        cfg = config.load(self.path)
        self.assertEqual(len(cfg.pop("_warnings")), 1)
        self.assertEqual(cfg, config.DEFAULTS)

    def test_bad_section_falls_back_others_kept(self):
        self.write(json.dumps({"keyboard": 5, "chassis": {"brightness": 40, "zones": "red"}}))
        cfg = config.load(self.path)
        self.assertEqual(cfg["keyboard"], config.DEFAULTS["keyboard"])
        self.assertEqual(cfg["chassis"]["brightness"], 40)
        self.assertEqual(cfg["chassis"]["zones"], config.DEFAULTS["chassis"]["zones"])
        self.assertEqual(len(cfg["_warnings"]), 2)
        self.assertTrue(cfg["_warnings"][0].startswith("keyboard"))
        self.assertTrue(cfg["_warnings"][1].startswith("chassis.zones"))

    def test_save_atomic_round_trip(self):
        cfg = config.load(self.path)
        cfg["_warnings"].append("something")
        config.update(cfg, "keyboard", {"effect": "spectrum", "speed": 2})
        config.save(cfg, self.path)
        d = os.path.dirname(self.path)
        self.assertEqual(os.listdir(d), ["config.json"])
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)
        with open(self.path) as f:
            raw = json.load(f)
        self.assertNotIn("_warnings", raw)
        self.assertEqual(raw["keyboard"]["effect"], "spectrum")
        again = config.load(self.path)
        self.assertEqual(again.pop("_warnings"), [])
        cfg.pop("_warnings")
        self.assertEqual(again, cfg)

    def test_save_replaces_existing_and_cleans_up_on_failure(self):
        config.save({"keyboard": {"effect": "static"}}, self.path)
        with self.assertRaises(TypeError):
            config.save({"keyboard": {"bad": object()}}, self.path)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["config.json"])
        config.save({"keyboard": {"effect": "aurora"}}, self.path)
        with open(self.path) as f:
            self.assertEqual(json.load(f), {"keyboard": {"effect": "aurora"}})

    def test_update(self):
        cfg = {"keyboard": {"effect": "static", "speed": 1}, "thermal": 3}
        self.assertIs(config.update(cfg, "keyboard", {"speed": 2}), cfg)
        self.assertEqual(cfg["keyboard"], {"effect": "static", "speed": 2})
        config.update(cfg, "thermal", {"auto": False})
        self.assertEqual(cfg["thermal"], {"auto": False})
        config.update(cfg, "new", {"a": 1})
        self.assertEqual(cfg["new"], {"a": 1})
        with self.assertRaises(TypeError):
            config.update(cfg, "keyboard", 5)

    def test_env_paths(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/x/conf", "XDG_STATE_HOME": "/x/state"}):
            self.assertEqual(config.config_path(), "/x/conf/mothership/config.json")
            self.assertEqual(config.state_path(), "/x/state/mothership/state.json")
        env = {k: v for k, v in os.environ.items() if k not in ("XDG_CONFIG_HOME", "XDG_STATE_HOME")}
        env["HOME"] = "/home/someone"
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(config.config_path(), "/home/someone/.config/mothership/config.json")
            self.assertEqual(config.state_path(), "/home/someone/.local/state/mothership/state.json")
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative", "HOME": "/home/someone"}):
            self.assertEqual(config.config_path(), "/home/someone/.config/mothership/config.json")

    def test_load_and_save_default_to_env_path(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name}):
            cfg = config.load()
            config.update(cfg, "thermal", {"auto": False})
            config.save(cfg)
            self.assertTrue(os.path.exists(self.path))
            self.assertFalse(config.load()["thermal"]["auto"])


if __name__ == "__main__":
    unittest.main()
