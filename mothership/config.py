"""User settings (the desired state) and daemon state files.

`config.json` holds what the user asked for: the daemon applies it at start, after resume and
when a device reappears. `load()` never fails on a bad file: a file that is not valid JSON, or a
section of the wrong type, falls back to the defaults for that part and keeps everything else;
what was wrong is listed in `cfg["_warnings"]` (never saved) so the caller can log it once.
Unknown sections and keys are kept, so a newer config survives an older daemon.
"""
import copy
import json
import os
import tempfile

DEFAULTS = {
    "keyboard": {"effect": "static", "colors": ["ff2000"], "speed": 1, "direction": "right",
                 "brightness": 100, "on": "static", "fire": False},
    "chassis": {"effect": "static", "colors": ["00ff00"],
                "zones": {"head": "00ff00", "rear": "ff0000", "touchpad": "ff0000"},
                "brightness": 100, "duration_ms": 3000},
    "thermal": {"auto": True},
    "power_button": {},  # last values written to flash, informational only
}

WARNINGS = "_warnings"


def _xdg(var, fallback):
    d = os.environ.get(var, "")
    if not os.path.isabs(d):  # the XDG spec says relative values are invalid and ignored
        d = os.path.join(os.path.expanduser("~"), fallback)
    return d


def config_path():
    return os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "mothership", "config.json")


def state_path():
    return os.path.join(_xdg("XDG_STATE_HOME", os.path.join(".local", "state")), "mothership", "state.json")


def _merge(base, over, where, warnings):
    """Deep-merge `over` into a copy of `base`. A nested dict in the defaults only takes a dict."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(out.get(k), dict):
            if isinstance(v, dict):
                out[k] = _merge(out[k], v, f"{where}.{k}", warnings)
            else:
                warnings.append(f"{where}.{k}: expected an object, got {type(v).__name__}; using defaults")
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(path=None):
    path = path or config_path()
    cfg = copy.deepcopy(DEFAULTS)
    warnings = []
    data = None
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = None
    except (OSError, UnicodeDecodeError) as e:
        text = None
        warnings.append(f"{path}: cannot read ({e}); using defaults")
    if text is not None:
        try:
            data = json.loads(text)
        except ValueError as e:
            warnings.append(f"{path}: not valid JSON ({e}); using defaults")
        else:
            if not isinstance(data, dict):
                warnings.append(f"{path}: expected an object, got {type(data).__name__}; using defaults")
                data = None
    for section, value in (data or {}).items():
        if section == WARNINGS:
            continue
        if section in DEFAULTS:
            if isinstance(value, dict):
                cfg[section] = _merge(DEFAULTS[section], value, section, warnings)
            else:
                warnings.append(f"{section}: expected an object, got {type(value).__name__}; using defaults")
        else:
            cfg[section] = value  # unknown section: kept as-is
    cfg[WARNINGS] = warnings
    return cfg


def save(cfg, path=None):
    """Write atomically: a temp file in the same directory, fsync, then os.replace."""
    path = path or config_path()
    data = {k: v for k, v in cfg.items() if k != WARNINGS}
    text = json.dumps(data, indent=2) + "\n"
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fchmod(f.fileno(), 0o644)
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:  # make the rename itself durable; not fatal where directories can't be opened
        dfd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def update(cfg, section, values):
    """Shallow-merge `values` into `cfg[section]` (created if missing or not an object); returns cfg."""
    if not isinstance(values, dict):
        raise TypeError(f"{section}: values must be an object, got {type(values).__name__}")
    if not isinstance(cfg.get(section), dict):
        cfg[section] = {}
    cfg[section].update(values)
    return cfg
