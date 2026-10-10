"""AW-ELC chassis lighting controllers (USB 187c:0550/0551, "API v4").

Lid logo, rear light loop, touchpad zones (on lit-touchpad models) and the power button. Commands are 33-byte
HID output reports (no report id, so 34 bytes with the leading 0 on hidraw), byte 0 = 0x03,
byte 1 = opcode. The controller has no named effects: an effect is an animation, a list of
series (a set of LEDs plus up to N actions: colour / pulse / morph with a duration and
tempo), uploaded between BEGIN and a finishing command. RUN_FROM_RAM plays it without
saving; COMMIT_TO_FLASH, DELETE, MAKE_DEFAULT and MAKE_STARTUP write flash and are only
reachable through functions that take write_flash=True. Opcode 0xFF (erase the whole flash)
is deliberately not implemented.
"""
import time

LEN = 33
OP_REPORT, OP_USER_ANIM, OP_POWER_ANIM = 0x20, 0x21, 0x22
OP_SERIES, OP_ACTION, OP_DIM, OP_COLOR = 0x23, 0x24, 0x26, 0x27
BEGIN, COMMIT_TO_FLASH, RUN_FROM_RAM, DELETE, RUN, MAKE_DEFAULT, MAKE_STARTUP = 1, 2, 3, 4, 5, 6, 7
PERSISTENT_SUBS = {COMMIT_TO_FLASH, DELETE, MAKE_DEFAULT, MAKE_STARTUP}
PREVIEW_ID = 0xFFFF
COLOR, PULSE, MORPH = 0, 1, 2
BUSY = 0x22

POWER_STATES = {"ac-sleep": 91, "ac-full": 92, "ac-charging": 93,
                "dc-sleep": 94, "dc-on": 95, "dc-low": 96}

RAINBOW = [(255, 0, 0), (255, 165, 0), (255, 255, 0), (0, 128, 0), (0, 191, 255), (0, 0, 255), (128, 0, 128)]


def payload(*b):
    if len(b) > LEN:
        raise ValueError("ELC packet longer than 33 bytes")
    buf = bytearray(LEN)
    buf[: len(b)] = bytes(b)
    return buf


def _u16(v):
    if not 0 <= v <= 0xFFFF:
        raise ValueError(f"value out of range: {v}")
    return v >> 8, v & 0xFF


def _leds(leds, count=None):
    leds = list(leds)
    for z in leds:
        if not isinstance(z, int) or not 0 <= z < 256 or (count is not None and z >= count):
            raise ValueError(f"zone {z!r} out of range" + (f" (controller has {count})" if count else ""))
    return leds


def report(sub, arg=None):
    return payload(0x03, OP_REPORT, sub) if arg is None else payload(0x03, OP_REPORT, sub, arg)


def anim_cmd(sub, anim_id, duration=0, write_flash=False, power=False):
    """0x21 (user) or 0x22 (power state) animation command."""
    if sub in PERSISTENT_SUBS and write_flash is not True:
        raise PermissionError("this animation command writes the controller's flash; pass write_flash=True")
    op = OP_POWER_ANIM if power else OP_USER_ANIM
    return payload(0x03, op, *_u16(sub), *_u16(anim_id), *_u16(duration))


def color_packets(rgb, leds, count=None):
    leds = _leds(leds, count)
    r, g, b = rgb
    return [payload(0x03, OP_COLOR, r, g, b, 0x00, len(leds[i : i + 26]), *leds[i : i + 26])
            for i in range(0, len(leds), 26)]


def dim_packets(dim_pct, leds, count=None):
    """dim_pct: 0 = full brightness, 100 = off."""
    if not 0 <= dim_pct <= 100:
        raise ValueError("dim must be 0-100")
    leds = _leds(leds, count)
    return [payload(0x03, OP_DIM, int(dim_pct), page, len(leds[i : i + 28]), *leds[i : i + 28])
            for page, i in enumerate(range(0, len(leds), 28))]


def series_packets(leds, loop=True, count=None):
    leds = _leds(leds, count)
    return [payload(0x03, OP_SERIES, 1 if loop else 0, page, len(leds[i : i + 28]), *leds[i : i + 28])
            for page, i in enumerate(range(0, len(leds), 28))]


def action_bytes(effect, duration_ms, tempo, rgb):
    if effect not in (COLOR, PULSE, MORPH):
        raise ValueError(f"bad action effect {effect!r}")
    return bytes([effect, *_u16(duration_ms), *_u16(tempo), *rgb])


def action_packets(actions):
    """actions: [(effect, duration_ms, tempo, (r, g, b))], three per packet."""
    out = []
    for i in range(0, len(actions), 3):
        b = payload(0x03, OP_ACTION)
        for j, a in enumerate(actions[i : i + 3]):
            b[2 + 8 * j : 10 + 8 * j] = action_bytes(*a)
        out.append(b)
    return out


def recipe(name, leds, colors=(), duration_ms=3000, tempo=100, columns=None):
    """Effect name -> list of (leds, actions). columns (list of LED lists, left to right)
    drive the travelling effects."""
    cols = [tuple(c) for c in colors] or [(0, 240, 240)]
    c1 = cols[0]
    leds = list(leds)
    if name == "static":
        return [(leds, [(COLOR, 1000, 250, c1)])]
    if name == "breathing":
        half = max(100, duration_ms // 2)
        return [(leds, [(MORPH, half, tempo, c1), (MORPH, half, tempo, (0, 0, 0))])]
    if name == "pulse":
        return [(leds, [(PULSE, duration_ms, tempo, c1)])]
    if name == "morph":
        seq = cols if len(cols) > 1 else [c1, (0, 0, 0)]
        step = max(100, duration_ms // len(seq))
        return [(leds, [(MORPH, step, tempo, c) for c in seq])]
    if name == "spectrum":
        step = max(100, duration_ms // len(RAINBOW))
        return [(leds, [(MORPH, step, tempo, c) for c in RAINBOW])]
    if name == "wave":
        groups = columns or [[z] for z in leds]
        step = max(100, duration_ms // len(RAINBOW))
        out = []
        for k, group in enumerate(groups):
            shift = k % len(RAINBOW)
            pal = RAINBOW[shift:] + RAINBOW[:shift]
            out.append((list(group), [(MORPH, step, tempo, c) for c in pal]))
        return out
    raise ValueError(f"unknown chassis effect {name!r}; one of static breathing pulse morph spectrum wave")


class Elc:
    def __init__(self, hid, led_count=None):
        self.hid = hid
        self.led_count = led_count

    # -- transport
    def send(self, p, wait=0.01):
        self.hid.write(b"\x00" + bytes(p))
        if wait:
            time.sleep(wait)

    def reply(self):
        return self.hid.get_input(bytearray(LEN + 1))

    def wait_ready(self, timeout=2.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.reply()[2] != BUSY:
                return
            time.sleep(0.02)

    def query(self, p):
        self.send(p)
        return self.reply()

    # -- reads
    def info(self):
        v = self.query(report(0))
        c = self.query(report(2))
        self.led_count = c[6] or self.led_count
        return {"firmware": f"{v[4]}.{v[5]}.{v[6]}", "platform": f"0x{c[4] << 8 | c[5]:04x}", "leds": c[6]}

    # -- volatile lighting
    def upload(self, series, anim_id=PREVIEW_ID, finish=RUN_FROM_RAM, power=False, write_flash=False):
        self.wait_ready()
        self.send(anim_cmd(BEGIN, anim_id, power=power))
        for leds, actions in series:
            for p in series_packets(leds, count=self.led_count):
                self.send(p)
            for p in action_packets(actions):
                self.send(p)
        self.send(anim_cmd(finish, anim_id, power=power, write_flash=write_flash))

    def play(self, series):
        """Run an animation from RAM (nothing is saved)."""
        self.upload(series)

    def static(self, groups):
        """groups: {(r, g, b): [zones]} shown at once, from RAM."""
        self.wait_ready()
        self.send(anim_cmd(BEGIN, PREVIEW_ID))
        for rgb, zones in groups.items():
            for p in color_packets(rgb, zones, self.led_count):
                self.send(p)
        self.send(anim_cmd(RUN_FROM_RAM, PREVIEW_ID))

    def dim(self, dim_pct, zones):
        for p in dim_packets(dim_pct, zones, self.led_count):
            self.send(p)

    def stop(self):
        self.send(anim_cmd(RUN, 0))

    # -- persistent (flash)
    def save_power_state(self, state, series, write_flash=False):
        """Store the animation the controller shows by itself in a power state."""
        if write_flash is not True:
            raise PermissionError("power-state animations are saved in the controller's flash; pass write_flash=True")
        if state not in POWER_STATES:
            raise ValueError(f"power state must be one of {', '.join(POWER_STATES)}")
        sid = POWER_STATES[state]
        self.wait_ready()
        self.send(anim_cmd(DELETE, sid, power=True, write_flash=True), wait=0.25)
        self.upload(series, anim_id=sid, finish=COMMIT_TO_FLASH, power=True, write_flash=True)
