"""Client-side approximations of the lighting effects (a port of the desktop UI's Effects.js),
so the terminal mirror shows what the machine is doing without asking the hardware.

Colours are (r, g, b) floats in 0..255 plus an intensity 0..1.
"""
import math

SPEED = [0.6, 1.0, 1.7]
KB_ANIMATED = ("breathing", "wave", "spectrum", "scanner", "aurora", "fire")
CH_ANIMATED = ("breathing", "pulse", "morph", "spectrum", "wave")
RAINBOW = [(255, 0, 0), (255, 165, 0), (255, 255, 0), (0, 128, 0), (0, 191, 255), (0, 0, 255), (128, 0, 128)]


def parse_hex(s, fallback=(255, 255, 255)):
    t = str(s or "").lstrip("#")
    if len(t) != 6:
        return fallback
    try:
        return (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))
    except ValueError:
        return fallback


def to_hex(rgb):
    return "".join(f"{max(0, min(255, round(v))):02x}" for v in rgb)


def hsv(h, s, v):
    h = h % 1.0
    i = int(h * 6)
    f = h * 6 - i
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]
    return (r * 255, g * 255, b * 255)


def hue_of(rgb):
    r, g, b = (c / 255 for c in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d == 0:
        return 0.0
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return (h / 6) % 1.0


def mix(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def frac(x):
    return x - math.floor(x)


def tri(x):
    f = frac(x)
    return f * 2 if f < 0.5 else 2 - f * 2


def _hash(a, b):
    return frac(math.sin(a * 127.1 + b * 311.7) * 43758.5453)


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def animated(kb):
    if not kb:
        return False
    return kb.get("on") in ("press", "release") or kb.get("effect") in KB_ANIMATED


def chassis_animated(ch):
    return bool(ch) and ch.get("effect") in CH_ANIMATED


def heat_color(h):
    """Fire's heat ramp: black, ember red, orange, yellow."""
    h = _clamp(h)
    if h < 0.35:
        return mix((0, 0, 0), (170, 12, 0), h / 0.35)
    if h < 0.7:
        return mix((170, 12, 0), (255, 90, 0), (h - 0.35) / 0.35)
    return mix((255, 90, 0), (255, 200, 40), (h - 0.7) / 0.3)


def _speed(kb):
    try:
        return SPEED[int(kb.get("speed", 1))]
    except (TypeError, ValueError, IndexError):
        return 1.0


def _bri(cfg):
    b = cfg.get("brightness", 100)
    try:
        return _clamp(float(b) / 100)
    except (TypeError, ValueError):
        return 1.0


def still_time(kb):
    """A moment that shows the effect well (for a single printed frame)."""
    eff = kb.get("effect")
    sp = _speed(kb)
    if eff == "breathing":
        return 2.0 / sp            # full brightness
    if eff == "scanner":
        return 1.3 / sp / 2        # band near the middle
    return 1.7


def chassis_still_time(ch):
    """A moment that shows a chassis effect well."""
    try:
        dur = max(300, int(ch.get("duration_ms") or 3000)) / 1000
    except (TypeError, ValueError):
        dur = 3.0
    return {"breathing": dur / 2, "pulse": dur * 0.15}.get(ch.get("effect"), dur * 0.3)


def key_color(kb, led, nx, ny, t, still=False):
    """One key: nx 0..1 left to right, ny 0..1 top (F-keys) to bottom (Space). -> (rgb, intensity)."""
    eff = kb.get("effect") or "static"
    cols = [parse_hex(c) for c in (kb.get("colors") or [])]
    c1 = cols[0] if cols else (255, 32, 0)
    c2 = cols[1] if len(cols) > 1 else c1
    sp = _speed(kb)
    if eff == "off":
        return (0, 0, 0), 0.0
    if eff == "static-blue":
        c, i = (0, 255, 255), 1.0
    elif eff == "perkey":
        c, i = parse_hex((kb.get("keys") or {}).get(str(led)), c1), 1.0
    elif eff == "breathing":
        ph = t * sp / 4
        lv = 0.5 - 0.5 * math.cos(2 * math.pi * ph)
        c, i = (c2 if math.floor(ph) % 2 else c1), 0.04 + 0.96 * lv
    elif eff == "spectrum":
        c, i = hsv(t * sp / 6, 1, 1), 1.0
    elif eff == "wave":
        d = kb.get("direction")
        pos = {"left": -nx, "up": -ny * 0.6, "down": ny * 0.6,
               "bounce": tri(nx * 0.5 + t * sp * 0.1) * 0.8,
               "bounce-v": tri(ny * 0.5 + t * sp * 0.1) * 0.8}.get(d, nx)
        c, i = hsv(pos - t * sp * 0.35, 1, 1), 1.0
    elif eff == "scanner":
        band = tri(t * sp / 2.6) * 1.1 - 0.05
        lit = max(0.0, 1 - abs(nx - band) / 0.14) ** 1.4
        if len(cols) > 1:
            c, i = mix(c2, c1, lit), 0.25 + 0.75 * lit
        else:
            c, i = c1, 0.03 + 0.97 * lit
    elif eff == "aurora":
        w = math.sin(nx * 5.2 + t * sp * 0.45) * 0.5 + math.sin(ny * 3.1 - t * sp * 0.3 + nx * 2) * 0.5
        c = hsv(0.36 + 0.22 * (w * 0.5 + 0.5), 0.9, 1)
        i = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * sp * 0.8 + nx * 7))
    elif eff == "gradient":
        b = c2 if len(cols) > 1 else hsv(hue_of(c1) + 0.25, 1, 1)
        c, i = mix(c1, b, nx), 1.0
    elif eff == "fire":
        seed = _hash(led, 1.7)
        n = (0.5 + 0.28 * math.sin(t * (6.1 + seed * 3) + seed * 12.9)
             + 0.22 * math.sin(t * 2.7 + seed * 4.1 - ny * 5.0))
        tongue = 0.12 * math.sin(nx * 9.0 + t * 1.9) + 0.08 * math.sin(nx * 17.0 - t * 3.1)
        heat = ny ** 1.25 * 0.95 + (n - 0.5) * 0.5 + tongue - 0.06
        c, i = heat_color(heat), _clamp(heat * 1.35)
    else:
        c, i = c1, 1.0
    # Light keys as I type: the effect shows only where (simulated) keys were just pressed.
    if not still and kb.get("on") in ("press", "release") and eff != "fire":
        rate = 3
        slot = math.floor(t * rate)
        glow = 0.0
        for s in range(slot, slot - 4, -1):
            if _hash(led, s) < 0.045:
                glow = max(glow, math.exp(-(t * rate - s) * 1.3))
        i *= glow
    return c, i * _bri(kb)


def rainbow_at(p):
    p = frac(p) * len(RAINBOW)
    i = int(p)
    return mix(RAINBOW[i], RAINBOW[(i + 1) % len(RAINBOW)], p - i)


def zone_color(ch, zone, nx, t):
    """A chassis zone ("head", "rear_left", "rear_right", "touchpad", "power"); nx places it for
    travelling effects."""
    eff = ch.get("effect") or "static"
    cols = [parse_hex(c) for c in (ch.get("colors") or [])]
    c1 = cols[0] if cols else (0, 240, 240)
    try:
        dur = max(300, int(ch.get("duration_ms") or 3000)) / 1000
    except (TypeError, ValueError):
        dur = 3.0
    if eff == "off":
        return (0, 0, 0), 0.0
    if eff == "static":
        z = ch.get("zones") or {}
        hx = z.get(zone) or (z.get("rear") if zone in ("rear_left", "rear_right") else None)
        c, i = (parse_hex(hx) if hx else c1), 1.0
    elif eff == "breathing":
        c, i = c1, 0.5 - 0.5 * math.cos(2 * math.pi * t / dur)
    elif eff == "pulse":
        p = frac(t / dur)
        c, i = c1, (p / 0.15 if p < 0.15 else math.exp(-(p - 0.15) * 5))
    elif eff == "morph":
        seq = cols if len(cols) > 1 else [c1, (0, 0, 0)]
        q = frac(t / dur) * len(seq)
        k = int(q)
        c, i = mix(seq[k], seq[(k + 1) % len(seq)], q - k), 1.0
    elif eff == "spectrum":
        c, i = rainbow_at(t / dur), 1.0
    elif eff == "wave":
        c, i = rainbow_at(t / dur - nx), 1.0
    else:
        c, i = c1, 1.0
    return c, i * _bri(ch)
