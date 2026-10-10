"""Per-key RGB keyboards on Alienware laptops ("API v5": Darfon/ITE controllers).

Transport: 64-byte HID feature reports with report id 0xcc on the vendor lighting
interface (usage page 0xff89). Byte 1 is the command. Reads are a SetFeature of the
request followed by a GetFeature into the same buffer, which works on a write-only fd,
so the device is never opened for reading (its input reports can carry keystrokes).

Everything here is volatile unless a function says otherwise: the controller forgets it
on power loss and the daemon re-applies it after resume. Commands that write the
controller's flash are only built by functions that take write_flash=True.
"""
import time

LEN, RID = 64, 0xCC

# 0x80 mode byte per firmware effect, its flag byte [9], and the (speed [3], duration [16])
# step pairs for the three speed levels: the parameter values that reproduce the firmware's
# preset looks (any 0-255 values are accepted by the keyboard).
EFFECTS = {
    "static":      {"mode": 1,  "flag": 0, "steps": [(1, 1), (2, 1), (3, 1)]},
    "breathing":   {"mode": 2,  "flag": 0, "steps": [(1, 2), (7, 5), (9, 6)]},
    "wave":        {"mode": 3,  "flag": 1, "steps": [(2, 2), (5, 5), (9, 6)]},
    "scanner":     {"mode": 10, "flag": 0, "steps": [(4, 5), (7, 6), (15, 7)]},
    "spectrum":    {"mode": 14, "flag": 1, "steps": [(2, 4), (6, 1), (7, 2)]},
    "aurora":      {"mode": 3,  "flag": 1, "steps": [(3, 0), (7, 0), (14, 0)]},
    "gradient":    {"mode": 3,  "flag": 1, "steps": [(0, 0), (0, 0), (0, 0)]},
}
# Aurora's fixed parameter block, bytes [10..21].
AURORA_BLOCK = bytes([0x00, 0xEE, 0xAA, 0x28, 0x00, 0xDC, 0x00, 0x03, 0xFF, 0x00, 0x05, 0xDD])
DIRECTIONS = {"left": 1, "right": 2, "up": 3, "down": 4, "bounce": 5, "bounce-v": 6}
PLAY = {"static": 1, "press": 2, "release": 3}
MODE_PERKEY, MODE_EFFECT = 0x8C, 0x80
# Effect slots AWCC clears before entering per-key mode.
SLOTS = (0x01, 0x02, 0x05, 0x08, 0x09, 0x0E)
# Commands that persist in the controller; never sent without write_flash=True.
PERSIST_SAVE_LAST, PERSIST_BOOT = (0x84, 0x03, 0x00), (0x85, 0xAE)


def pkt(*b):
    buf = bytearray(LEN)
    buf[0] = RID
    buf[1 : 1 + len(b)] = bytes(b)
    return buf


def _rgb(c):
    if isinstance(c, str):
        c = parse_color(c)
    if len(c) != 3 or not all(isinstance(v, int) and 0 <= v <= 255 for v in c):
        raise ValueError(f"bad color {c!r}")
    return tuple(c)


def parse_color(s):
    """'ff4000' / '#FF4000' -> (255, 64, 0)."""
    t = s.strip().lstrip("#")
    if len(t) != 6:
        raise ValueError(f"bad color {s!r}: use RRGGBB")
    try:
        return tuple(int(t[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise ValueError(f"bad color {s!r}: use RRGGBB") from None


def _pct(p):
    if not isinstance(p, (int, float)) or not 0 <= p <= 100:
        raise ValueError(f"brightness must be 0-100, got {p!r}")
    return p


def effect_packet(name, colors=(), speed=1, direction="right", play="static", loop=True):
    """The 0x80 packet that starts a firmware effect on the whole keyboard."""
    if name not in EFFECTS:
        raise ValueError(f"unknown effect {name!r}; one of {', '.join(EFFECTS)}")
    if speed not in (0, 1, 2):
        raise ValueError("speed must be 0, 1 or 2")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {', '.join(DIRECTIONS)}")
    if play not in PLAY:
        raise ValueError(f"play must be one of {', '.join(PLAY)}")
    e = EFFECTS[name]
    cols = [_rgb(c) for c in colors] or [(255, 255, 255)]
    c1, c2 = cols[0], cols[1] if len(cols) > 1 else cols[0]
    b = pkt(0x80, e["mode"])
    step, dur = e["steps"][speed]
    b[3] = step
    b[6], b[7], b[8], b[9] = DIRECTIONS[direction], PLAY[play], 1 if loop else 0, e["flag"]
    b[10:13], b[13:16] = bytes(c1), bytes(c2)
    b[16] = dur
    if name == "aurora":
        b[10:22] = AURORA_BLOCK
    elif name == "gradient":
        b[17] = 2
    return b


def brightness_packet(pct):
    return pkt(0x8B, 0x01, round(_pct(pct) * 255 / 100))


def level_packet(pct):
    """Per-LED brightness level for every key (AWCC sends it below 100 %)."""
    return pkt(0x83, 0x38, 0x9C, round(_pct(pct) * 254 / 100))


def stop_packet():
    return pkt(0x8C, 0x10)


def perkey_packets(colors, enter=True, loop=True):
    """colors: {led id: (r, g, b)}. enter=True first switches the board into per-key mode
    (stop, clear the effect slots, map every coloured LED to slot 1, configure slot 1)."""
    cols = {}
    for led, c in colors.items():
        if not isinstance(led, int) or not 0 <= led < 140:
            raise ValueError(f"bad LED id {led!r}")
        cols[led] = _rgb(c)
    out = []
    if enter:
        out.append(stop_packet())
        out += [pkt(0x8C, 0x01, s) for s in SLOTS]
        emap = bytearray(140)
        for led in cols:
            emap[led] = 1
        for i, cmd in enumerate((0x05, 0x06, 0x07)):
            chunk = emap[60 * i : 60 * i + 60]
            b = pkt(0x8C, cmd, 0x00)
            b[4 : 4 + len(chunk)] = chunk
            out.append(b)
        out.append(pkt(0x8C, 0x01, 0x01, 0x01, 0x00, 0x00, 0x01, 0x01, 1 if loop else 0, 0x00,
                       0, 0, 0, 0, 0, 0, 0x01))
    recs = sorted(cols.items())
    for i in range(0, len(recs), 15):
        b = pkt(0x8C, 0x02, 0x00)
        for j, (led, rgb) in enumerate(recs[i : i + 15]):
            b[4 + 4 * j : 8 + 4 * j] = bytes([led + 1, *rgb])
        out.append(b)
    out.append(pkt(0x8C, 0x13))
    return out


def parse_status(r91=None, r93=None, r94=None):
    st = {}
    if r91 is not None:
        fw = bytes(r91[1:5])                     # four ASCII digits, e.g. "3326" (= USB bcdDevice)
        st["firmware"] = fw.decode("ascii", "replace") if all(32 <= c < 127 for c in fw) else fw.hex()
    if r93 is not None:
        fam = {0x11: "ansi", 0x21: "ansi", 0x01: "iso", 0x10: "jis"}
        st["layout"] = fam.get(r93[3], f"0x{r93[3]:02x}")
        st["layout_id"] = r93[4]
        st["chassis"] = "light" if r93[5] == 0xFF else "dark"
    if r94 is not None:
        st["mode"] = {MODE_PERKEY: "perkey", MODE_EFFECT: "effect"}.get(r94[2], f"0x{r94[2]:02x}")
        st["bank"] = r94[19]
        st["brightness"] = round(r94[21] * 100 / 255)
        st["color"] = "%02x%02x%02x" % (r94[24], r94[23], r94[22])   # stored as B, G, R
    return st


class Keyboard:
    def __init__(self, hid, keys=None):
        self.hid = hid
        self.keys = keys or {}       # led id -> geometry; used by static()/off()
        self.perkey = False

    # -- transport
    def send(self, buf):
        self.hid.set_feature(buf)

    def query(self, *req):
        b = pkt(*req)
        self.hid.set_feature(b)
        return self.hid.get_feature(pkt())

    def ready(self, tries=10):
        """Wait while the controller reports busy (0x93 reply byte 2 == 0x80)."""
        for _ in range(tries):
            if self.query(0x93)[2] != 0x80:
                return
            time.sleep(0.2)
        raise OSError("keyboard busy")

    # -- reads
    def status(self):
        return parse_status(self.query(0x91), self.query(0x93), self.query(0x94))

    # -- lighting
    def effect(self, name, colors=(), speed=1, direction="right", play="static", brightness=100):
        pk = effect_packet(name, colors, speed, direction, play)
        self.ready()
        self.send(pk)
        self.send(brightness_packet(brightness))
        self.perkey = False

    def reactive(self, color, on="press", speed=1, brightness=100):
        """Firmware key-press lighting for the whole board (whether a model honours it is
        checked by the caller from status/observation)."""
        self.effect("static", [color], speed=speed, play=on, brightness=brightness)

    def brightness(self, pct):
        self.send(brightness_packet(pct))
        if self.perkey and pct < 100:
            self.send(level_packet(pct))

    def set_keys(self, colors, brightness=100, enter=None):
        """Per-key colours; enters per-key mode the first time (or when enter=True)."""
        if enter is None:
            enter = not self.perkey
        self.ready()
        for b in perkey_packets(colors, enter=enter):
            self.send(b)
        self.send(brightness_packet(brightness))
        if brightness < 100:
            self.send(level_packet(brightness))
        self.perkey = True

    def static(self, color, brightness=100):
        rgb = _rgb(color)
        self.set_keys({led: rgb for led in self.keys}, brightness)

    def off(self):
        self.send(brightness_packet(0))

    # -- persistent (flash)
    def save_as_power_on(self, write_flash=False):
        """Store the current effect as the one the keyboard starts with. Writes flash."""
        if write_flash is not True:
            raise PermissionError("writes the keyboard's flash; pass write_flash=True")
        self.send(pkt(*PERSIST_SAVE_LAST))
