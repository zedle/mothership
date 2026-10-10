"""Graphics mode (hybrid vs discrete GPU only) and the way to change it.

On laptops with a display MUX the built-in panel is wired either to the integrated GPU (hybrid:
the discrete GPU renders on demand) or straight to the discrete GPU. The mode is a firmware
setup option; changing it needs a restart through the firmware setup screen, which
`systemctl reboot --firmware-setup` opens directly. The current mode is read from which GPU's
driver owns the connected internal panel connector.
"""
import glob
import os
import subprocess

INTERNAL = ("eDP", "LVDS", "DSI")


def panel(root="/"):
    """{"connector", "driver"} of the connected internal panel, or None."""
    for c in sorted(glob.glob(os.path.join(root, "sys/class/drm/card*-*"))):
        name = os.path.basename(c).split("-", 1)[-1]
        if not name.startswith(INTERNAL):
            continue
        try:
            with open(os.path.join(c, "status")) as f:
                if f.read().strip() != "connected":
                    continue
            driver = os.path.basename(os.path.realpath(os.path.join(c, "..", "device", "driver")))
        except OSError:
            continue
        return {"connector": os.path.basename(c), "driver": driver}
    return None


def mode(root="/"):
    p = panel(root)
    if not p:
        return {"mode": "unknown"}
    discrete = p["driver"] in ("nvidia", "nouveau", "amdgpu") and not glob.glob(
        os.path.join(root, "sys/bus/pci/drivers/i915/0000:*"))
    if p["driver"] in ("nvidia", "nouveau"):
        m = "discrete"
    elif p["driver"] in ("i915", "xe") or not discrete:
        m = "hybrid"
    else:
        m = "discrete"
    return {"mode": m, **p}


def reboot_to_firmware_setup(confirm=False):
    if confirm is not True:
        raise PermissionError("this restarts the computer into the firmware setup screen; confirm it")
    subprocess.run(["systemctl", "reboot", "--firmware-setup"], check=True, timeout=30)
