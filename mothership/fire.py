"""Fire on the per-key keyboard; the keys you press flare up and radiate into it.

Run only by the sandboxed system service mothership-fire.service (DynamicUser, groups
input + mothership, no network, no home, read-only filesystem except /run/mothership):
it reads keystrokes, so nothing else in mothership does. It never logs or stores which
key was pressed. Port of kbd-fire.

Coordination with the user daemon happens through RUN_DIR (/run/mothership, or
$MOTHERSHIP_RUN):

- `effect`: the daemon writes it. The service renders only while its first word is
  `fire`. Optional words after it: `brightness=0-100`, and `chassis` (lid alien head
  green, the rest red, as kbd-fire did) or `chassis=RRGGBB,RRGGBB` (head, rest). Without
  `chassis` the service leaves the AW-ELC alone. Anything else: the service closes the
  input devices, sends nothing and checks again once a second.
- `fire-active`: written by the service while it renders and removed once it has
  stopped sending frames, so the daemon can wait for it to vanish (briefly) before
  applying another keyboard effect.
- `unlocked`: key flares only while its mtime is under 12 s old. gage.lock removes it
  when a lock is requested and touches it every 5 s while unlocked, so the password
  never lights up and a dead refresher fails closed.
- `mute`, `micmute`: present while muted (kept by the daemon); those keys turn white.
  Caps Lock is white while on (sysfs LEDs).

Frames are volatile per-key colours through keyboard.Keyboard.set_keys(); the board is
switched into per-key mode on the first frame, after a resume and after a pause.
"""
import glob
import math
import os
import random
import select
import signal
import struct
import sys
import time

from . import models
from .layout import CAPS_LED, COLS, KEYCODES, KEYS, MICMUTE_LED, MUTE_LED, ROWS, WIDTH

RUN_DIR = os.environ.get("MOTHERSHIP_RUN", "/run/mothership")
FPS = 15
UNLOCKED_MAX_AGE = 12.0
IDLE_POLL = 1.0
INPUT_RESCAN = 5.0
WHITE = (255, 255, 255)
EMBER_HEAT = 0.45
HEAD_COLOR, REST_COLOR = (0, 255, 0), (255, 0, 0)
ACTIVE_MARK = "fire-active"

# Black-body-ish ramp; the floor keeps cold keys a dim ember instead of dark.
RAMP = [(0.00, (40, 0, 0)), (0.30, (150, 6, 0)), (0.55, (255, 40, 0)),
        (0.75, (255, 110, 0)), (0.90, (255, 190, 20)), (1.00, (255, 235, 90)), (1.30, (255, 255, 200))]


def log(msg):
    print(f"mothership-fire: {msg}", flush=True)


def palette(h):
    """Heat (0..1.3) -> (r, g, b) ints."""
    h = max(0.0, min(RAMP[-1][0], h))
    for (h0, c0), (h1, c1) in zip(RAMP, RAMP[1:]):
        if h <= h1:
            t = (h - h0) / (h1 - h0)
            return tuple(int(round(a + (b - a) * t)) for a, b in zip(c0, c1))
    return RAMP[-1][1]


def key_cols(led, keys=KEYS):
    """LED -> (row, range of heat columns it covers)."""
    r, x, w = keys[led]
    c0 = int(x / WIDTH * COLS)
    c1 = max(c0, int((x + w - 1) / WIDTH * COLS))
    return r, range(c0, min(c1, COLS - 1) + 1)


class FireSim:
    """The heat simulation, free of devices: step(dt, pressed_leds) -> {led: (r, g, b)}."""

    def __init__(self, keys=KEYS, rng=None):
        self.keys = keys
        self.rng = rng or random.Random()
        self.heat = [[0.0] * COLS for _ in range(ROWS)]
        self.gusts = [self.rng.random() * 6.28 for _ in range(COLS)]
        self.sparks = []            # [led, energy]: flares from pressed keys
        self.t = 0.0
        self.spans = {led: key_cols(led, keys) for led in keys}

    def step(self, dt=1 / FPS, pressed=()):
        rnd = self.rng.uniform
        frames = max(0.0, min(dt, 0.5)) * FPS      # the constants below are tuned per 15 fps frame
        self.t += dt
        for led in pressed:
            if led in self.spans:
                self.sparks.append([led, 1.0])
        new = [[0.0] * COLS for _ in range(ROWS)]
        fuel = [0.62 + 0.25 * (0.5 + 0.5 * math.sin(self.t * 1.3 + self.gusts[c])) + rnd(-0.12, 0.12)
                for c in range(COLS)]
        for r in range(ROWS - 1, -1, -1):   # heat rises from the row below, spreads and cools
            src = fuel if r == ROWS - 1 else self.heat[r + 1]
            for c in range(COLS):
                below = src[c - 1] + 2 * src[c] + src[(c + 1) % COLS]
                new[r][c] = below / 4 * rnd(0.72, 0.92) + rnd(-0.04, 0.06)
        for s in self.sparks:               # flares: a hot core that spreads sideways and up
            r, cols = self.spans[s[0]]
            e = s[1]
            for c in range(cols.start - 2, cols.stop + 2):
                if 0 <= c < COLS:
                    d = max(0, cols.start - c, c - (cols.stop - 1))
                    new[r][c] += e * (1.0, 0.55, 0.22)[d]
                    if r > 0:
                        new[r - 1][c] += e * (0.45, 0.25, 0.1)[d]
            s[1] *= 0.6 ** frames
        self.sparks = [s for s in self.sparks if s[1] > 0.08]
        keep = 0.35 ** frames               # temporal smoothing so 15 fps reads as flame
        for r in range(ROWS):
            for c in range(COLS):
                self.heat[r][c] = self.heat[r][c] * keep + new[r][c] * (1 - keep)
        return self.colors()

    def key_heat(self, led):
        r, span = self.spans[led]
        return sum(self.heat[r][c] for c in span) / len(span)

    def colors(self):
        return {led: palette(self.key_heat(led)) for led in self.keys}

    def embers(self):
        return {led: palette(EMBER_HEAT) for led in self.keys}


# ------------------------------------------------------------------ run-dir flags
def flag_fresh(path, now, max_age=UNLOCKED_MAX_AGE):
    try:
        return now - os.stat(path).st_mtime < max_age
    except OSError:
        return False


def _hex(s):
    t = s.strip().lstrip("#")
    if len(t) != 6:
        raise ValueError(s)
    return tuple(int(t[i : i + 2], 16) for i in (0, 2, 4))


def parse_effect(text):
    """Contents of RUN_DIR/effect -> None (not fire) or {"brightness": int, "chassis": (head, rest) | None}."""
    words = (text or "").split()
    if not words or words[0] != "fire":
        return None
    out = {"brightness": 100, "chassis": None}
    for w in words[1:]:
        key, _, val = w.partition("=")
        try:
            if key == "brightness":
                out["brightness"] = max(0, min(100, int(val)))
            elif key == "chassis":
                out["chassis"] = tuple(_hex(v) for v in val.split(",", 1)) if val else (HEAD_COLOR, REST_COLOR)
                if len(out["chassis"]) == 1:
                    out["chassis"] = (out["chassis"][0], out["chassis"][0])
        except ValueError:
            pass                    # a malformed option is ignored, the fire still runs
    return out


def read_effect(path):
    try:
        with open(path) as f:
            return parse_effect(f.read(256))
    except OSError:
        return None


# ------------------------------------------------------------------ key input
EV_KEY, KEY_A, KEY_SPACE = 1, 30, 57
EVENT = struct.Struct("llHHi")      # struct input_event (64-bit)


class KeyInputs:
    """Event nodes that report letter keys. wait() returns the LEDs of keys pressed while
    accept() holds; events read while it doesn't are discarded unparsed."""

    def __init__(self, sys_root="/sys", dev_root="/dev/input"):
        self.sys_root, self.dev_root = sys_root, dev_root
        self.fds = []

    def open(self):
        self.close()
        for d in sorted(glob.glob(os.path.join(self.sys_root, "class/input/event*"))):
            try:
                with open(os.path.join(d, "device/capabilities/key")) as f:
                    words = f.read().split()
                bits = int("".join(w.rjust(16, "0") for w in words), 16)
                if bits >> KEY_A & 1 and bits >> KEY_SPACE & 1:
                    path = os.path.join(self.dev_root, os.path.basename(d))
                    self.fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC))
            except (OSError, ValueError):
                pass
        return bool(self.fds)

    def close(self):
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self.fds = []

    def wait(self, timeout, accept):
        if not self.fds:
            if timeout > 0:
                time.sleep(timeout)
            return []
        leds = []
        end = time.monotonic() + timeout
        while True:
            left = max(0.0, end - time.monotonic())
            ready = select.select(self.fds, [], [], left)[0]
            for fd in ready:
                try:
                    data = os.read(fd, EVENT.size * 64)
                except BlockingIOError:
                    continue
                except OSError:          # device went away (resume, unplug)
                    self.fds.remove(fd)
                    os.close(fd)
                    continue
                if not accept():
                    continue
                for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, typ, code, value = EVENT.unpack_from(data, i)
                    if typ == EV_KEY and value == 1 and code in KEYCODES:
                        leds.append(KEYCODES[code])
            if left <= 0 or not self.fds:
                return leds


# ------------------------------------------------------------------ service
class FireService:
    def __init__(self, open_keyboard, open_chassis=None, inputs=None, sim=None, run_dir=None,
                 sys_root="/sys", clock=time.time):
        self.open_keyboard = open_keyboard
        self.open_chassis = open_chassis
        self.inputs = inputs if inputs is not None else KeyInputs(sys_root)
        self.sim = sim or FireSim()
        self.run_dir = run_dir or os.environ.get("MOTHERSHIP_RUN", RUN_DIR)
        self.sys_root = sys_root
        self.clock = clock
        self.kb = None
        self.ch = None
        self.active = False
        self.enter = True
        self.chassis_done = None
        self.rescan = 0.0

    def path(self, name):
        return os.path.join(self.run_dir, name)

    def unlocked(self):
        return flag_fresh(self.path("unlocked"), self.clock())

    def caps_on(self):
        for b in glob.glob(os.path.join(self.sys_root, "class/leds/input*::capslock/brightness")):
            try:
                with open(b) as f:
                    if f.read().strip() != "0":
                        return True
            except OSError:
                pass
        return False

    def indicators(self, cols):
        if self.caps_on():
            cols[CAPS_LED] = WHITE
        for name, led in (("mute", MUTE_LED), ("micmute", MICMUTE_LED)):
            if os.path.exists(self.path(name)):
                cols[led] = WHITE
        return cols

    def _mark(self, on):
        try:
            if on:
                with open(self.path(ACTIVE_MARK), "w") as f:
                    f.write(f"{os.getpid()}\n")
            else:
                os.unlink(self.path(ACTIVE_MARK))
        except OSError:
            pass

    def _start(self):
        self.active, self.enter, self.chassis_done = True, True, None
        self.inputs.open()
        self.rescan = time.monotonic() + INPUT_RESCAN
        self._mark(True)

    def stop(self):
        """Stop rendering: close the input devices; the keyboard keeps its last frame."""
        self.inputs.close()
        self.active = False
        self.enter = True
        self.chassis_done = None
        self._mark(False)

    def resumed(self):
        """After a resume the firmware may have restarted its own effect."""
        self.enter = True
        self.chassis_done = None
        if self.active:
            self.inputs.open()

    def _chassis(self, colors):
        if colors == self.chassis_done:
            return
        self.chassis_done = colors
        if colors is None or self.open_chassis is None:
            return
        try:
            self.ch = self.ch or self.open_chassis()
            if self.ch is None:
                return
            head, rest = colors
            try:
                info = self.ch.info()
                cmap = models.chassis_map(info["platform"]) or models.generic_map(self.ch.led_count or 20)
            except (OSError, KeyError, IndexError):
                cmap = models.chassis_map("0x0306")
            head_zones = cmap["zones"].get("head", [])
            others = [z for z in models.zone_leds(cmap, "all") if z not in head_zones]
            groups = {}
            if head_zones:
                groups[head] = list(head_zones)
            if others:
                groups.setdefault(rest, []).extend(others)
            self.ch.static(groups)
        except (OSError, ValueError) as e:
            log(f"chassis: {e}")
            self.ch = None

    def tick(self, wait=0.0):
        """One frame: returns True if a frame was rendered, False when idle."""
        eff = read_effect(self.path("effect"))
        if eff is None:
            if self.active:
                self.stop()
            return False
        if self.kb is None:
            try:
                self.kb = self.open_keyboard()
            except OSError as e:
                log(f"keyboard: {e}")
            if self.kb is None:
                return False
            self.enter = True
        if not self.active:
            self._start()
        if not self.inputs.fds and time.monotonic() > self.rescan:
            self.inputs.open()
            self.rescan = time.monotonic() + INPUT_RESCAN
        self._chassis(eff["chassis"])
        leds = self.inputs.wait(wait, self.unlocked)
        if not self.unlocked():
            leds = []
        cols = self.indicators(self.sim.step(1 / FPS, leds))
        try:
            self.kb.set_keys(cols, brightness=eff["brightness"], enter=self.enter)
            self.enter = False
        except OSError as e:
            log(f"keyboard: {e}")
            self._drop_keyboard()
            return False
        return True

    def _drop_keyboard(self):
        try:
            self.kb.hid.close()
        except (OSError, AttributeError):
            pass
        self.kb = None
        self.enter = True

    def leave_embers(self):
        if self.active and self.kb is not None:
            try:
                self.kb.set_keys(self.indicators(self.sim.embers()), enter=self.enter)
            except OSError:
                pass

    def run(self):
        step = 1 / FPS
        last = (time.monotonic(), time.clock_gettime(time.CLOCK_BOOTTIME))
        next_frame = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                boot = time.clock_gettime(time.CLOCK_BOOTTIME)
                if (boot - last[1]) - (now - last[0]) > 2:
                    self.resumed()
                last = (now, boot)
                if self.tick(wait=max(0.0, next_frame - now)):
                    next_frame += step
                    if next_frame < time.monotonic():
                        next_frame = time.monotonic() + step
                else:
                    time.sleep(IDLE_POLL)
                    next_frame = time.monotonic()
        finally:
            self.leave_embers()
            self.stop()


def _sigterm(*_):
    raise SystemExit(0)


def main(argv=None):
    machine = models.detect()
    for _ in range(10):          # at boot the hidraw node can appear a little after us
        if machine.keyboard_path:
            break
        time.sleep(1)
        machine = models.detect()
    if not machine.keyboard_path:
        log("no Alienware per-key keyboard (0d62, report 0xcc); nothing to do")
        return 0

    def open_keyboard():
        return models.detect().open_keyboard(keys=KEYS)

    def open_chassis():
        return models.detect().open_chassis()

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)
    svc = FireService(open_keyboard, open_chassis)
    log(f"waiting for the fire effect in {svc.run_dir}/effect")
    try:
        svc.run()
    except SystemExit:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
