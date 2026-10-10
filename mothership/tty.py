"""Terminal rendering for the CLI and the TUI (standard library only).

Chrome (labels, headings, gauges, chips) uses the terminal's own palette: default foreground,
bold, dim, reverse and the 8 ANSI colours, so it reads right on light and dark themes. Only the
machine's actual light colours are painted in 24-bit colour (or the nearest of the 256-colour
palette when the terminal doesn't announce truecolor). NO_COLOR, TERM=dumb or output that isn't
a terminal gives plain text.
"""
import math
import os
import re
import sys

from . import effects as fx
from . import layout

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
GREEN, YELLOW, RED, BLUE, MAGENTA, CYAN = 32, 33, 31, 34, 35, 36

# Keycap legends by LED id (US layout), as the desktop UI draws them.
LABELS = {
    0: "Esc", **{i: f"F{i}" for i in range(1, 13)}, 13: "Home", 14: "End", 15: "Del",
    20: "`", **{21 + i: str((i + 1) % 10) for i in range(10)}, 31: "-", 32: "=", 35: "Back", 19: "Mic",
    40: "Tab", **dict(zip(range(42, 52), "QWERTYUIOP")), 52: "[", 53: "]", 55: "\\", 16: "Mute",
    61: "Caps", **dict(zip(range(62, 71), "ASDFGHJKL")), 71: ";", 72: "'", 74: "Enter", 18: "Vol+",
    81: "Shift", **dict(zip(range(83, 90), "ZXCVBNM")), 90: ",", 91: ".", 92: "/", 94: "Shift",
    114: "↑", 17: "Vol-",
    100: "Ctrl", 101: "Fn", 103: "Super", 104: "Alt", 106: "", 107: "", 111: "Alt", 109: "Menu",
    112: "Ctrl", 133: "←", 134: "↓", 135: "→",
}
SHORT = {"Home": "Hm", "Back": "Bk", "Mute": "Mu", "Caps": "Cp", "Enter": "Ent", "Shift": "Sh",
         "Vol+": "V+", "Vol-": "V-", "Ctrl": "Ct", "Super": "Su", "Menu": "Mn", "Esc": "Es", "Mic": "Mi"}
CAP = (30, 30, 34)          # an unlit keycap (dark chassis)

ASCII = {"✓": "ok", "·": "-", "●": "*", "━": "=", "╸": "-", "▀": "#", "─": "-", "╭": "+", "╮": "+",
         "╰": "+", "╯": "+", "◆": "*", "!": "!", "▮": "#", "▬": "=", "°": "", "−": "-", "…": "...",
         "←": "<", "→": ">", "↑": "^", "↓": "v", "⏎": "enter", "▸": ">", "│": "|", "◂": "<"}

THERMAL_NAMES = {"low-power": "low power", "balanced-performance": "balanced+", "performance": "performance"}


def vlen(s):
    """Visible length (ANSI escapes removed)."""
    return len(ANSI_RE.sub("", s))


def strip(s):
    return ANSI_RE.sub("", s)


def clip(s, width):
    """Cut a string with escapes to `width` visible columns."""
    if vlen(s) <= width:
        return s
    out, n, i = [], 0, 0
    while i < len(s) and n < width:
        m = ANSI_RE.match(s, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        out.append(s[i])
        n += 1
        i += 1
    if "\x1b[" in s:
        out.append("\x1b[0m")
    return "".join(out)


def pad(s, width):
    return s + " " * max(0, width - vlen(s))


def rgb256(rgb):
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)

    def q(v):
        return 0 if v < 48 else 1 if v < 115 else (v - 35) // 40
    levels = [0, 95, 135, 175, 215, 255]
    cr, cg, cb = q(r), q(g), q(b)
    cube = 16 + 36 * cr + 6 * cg + cb
    dc = (levels[cr] - r) ** 2 + (levels[cg] - g) ** 2 + (levels[cb] - b) ** 2
    avg = (r + g + b) // 3
    gi = max(0, min(23, (avg - 3) // 10))
    gv = 8 + gi * 10
    dg = (gv - r) ** 2 + (gv - g) ** 2 + (gv - b) ** 2
    return 232 + gi if dg < dc else cube


def luminance(rgb):
    r, g, b = (v / 255 for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class Term:
    """What the output can show: mode is "truecolor", "256" or "plain"."""

    def __init__(self, mode="truecolor", width=80, unicode=True, tty=True):
        self.mode = mode
        self.width = max(20, int(width))
        self.unicode = unicode
        self.tty = tty

    @property
    def color(self):
        return self.mode != "plain"

    @classmethod
    def detect(cls, stream=None, env=None):
        stream = stream or sys.stdout
        env = os.environ if env is None else env
        try:
            tty = stream.isatty()
        except (AttributeError, ValueError):
            tty = False
        forced = env.get("MOTHERSHIP_COLOR", "").lower()
        if forced in ("truecolor", "256", "plain"):
            mode = forced
        elif env.get("NO_COLOR") or not tty or env.get("TERM", "") == "dumb":
            mode = "plain"
        elif env.get("COLORTERM", "").lower() in ("truecolor", "24bit") or "direct" in env.get("TERM", ""):
            mode = "truecolor"
        else:
            mode = "256"
        width = 0
        if tty:
            try:
                width = os.get_terminal_size(stream.fileno()).columns
            except (OSError, AttributeError, ValueError):
                width = 0
        if not width:
            try:
                width = int(env.get("COLUMNS", "") or 80)
            except ValueError:
                width = 80
        enc = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        return cls(mode, width, unicode=enc.startswith("utf") or not enc, tty=tty)

    # ---- glyphs and SGR
    def g(self, s):
        if self.unicode:
            return s
        return "".join(ASCII.get(ch, ch if ord(ch) < 128 else "?") for ch in s)

    def sgr(self, *codes):
        return f"\x1b[{';'.join(str(c) for c in codes)}m" if self.color and codes else ""

    @property
    def reset(self):
        return "\x1b[0m" if self.color else ""

    def _col(self, rgb, base):
        r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
        if self.mode == "truecolor":
            return f"{base};2;{r};{g};{b}"
        return f"{base};5;{rgb256((r, g, b))}"

    def style(self, fg=None, bg=None, dim=False, bold=False, reverse=False, ansi=None, underline=False):
        if not self.color:
            return ""
        codes = ["0"]
        if bold:
            codes.append("1")
        if dim:
            codes.append("2")
        if underline:
            codes.append("4")
        if reverse:
            codes.append("7")
        if ansi:
            codes.append(str(ansi))
        if fg is not None:
            codes.append(self._col(fg, 38))
        if bg is not None:
            codes.append(self._col(bg, 48))
        return f"\x1b[{';'.join(codes)}m"

    def paint(self, text, **kw):
        if not self.color or not text:
            return text
        return self.style(**kw) + text + "\x1b[0m"

    def bold(self, s):
        return self.paint(s, bold=True)

    def dim(self, s):
        return self.paint(s, dim=True)

    def tone(self, s, ansi, bold=False):
        return self.paint(s, ansi=ansi, bold=bold)


# --------------------------------------------------------------------------- components
def swatch(term, color, width=2, hex_label=False):
    """A colour block; plain text shows the hex instead."""
    rgb = fx.parse_hex(color) if isinstance(color, str) else color
    hx = color.lstrip("#").lower() if isinstance(color, str) else fx.to_hex(rgb)
    if not term.color:
        return f"#{hx}"
    block = term.paint(term.g("█") * width, fg=rgb)
    return f"{block} {term.dim(hx)}" if hex_label else block


def dot(term, rgb, intensity=1.0, glyph="●"):
    rgb = lit(rgb, intensity)
    if not term.color:
        return term.g(glyph if intensity > 0.08 else "·")
    return term.paint(term.g(glyph), fg=rgb)


def chip(term, text, active=False, cursor=False, disabled=False):
    """Ink-style pill: the active choice in reverse video, the cursor bold and underlined."""
    if not term.color:
        if active and cursor:
            return f"[>{text}<]"
        if active:
            return f"[{text}]"
        if cursor:
            return f">{text}<"
        return f" {text} "
    if active:
        return term.paint(f" {text} ", reverse=True, bold=True, underline=cursor)
    if disabled:
        return term.paint(f" {text} ", dim=True)
    if cursor:
        return term.paint(f" {text} ", bold=True, underline=True)
    return f" {text} "


def gauge(term, frac, width=16, ansi=None):
    """A horizontal bar 0..1 drawn in the terminal's palette."""
    frac = max(0.0, min(1.0, frac or 0.0))
    if not term.color or not term.unicode:
        n = round(frac * width)
        return "#" * n + "-" * (width - n)
    halves = round(frac * width * 2)
    full, half = divmod(halves, 2)
    filled = "━" * full + ("╸" if half else "")
    rest = width - full - (1 if half else 0)
    return term.paint(filled, ansi=ansi, bold=True) + term.paint("━" * rest, dim=True)


def lit(rgb, intensity):
    """A light at an intensity as the eye sees it on a dark keycap."""
    i = max(0.0, min(1.0, intensity))
    return fx.mix(CAP, rgb, i) if i < 1 else rgb


def temp_tone(name, v):
    if v is None:
        return None
    warn, hot = (75, 90) if name in ("cpu", "package") else (72, 84)
    return GREEN if v < warn else YELLOW if v < hot else RED


# --------------------------------------------------------------------------- keyboard
def _rows():
    rows = {}
    seen = set()
    for led, (row, x, w) in sorted(layout.KEYS.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[0])):
        if (row, x, w) in seen:
            continue
        seen.add((row, x, w))
        rows.setdefault(row, []).append((led, x, w))
    return [rows[r] for r in sorted(rows)]


ROWS = _rows()


def key_spans(width):
    """[(row, [(led, start, end)])] mapping the layout onto `width` terminal columns, with at
    least one blank column between neighbours."""
    s = width / layout.WIDTH
    out = []
    for keys in ROWS:
        spans = []
        for i, (led, x, w) in enumerate(keys):
            a = int(round(x * s))
            b = int(round((x + w) * s))
            if i + 1 < len(keys):
                b = min(b, int(round(keys[i + 1][1] * s)) - 1)
            b = max(b, a + 1)
            spans.append((led, a, min(b, width)))
        out.append(spans)
    return out


KEY_PITCH = 63.6     # canvas units from one key to the next


def fit_width(avail):
    """The widest keyboard <= avail columns where the key pitch is a whole number of columns,
    so every gap comes out the same."""
    n = max(2, int(avail * KEY_PITCH / layout.WIDTH))
    w = int(round(n * layout.WIDTH / KEY_PITCH))
    return max(32, min(int(avail), w if w >= avail * 0.85 else int(avail)))


def key_colors(kb, t=0.0, still=False):
    """{led: (rgb, intensity)} for every key under a keyboard config."""
    out = {}
    for ri, keys in enumerate(ROWS):
        for led, x, w in keys:
            nx = (x + w / 2) / layout.WIDTH
            ny = ri / (len(ROWS) - 1)
            out[led] = fx.key_color(kb, led, nx, ny, t, still=still)
    # LEDs that light the same cap (106 and 107: the Space bar) share its colour.
    for led, geo in layout.KEYS.items():
        if led not in out:
            twin = next(k for k, g in layout.KEYS.items() if g == geo and k in out)
            out[led] = out[twin]
    return out


def _label(led, n):
    text = LABELS.get(led, "")
    if len(text) > n:
        text = SHORT.get(text, text)
    return text[:n] if n >= 1 else ""


def keyboard(term, colors, width, unlit=(), labels=True, tall=True):
    """Draw the keyboard `width` columns wide. colors = {led: (rgb, intensity)}.

    Colour terminals get keycaps from half blocks (two pixels per cell: a cap is 3 pixels
    tall with a 1-pixel gap); keys without a light are dim outlines. Plain text gets [labels].
    """
    unlit = set(unlit)
    width = max(32, int(width))
    rows = key_spans(width)
    lines = []
    for spans in rows:
        if not term.color:
            buf = [" "] * width
            for led, a, b in spans:
                n = b - a
                if led in unlit:
                    cell = term.g("·") * n
                elif n >= 3:
                    cell = "[" + _label(led, n - 2).center(n - 2) + "]"
                else:
                    cell = (_label(led, 1) or "#").ljust(n)
                buf[a:b] = list(cell[:n])
            lines.append("".join(buf).rstrip())
            continue
        top, bot = [], []
        pos = 0
        for led, a, b in spans:
            if a > pos:
                top.append(" " * (a - pos))
                bot.append(" " * (a - pos))
            n = b - a
            if led in unlit:
                if n >= 2:
                    lab = _label(led, n - 2)
                    top.append(term.paint(term.g("╭" + "─" * (n - 2) + "╮"), dim=True))
                    bot.append(term.paint(term.g("╰" + lab.center(n - 2, "─") + "╯"), dim=True))
                else:
                    top.append(term.dim("·"))
                    bot.append(" ")
            else:
                rgb, i = colors.get(led, ((0, 0, 0), 0.0))
                face = lit(rgb, i)
                lab = _label(led, n - 2 if n >= 5 else n - 1 if n >= 4 else n) if labels else ""
                ink = fx.mix(face, (0, 0, 0), 0.72) if luminance(face) > 0.42 else fx.mix(face, (255, 255, 255), 0.62)
                top.append(term.paint(lab.center(n), fg=ink, bg=face, bold=True))
                bot.append(term.paint(term.g("▀") * n, fg=face) if tall else "")
            pos = b
        lines.append("".join(top))
        if tall:
            lines.append("".join(bot))
    return lines


# --------------------------------------------------------------------------- chassis
REAR_SEGMENTS = 10


def chassis_colors(ch, zones, t=0.0):
    """{"head": (rgb, i), "rear": [(rgb, i)] * 10, "touchpad": (rgb, i) or None}."""
    out = {"head": fx.zone_color(ch, "head", 1.0, t)}
    rear = []
    for k in range(REAR_SEGMENTS):
        zone = "rear_left" if k < REAR_SEGMENTS // 2 else "rear_right"
        rear.append(fx.zone_color(ch, zone, k / REAR_SEGMENTS, t))
    out["rear"] = rear
    out["touchpad"] = fx.zone_color(ch, "touchpad", 0.85, t) if "touchpad" in (zones or ()) else None
    return out


def chassis_strip(term, cc, note=""):
    """One line: the lid logo, the rear light loop (10 segments) and the touchpad if present."""
    d = term.dim
    hrgb, hi = cc["head"]
    parts = [d("lid ") + dot(term, hrgb, hi, "●")]
    if term.color:
        rear = "".join(term.paint(term.g("▮"), fg=lit(c, i)) for c, i in cc["rear"])
    else:
        rear = "".join("#" if i > 0.08 else "." for _, i in cc["rear"])
    parts.append(d("rear ") + rear)
    if cc.get("touchpad"):
        trgb, ti = cc["touchpad"]
        tp = term.paint(term.g("▬▬▬"), fg=lit(trgb, ti)) if term.color else ("===" if ti > 0.08 else "...")
        parts.append(d("touchpad ") + tp)
    line = "   ".join(parts)
    return line + ("   " + d(note) if note else "")


# --------------------------------------------------------------------------- descriptions
def title(name):
    return {"static-blue": "Static blue", "perkey": "Per-key", "off": "Off"}.get(name, str(name).replace("-", " ").capitalize())


KB_COLORED = ("static", "breathing", "scanner", "gradient")
KB_SPEEDS = ("breathing", "wave", "scanner", "spectrum", "aurora")


def effect_swatch(term, kb, n=3):
    """A tiny preview of a keyboard effect: n cells sampled across the board."""
    cols = []
    for k in range(n):
        nx = (k + 0.5) / n
        rgb, i = fx.key_color(kb, 50, nx, 0.85, fx.still_time(kb), still=True)
        cols.append(lit(rgb, max(i, 0.0)))
    if not term.color:
        return ""
    return "".join(term.paint(term.g("█"), fg=c) for c in cols)


def describe_kb(term, kb):
    eff = kb.get("effect") or "static"
    bits = [term.bold(title(eff))]
    if eff in KB_COLORED:
        bits.append(" ".join(swatch(term, c, 2, hex_label=True) for c in (kb.get("colors") or ["ffffff"])[:2]))
    if eff in KB_SPEEDS:
        bits.append(f"speed {kb.get('speed', 1)}")
    if eff == "wave" and kb.get("direction"):
        bits.append(str(kb["direction"]))
    if eff == "perkey":
        bits.append(f"{len(kb.get('keys') or {})} keys set")
    if kb.get("on") in ("press", "release") and eff != "fire":
        bits.append(f"on key {kb['on']}")
    if eff != "off":
        bits.append(f"{kb.get('brightness', 100)}%")
    sw = effect_swatch(term, kb)
    return (sw + " " if sw else "") + term.dim(" · ").join(bits)


CH_COLORED = ("breathing", "pulse", "morph")


def describe_chassis(term, ch, zones=None):
    eff = ch.get("effect") or "static"
    bits = [term.bold(title(eff))]
    if eff == "static":
        z = ch.get("zones") or {}
        base = (ch.get("colors") or ["ffffff"])[0]
        names = [n for n in ("head", "rear", "touchpad") if zones is None or n == "rear" and
                 ("rear_left" in zones or "rear" in zones) or n in zones]
        if not z:
            bits.append(swatch(term, base, 2, hex_label=True))
        else:
            label = {"head": "lid"}
            bits.append("  ".join(f"{label.get(n, n)} {swatch(term, z.get(n, base), 2)}" for n in names))
    elif eff in CH_COLORED:
        bits.append(" ".join(swatch(term, c, 2, hex_label=True) for c in (ch.get("colors") or ["00f0f0"])[:3]))
    if eff not in ("static", "off"):
        bits.append(f"{(ch.get('duration_ms') or 3000) / 1000:g} s")
    if eff != "off":
        bits.append(f"{ch.get('brightness', 100)}%")
    return term.dim(" · ").join(bits)


def ok_line(term, what, detail=""):
    """✓ What  detail"""
    mark = term.tone(term.g("✓"), GREEN, bold=True)
    return f"{mark} {term.bold(what)}" + (f"  {detail}" if detail else "")


def short_error(msg):
    msg = re.sub(r"^\[Errno \d+\] ", "", str(msg))
    msg = re.sub(r" \(is mothership's udev rule installed and are you in its group\?\)", " (udev rule / group?)", msg)
    msg = re.sub(r": '/sys/[^']*'$", "", msg)
    return msg


# --------------------------------------------------------------------------- status
def header(term, st):
    from . import __version__
    kb = st.get("keyboard") or {}
    ch = st.get("chassis") or {}
    d = term.dim
    sep = d(term.g(" · "))
    bits = [term.tone(term.g("◆"), MAGENTA, bold=True) + " " + term.bold("mothership") + " " + d(__version__)]
    bits.append(d("keyboard fw ") + str(kb["firmware"]) if kb.get("firmware") else d("no keyboard"))
    if ch.get("firmware"):
        bits.append(d("lighting fw ") + str(ch["firmware"]))
    elif (st.get("devices") or {}).get("chassis"):
        bits.append(d("lighting controller unreachable"))
    gm = (st.get("graphics") or {}).get("mode")
    if gm and gm != "unknown":
        bits.append(f"{gm} " + d("graphics"))
    return sep.join(bits)


def thermal_lines(term, th, cfg_th=None, width=80):
    cfg_th = cfg_th or {}
    if not th:
        return []
    if th.get("error"):
        return [term.dim("Thermal   ") + term.tone(short_error(th["error"]), YELLOW)]
    if th.get("available") is False:
        return [term.dim("Thermal   not available")]
    d = term.dim
    out = []
    mode = th.get("mode") or "?"
    gmode = th.get("gmode")
    if gmode is None:
        gmode = cfg_th.get("gmode") if "gmode" in cfg_th else mode == "performance"
    line = d("Thermal   ") + chip(term, THERMAL_NAMES.get(mode, mode), active=True)
    if gmode:
        line += " " + (term.paint(" G-MODE ", ansi=RED, bold=True, reverse=True) if term.color else "[G-MODE]")
    auto = cfg_th.get("auto")
    if auto is not None:
        line += "  " + (term.tone("auto", CYAN) if auto else d("manual"))
    ac = th.get("ac")
    if ac is not None:
        line += "  " + (d("on AC") if ac else term.tone("on battery", YELLOW))
    out.append(line)

    fans = th.get("fans") or []
    names = [f.get("label") or f"Fan {f.get('id')}" for f in fans]
    seen = {}
    labels = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        labels.append(f"{n} {seen[n]}" if names.count(n) > 1 else n)
    cells = []
    gw = 14 if width >= 10 + 2 * (9 + 14 + 13) + 3 else 8
    for f, lab in zip(fans, labels):
        rpm = f.get("rpm") or 0
        top = max(f.get("max") or 0, rpm, 1)
        frac = rpm / max(top, 5000)
        cell = f"{d(lab.lower()[:9].ljust(9))} {gauge(term, frac, gw, CYAN)} {rpm:>5} {d('rpm')}"
        if f.get("boost_pct"):
            cell += " " + term.tone(f"+{f['boost_pct']}%", CYAN)
        cells.append(cell)
    cols = 2 if width >= 10 + 2 * (9 + gw + 13) + 3 and len(cells) > 1 else 1
    for i in range(0, len(cells), cols):
        row = cells[i:i + cols]
        out.append(d("Fans      " if i == 0 else "          ") + "   ".join(pad(c, 9 + gw + 13) for c in row).rstrip())

    temps = th.get("temps") or {}
    tb = []
    for key, name in (("cpu", "CPU"), ("package", "package"), ("gpu", "GPU")):
        v = temps.get(key)
        if v is not None:
            tb.append(f"{d(name)} {term.tone(f'{v:.0f}°C', temp_tone(key, v), bold=True)}")
    g = th.get("dgpu") or {}
    if g:
        if g.get("state") == "active" and g.get("temp") is not None:
            extra = f" {g['watts']:.0f} W" if g.get("watts") is not None else ""
            gt = "{:.0f}°C".format(g["temp"])
            tb.append(d("dGPU") + " " + term.tone(gt, temp_tone("gpu", g["temp"]), bold=True) + d(extra))
        else:
            tb.append(f"{d('dGPU')} {d(str(g.get('state') or '?'))}")
    if tb:
        out.append(d("Temps     ") + "   ".join(tb))

    lim = []
    pl = th.get("power_limits")
    if pl:
        named = {"long_term": "PL1", "short_term": "PL2"}
        lim.append("  ".join(f"{d(named.get(k, k))} {v} W" for k, v in pl.items()))
    tcc = th.get("tcc_offset")
    if th.get("tcc_locked"):
        lim.append(f"{d('TCC')} locked by BIOS")
    elif tcc is not None:
        lim.append(f"{d('TCC')} {'−' + str(tcc) if tcc else '0'} °C" if term.unicode else f"TCC -{tcc} C")
    pi = th.get("power_info")
    if pi:
        w = pi.get("watts") or []
        s = f"{d('adapter')} {' + '.join(f'{x} W' for x in w) or '?'}"
        if pi.get("status") == "undersized":
            s += " " + term.tone("undersized", YELLOW, bold=True)
        lim.append(s)
    if lim:
        out.append(d("Limits    ") + "   ".join(lim))
    return out


def problems_line(term, errors, width):
    if not errors:
        return ""
    txt = term.g(" · ").join(f"{k}: {short_error(v)}" for k, v in errors.items())
    line = term.g("! ") + txt
    if len(line) > width:
        line = line[: max(1, width - 1)] + term.g("…")
    return term.dim(line)


def render_status(term, st, t=None, art=None):
    """The whole `mothership status` screen as a string."""
    st = st or {}
    art = term.tty if art is None else art
    cfg = st.get("config") or {}
    kbc = dict(cfg.get("keyboard") or {})
    chc = dict(cfg.get("chassis") or {})
    devices = st.get("devices") or {}
    kst = st.get("keyboard") or {}
    W = min(term.width, 110)
    ind = "  "
    lines = [header(term, st), ""]

    has_kb = bool(kst) or bool(devices.get("keyboard"))
    if has_kb and kbc and art and W >= 40:
        tt = fx.still_time(kbc) if t is None else t
        cols = key_colors(kbc, tt, still=t is None)
        kw = fit_width(min(W - 2 * len(ind), 100))
        for ln in keyboard(term, cols, kw, unlit=kst.get("unlit") or ()):
            lines.append(ind + ln)
        lines.append("")
    d = term.dim
    if has_kb:
        desc = describe_kb(term, kbc) if kbc else d("no settings yet")
        if kst.get("error"):
            desc += "  " + term.tone(short_error(kst["error"]), YELLOW)
        lines.append(d("Keyboard  ") + desc)
    else:
        lines.append(d("Keyboard  not found"))

    chs = st.get("chassis")
    if chs or devices.get("chassis"):
        zones = (chs or {}).get("zones")
        cc = chassis_colors(chc, zones or (), fx.chassis_still_time(chc) if t is None else t)
        note = "" if chs else "controller unreachable: showing settings"
        lines.append(d("Lights    ") + describe_chassis(term, chc, zones))
        lines.append(d("          ") + chassis_strip(term, cc, note))

    th = thermal_lines(term, st.get("thermal"), cfg.get("thermal"), W)
    if th:
        lines.append("")
        lines.extend(th)
    pl = problems_line(term, st.get("errors"), term.width if term.tty else 10 ** 6)
    if pl:
        lines.append("")
        lines.append(pl)
    return "\n".join(clip(ln, term.width) if term.tty else ln for ln in lines)


# --------------------------------------------------------------------------- command results
POWER_LABELS = {"ac-sleep": "AC, asleep", "ac-full": "AC, charged", "ac-charging": "AC, charging",
                "dc-sleep": "battery, asleep", "dc-on": "battery", "dc-low": "battery low"}


def describe_profile(term, p, active=False):
    d = term.dim
    bits = []
    if p.get("keyboard"):
        k = p["keyboard"]
        bits.append(f"{d('kb')} {k.get('effect')}" + (" " + swatch(term, k["colors"][0]) if k.get("colors") else ""))
    if p.get("chassis"):
        c = p["chassis"]
        bits.append(f"{d('lights')} {c.get('effect')}" + (" " + swatch(term, c["colors"][0]) if c.get("colors") else ""))
    if p.get("thermal"):
        bits.append(f"{d('mode')} {p['thermal'].get('mode')}")
    match = f"/{p.get('match')}/" + (f" {d('title')} /{p['title']}/" if p.get("title") else "")
    mark = term.tone(term.g("●"), GREEN) if active else " "
    return f"{mark} {term.bold(str(p.get('name') or '?'))}  {d(match)}  " + term.dim(" · ").join(bits)


def render_result(term, cmd, args, result, context=None):
    """Human output for one daemon command's result (the CLI's default; --json prints raw)."""
    ctx = context or {}
    args = args or {}
    d = term.dim
    if cmd == "status":
        return render_status(term, result)
    if cmd == "devices":
        r = result or {}
        out = [d("Keyboard  ") + (r.get("keyboard") or d("not found")),
               d("Lighting  ") + ((r.get("chassis") or "") + (f" {d('(187c:' + r['chassis_pid'] + ')')}" if r.get("chassis_pid") else "")
                                  if r.get("chassis") else d("not found"))]
        return "\n".join(out)
    if cmd == "reapply":
        return ok_line(term, "Lighting", "re-applied")
    if cmd.startswith("keyboard."):
        r = result or {}
        line = ok_line(term, "Keyboard", describe_kb(term, r.get("keyboard") or {}))
        return line
    if cmd.startswith("chassis."):
        r = result or {}
        return ok_line(term, "Lights", describe_chassis(term, r.get("chassis") or {}))
    if cmd == "power.show":
        r = result or {}
        saved = r.get("saved") or {}
        out = [term.bold("Power button") + d("  colour per power state, saved in the lighting controller")]
        for s in r.get("states") or []:
            col = saved.get(s)
            val = swatch(term, col, 2, hex_label=True) if col else d("not set by mothership")
            out.append(f"  {d(POWER_LABELS.get(s, s).ljust(16))} {d(s.ljust(12))} {val}")
        if not saved:
            out.append(d("  set with: mothership power set <state|all> RRGGBB --write-flash"))
        return "\n".join(out)
    if cmd == "power.set":
        states = (result or {}).get("saved") or []
        return ok_line(term, "Power button", f"{swatch(term, args.get('color', 'ffffff'), 2, hex_label=True)}  "
                       + d("saved to flash for ") + ", ".join(states))
    if cmd == "thermal.status":
        return "\n".join(thermal_lines(term, result, ctx.get("thermal_cfg"), min(term.width, 110)))
    if cmd.startswith("thermal."):
        th = result or {}
        verb = cmd.split(".", 1)[1]
        if verb == "mode":
            return ok_line(term, "Thermal mode", chip(term, THERMAL_NAMES.get(th.get("mode"), str(th.get("mode"))), active=True)
                           + "  " + d("fan rules off (mothership fans auto on)"))
        if verb == "gmode":
            on = args.get("on")
            if on == "toggle":
                on = th.get("gmode", th.get("mode") == "performance")
            return ok_line(term, "G-Mode", (term.tone("on", RED, bold=True) if on else "off")
                           + d("  thermal mode ") + str(th.get("mode")))
        if verb == "boost":
            v = args.get("value")
            return ok_line(term, "Fan boost", f"{v}%" + (f" {d('fan')} {args['fan']}" if args.get("fan") else "")
                           if v else "off")
        if verb == "auto":
            return ok_line(term, "Fan rules", "automatic" if args.get("on") else "manual")
        if verb == "tcc":
            v = args.get("value", 0)
            return ok_line(term, "CPU temperature limit", f"{term.g('−')}{v} °C" if v else "stock")
        if verb == "power_limit":
            v = args.get("value")
            where = args.get("mode") or "all modes"
            return ok_line(term, "Power limit", (f"{v} W" if v else "stock") + d(f"  ({where})"))
        return ok_line(term, "Thermal", str(th.get("mode")))
    if cmd == "profiles.get":
        r = result or {}
        profs = r.get("profiles") or []
        act = (r.get("active") or {}).get("name")
        if not profs:
            return d('no profiles  (mothership profile add <name> --match "<window class regex>" ...)')
        return "\n".join(describe_profile(term, p, p.get("name") == act) for p in profs)
    if cmd == "profiles.set":
        name = ctx.get("name")
        if ctx.get("verb") == "remove":
            return ok_line(term, "Profile removed", str(name))
        prof = next((p for p in (result or {}).get("profiles", []) if p.get("name") == name), None)
        return ok_line(term, "Profile", strip(describe_profile(term, prof)).strip() if prof and not term.color
                       else (describe_profile(term, prof).strip() if prof else str(name)))
    if cmd == "macro.keys":
        r = result or {}
        saved = r.get("saved") or {}
        return "\n".join(f"  {term.bold(k.ljust(3))} {saved.get(k) or d('empty')}" for k in r.get("keys") or [])
    if cmd == "macro.set":
        r = result or {}
        return ok_line(term, f"Macro {r.get('key', '')}", f"{args.get('keys', '')}  " + d(f"saved to keyboard flash ({r.get('bytes', '?')} bytes)"))
    if cmd == "macro.clear":
        return ok_line(term, f"Macro {(result or {}).get('key', '')}", "cleared")
    if cmd == "graphics":
        r = result or {}
        names = {"hybrid": "hybrid (integrated GPU drives the screen)", "discrete": "discrete GPU only"}
        m = r.get("mode", "unknown")
        extra = f"  {d(r['connector'] + ' on ' + r['driver'])}" if r.get("connector") else ""
        return d("Graphics  ") + term.bold(names.get(m, m)) + extra
    if isinstance(result, str):
        return result
    import json
    return json.dumps(result, indent=2)


def warnings(term, cmd, result):
    """Problems a successful command still reports (e.g. the device refused the new setting)."""
    if isinstance(result, dict) and result.get("error"):
        what = cmd.split(".", 1)[0]
        return f"! {what}: {short_error(result['error'])}"
    return ""
