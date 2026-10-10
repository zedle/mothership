"""hidraw discovery and transport (Linux /dev/hidrawN).

Devices are found through sysfs: each /sys/class/hidraw/hidrawN/device/uevent carries
HID_ID=<bus>:<vendor>:<product>, and device/report_descriptor holds the raw HID report
descriptor, which tells the vendor lighting interface apart from the typing one.
"""
import fcntl
import glob
import os
import re
import select

_HID_ID = re.compile(r"^HID_ID=([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+)$", re.M)


def _ioc(nr, size):
    """_IOC(_IOC_READ | _IOC_WRITE, 'H', nr, size)."""
    return (3 << 30) | (size << 16) | (ord("H") << 8) | nr


def hidiocsfeature(n):
    return _ioc(0x06, n)


def hidiocgfeature(n):
    return _ioc(0x07, n)


def hidiocginput(n):
    return _ioc(0x0A, n)


def usage_pages(descriptor):
    """Global Usage Page items (tag 0x04) in a HID report descriptor."""
    pages, i = [], 0
    while i < len(descriptor):
        prefix = descriptor[i]
        if prefix == 0xFE:  # long item: size in the next byte
            i += 3 + (descriptor[i + 1] if i + 1 < len(descriptor) else 0)
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        data = descriptor[i + 1 : i + 1 + size]
        if prefix & 0xFC == 0x04:
            pages.append(int.from_bytes(data, "little"))
        i += 1 + size
    return pages


def report_ids(descriptor):
    """Report ID items (tag 0x84) in a HID report descriptor."""
    ids, i = [], 0
    while i < len(descriptor):
        prefix = descriptor[i]
        if prefix == 0xFE:
            i += 3 + (descriptor[i + 1] if i + 1 < len(descriptor) else 0)
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        data = descriptor[i + 1 : i + 1 + size]
        if prefix & 0xFC == 0x84:
            ids.append(int.from_bytes(data, "little"))
        i += 1 + size
    return ids


def find(vid, pids=None, usage_page=None, report_id=None, root="/sys/class/hidraw", dev="/dev"):
    """Device paths of hidraw nodes matching vid (and pids / a usage page / a report id)."""
    found = []
    for node in sorted(glob.glob(os.path.join(root, "hidraw*")), key=_natural):
        try:
            with open(os.path.join(node, "device", "uevent")) as f:
                m = _HID_ID.search(f.read())
        except OSError:
            continue
        if not m or int(m.group(2), 16) != vid:
            continue
        if pids is not None and int(m.group(3), 16) not in pids:
            continue
        if usage_page is not None or report_id is not None:
            try:
                with open(os.path.join(node, "device", "report_descriptor"), "rb") as f:
                    desc = f.read()
            except OSError:
                continue
            if usage_page is not None and usage_page not in usage_pages(desc):
                continue
            if report_id is not None and report_id not in report_ids(desc):
                continue
        found.append(os.path.join(dev, os.path.basename(node)))
    return found


def product_id(path, root="/sys/class/hidraw"):
    """USB product id of /dev/hidrawN, or None."""
    try:
        with open(os.path.join(root, os.path.basename(path), "device", "uevent")) as f:
            m = _HID_ID.search(f.read())
        return int(m.group(3), 16) if m else None
    except OSError:
        return None


def _natural(path):
    n = re.search(r"(\d+)$", path)
    return int(n.group(1)) if n else 0


class Hid:
    """One open hidraw node. write_only opens O_WRONLY: feature ioctls still work, but
    input reports (which on a keyboard's lighting interface can carry keystrokes) can't
    be read."""

    def __init__(self, path, write_only=False):
        self.path = path
        self.fd = os.open(path, (os.O_WRONLY if write_only else os.O_RDWR) | os.O_CLOEXEC)

    def set_feature(self, buf):
        buf = bytearray(buf)
        fcntl.ioctl(self.fd, hidiocsfeature(len(buf)), buf)

    def get_feature(self, buf):
        """buf[0] = report id; returns the filled buffer."""
        buf = bytearray(buf)
        fcntl.ioctl(self.fd, hidiocgfeature(len(buf)), buf)
        return bytes(buf)

    def get_input(self, buf):
        buf = bytearray(buf)
        fcntl.ioctl(self.fd, hidiocginput(len(buf)), buf)
        return bytes(buf)

    def write(self, buf):
        os.write(self.fd, bytes(buf))

    def read(self, n, timeout_ms=200):
        r, _, _ = select.select([self.fd], [], [], timeout_ms / 1000)
        return os.read(self.fd, n) if r else None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
