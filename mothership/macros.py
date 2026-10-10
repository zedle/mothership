"""Firmware macros on the keyboard's macro keys (F2-F6 on the x17 R2, slots 1-5 in bank 0).

The keyboard stores a macro per slot and plays it by itself: each event is
[HID usage, 0 press / 1 release, delay ms (big endian)]. Uploads go in 60-byte chunks,
`cc 73` for the first and `cc 74` for the rest, each after the keyboard reports ready
(`cc 96` reply byte 2 == 1). Storing or clearing a slot writes the keyboard's flash, so
every function here requires write_flash=True.
"""
import time

from .keyboard import pkt

MACRO_KEYS = {"F2": 1, "F3": 2, "F4": 3, "F5": 4, "F6": 5}
END = bytes([0xFF, 0x01, 0x00, 0x25])           # keystroke terminator
MAX_BYTES = 800

# USB HID keyboard usage IDs (HID Usage Tables, page 0x07).
USAGE = {**{chr(ord("a") + i): 0x04 + i for i in range(26)},
         **{str((i + 1) % 10): 0x1E + i for i in range(10)},
         "enter": 0x28, "esc": 0x29, "backspace": 0x2A, "tab": 0x2B, "space": 0x2C, "minus": 0x2D,
         "equal": 0x2E, "leftbrace": 0x2F, "rightbrace": 0x30, "backslash": 0x31, "semicolon": 0x33,
         "apostrophe": 0x34, "grave": 0x35, "comma": 0x36, "dot": 0x37, "slash": 0x38, "capslock": 0x39,
         **{f"f{i}": 0x39 + i for i in range(1, 13)},
         "print": 0x46, "scrolllock": 0x47, "pause": 0x48, "insert": 0x49, "home": 0x4A, "pageup": 0x4B,
         "delete": 0x4C, "end": 0x4D, "pagedown": 0x4E, "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
         **{f"f{i}": 0x68 + i - 13 for i in range(13, 25)},
         "mute": 0x7F, "volumeup": 0x80, "volumedown": 0x81,
         "ctrl": 0xE0, "shift": 0xE1, "alt": 0xE2, "super": 0xE3,
         "rctrl": 0xE4, "rshift": 0xE5, "ralt": 0xE6, "rsuper": 0xE7}
ALIASES = {"return": "enter", "escape": "esc", "del": "delete", "control": "ctrl", "win": "super",
           "meta": "super", "pgup": "pageup", "pgdn": "pagedown", "-": "minus", "=": "equal",
           "[": "leftbrace", "]": "rightbrace", "\\": "backslash", ";": "semicolon", "'": "apostrophe",
           "`": "grave", ",": "comma", ".": "dot", "/": "slash"}
MODIFIERS = {0xE0, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7}


def usage(name):
    n = name.strip().lower()
    n = ALIASES.get(n, n)
    if n not in USAGE:
        raise ValueError(f"unknown key {name!r}")
    return USAGE[n]


def parse(spec, step_ms=25):
    """'ctrl+shift+t' or 'h i space t h e r e' or 'ctrl+c 200ms ctrl+v' -> event records.

    Space-separated steps; a step is keys joined by '+', pressed in order and released in
    reverse; '<n>ms' sets the delay after the previous event."""
    events = []
    for step in spec.split():
        if step.endswith("ms") and step[:-2].isdigit():
            ms = max(5, min(65535, int(step[:-2])))
            if not events:
                raise ValueError("a delay needs a key before it")
            events[-1][2] = ms
            continue
        keys = [usage(k) for k in step.split("+")]
        for k in keys:
            events.append([k, 0, step_ms])
        for k in reversed(keys):
            events.append([k, 1, step_ms])
    if not events:
        raise ValueError("empty macro")
    return events


def encode(events):
    out = bytearray()
    for code, updown, ms in events:
        out += bytes([code, updown, ms >> 8, ms & 0xFF])
    out += END
    if len(out) > MAX_BYTES:
        raise ValueError(f"macro too long ({len(out)} bytes, max {MAX_BYTES})")
    return bytes(out)


def slot_of(key, bank=0):
    k = key.upper()
    if k not in MACRO_KEYS:
        raise ValueError(f"macro keys are {', '.join(MACRO_KEYS)}")
    if bank not in (0, 1, 2):
        raise ValueError("bank must be 0-2")
    return MACRO_KEYS[k] + bank * 5


def chunks(slot, data):
    """The 0x73/0x74 upload packets for one slot."""
    out = []
    for i in range(0, len(data), 60):
        cmd = 0x73 if i == 0 else 0x74
        part = data[i : i + 60]
        b = pkt(cmd, (slot << 3) | (len(data) >> 8), len(data) & 0xFF)
        b[4 : 4 + len(part)] = part
        out.append(b)
    return out


def wait_ready(kb, tries=50):
    for _ in range(tries):
        if kb.query(0x96)[2] == 1:
            return
        time.sleep(0.02)
    raise OSError("keyboard not ready for macro data")


def store(kb, key, spec, bank=0, write_flash=False):
    if write_flash is not True:
        raise PermissionError("macros are stored in the keyboard's flash; pass write_flash=True")
    slot = slot_of(key, bank)
    data = encode(parse(spec))
    for p in chunks(slot, data):
        wait_ready(kb)
        kb.send(p)
        time.sleep(0.01)
    return {"key": key.upper(), "slot": slot, "bytes": len(data)}


def clear(kb, key, bank=0, write_flash=False):
    if write_flash is not True:
        raise PermissionError("clearing a macro writes the keyboard's flash; pass write_flash=True")
    slot = slot_of(key, bank)
    wait_ready(kb)
    kb.send(pkt(0x73, slot << 3, 0x00))
    return {"key": key.upper(), "slot": slot, "cleared": True}
