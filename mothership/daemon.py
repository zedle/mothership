"""mothershipd: owns the lighting devices, applies the configured state, runs the thermal
rules and answers clients on a unix socket.

The configuration is the desired state. It is applied at start, after every resume (the
controllers forget volatile lighting while suspended), whenever a device reappears, and
whenever a client changes it. Nothing here writes controller flash except the explicit
power.set command, which must carry write_flash: true.
"""
import logging
import os
import re
import shutil
import subprocess
import threading
import time

from . import config as cfgmod
from . import elc as elc_mod
from . import ipc
from . import keyboard as kb_mod
from . import models
from . import thermal as th_mod

log = logging.getLogger("mothership")
RUN_DIR = os.environ.get("MOTHERSHIP_RUN", "/run/mothership")
REDETECT_S, TICK_S, RESUME_JUMP_S = 5.0, 1.0, 3.0

KB_FIRMWARE_EFFECTS = set(kb_mod.EFFECTS) | {"static-blue"}
CHASSIS_EFFECTS = ("static", "breathing", "pulse", "morph", "spectrum", "wave", "off")


def _colors(values):
    return [kb_mod.parse_color(c) if isinstance(c, str) else tuple(c) for c in values]


def power_recipe(state, rgb, leds):
    """What the power button shows by itself in each power state (saved in flash)."""
    if state in ("ac-sleep", "dc-sleep"):
        return elc_mod.recipe("breathing", leds, [rgb], duration_ms=2000)
    if state == "dc-low":
        return elc_mod.recipe("pulse", leds, [rgb], duration_ms=1000)
    if state == "ac-charging":
        return elc_mod.recipe("breathing", leds, [rgb], duration_ms=3000)
    return elc_mod.recipe("static", leds, [rgb])


class Daemon:
    def __init__(self, machine=None, cfg=None, thermal=None, run_dir=RUN_DIR, keys=None):
        self.machine = machine or models.detect()
        self.cfg = cfg if cfg is not None else cfgmod.load()
        self.thermal = thermal or th_mod.Thermal()
        self.auto = th_mod.Auto(self.cfg.get("thermal", {}))
        self.run_dir = run_dir
        self.keys = keys
        self.kb = None
        self.chassis = None
        self.cmap = None
        self.lock = threading.RLock()
        self.server = None
        self.stopping = threading.Event()
        self.last_redetect = 0.0
        self.last_thermal = 0.0
        self.applied_thermal = {}
        self.errors = {}
        self.active_profile = None
        self.profile_restore = None

    # ------------------------------------------------------------------ devices
    def open_devices(self):
        if self.kb is None and self.machine.keyboard_path:
            try:
                self.kb = self.machine.open_keyboard(keys=self.keys or self._layout_keys())
            except OSError as e:
                self.errors["keyboard"] = str(e)
        if self.chassis is None and self.machine.chassis_path:
            try:
                self.chassis = self.machine.open_chassis()
                info = self.chassis.info()
                cmap = models.chassis_map(info["platform"]) or models.generic_map(info["leds"])
                tp = self.cfg.get("chassis", {}).get("touchpad")
                flags = {"touchpad_lighting": tp if isinstance(tp, bool) else models.platform_flag("touchpad_lighting")}
                self.cmap = models.fit_map(cmap, flags)
                self.chassis_info = info
            except OSError as e:
                self.errors["chassis"] = str(e)
                self.chassis = None

    @staticmethod
    def _layout_keys():
        try:
            from . import layout
            return layout.KEYS
        except ImportError:
            return {}

    def drop(self, which):
        dev = getattr(self, which)
        if dev is not None:
            try:
                dev.hid.close()
            except OSError:
                pass
        setattr(self, which, None)

    def redetect(self):
        self.machine = models.detect(devices=self.machine.devices)
        before = (self.kb is not None, self.chassis is not None)
        self.open_devices()
        if (self.kb is not None, self.chassis is not None) != before:
            self.apply_lighting()

    # ------------------------------------------------------------------ apply
    def write_run(self, name, value):
        try:
            os.makedirs(self.run_dir, exist_ok=True)
            tmp = os.path.join(self.run_dir, f".{name}.tmp")
            with open(tmp, "w") as f:
                f.write(value)
            os.replace(tmp, os.path.join(self.run_dir, name))
        except OSError as e:
            self.errors["run"] = str(e)

    def apply_keyboard(self):
        k = self.effective("keyboard")
        fire = k.get("effect") == "fire" or k.get("fire") is True
        self.write_run("effect", "fire" if fire else "none")
        if fire or self.kb is None:
            return
        # The fire service marks fire-active while it renders; let its last frame land first.
        active = os.path.join(self.run_dir, "fire-active")
        end = time.monotonic() + 2.0
        while os.path.exists(active) and time.monotonic() < end:
            time.sleep(0.05)
        eff = k.get("effect", "static")
        bri = int(k.get("brightness", 100))
        cols = _colors(k.get("colors") or ["ffffff"])
        try:
            if eff == "off":
                self.kb.off()
            elif eff == "perkey":
                keys = {int(led): kb_mod.parse_color(c) for led, c in (k.get("keys") or {}).items()}
                base = cols[0]
                full = {led: keys.get(led, base) for led in (self.kb.keys or keys)}
                self.kb.set_keys(full or keys, brightness=bri)
            elif eff == "static-blue":
                self.kb.effect("static", [(0, 255, 255)], brightness=bri)
            elif eff in kb_mod.EFFECTS:
                self.kb.effect(eff, cols, speed=int(k.get("speed", 1)), direction=k.get("direction", "right"),
                               play=k.get("on", "static"), brightness=bri)
            else:
                raise ValueError(f"unknown keyboard effect {eff!r}")
            self.errors.pop("keyboard", None)
        except OSError as e:
            self.errors["keyboard"] = str(e)
            self.drop("kb")

    def apply_chassis(self):
        if self.chassis is None or self.cmap is None:
            return
        c = self.effective("chassis")
        eff = c.get("effect", "static")
        try:
            lights = models.zone_leds(self.cmap, "lights" if "lights" in self.cmap.get("groups", {}) else "all")
            if eff == "off":
                self.chassis.static({(0, 0, 0): lights})
            elif eff == "static":
                groups = {}
                zones = c.get("zones") or {}
                if zones:
                    for name, col in zones.items():
                        try:
                            leds = models.zone_leds(self.cmap, name)
                        except ValueError:
                            continue
                        groups.setdefault(kb_mod.parse_color(col), []).extend(leds)
                else:
                    groups[_colors(c.get("colors") or ["ffffff"])[0]] = lights
                self.chassis.static(groups)
            elif eff in CHASSIS_EFFECTS:
                series = elc_mod.recipe(eff, lights, _colors(c.get("colors") or []),
                                        duration_ms=int(c.get("duration_ms", 3000)),
                                        columns=self.cmap.get("columns"))
                self.chassis.play(series)
            else:
                raise ValueError(f"unknown chassis effect {eff!r}")
            bri = int(c.get("brightness", 100))
            self.chassis.dim(100 - bri, lights)
            self.errors.pop("chassis", None)
        except OSError as e:
            self.errors["chassis"] = str(e)
            self.drop("chassis")

    # ------------------------------------------------------------------ profiles
    def effective(self, section):
        """A config section with the active per-app profile's overrides on top."""
        base = dict(self.cfg.get(section, {}))
        over = (self.active_profile or {}).get(section) or {}
        base.update(over)
        return base

    def match_profile(self, wclass, title):
        for p in self.cfg.get("profiles", []) or []:
            pat = p.get("match")
            if not pat:
                continue
            try:
                if re.search(pat, wclass or "", re.I) or (p.get("title") and re.search(p["title"], title or "", re.I)):
                    return p
            except re.error:
                continue
        return None

    def on_focus(self, wclass, title):
        prof = self.match_profile(wclass, title)
        if prof is self.active_profile:
            return
        prev = self.active_profile
        self.active_profile = prof
        log.info("mothership: profile %s", prof.get("name", prof.get("match")) if prof else "off")
        with self.lock:
            self.apply_keyboard()
            self.apply_chassis()
        t = self.cfg.setdefault("thermal", {})
        try:
            if prof and (prof.get("thermal") or {}).get("mode") and self.thermal.available():
                if not prev or not (prev.get("thermal") or {}).get("mode"):
                    self.profile_restore = {"mode": self.thermal.mode(), "auto": t.get("auto", True)}
                t["auto"] = False
                if prof["thermal"]["mode"] == "gmode" and self.thermal.gmode_available():
                    self.thermal.set_gmode(True)
                else:
                    self.thermal.set_mode(prof["thermal"]["mode"])
            elif self.profile_restore and self.thermal.available():
                r, self.profile_restore = self.profile_restore, None
                if self.thermal.gmode_available() and self.thermal.gmode():
                    self.thermal.set_gmode(False)
                if r.get("mode"):
                    self.thermal.set_mode(r["mode"])
                t["auto"] = r.get("auto", True)
        except (OSError, ValueError) as e:
            self.errors["thermal"] = str(e)

    def start_focus_watch(self):
        """Hyprland's event socket: activewindow>>class,title on every focus change."""
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        if not sig:
            return
        path = os.path.join(rt, "hypr", sig, ".socket2.sock")

        def watch():
            import socket
            while not self.stopping.is_set():
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                        sock.connect(path)
                        buf = b""
                        while not self.stopping.is_set():
                            data = sock.recv(4096)
                            if not data:
                                break
                            buf += data
                            *lines, buf = buf.split(b"\n")
                            for line in lines:
                                if line.startswith(b"activewindow>>"):
                                    wclass, _, title = line[14:].decode("utf-8", "replace").partition(",")
                                    if self.cfg.get("profiles"):
                                        self.on_focus(wclass, title)
                except OSError:
                    pass
                self.stopping.wait(5)

        threading.Thread(target=watch, daemon=True).start()

    def apply_lighting(self):
        with self.lock:
            self.open_devices()
            self.apply_keyboard()
            self.apply_chassis()

    # Every Thermal_Control call (mode or boost) makes the x17 R2 BIOS rewrite its stored settings
    # in flash, and every mode change zeroes the fan boosts. So the automatic rules switch modes
    # at most once a minute, round boost to 10 % steps, write it only when it really changes
    # (at most every 20 s, unless the fans need to ramp up by 30 % or more), and re-apply it
    # after a mode change. Commands from the person are never delayed.
    MODE_MIN_S, BOOST_MIN_S, BOOST_STEP, BOOST_URGENT = 60.0, 20.0, 10, 30

    def apply_power_limit(self, mode=None):
        """The BIOS resets the CPU power limits on every thermal mode change: put the person's back."""
        limits = self.cfg.get("thermal", {}).get("power_limits") or {}
        mode = mode or self.thermal.mode()
        watts = limits.get(mode, limits.get("all"))
        if watts:
            try:
                self.thermal.set_power_limit(int(watts))
                self.errors.pop("power_limit", None)
            except (OSError, ValueError) as e:
                self.errors["power_limit"] = str(e)

    def apply_thermal_settings(self):
        t = self.cfg.get("thermal", {})
        if t.get("tcc_offset") is not None and self.thermal.tcc_offset() is not None and not t.get("tcc_locked"):
            try:
                if self.thermal.tcc_offset() != int(t["tcc_offset"]):
                    self.thermal.set_tcc_offset(int(t["tcc_offset"]))
                self.errors.pop("tcc", None)
            except th_mod.TccLocked:
                t["tcc_locked"] = True
                t.pop("tcc_offset", None)
            except (OSError, ValueError) as e:
                self.errors["tcc"] = str(e)
        if self.thermal.available():
            self.apply_power_limit()

    def check_adapter(self, now):
        if now - getattr(self, "adapter_checked", -1e9) < 60:
            return
        self.adapter_checked = now
        status = self.thermal.adapter_status()
        bad = status not in (None, "ok")
        if bad and not getattr(self, "adapter_warned", False):
            msg = {"undersized": "The power adapter is too small for this laptop: it can't run at full power "
                                 "and may drain the battery under load.",
                   "unsupported": "The power adapter isn't recognised: charging and performance may be limited."
                   }.get(status, f"The power adapter reports a problem ({status}).")
            if shutil.which("notify-send"):
                subprocess.run(["notify-send", "-a", "mothership", "Power adapter", msg], timeout=5, check=False)
            log.warning("mothership: adapter: %s", status)
        self.adapter_warned = bad

    def thermal_tick(self, now):
        t = self.cfg.get("thermal", {})
        try:
            self.check_adapter(now)
        except (OSError, subprocess.SubprocessError):
            pass
        if not t.get("auto", True) or not self.thermal.available():
            return
        try:
            snap = self.thermal.status()
            want = self.auto.decide(snap, now)
            scale = int(t.get("boost_scale", th_mod.DEFAULTS["boost_scale"]))
            last = self.applied_thermal
            mode_changed = False
            if want.get("mode") and want["mode"] != snap.get("mode"):
                if now - last.get("mode_at", -1e9) >= self.MODE_MIN_S:
                    self.thermal.set_mode(want["mode"])
                    last["mode"], last["mode_at"], mode_changed = want["mode"], now, True
                    self.apply_power_limit(want["mode"])
            pct = want.get("boost_pct")
            if pct is not None:
                pct = min(100, int(round(pct / self.BOOST_STEP)) * self.BOOST_STEP)
                prev = last.get("boost_pct")
                due = now - last.get("boost_at", -1e9) >= self.BOOST_MIN_S
                urgent = prev is not None and pct - prev >= self.BOOST_URGENT
                if mode_changed or prev is None or (pct != prev and (due or urgent)):
                    self.thermal.set_boost(pct, scale=scale)
                    last["boost_pct"], last["boost_at"] = pct, now
            self.applied_thermal = last
            self.errors.pop("thermal", None)
        except (OSError, ValueError) as e:
            self.errors["thermal"] = str(e)

    # ------------------------------------------------------------------ commands
    def save(self):
        cfgmod.save(self.cfg)

    def status(self):
        st = {"devices": self.machine.summary(), "config": {k: v for k, v in self.cfg.items() if not k.startswith("_")},
              "errors": dict(self.errors)}
        with self.lock:
            if self.kb is not None:
                # While the fire service streams frames, a status read would interleave with them
                # (garbled replies); report the last good read instead.
                fire_on = os.path.exists(os.path.join(self.run_dir, "fire-active"))
                if fire_on and getattr(self, "kb_status", None):
                    st["keyboard"] = dict(self.kb_status)
                else:
                    try:
                        self.kb_status = self.kb.status()
                        st["keyboard"] = dict(self.kb_status)
                    except OSError as e:
                        st["keyboard"] = {"error": str(e)}
            if self.chassis is not None:
                st["chassis"] = dict(getattr(self, "chassis_info", {}), zones=sorted(self.cmap["zones"]) if self.cmap else [])
            if self.kb is not None:
                st.setdefault("keyboard", {})["unlit"] = sorted(models.unlit_keys(self.machine.keyboard_pid or 0))
        try:
            from . import graphics
            st["graphics"] = graphics.mode()
        except OSError:
            pass
        if self.thermal.available():
            try:
                st["thermal"] = self.thermal.status()
                if self.cfg.get("thermal", {}).get("tcc_locked"):
                    st["thermal"]["tcc_locked"] = True
            except OSError as e:
                st["thermal"] = {"error": str(e)}
        return st

    def handle(self, cmd, args):
        args = args or {}
        section, _, verb = cmd.partition(".")
        if cmd == "status":
            return self.status()
        if cmd == "devices":
            return self.machine.summary()
        if cmd == "graphics.change":
            from . import graphics
            graphics.reboot_to_firmware_setup(confirm=args.get("confirm") is True)
            return "restarting"
        if cmd == "reapply":
            self.apply_lighting()
            return "ok"
        if cmd == "profiles.get":
            return {"profiles": self.cfg.get("profiles", []), "active": self.active_profile}
        if cmd == "profiles.set":
            profs = args.get("profiles")
            if not isinstance(profs, list) or not all(isinstance(p, dict) and p.get("match") for p in profs):
                raise ValueError("profiles must be a list of objects with a 'match' regex")
            for p in profs:
                re.compile(p["match"])
            self.cfg["profiles"] = profs
            self.save()
            return {"profiles": profs}
        if cmd == "config.get":
            return {k: v for k, v in self.cfg.items() if not k.startswith("_")}
        if section == "keyboard":
            return self._keyboard_cmd(verb, args)
        if section == "chassis":
            return self._chassis_cmd(verb, args)
        if section == "power":
            return self._power_cmd(verb, args)
        if section == "thermal":
            return self._thermal_cmd(verb, args)
        if section == "macro":
            return self._macro_cmd(verb, args)
        raise ValueError(f"unknown command {cmd!r}")

    def _keyboard_cmd(self, verb, a):
        k = self.cfg["keyboard"]
        if verb == "effect":
            name = a["name"]
            if name != "fire" and name not in KB_FIRMWARE_EFFECTS and name not in ("perkey", "off"):
                raise ValueError(f"unknown keyboard effect {name!r}")
            if name in kb_mod.EFFECTS:      # validate before saving
                kb_mod.effect_packet(name, _colors(a.get("colors") or k.get("colors") or ["ffffff"]),
                                     int(a.get("speed", k.get("speed", 1))), a.get("direction", k.get("direction", "right")),
                                     a.get("on", "static"))
            k.update({"effect": name, "on": a.get("on", "static")})
            for key in ("colors", "speed", "direction"):
                if key in a:
                    k[key] = a[key]
        elif verb == "brightness":
            kb_mod.brightness_packet(a["value"])
            k["brightness"] = int(a["value"])
        elif verb == "keys":
            for led, col in (a.get("keys") or {}).items():
                kb_mod.parse_color(col)
            k.setdefault("keys", {}).update({str(led): col for led, col in a["keys"].items()})
            k["effect"] = "perkey"
        elif verb == "reactive":
            k.update({"effect": "static", "colors": [a["color"]], "on": a.get("on", "press")})
        else:
            raise ValueError(f"unknown keyboard command {verb!r}")
        self.save()
        with self.lock:
            self.open_devices()
            self.apply_keyboard()
        return {"keyboard": k, "error": self.errors.get("keyboard")}

    def _chassis_cmd(self, verb, a):
        c = self.cfg["chassis"]
        if verb == "effect":
            if a["name"] not in CHASSIS_EFFECTS:
                raise ValueError(f"unknown chassis effect {a['name']!r}; one of {', '.join(CHASSIS_EFFECTS)}")
            c["effect"] = a["name"]
            if "colors" in a:
                _colors(a["colors"])
                c["colors"] = a["colors"]
            if "duration_ms" in a:
                c["duration_ms"] = int(a["duration_ms"])
            if a["name"] == "static" and "colors" in a:
                c["zones"] = {}
        elif verb == "color":
            zone, col = a.get("zone", "all"), a["color"]
            kb_mod.parse_color(col)
            if self.cmap is not None:
                models.zone_leds(self.cmap, zone)
            zones = c.get("zones") or {}
            if zone == "all":
                zones = {}
                c["colors"] = [col]
            else:
                zones[zone] = col
            c.update({"effect": "static", "zones": zones})
        elif verb == "brightness":
            if not 0 <= int(a["value"]) <= 100:
                raise ValueError("brightness must be 0-100")
            c["brightness"] = int(a["value"])
        else:
            raise ValueError(f"unknown chassis command {verb!r}")
        self.save()
        with self.lock:
            self.open_devices()
            self.apply_chassis()
        return {"chassis": c, "error": self.errors.get("chassis")}

    def _power_cmd(self, verb, a):
        if verb == "show":
            return {"states": list(elc_mod.POWER_STATES), "saved": self.cfg.get("power_button", {})}
        if verb != "set":
            raise ValueError(f"unknown power command {verb!r}")
        if a.get("write_flash") is not True:
            raise PermissionError("power-button colours are saved in the lighting controller's flash; "
                                  "confirm with write_flash (CLI: --write-flash)")
        if self.chassis is None or self.cmap is None or not self.cmap.get("power_states"):
            raise RuntimeError("no supported lighting controller with power-state animations")
        rgb = kb_mod.parse_color(a["color"])
        states = list(elc_mod.POWER_STATES) if a.get("state", "all") == "all" else [a["state"]]
        leds = self.cmap["zones"]["power"]
        with self.lock:
            for st in states:
                self.chassis.save_power_state(st, power_recipe(st, rgb, leds), write_flash=True)
            self.apply_chassis()
        self.cfg.setdefault("power_button", {}).update({st: a["color"] for st in states})
        self.save()
        return {"saved": states}

    def _macro_cmd(self, verb, a):
        from . import macros
        if verb == "keys":
            return {"keys": list(macros.MACRO_KEYS), "saved": self.cfg.get("macros", {})}
        if a.get("write_flash") is not True:
            raise PermissionError("macros are stored in the keyboard's flash; confirm with write_flash (CLI: --write-flash)")
        if self.kb is None:
            raise RuntimeError("no supported keyboard")
        with self.lock:
            if verb == "set":
                r = macros.store(self.kb, a["key"], a["keys"], write_flash=True)
                self.cfg.setdefault("macros", {})[a["key"].upper()] = a["keys"]
            elif verb == "clear":
                r = macros.clear(self.kb, a["key"], write_flash=True)
                self.cfg.setdefault("macros", {}).pop(a["key"].upper(), None)
            else:
                raise ValueError(f"unknown macro command {verb!r}")
        self.save()
        return r

    def _thermal_cmd(self, verb, a):
        t = self.cfg.setdefault("thermal", {})
        if not self.thermal.available():
            raise RuntimeError("no Alienware thermal interface (alienware-wmi platform profile / hwmon)")
        if verb == "status":
            return self.thermal.status()
        if verb == "mode":
            self.thermal.set_mode(a["name"])
            t["auto"] = False
        elif verb == "tcc":
            v = int(a["value"])
            try:
                self.thermal.set_tcc_offset(v)
            except th_mod.TccLocked:
                t["tcc_locked"] = True
                t.pop("tcc_offset", None)
                self.save()
                raise
            t["tcc_offset"] = v
        elif verb == "power_limit":
            mode = a.get("mode") or "all"
            limits = t.setdefault("power_limits", {})
            if a.get("value") in (None, "off"):
                limits.pop(mode, None)
            else:
                w = int(a["value"])
                if not th_mod.POWER_MIN_W <= w <= th_mod.POWER_MAX_W:
                    raise ValueError(f"power limit must be {th_mod.POWER_MIN_W}-{th_mod.POWER_MAX_W} W")
                limits[mode] = w
            self.apply_power_limit()
        elif verb == "boost":
            pct = a.get("value")
            self.thermal.set_boost(None if pct in (None, "off") else int(pct), a.get("fan"),
                                   scale=int(t.get("boost_scale", th_mod.DEFAULTS["boost_scale"])))
            t["auto"] = False
        elif verb == "auto":
            t["auto"] = bool(a.get("on", True))
            self.auto = th_mod.Auto(t)
        elif verb == "gmode" and self.thermal.gmode_available():
            # Real G-Mode (thermal mode 0xAB) through the extended driver's gmode file.
            on = a.get("on", "toggle")
            if on == "toggle":
                on = not self.thermal.gmode()
            self.thermal.set_gmode(bool(on))
            if on:
                t["auto"] = False
            t["gmode"] = bool(on)
        elif verb == "gmode":
            on = a.get("on", "toggle")
            cur = self.thermal.mode()
            hot = t.get("hot_profile", th_mod.DEFAULTS["hot_profile"])
            if on == "toggle":
                on = cur != hot
            if on:
                t["gmode_prev"] = cur if cur != hot else t.get("gmode_prev", "balanced")
                self.thermal.set_mode(hot)
                t["auto"] = False
            else:
                self.thermal.set_mode(t.get("gmode_prev", "balanced"))
            t["gmode"] = bool(on)
        else:
            raise ValueError(f"unknown thermal command {verb!r}")
        if verb in ("mode", "gmode"):
            self.apply_power_limit()
        self.save()
        return self.thermal.status()

    # ------------------------------------------------------------------ main loop
    def start_mute_watch(self):
        """Mirror PipeWire mute state into RUN_DIR flags for the fire service's indicators."""
        if not shutil.which("pactl"):
            return

        def check():
            for name, args in (("mute", ["get-sink-mute", "@DEFAULT_SINK@"]),
                               ("micmute", ["get-source-mute", "@DEFAULT_SOURCE@"])):
                try:
                    out = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=3).stdout
                except (OSError, subprocess.TimeoutExpired):
                    continue
                path = os.path.join(self.run_dir, name)
                if "yes" in out:
                    self.write_run(name, "1")
                elif os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

        def watch():
            backoff = 2
            while not self.stopping.is_set():
                check()
                try:
                    p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True)
                except OSError:
                    return
                started = time.monotonic()
                for line in p.stdout:
                    if self.stopping.is_set():
                        break
                    if "'change' on sink" in line or "'change' on source" in line or "on server" in line:
                        check()
                p.kill()
                p.wait()
                # PipeWire not reachable (yet): retry with backoff up to 5 minutes.
                backoff = 2 if time.monotonic() - started > 60 else min(backoff * 2, 300)
                self.stopping.wait(backoff)

        threading.Thread(target=watch, daemon=True).start()

    def run(self, socket_path=None):
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        for w in self.cfg.get("_warnings", []):
            log.warning("config: %s", w)
        self.apply_lighting()
        self.apply_thermal_settings()
        self.server = ipc.Server(socket_path or ipc.socket_path(), self.handle)
        self.server.start()
        self.start_mute_watch()
        self.start_focus_watch()
        log.info("mothership: keyboard=%s chassis=%s thermal=%s", self.machine.keyboard_path,
                 self.machine.chassis_path, self.thermal.available())
        offset = time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()
        try:
            while not self.stopping.wait(TICK_S):
                now = time.monotonic()
                o = time.clock_gettime(time.CLOCK_BOOTTIME) - now
                if o - offset > RESUME_JUMP_S:          # time passed while suspended
                    log.info("mothership: resumed, re-applying lighting")
                    time.sleep(2)                        # let the USB devices come back
                    self.redetect()
                    self.apply_lighting()
                offset = o
                if now - self.last_redetect > REDETECT_S:
                    self.last_redetect = now
                    if (self.kb is None and self.machine.keyboard_path is None) or self.chassis is None or self.kb is None:
                        self.redetect()
                if now - self.last_thermal > float(self.cfg.get("thermal", {}).get("interval", 3)):
                    self.last_thermal = now
                    self.thermal_tick(now)
        finally:
            self.server.stop()

    def stop(self):
        self.stopping.set()


def main():
    import signal
    d = Daemon()
    signal.signal(signal.SIGTERM, lambda *_: d.stop())
    signal.signal(signal.SIGINT, lambda *_: d.stop())
    d.run()
