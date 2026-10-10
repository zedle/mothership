"""`mothership tui`: a full-screen terminal front end (standard library only).

Raw ANSI over termios rather than curses: curses can't paint 24-bit colours per cell (its colour
pairs are a small fixed table), and the mirror needs one colour per key per frame. The screen is
an alternate buffer; each frame is diffed line by line against the last one and only changed
lines are sent, wrapped in synchronized-output markers (ignored by terminals without them), so
it stays light over SSH. The terminal is restored on exit, on exceptions, on Ctrl-C and SIGTERM.

The pure parts (State: tabs, rows, selection, key handling -> daemon requests; frame()) need
no terminal and are unit tested.
"""
import os
import queue
import select
import signal
import sys
import threading
import time

from . import effects as fx
from . import ipc
from . import tty

TABS = ("Keyboard", "Lights", "Thermal", "Power")
PALETTE = ["ff0000", "ff5a00", "ffb000", "ffff00", "00ff40", "00ffb0", "00e0ff", "0040ff", "8000ff",
           "ff00c0", "ffffff"]
KB_EFFECTS = ["static", "breathing", "wave", "spectrum", "scanner", "aurora", "gradient", "fire", "off"]
CH_EFFECTS = ["static", "breathing", "pulse", "morph", "spectrum", "wave", "off"]
SPEEDS = [(0, "slow"), (1, "medium"), (2, "fast")]
DIRECTIONS = [("left", "←"), ("right", "→"), ("up", "↑"), ("down", "↓"), ("bounce", "↔"), ("bounce-v", "↕")]
DURATIONS = [(1000, "1 s"), (2000, "2 s"), (3000, "3 s"), (5000, "5 s"), (8000, "8 s")]
BOOSTS = [(None, "off"), (25, "25%"), (50, "50%"), (75, "75%"), (100, "100%")]
TCCS = [(0, "stock"), (3, "−3 °C"), (5, "−5 °C"), (10, "−10 °C"), (15, "−15 °C")]
ZONES = [("all", "all"), ("head", "lid"), ("rear", "rear"), ("touchpad", "touchpad")]
STEP = 10
TOAST_S = 4.0

KEYS = {
    "\x1b[A": "up", "\x1bOA": "up", "\x1b[B": "down", "\x1bOB": "down",
    "\x1b[C": "right", "\x1bOC": "right", "\x1b[D": "left", "\x1bOD": "left",
    "\x1b[Z": "backtab", "\t": "tab", "\r": "enter", "\n": "enter", "\x1b": "esc", "\x03": "ctrl-c",
    "k": "up", "j": "down", "l": "right", "h": "left",
}


def parse_keys(data):
    """Split raw terminal input into key names ("up", "enter", "q", ...)."""
    out = []
    i = 0
    while i < len(data):
        if data[i] == "\x1b" and i + 1 < len(data) and data[i + 1] in "[O":
            j = i + 2
            while j < len(data) and not (data[j].isalpha() or data[j] == "~"):
                j += 1
            seq = data[i:j + 1]
            out.append(KEYS.get(seq, "unknown"))
            i = j + 1
            continue
        ch = data[i]
        out.append(KEYS.get(ch, ch))
        i += 1
    return out


class Row:
    def __init__(self, key, label, options, enabled=True, kind="chip"):
        self.key, self.label, self.options, self.enabled, self.kind = key, label, options, enabled, kind

    def index(self, value):
        for i, (v, _) in enumerate(self.options):
            if v == value:
                return i
        return None


class State:
    """Tabs, rows, the draft selection and what each key press asks the daemon to do."""

    def __init__(self):
        self.tab = 0
        self.row = {t: 0 for t in range(len(TABS))}
        self.status = {}
        self.draft = {}           # (tab, row key) -> value
        self.dirty = set()        # tabs with a draft the user changed and hasn't applied

    # ---- data
    def cfg(self, section):
        return dict(((self.status or {}).get("config") or {}).get(section) or {})

    def zones(self):
        return ((self.status or {}).get("chassis") or {}).get("zones") or []

    def thermal(self):
        return (self.status or {}).get("thermal") or {}

    def set_status(self, st):
        self.status = st or {}
        for t in range(len(TABS)):
            if t not in self.dirty:
                self.sync(t)

    def sync(self, tab):
        """Draft = what's configured now."""
        for k in [k for k in self.draft if k[0] == tab]:
            del self.draft[k]
        self.dirty.discard(tab)
        if tab == 0:
            kb = self.cfg("keyboard")
            self.draft.update({(0, "effect"): kb.get("effect", "static"),
                               (0, "color"): ((kb.get("colors") or ["ffffff"])[0]).lower(),
                               (0, "speed"): int(kb.get("speed", 1)), (0, "direction"): kb.get("direction", "right")})
        elif tab == 1:
            ch = self.cfg("chassis")
            zones = ch.get("zones") or {}
            zone = "all"
            col = ((ch.get("colors") or ["00f0f0"])[0]).lower()
            if zones:
                zone = next(iter(zones))
                col = zones[zone].lower()
            self.draft.update({(1, "effect"): ch.get("effect", "static"), (1, "zone"): zone, (1, "color"): col,
                               (1, "duration"): int(ch.get("duration_ms", 3000))})
        elif tab == 2:
            th = self.thermal()
            tc = self.cfg("thermal")
            self.draft.update({(2, "mode"): th.get("mode"), (2, "auto"): bool(tc.get("auto", True)),
                               (2, "boost"): _boost_now(th), (2, "tcc"): th.get("tcc_offset") or 0})

    def value(self, key, tab=None):
        return self.draft.get((self.tab if tab is None else tab, key))

    def palette(self, current):
        cols = list(PALETTE)
        if current and current.lower() not in cols:
            cols.insert(0, current.lower())
        return [(c, c) for c in cols]

    def rows(self, tab=None):
        tab = self.tab if tab is None else tab
        if tab == 0:
            eff = self.value("effect", 0)
            return [Row("effect", "Effect", [(e, tty.title(e)) for e in KB_EFFECTS]),
                    Row("color", "Colour", self.palette(self.value("color", 0)), eff in tty.KB_COLORED, "swatch"),
                    Row("speed", "Speed", SPEEDS, eff in tty.KB_SPEEDS),
                    Row("direction", "Direction", DIRECTIONS, eff == "wave")]
        if tab == 1:
            eff = self.value("effect", 1)
            zones = [z for z in ZONES if z[0] in ("all", "head", "rear") or z[0] in self.zones()]
            return [Row("effect", "Effect", [(e, tty.title(e)) for e in CH_EFFECTS]),
                    Row("zone", "Zone", zones, eff == "static"),
                    Row("color", "Colour", self.palette(self.value("color", 1)),
                        eff in ("static", "breathing", "pulse", "morph"), "swatch"),
                    Row("duration", "Cycle", DURATIONS, eff not in ("static", "off"))]
        if tab == 2:
            th = self.thermal()
            if not th or th.get("error") or th.get("available") is False:
                return []
            rows = [Row("mode", "Mode", [(m, tty.THERMAL_NAMES.get(m, m)) for m in th.get("modes") or []]),
                    Row("auto", "Fan rules", [(True, "automatic"), (False, "manual")]),
                    Row("boost", "Fan boost", BOOSTS)]
            if th.get("tcc_offset") is not None and not th.get("tcc_locked"):
                rows.append(Row("tcc", "CPU limit", TCCS))
            return rows
        return []

    def enabled_rows(self):
        return [i for i, r in enumerate(self.rows()) if r.enabled]

    def current_row(self):
        rows = self.rows()
        en = self.enabled_rows()
        if not en:
            return None
        if self.row[self.tab] not in en:
            self.row[self.tab] = en[0]
        return rows[self.row[self.tab]]

    # ---- keys
    def key(self, k):
        """Handle one key; returns a list of actions: ("request", cmd, args), ("refresh",), ("quit",)."""
        if k in ("q", "esc", "ctrl-c"):
            return [("quit",)]
        if k in ("tab", "backtab"):
            self.tab = (self.tab + (1 if k == "tab" else -1)) % len(TABS)
            return []
        if k in ("1", "2", "3", "4"):
            self.tab = int(k) - 1
            return []
        if k == "r":
            for t in range(len(TABS)):
                self.sync(t)
            return [("refresh",)]
        if k == "g":
            return [("request", "thermal.gmode", {"on": "toggle"})]
        if k in ("[", "]"):
            d = STEP if k == "]" else -STEP
            if self.tab == 1:
                cur = int(self.cfg("chassis").get("brightness", 100))
                return [("request", "chassis.brightness", {"value": max(0, min(100, cur + d))})]
            cur = int(self.cfg("keyboard").get("brightness", 100))
            return [("request", "keyboard.brightness", {"value": max(0, min(100, cur + d))})]
        row = self.current_row()
        if row is None:
            return []
        if k in ("up", "down"):
            en = self.enabled_rows()
            i = en.index(self.row[self.tab])
            self.row[self.tab] = en[(i + (1 if k == "down" else -1)) % len(en)]
            return []
        if k in ("left", "right"):
            i = row.index(self.value(row.key))
            i = 0 if i is None else (i + (1 if k == "right" else -1)) % len(row.options)
            self.draft[(self.tab, row.key)] = row.options[i][0]
            if self.tab in (0, 1):
                self.dirty.add(self.tab)
            return []
        if k == "enter":
            return self.apply(row)
        return []

    def apply(self, row=None):
        v = self.value
        if self.tab == 0:
            eff = v("effect")
            if eff in ("off", "fire"):
                args = {"name": eff}
            else:
                args = {"name": eff, "on": "static"}
                if eff in tty.KB_COLORED:
                    args["colors"] = [v("color")]
                if eff in tty.KB_SPEEDS:
                    args["speed"] = v("speed")
                if eff == "wave":
                    args["direction"] = v("direction")
            self.dirty.discard(0)
            return [("request", "keyboard.effect", args)]
        if self.tab == 1:
            eff = v("effect")
            self.dirty.discard(1)
            if eff == "static":
                return [("request", "chassis.color", {"zone": v("zone"), "color": v("color")})]
            if eff == "off":
                return [("request", "chassis.effect", {"name": "off"})]
            args = {"name": eff, "duration_ms": v("duration")}
            if eff in ("breathing", "pulse", "morph"):
                args["colors"] = [v("color")]
            return [("request", "chassis.effect", args)]
        if self.tab == 2 and row is not None:
            val = v(row.key)
            if row.key == "mode":
                return [("request", "thermal.mode", {"name": val})]
            if row.key == "auto":
                return [("request", "thermal.auto", {"on": bool(val)})]
            if row.key == "boost":
                return [("request", "thermal.boost", {"value": val, "fan": None})]
            if row.key == "tcc":
                return [("request", "thermal.tcc", {"value": val})]
        return []

    def preview(self):
        """The keyboard and chassis configs the mirror should show (draft while editing)."""
        kb = self.cfg("keyboard")
        ch = self.cfg("chassis")
        if 0 in self.dirty:
            kb.update({"effect": self.value("effect", 0), "colors": [self.value("color", 0)],
                       "speed": self.value("speed", 0), "direction": self.value("direction", 0), "on": "static"})
        if 1 in self.dirty:
            eff = self.value("effect", 1)
            ch.update({"effect": eff, "colors": [self.value("color", 1)], "duration_ms": self.value("duration", 1)})
            if eff == "static":
                zone = self.value("zone", 1)
                zones = dict(ch.get("zones") or {}) if zone != "all" else {}
                if zone != "all":
                    zones[zone] = self.value("color", 1)
                ch["zones"] = zones
        return kb, ch


def _boost_now(th):
    fans = th.get("fans") or []
    pcts = [f.get("boost_pct") or 0 for f in fans]
    top = max(pcts) if pcts else 0
    if not top:
        return None
    return min((b for b, _ in BOOSTS if b), key=lambda b: abs(b - top))


# --------------------------------------------------------------------------- drawing
def _row_line(term, state, row, is_cur):
    d = term.dim
    label = row.label.ljust(10)
    head = (term.tone(term.g("▸ "), tty.MAGENTA, bold=True) if is_cur else "  ") + \
        (term.bold(label) if is_cur else d(label) if row.enabled else d(label))
    sel = state.value(row.key)
    parts = []
    for v, text in row.options:
        active = v == sel
        if row.kind == "swatch":
            if not term.color:
                parts.append(f"[{text}]" if active else f" {text[:3]} ")
                continue
            block = term.paint(term.g("██"), fg=fx.parse_hex(v)) if row.enabled else term.paint(term.g("░░"), fg=fx.parse_hex(v))
            if active:
                parts.append(term.paint("[", bold=True, underline=is_cur) + block + term.paint("]", bold=True, underline=is_cur))
            else:
                parts.append(" " + block + " ")
        else:
            parts.append(tty.chip(term, term.g(text), active=active and row.enabled, cursor=is_cur and active,
                                  disabled=not row.enabled))
    return head + " " + "".join(parts)


def tab_bar(term, state, width):
    out = []
    for i, name in enumerate(TABS):
        label = f" {i + 1} {name} "
        out.append(term.paint(label, reverse=True, bold=True) if i == state.tab else term.dim(label))
    return " " + " ".join(out)


def body(term, state, width, t):
    d = term.dim
    lines = []
    st = state.status or {}
    if state.tab in (0, 1, 2):
        rows = state.rows()
        cur = state.current_row()
        for r in rows:
            lines.append(_row_line(term, state, r, cur is not None and r.key == cur.key))
    if state.tab == 0:
        kb = state.cfg("keyboard")
        b = int(kb.get("brightness", 100))
        lines.append("  " + d("Brightness".ljust(10)) + " " + tty.gauge(term, b / 100, 20, tty.CYAN) + f" {b:>3}%  " + d("[ ]"))
        if 0 in state.dirty:
            lines.append("")
            lines.append("  " + term.tone("preview", tty.MAGENTA, bold=True) + d(" · ⏎ applies it, r drops it"))
    elif state.tab == 1:
        ch = state.cfg("chassis")
        b = int(ch.get("brightness", 100))
        lines.append("  " + d("Brightness".ljust(10)) + " " + tty.gauge(term, b / 100, 20, tty.CYAN) + f" {b:>3}%  " + d("[ ]"))
        if not st.get("chassis"):
            lines.append("  " + term.tone("lighting controller not reachable: changes are saved and applied when it is", tty.YELLOW))
        if 1 in state.dirty:
            lines.append("")
            lines.append("  " + term.tone("preview", tty.MAGENTA, bold=True) + d(" · ⏎ applies it, r drops it"))
    elif state.tab == 2:
        th = st.get("thermal")
        if not th:
            lines.append("  " + d("no Alienware thermal interface on this machine"))
        else:
            lines.append("")
            lines.extend("  " + ln for ln in tty.thermal_lines(term, th, state.cfg("thermal"), width - 2))
            lines.append("  " + d("g toggles G-Mode · ⏎ applies the selected row"))
    elif state.tab == 3:
        pb = state.cfg("power_button")
        lines.append("  " + term.bold("Power button") + d("  colour per power state (saved in the controller's flash)"))
        for s in ("ac-full", "ac-charging", "ac-sleep", "dc-on", "dc-low", "dc-sleep"):
            col = pb.get(s)
            val = tty.swatch(term, col, 2, hex_label=True) if col else d("not set by mothership")
            lines.append(f"    {d(tty.POWER_LABELS[s].ljust(17))}{val}")
        lines.append("  " + d("Read-only here: these writes go to flash. Use the CLI:"))
        lines.append("  " + d("  mothership power set <state|all> RRGGBB --write-flash"))
        th = st.get("thermal") or {}
        extra = []
        gm = (st.get("graphics") or {}).get("mode")
        if gm:
            extra.append(d("Graphics  ") + gm + d("  (mothership graphics change)"))
        if th.get("ac") is not None:
            extra.append(d("Power     ") + ("AC adapter" if th["ac"] else term.tone("battery", tty.YELLOW)))
        if extra:
            lines.append("")
            lines.extend("  " + e for e in extra)
    return lines


MAX_W = 104


def frame(term, state, width, height, t, toast=None, live=True):
    """All screen lines for one frame (exactly `height` lines, each clipped to width). The
    content is a column at most MAX_W wide, centred in wide terminals."""
    full = width
    width = min(width, MAX_W)
    margin = " " * ((full - width) // 2)
    st = state.status or {}
    lines = [tty.header(term, st) if st else term.bold("mothership")]
    tag = term.tone(term.g("●") + " live", tty.GREEN) if live else term.tone(term.g("●") + " offline", tty.RED)
    head = lines[0]
    if tty.vlen(head) + tty.vlen(tag) + 2 <= width:
        lines[0] = head + " " * (width - tty.vlen(head) - tty.vlen(tag) - 1) + tag
    lines.append("")
    kb, ch = state.preview()
    kst = st.get("keyboard") or {}
    devs = st.get("devices") or {}
    body_lines = body(term, state, width, t)
    room = height - len(body_lines) - 7
    if (kst or devs.get("keyboard")) and kb:
        tall = room >= 14
        if room >= 8:
            kw = tty.fit_width(width - 4)
            pad = " " * max(2, (width - kw) // 2)
            for ln in tty.keyboard(term, tty.key_colors(kb, t), kw, unlit=kst.get("unlit") or (), tall=tall):
                lines.append(pad + ln)
    if st.get("chassis") or devs.get("chassis"):
        cc = tty.chassis_colors(ch, (st.get("chassis") or {}).get("zones") or (), t)
        strip = tty.chassis_strip(term, cc)
        lines.append(" " * max(2, (width - tty.vlen(strip)) // 2) + strip)
    lines.append("")
    lines.append(tab_bar(term, state, width))
    lines.append(term.dim(term.g("─") * width))
    lines.extend(body_lines)
    help_ = term.dim(term.g("tab/1-4 section  ↑↓ row  ←→ choose  ⏎ apply  [ ] brightness  g G-Mode  r refresh  q quit"))
    foot = [toast or "", help_]
    lines = lines[: max(0, height - len(foot))]
    lines += [""] * (height - len(foot) - len(lines))
    lines += foot
    return [tty.clip(margin + ln if ln else ln, full) for ln in lines[:height]]


# --------------------------------------------------------------------------- terminal app
class App:
    def __init__(self, request=ipc.request, out=None, inp=None):
        self.request = request
        self.out = out or sys.stdout
        self.inp = inp or sys.stdin
        self.state = State()
        self.lock = threading.Lock()
        self.live = False
        self.error = None
        self.toast = None
        self.toast_at = 0.0
        self.jobs = queue.Queue()
        self.stop = threading.Event()
        self.poke = threading.Event()
        self.prev = []
        self.size = (0, 0)
        self.term = tty.Term.detect(self.out)
        ssh = os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY")
        self.fps = 8 if ssh else 15

    # ---- background
    def poll(self):
        while not self.stop.is_set():
            try:
                st = self.request("status", {})
                with self.lock:
                    self.state.set_status(st)
                    self.live = True
                    self.error = None
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
                with self.lock:
                    self.live = False
                    self.error = str(e)
            self.poke.wait(2.0)
            self.poke.clear()

    def worker(self):
        while not self.stop.is_set():
            try:
                cmd, args = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            term = self.term
            try:
                result = self.request(cmd, args)
                msg = tty.render_result(term, cmd, args, result).split("\n")[0]
                warn = tty.warnings(term, cmd, result)
                if warn:
                    msg += "  " + term.tone(warn, tty.YELLOW)
            except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
                msg = term.tone(term.g("✗ "), tty.RED, bold=True) + tty.short_error(e)
            with self.lock:
                self.toast, self.toast_at = msg, time.monotonic()
            self.poke.set()

    # ---- terminal
    def write(self, s):
        data = s.encode("utf-8", "replace")
        fd = self.out.fileno()
        while data:
            n = os.write(fd, data)
            data = data[n:]

    def draw(self, t):
        cols, rows = os.get_terminal_size(self.out.fileno())
        if cols <= 0 or rows <= 0:            # serial consoles / some ptys report 0x0
            cols, rows = int(os.environ.get("COLUMNS", 80) or 80), int(os.environ.get("LINES", 24) or 24)
        if (cols, rows) != self.size:
            self.size = (cols, rows)
            self.prev = []
            self.write("\x1b[2J")
        self.term.width = cols
        with self.lock:
            toast = self.toast if self.toast and time.monotonic() - self.toast_at < TOAST_S else None
            if not self.live and self.error:
                toast = self.term.tone(tty.short_error(self.error), tty.RED)
            lines = frame(self.term, self.state, cols, rows, t, toast, self.live)
        buf = []
        for i, ln in enumerate(lines):
            if i < len(self.prev) and self.prev[i] == ln:
                continue
            buf.append(f"\x1b[{i + 1};1H\x1b[0m{ln}\x1b[0m\x1b[K")
        self.prev = lines
        if buf:
            self.write("\x1b[?2026h" + "".join(buf) + "\x1b[?2026l")

    def run(self):
        import termios
        self.term = tty.Term.detect(self.out)
        fd = self.inp.fileno()
        old = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[3] &= ~(termios.ECHO | termios.ICANON)
        new[6][termios.VMIN], new[6][termios.VTIME] = 0, 0
        prev_term = signal.getsignal(signal.SIGTERM)
        prev_hup = signal.getsignal(signal.SIGHUP)

        def bye(*_):
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, bye)
        signal.signal(signal.SIGHUP, bye)
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
            self.write("\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[2J")
            threading.Thread(target=self.poll, daemon=True).start()
            threading.Thread(target=self.worker, daemon=True).start()
            t0 = time.monotonic()
            period = 1.0 / self.fps
            while True:
                start = time.monotonic()
                self.draw(start - t0)
                deadline = start + period
                while True:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        break
                    r, _, _ = select.select([fd], [], [], left)
                    if not r:
                        break
                    data = os.read(fd, 1024).decode("utf-8", "replace")
                    if not data:
                        break
                    for k in parse_keys(data):
                        with self.lock:
                            actions = self.state.key(k)
                        for a in actions:
                            if a[0] == "quit":
                                return 0
                            if a[0] == "refresh":
                                self.poke.set()
                            if a[0] == "request":
                                self.jobs.put((a[1], a[2]))
                    self.draw(time.monotonic() - t0)
        except KeyboardInterrupt:
            return 0
        finally:
            self.stop.set()
            self.poke.set()
            try:
                self.write("\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l")
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                signal.signal(signal.SIGTERM, prev_term)
                signal.signal(signal.SIGHUP, prev_hup)


def main():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("mothership tui: needs an interactive terminal (try `mothership status`)", file=sys.stderr)
        return 2
    return App().run()
