"""mothership command line. Talks to the daemon (mothershipd); `mothership daemon` runs it."""
import argparse
import json
import sys

from . import __version__, ipc
from . import keyboard as kb_mod

KB_EFFECTS = ["static", "breathing", "wave", "scanner", "spectrum", "aurora", "gradient", "static-blue", "fire",
              "perkey", "off"]
CH_EFFECTS = ["static", "breathing", "pulse", "morph", "spectrum", "wave", "off"]
POWER_STATES = ["all", "ac-sleep", "ac-full", "ac-charging", "dc-sleep", "dc-on", "dc-low"]


def color(s):
    try:
        kb_mod.parse_color(s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None
    return s.lstrip("#").lower()


def pct(s):
    v = int(s)
    if not 0 <= v <= 100:
        raise argparse.ArgumentTypeError("must be 0-100")
    return v


def parser():
    p = argparse.ArgumentParser(prog="mothership", description="Alienware lighting, thermal and firmware control.")
    p.add_argument("--json", action="store_true", help="print raw JSON")
    p.add_argument("--version", action="version", version=f"mothership {__version__}")
    sub = p.add_subparsers(dest="group", required=True)

    sub.add_parser("status", help="devices, lighting, thermal")
    sub.add_parser("devices", help="detected hardware")
    sub.add_parser("reapply", help="re-send the configured lighting")
    sub.add_parser("daemon", help="run the daemon (the user unit does this)")
    sub.add_parser("tui", help="full-screen terminal control panel with a live mirror")

    kb = sub.add_parser("kb", aliases=["keyboard"], help="keyboard lighting").add_subparsers(dest="verb", required=True)
    e = kb.add_parser("effect", help="firmware effect, fire, or off")
    e.add_argument("name", choices=KB_EFFECTS)
    e.add_argument("--color", "-c", type=color, action="append", dest="colors", help="RRGGBB (repeat for 2)")
    e.add_argument("--speed", type=int, choices=[0, 1, 2])
    e.add_argument("--dir", dest="direction", choices=list(kb_mod.DIRECTIONS))
    e.add_argument("--on", choices=list(kb_mod.PLAY), default="static", help="firmware: light on key press/release")
    b = kb.add_parser("brightness"); b.add_argument("value", type=pct)
    s = kb.add_parser("static"); s.add_argument("color", type=color)
    r = kb.add_parser("reactive", help="light keys as they are pressed (firmware)")
    r.add_argument("color", type=color); r.add_argument("--release", action="store_true")
    k = kb.add_parser("key", help="set single keys: LED=RRGGBB ...")
    k.add_argument("assign", nargs="+")
    kb.add_parser("off")
    kb.add_parser("fire", help="the fire effect (pressed keys flare)")

    ch = sub.add_parser("chassis", aliases=["lights"], help="lid / rear / touchpad lights").add_subparsers(dest="verb", required=True)
    c = ch.add_parser("color"); c.add_argument("zone", help="all, head, rear, touchpad, rear_left, rear_right")
    c.add_argument("color", type=color)
    ce = ch.add_parser("effect"); ce.add_argument("name", choices=CH_EFFECTS)
    ce.add_argument("--color", "-c", type=color, action="append", dest="colors")
    ce.add_argument("--duration", type=int, dest="duration_ms", help="cycle length in ms")
    cb = ch.add_parser("brightness"); cb.add_argument("value", type=pct)
    ch.add_parser("off")

    pw = sub.add_parser("power", help="power-button colours per power state (saved in the controller)").add_subparsers(dest="verb", required=True)
    pw.add_parser("show")
    ps = pw.add_parser("set"); ps.add_argument("state", choices=POWER_STATES); ps.add_argument("color", type=color)
    ps.add_argument("--write-flash", action="store_true", help="required: this writes the controller's flash")

    fa = sub.add_parser("fans", aliases=["thermal"], help="thermal mode and fans").add_subparsers(dest="verb")
    fa.add_parser("status")
    m = fa.add_parser("mode"); m.add_argument("name")
    bo = fa.add_parser("boost"); bo.add_argument("value", help="0-100 or off"); bo.add_argument("--fan", type=int)
    au = fa.add_parser("auto"); au.add_argument("state", choices=["on", "off"])
    tc = fa.add_parser("tcc", help="lower the CPU's throttle temperature by 0-15 °C (cooler, quieter)")
    tc.add_argument("value", type=int, choices=range(0, 16), metavar="0-15")
    pl = fa.add_parser("power-limit", help="CPU package power limit in watts, per thermal mode or for all")
    pl.add_argument("value", help="watts, or off"); pl.add_argument("--mode", help="thermal mode (default: all)")

    pr = sub.add_parser("profile", help="per-app profiles: lighting/thermal while a matching window is focused").add_subparsers(dest="verb", required=True)
    pr.add_parser("list")
    pa = pr.add_parser("add", help='e.g. mothership profile add wow --match "^wow" --kb spectrum --mode gmode')
    pa.add_argument("name"); pa.add_argument("--match", required=True, help="regex on the window class")
    pa.add_argument("--title", help="regex on the window title (alternative match)")
    pa.add_argument("--kb", choices=KB_EFFECTS, help="keyboard effect"); pa.add_argument("--kb-color", type=color)
    pa.add_argument("--chassis", choices=CH_EFFECTS); pa.add_argument("--chassis-color", type=color)
    pa.add_argument("--mode", help="thermal mode name, or gmode")
    prr = pr.add_parser("remove"); prr.add_argument("name")

    sub.add_parser("probe", help="map an unknown model's chassis lights to zones (lights one LED at a time)")

    mc = sub.add_parser("macro", help="firmware macros on the macro keys (F2-F6), saved in the keyboard").add_subparsers(dest="verb", required=True)
    mc.add_parser("keys")
    ms = mc.add_parser("set", help='e.g. mothership macro set F2 "ctrl+shift+t" --write-flash')
    ms.add_argument("key"); ms.add_argument("keys", help="steps separated by spaces, keys joined by +, delays like 200ms")
    ms.add_argument("--write-flash", action="store_true")
    mx = mc.add_parser("clear"); mx.add_argument("key"); mx.add_argument("--write-flash", action="store_true")

    fw = sub.add_parser("firmware", help="lighting controller firmware (AW-ELC)").add_subparsers(dest="verb", required=True)
    fc = fw.add_parser("check", help="validate an image against this machine (changes nothing)")
    fc.add_argument("image", help="Dell's elc-*-vX.Y.Z.hex (from the AWCC package)")
    fc.add_argument("--allow-downgrade", action="store_true")
    fb = fw.add_parser("backup", help="read the controller's whole flash to a file (root)")
    fb.add_argument("--dir", default="/var/lib/mothership/firmware")
    fu = fw.add_parser("update", help="back up, write and verify an image (root; at your own risk)")
    fu.add_argument("image"); fu.add_argument("--dir", default="/var/lib/mothership/firmware")
    fu.add_argument("--allow-downgrade", action="store_true")
    fu.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    fr = fw.add_parser("restore", help="write a backup's application area back (root; at your own risk)")
    fr.add_argument("backup"); fr.add_argument("--dir", default="/var/lib/mothership/firmware")
    fr.add_argument("--yes", action="store_true")

    gr = sub.add_parser("graphics", help="graphics mode (hybrid or discrete GPU only)")
    gr.add_argument("action", nargs="?", choices=["status", "change"], default="status",
                    help="change: restart into the firmware setup screen to switch it")
    gr.add_argument("--yes", action="store_true", help="restart without asking")

    g = sub.add_parser("gmode", help="G-Mode (full performance)"); g.add_argument("state", choices=["on", "off", "toggle"], nargs="?", default="toggle")
    return p


def to_request(a):
    g = a.group
    if g in ("status", "devices", "reapply"):
        return g, {}
    if g in ("kb", "keyboard"):
        if a.verb == "effect":
            args = {"name": a.name, "on": a.on}
            for key in ("colors", "speed", "direction"):
                if getattr(a, key) is not None:
                    args[key] = getattr(a, key)
            return "keyboard.effect", args
        if a.verb == "brightness":
            return "keyboard.brightness", {"value": a.value}
        if a.verb == "static":
            return "keyboard.effect", {"name": "static", "colors": [a.color], "on": "static"}
        if a.verb == "reactive":
            return "keyboard.reactive", {"color": a.color, "on": "release" if a.release else "press"}
        if a.verb == "key":
            keys = {}
            for item in a.assign:
                led, _, col = item.partition("=")
                keys[int(led)] = color(col)
            return "keyboard.keys", {"keys": keys}
        if a.verb == "off":
            return "keyboard.effect", {"name": "off"}
        if a.verb == "fire":
            return "keyboard.effect", {"name": "fire"}
    if g in ("chassis", "lights"):
        if a.verb == "color":
            return "chassis.color", {"zone": a.zone, "color": a.color}
        if a.verb == "effect":
            args = {"name": a.name}
            if a.colors:
                args["colors"] = a.colors
            if a.duration_ms:
                args["duration_ms"] = a.duration_ms
            return "chassis.effect", args
        if a.verb == "brightness":
            return "chassis.brightness", {"value": a.value}
        if a.verb == "off":
            return "chassis.effect", {"name": "off"}
    if g == "power":
        if a.verb == "show":
            return "power.show", {}
        return "power.set", {"state": a.state, "color": a.color, "write_flash": a.write_flash}
    if g in ("fans", "thermal"):
        v = a.verb or "status"
        if v == "status":
            return "thermal.status", {}
        if v == "mode":
            return "thermal.mode", {"name": a.name}
        if v == "boost":
            return "thermal.boost", {"value": None if a.value == "off" else int(a.value), "fan": a.fan}
        if v == "auto":
            return "thermal.auto", {"on": a.state == "on"}
        if v == "tcc":
            return "thermal.tcc", {"value": a.value}
        if v == "power-limit":
            return "thermal.power_limit", {"value": None if a.value == "off" else int(a.value), "mode": a.mode}
    if g == "profile":
        if a.verb == "list":
            return "profiles.get", {}
        cur = ipc.request("profiles.get", {})["profiles"]
        cur = [p for p in cur if p.get("name") != a.name]
        if a.verb == "add":
            p = {"name": a.name, "match": a.match}
            if a.title:
                p["title"] = a.title
            if a.kb:
                p["keyboard"] = {"effect": a.kb, **({"colors": [a.kb_color]} if a.kb_color else {})}
            if a.chassis:
                p["chassis"] = {"effect": a.chassis, **({"colors": [a.chassis_color], "zones": {}} if a.chassis_color else {})}
            if a.mode:
                p["thermal"] = {"mode": a.mode}
            cur.append(p)
        return "profiles.set", {"profiles": cur}
    if g == "macro":
        if a.verb == "keys":
            return "macro.keys", {}
        if not a.write_flash:
            raise SystemExit("mothership: macros are stored in the keyboard's flash; run again with --write-flash")
        if a.verb == "set":
            from . import macros
            macros.encode(macros.parse(a.keys))            # validate before sending
            return "macro.set", {"key": a.key, "keys": a.keys, "write_flash": True}
        return "macro.clear", {"key": a.key, "write_flash": True}
    if g == "gmode":
        return "thermal.gmode", {"on": {"on": True, "off": False}.get(a.state, "toggle")}
    raise SystemExit(f"mothership: nothing to do for {g}")


def elc_device():
    from . import elc, hidraw
    paths = hidraw.find(0x187C, {0x0550, 0x0551})
    if not paths:
        raise SystemExit("mothership: no AW-ELC lighting controller found (or it is in its bootloader)")
    with hidraw.Hid(paths[0]) as h:
        info = elc.Elc(h).info()
    return {"pid": hidraw.product_id(paths[0]), "firmware": info["firmware"], "platform": info["platform"]}


FLASH_WARNING = ("mothership is not Dell software. Flashing writes to a controller inside your laptop: a failed or\n"
                 "interrupted update, a power loss or a wrong image can leave the lighting controller unusable, and\n"
                 "a repair can need a new motherboard. The firmware you supply stays Dell's. No warranty (see LICENSE).")


def firmware_cmd(a):
    import os
    from . import firmware as fw
    try:
        if a.verb == "check":
            dev = elc_device()
            img = fw.inspect_image(a.image)
            problems = fw.check(img, dev, a.allow_downgrade)
            print(f"controller: {dev['pid']:04x} firmware {dev['firmware']} (platform {dev['platform']})")
            print(f"image:      {fw.fmt_version(img['version'])}, {img['size']} bytes at 0x{img['start']:08x}, "
                  f"for {', '.join(f'{p:04x}' for p in img['pids'])}")
            print("ok to update" if not problems else "not ok: " + "; ".join(problems))
            return 0 if not problems else 1
        if os.geteuid() != 0:
            raise fw.FirmwareError("run with sudo: resetting the controller and DFU need root")
        os.makedirs(a.dir, exist_ok=True)
        if a.verb == "backup":
            dev = elc_device()
            path = os.path.join(a.dir, f"elc-{dev['pid']:04x}-v{dev['firmware']}-backup.bin")
            fw.enter_bootloader()
            try:
                fw.backup(path)
            finally:
                fw.leave_bootloader()
            print(path)
            return 0
        if a.verb == "update":
            dev = elc_device()
            img = fw.inspect_image(a.image)
            problems = fw.check(img, dev, a.allow_downgrade)
            if problems:
                raise fw.FirmwareError("; ".join(problems))
            print(FLASH_WARNING)
            if not a.yes:
                ans = input(f"Update the lighting controller from {dev['firmware']} to {fw.fmt_version(img['version'])}? "
                            "It is backed up first. Type 'update' to continue: ")
                if ans.strip() != "update":
                    print("cancelled")
                    return 1
            r = fw.update(a.image, a.dir, dev, a.allow_downgrade)
            print(f"updated; backup: {r['backup']}")
            print(f"controller now reports {elc_device()['firmware']}")
            return 0
        if a.verb == "restore":
            print(FLASH_WARNING)
            if not a.yes and input("Write this backup's application back to the controller? Type 'restore': ").strip() != "restore":
                print("cancelled")
                return 1
            fw.enter_bootloader()
            fw.restore(a.backup, a.dir)
            fw.leave_bootloader()
            print(f"restored; controller reports {elc_device()['firmware']}")
            return 0
    except fw.FirmwareError as e:
        print(f"mothership: {e}", file=sys.stderr)
        return 1


def show(result, as_json, cmd=None, args=None, context=None):
    if as_json:
        print(json.dumps(result, indent=None) if not isinstance(result, str) else result)
        return
    from . import tty
    term = tty.Term.detect()
    if cmd is None:
        print(result if isinstance(result, str) else json.dumps(result, indent=2))
        return
    print(tty.render_result(term, cmd, args, result, context))
    warn = tty.warnings(term, cmd, result)
    if warn:
        print(warn, file=sys.stderr)


def main(argv=None):
    a = parser().parse_args(argv)
    if a.group == "daemon":
        from . import daemon
        return daemon.main()
    if a.group == "tui":
        from . import tui
        return tui.main()
    if a.group == "firmware":
        return firmware_cmd(a)
    if a.group == "probe":
        from . import elc, hidraw, probe
        paths = hidraw.find(0x187C, {0x0550, 0x0551})
        if not paths:
            print("mothership: no AW-ELC lighting controller found", file=sys.stderr)
            return 1
        with hidraw.Hid(paths[0]) as h:
            probe.run(elc.Elc(h))
        try:
            ipc.request("reapply", {})
        except (ConnectionError, RuntimeError, TimeoutError):
            pass
        return 0
    if a.group == "graphics":
        from . import graphics
        m = graphics.mode()
        if a.action == "status":
            show(m, a.json, "graphics", {})
            return 0
        names = {"hybrid": "hybrid (integrated GPU drives the screen)", "discrete": "discrete GPU only"}
        print(f"Graphics mode now: {names.get(m['mode'], m['mode'])}.\n"
              "The computer restarts into its setup screen: change the graphics/display mode option there, "
              "then save and exit.")
        if not a.yes and input("Restart now? Type 'restart': ").strip() != "restart":
            print("cancelled")
            return 1
        graphics.reboot_to_firmware_setup(confirm=True)
        return 0
    if a.group == "power" and getattr(a, "verb", None) == "set" and not a.write_flash:
        print("mothership: power-button colours are stored in the lighting controller's flash.\n"
              "Run again with --write-flash to do it (avoid doing this often).", file=sys.stderr)
        return 2
    cmd, args = to_request(a)
    try:
        result = ipc.request(cmd, args)
    except ConnectionError:
        print("mothership: the daemon isn't running (systemctl --user start mothershipd)", file=sys.stderr)
        return 3
    except TimeoutError:
        print("mothership: the daemon didn't answer in time", file=sys.stderr)
        return 3
    except RuntimeError as e:
        print(f"mothership: {e}", file=sys.stderr)
        return 1
    context = {"verb": getattr(a, "verb", None), "name": getattr(a, "name", None)}
    if cmd == "thermal.status" and not a.json:
        try:
            context["thermal_cfg"] = (ipc.request("config.get", {}) or {}).get("thermal")
        except (ConnectionError, TimeoutError, RuntimeError):
            pass
    show(result, a.json, cmd, args, context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
