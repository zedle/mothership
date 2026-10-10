"""Map an unknown AW-ELC lighting controller's LEDs to zones, interactively.

Lights one LED at a time (white, from the controller's RAM: nothing is saved in it) and asks
what lit up. The answers become a zone map saved to ~/.config/mothership/zones/<platform>.json,
which mothership uses for that controller from then on, and which can be contributed to
mothership/data/devices.json. The power button usually ignores these colours (it shows its own
per-power-state animation), so an LED that lights nothing is offered as the power button.
"""
import json
import os

from . import config as cfgmod

ANSWERS = {
    "l": "head", "logo": "head", "lid": "head", "h": "head", "head": "head",
    "rl": "rear_left", "rear left": "rear_left", "rr": "rear_right", "rear right": "rear_right",
    "r": "rear", "rear": "rear",
    "t": "touchpad", "touchpad": "touchpad",
    "k": "keyboard", "keyboard": "keyboard",
    "o": "other", "other": "other",
    "n": "nothing", "nothing": "nothing", "": "nothing",
}
PROMPT = ("What lit up?  [l] lid logo  [rl] rear left  [rr] rear right  [r] rear  [t] touchpad  "
          "[k] keyboard  [o] other  [n/Enter] nothing  [q] stop: ")


def zones_dir():
    return os.path.join(os.path.dirname(cfgmod.config_path()), "zones")


def user_map_path(platform):
    return os.path.join(zones_dir(), f"{platform}.json")


def load_user_map(platform):
    try:
        with open(user_map_path(platform)) as f:
            m = json.load(f)
        return m if isinstance(m, dict) and isinstance(m.get("zones"), dict) else None
    except (OSError, ValueError):
        return None


def build_map(answers, led_count):
    """answers: {led: zone name} -> a devices.json-style chassis map."""
    zones = {}
    for led in range(led_count):
        z = answers.get(led, "nothing")
        if z == "nothing":
            continue
        zones.setdefault(z, []).append(led)
    dark = [led for led in range(led_count) if answers.get(led, "nothing") == "nothing"]
    if len(dark) == 1 and "power" not in zones:
        zones["power"] = dark                  # the power button ignores static colours
    groups = {}
    if "rear_left" in zones or "rear_right" in zones:
        groups["rear"] = [z for z in ("rear_left", "rear_right") if z in zones]
    groups["lights"] = [z for z in zones if z != "power"]
    columns = [[led] for z in groups["lights"] for led in zones[z]]
    return {"zones": zones, "groups": groups, "columns": columns, "power_states": "power" in zones,
            "_probed": True}


def run(elc, ask=input, say=print):
    info = elc.info()
    count, platform = info["leds"], info["platform"]
    say(f"Lighting controller {platform}, firmware {info['firmware']}, {count} LEDs.")
    say("Each LED lights up white on its own; everything else goes dark. Look at the lid, the back "
        "and the touchpad.")
    answers = {}
    try:
        for led in range(count):
            others = [z for z in range(count) if z != led]
            elc.static({(255, 255, 255): [led], (0, 0, 0): others})
            while True:
                a = ask(f"LED {led:2d}: {PROMPT}").strip().lower()
                if a == "q":
                    raise KeyboardInterrupt
                if a in ANSWERS:
                    answers[led] = ANSWERS[a]
                    break
                say("  type one of the letters in brackets")
    except (KeyboardInterrupt, EOFError):
        say("\nStopped; LEDs not asked about count as nothing.")
    m = build_map(answers, count)
    os.makedirs(zones_dir(), exist_ok=True)
    path = user_map_path(platform)
    with open(path, "w") as f:
        json.dump(m, f, indent=2)
        f.write("\n")
    say(f"\nSaved {path}; mothership uses it for this controller from now on.")
    say("To add your model to mothership, open an issue or pull request with this map:\n")
    say(json.dumps({platform: {k: v for k, v in m.items() if not k.startswith("_")}}, indent=2))
    return m
