mothership @VERSION@: lighting, thermal and firmware control for Alienware laptops on Linux.

`mothership` is the app (daemon, command line, terminal UI, Omarchy bar widget). `mothership-dkms` is
optional: the extended `alienware-wmi` kernel module (real G-Mode, power adapter information), built by DKMS
for every kernel whose headers are installed.

## Install

**Debian 12+ / Ubuntu 24.04+**

```sh
base=https://github.com/@REPO@/releases/download/v@VERSION@
curl -LO "$base/mothership_@VERSION@_all.deb" -LO "$base/mothership-dkms_@VERSION@_all.deb"
sudo apt install ./mothership_@VERSION@_all.deb ./mothership-dkms_@VERSION@_all.deb   # dkms one optional
```

**Fedora**

```sh
base=https://github.com/@REPO@/releases/download/v@VERSION@
sudo dnf install "$base/mothership-@VERSION@-1.noarch.rpm" "$base/mothership-dkms-@VERSION@-1.noarch.rpm"
```

**openSUSE Tumbleweed**

```sh
base=https://github.com/@REPO@/releases/download/v@VERSION@
curl -LO "$base/mothership-@VERSION@-1.noarch.rpm" -LO "$base/mothership-dkms-@VERSION@-1.noarch.rpm"
sudo zypper install --allow-unsigned-rpm ./mothership-@VERSION@-1.noarch.rpm ./mothership-dkms-@VERSION@-1.noarch.rpm
```

**Arch Linux**

```sh
base=https://github.com/@REPO@/releases/download/v@VERSION@
sudo pacman -U "$base/mothership-@ARCHVER@-any.pkg.tar.zst" "$base/mothership-dkms-@ARCHVER@-any.pkg.tar.zst"
```

The kernel module needs your kernel's headers: `linux-headers-$(uname -r)` (Debian/Ubuntu), `kernel-devel`
(Fedora), `kernel-default-devel` (openSUSE), `linux-headers` (Arch). Check the downloads with
`sha256sum -c SHA256SUMS --ignore-missing`.

## After installing

```sh
sudo usermod -aG mothership "$USER"            # then log out and in again
systemctl --user enable --now mothershipd
sudo systemctl enable --now mothership-fire    # only for the Fire effect (key flares)
mothership status
```

With `mothership-dkms`, reboot (or `sudo modprobe -r alienware-wmi && sudo modprobe alienware-wmi`) so the
extended module replaces the stock one; `modinfo -F version alienware-wmi` then prints `mothership-1`.

mothership is not affiliated with Dell. "Alienware" is a trademark of Dell Inc. See NOTICE.
