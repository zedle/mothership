"""AW-ELC firmware updates (STM32F070 lighting controller, USB 187c:0550).

The controller runs a small DFU bootloader in the first 12 KB of flash, which marks itself
read-only, and the application from 0x08007000. Factory data lives in the last pages
(0x0801E000 up) and must never be erased. On Dell laptops the controller is put into its
bootloader by pulsing its reset line through a BIOS WMI method (FWUpdateGPIOtoggle), which
Linux's alienware-wmi driver exposes in debugfs (root only):
    /sys/kernel/debug/alienware-wmi-<wmi device>/gpio_ctl/pin1   (NRST)
    /sys/kernel/debug/alienware-wmi-<wmi device>/gpio_ctl/pin0   (BOOT0: ST's ROM bootloader)
The bootloader then enumerates as a DfuSe device (0483:df11), which dfu-util drives.

Safety rules enforced here:
- the image must lie entirely inside the application area and carry the target's USB ids;
- the whole flash is read back to a backup file before anything is written;
- only the application pages are written (dfu-util erases just the pages it writes);
- the written range is read back and compared;
- AC power required; no downgrade without allow_downgrade.
Images are not shipped: the user supplies Dell's .hex (from the AWCC package).
"""
import glob
import os
import re
import shutil
import subprocess
import time

FLASH_BASE, FLASH_SIZE = 0x08000000, 128 * 1024
APP_START, APP_END = 0x08007000, 0x0801E000          # writable application area (end exclusive)
BOOT_END = 0x08003000
DFU_ID = "0483:df11"
ELC_VID = 0x187C
TARGETS = {0x0550: "STM32F070 (x15/x17 R2 and siblings)"}
NAME_RE = re.compile(r"elc-[a-z]{3}-v(\d+)\.(\d+)\.(\d+)\.hex$")


class FirmwareError(Exception):
    pass


# ------------------------------------------------------------------ images
def parse_ihex(text):
    """Intel HEX -> {address: byte}. Verifies record checksums."""
    data, base = {}, 0
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise FirmwareError(f"line {n}: not an Intel HEX record")
        raw = bytes.fromhex(line[1:])
        if sum(raw) & 0xFF:
            raise FirmwareError(f"line {n}: checksum mismatch")
        count, addr, rtype, payload = raw[0], raw[1] << 8 | raw[2], raw[3], raw[4:-1]
        if len(payload) != count:
            raise FirmwareError(f"line {n}: length mismatch")
        if rtype == 0x00:
            for i, b in enumerate(payload):
                data[base + addr + i] = b
        elif rtype == 0x01:
            break
        elif rtype == 0x02:
            base = (payload[0] << 8 | payload[1]) << 4
        elif rtype == 0x04:
            base = (payload[0] << 8 | payload[1]) << 16
        elif rtype in (0x03, 0x05):
            pass                                       # start address records
        else:
            raise FirmwareError(f"line {n}: unknown record type {rtype}")
    return data


def to_binary(data, start, end=None):
    end = end if end is not None else max(data) + 1
    out = bytearray(b"\xff" * (end - start))
    for a, b in data.items():
        if start <= a < end:
            out[a - start] = b
    return bytes(out)


def inspect_image(path):
    """Validate an AW-ELC application image; returns its facts or raises FirmwareError."""
    with open(path) as f:
        data = parse_ihex(f.read())
    if not data:
        raise FirmwareError("image is empty")
    lo, hi = min(data), max(data) + 1
    if lo < APP_START or hi > APP_END:
        raise FirmwareError(f"image covers 0x{lo:08x}-0x{hi - 1:08x}, outside the application area "
                            f"0x{APP_START:08x}-0x{APP_END - 1:08x}: refusing (it could overwrite the bootloader "
                            "or factory data)")
    if lo != APP_START:
        raise FirmwareError(f"image starts at 0x{lo:08x}, expected 0x{APP_START:08x}")
    blob = to_binary(data, APP_START, hi)
    sp = int.from_bytes(blob[0:4], "little")
    reset = int.from_bytes(blob[4:8], "little")
    if not (0x20000000 < sp <= 0x20004000) or not (APP_START <= (reset & ~1) < hi) or not reset & 1:
        raise FirmwareError(f"vector table looks wrong (SP 0x{sp:08x}, reset 0x{reset:08x})")
    pids = sorted({int.from_bytes(blob[m.start() + 10 : m.start() + 12], "little")
                   for m in re.finditer(re.escape(bytes([0x12, 0x01])), blob)
                   if int.from_bytes(blob[m.start() + 8 : m.start() + 10], "little") == ELC_VID})
    if not pids:
        raise FirmwareError("no AW-ELC USB descriptor (VID 187c) found in the image")
    m = NAME_RE.search(os.path.basename(path))
    version = tuple(int(x) for x in m.groups()) if m else None
    return {"path": path, "start": APP_START, "end": hi, "size": hi - APP_START, "pids": pids,
            "version": version, "binary": blob}


def fmt_version(v):
    return ".".join(map(str, v)) if v else "unknown"


# ------------------------------------------------------------------ plan
def on_ac(root="/"):
    for d in glob.glob(os.path.join(root, "sys/class/power_supply/*")):
        try:
            if open(d + "/type").read().strip() == "Mains" and open(d + "/online").read().strip() == "1":
                return True
        except OSError:
            continue
    return False


def check(image, device, allow_downgrade=False, ac=None):
    """device: {"pid": int, "firmware": "1.1.7"}. Returns a list of problems (empty = go)."""
    problems = []
    if device["pid"] not in image["pids"]:
        problems.append(f"image is for PID {', '.join(f'{p:04x}' for p in image['pids'])}, "
                        f"the controller is {device['pid']:04x}")
    if device["pid"] not in TARGETS:
        problems.append(f"PID {device['pid']:04x} is not a supported flash target")
    cur = tuple(int(x) for x in device["firmware"].split("."))
    if image["version"] is None:
        problems.append("can't tell the image version (expected a name like elc-gcc-v1.1.12.hex)")
    elif image["version"] <= cur and not allow_downgrade:
        problems.append(f"image {fmt_version(image['version'])} is not newer than the installed {device['firmware']}")
    if not (on_ac() if ac is None else ac):
        problems.append("connect the power adapter first")
    return problems


# ------------------------------------------------------------------ device steps (root)
def gpio_dir():
    found = glob.glob("/sys/kernel/debug/alienware-wmi-*/gpio_ctl")
    if not found:
        raise FirmwareError("alienware-wmi's debugfs GPIO controls are missing (need root and debugfs mounted)")
    return found[0]


def pulse_reset(boot0=False):
    d = gpio_dir()

    def pin(n, v):
        with open(os.path.join(d, f"pin{n}"), "w") as f:
            f.write("1" if v else "0")

    if boot0:
        pin(0, 1)
    pin(1, 0)
    time.sleep(0.01)
    pin(1, 1)
    if boot0:
        time.sleep(0.5)
        pin(0, 0)


def usb_present(vidpid):
    vid, pid = vidpid.split(":")
    for d in glob.glob("/sys/bus/usb/devices/*"):
        try:
            if open(d + "/idVendor").read().strip() == vid and open(d + "/idProduct").read().strip() == pid:
                return True
        except OSError:
            continue
    return False


def wait_for(vidpid, timeout=8.0, present=True):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if usb_present(vidpid) == present:
            return True
        time.sleep(0.1)
    return False


def dfu(*args, timeout=120):
    exe = shutil.which("dfu-util")
    if not exe:
        raise FirmwareError("dfu-util is not installed (pacman -S dfu-util)")
    r = subprocess.run([exe, "-d", DFU_ID, "-a", "0", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise FirmwareError(f"dfu-util {' '.join(args)} failed:\n{r.stdout[-2000:]}{r.stderr[-2000:]}")
    return r.stdout


def enter_bootloader(log=print):
    if usb_present(DFU_ID):
        return "already"
    log("resetting the lighting controller into its bootloader")
    pulse_reset()
    if wait_for(DFU_ID, 6):
        return "bootloader"
    log("the bootloader didn't stay up; trying the STM32 ROM bootloader (BOOT0)")
    pulse_reset(boot0=True)
    if wait_for(DFU_ID, 6):
        return "rom"
    raise FirmwareError("the controller didn't appear as a DFU device (0483:df11)")


def leave_bootloader(log=print):
    log("restarting the lighting controller")
    try:
        dfu("-s", f"0x{APP_START:08x}:leave", "-U", os.devnull, "-Z", "4", timeout=30)
    except FirmwareError:
        pass
    if not wait_for(f"{ELC_VID:04x}:0550", 5):
        pulse_reset()
    if not wait_for(f"{ELC_VID:04x}:0550", 8):
        raise FirmwareError("the controller didn't come back as 187c:0550; it is still in its bootloader, "
                            "so the update (or a restore of the backup) can be retried")


def backup(path, log=print):
    log(f"reading all {FLASH_SIZE // 1024} KB of flash to {path}")
    dfu("-s", f"0x{FLASH_BASE:08x}:{FLASH_SIZE}", "-U", path)
    size = os.path.getsize(path)
    if size != FLASH_SIZE:
        raise FirmwareError(f"backup is {size} bytes, expected {FLASH_SIZE}")
    return path


def write_and_verify(image, workdir, log=print):
    app = os.path.join(workdir, "app.bin")
    with open(app, "wb") as f:
        f.write(image["binary"])
    log(f"writing {image['size']} bytes at 0x{APP_START:08x}")
    dfu("-s", f"0x{APP_START:08x}", "-D", app, timeout=300)
    back = os.path.join(workdir, "readback.bin")
    if os.path.exists(back):
        os.unlink(back)
    dfu("-s", f"0x{APP_START:08x}:{image['size']}", "-U", back)
    with open(back, "rb") as f:
        if f.read() != image["binary"]:
            raise FirmwareError("read-back differs from the image: the controller stays in its bootloader; "
                                "retry, or restore the backup")
    log("verified")


def restore(backup_path, workdir, log=print):
    """Write the backup's application area back (never the bootloader or factory pages)."""
    with open(backup_path, "rb") as f:
        full = f.read()
    if len(full) != FLASH_SIZE:
        raise FirmwareError("not a full-flash backup")
    blob = full[APP_START - FLASH_BASE : APP_END - FLASH_BASE].rstrip(b"\xff")
    image = {"binary": blob, "size": len(blob)}
    write_and_verify(image, workdir, log)


def update(image_path, backup_dir, device, allow_downgrade=False, dry_run=False, log=print):
    image = inspect_image(image_path)
    problems = check(image, device, allow_downgrade)
    if problems:
        raise FirmwareError("; ".join(problems))
    log(f"image {fmt_version(image['version'])} ({image['size']} bytes) -> controller {device['firmware']}")
    if dry_run:
        return {"dry_run": True, "image": fmt_version(image["version"])}
    if os.geteuid() != 0:
        raise FirmwareError("run as root (sudo): resetting the controller and DFU need it")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bpath = os.path.join(backup_dir, f"elc-{device['pid']:04x}-v{device['firmware']}-{stamp}.bin")
    enter_bootloader(log)
    backup(bpath, log)
    write_and_verify(image, backup_dir, log)
    leave_bootloader(log)
    return {"backup": bpath, "image": fmt_version(image["version"])}
