#!/bin/sh
# Installs the built packages on a fresh distribution (a CI container, as root), checks what
# they installed, then removes them and checks they cleaned up.
#   packaging/ci/install-test.sh <deb|rpm|arch> <directory with the packages>
# The kernel module isn't built: containers have no headers for the host's kernel. Only its
# DKMS source tree is checked.
set -eu
kind=$1
dir=$(cd "$2" && pwd)
fail() { echo "FAIL: $*" >&2; exit 1; }
step() { echo "--- $*"; }

step "install ($kind)"
case $kind in
  deb)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends "$dir"/mothership_*_all.deb "$dir"/mothership-dkms_*_all.deb
    pydir=/usr/lib/mothership/python ;;
  rpm)
    dnf install -y -q --setopt=install_weak_deps=False \
      "$dir"/mothership-[0-9]*.noarch.rpm "$dir"/mothership-dkms-[0-9]*.noarch.rpm
    pydir=/usr/lib/mothership/python ;;
  arch)
    pacman -Syu --noconfirm --needed >/dev/null
    pacman -U --noconfirm "$dir"/mothership-[0-9]*.pkg.tar.zst "$dir"/mothership-dkms-[0-9]*.pkg.tar.zst
    pydir= ;;
  *) fail "unknown kind $kind" ;;
esac

step "files"
for f in /usr/bin/mothership \
         /usr/lib/udev/rules.d/70-mothership.rules \
         /usr/lib/sysusers.d/mothership.conf \
         /usr/lib/tmpfiles.d/mothership.conf \
         /usr/lib/systemd/user/mothershipd.service \
         /usr/lib/systemd/system/mothership-fire.service \
         /usr/share/mothership/omarchy/mothership/manifest.json \
         /usr/share/mothership/claude/skills/mothership/SKILL.md; do
  [ -f "$f" ] || fail "missing $f"
done
[ -x /usr/share/mothership/omarchy/mothership/mothership-cli ] || fail "mothership-cli not executable"
[ "$(readlink -f "$(command -v mothership)")" = "$(readlink -f /usr/bin/mothership)" ] || fail "mothership on PATH is not /usr/bin/mothership"
getent group mothership >/dev/null || fail "no mothership group"

step "launcher"
mothership --version
mothership --help >/dev/null
rc=0; mothership status >/dev/null 2>&1 || rc=$?
[ "$rc" = 3 ] || fail "mothership status without a daemon exited $rc, expected 3"
if [ -n "$pydir" ]; then
  [ -d "$pydir/mothership" ] || fail "missing $pydir/mothership"
  python3 -I -c "import sys; sys.path.insert(0, '$pydir'); import mothership.cli, mothership.daemon, mothership.fire, mothership.tui; print('import ok from', mothership.__file__)"
  ls "$pydir"/mothership/__pycache__/*.pyc >/dev/null 2>&1 || fail "postinstall did not byte-compile"
else
  python3 -I -c "import mothership.cli, mothership.daemon, mothership.fire, mothership.tui; print('import ok from', mothership.__file__)"
fi

step "fire service command"
cmd=$(sed -n 's/^ExecStart=//p' /usr/lib/systemd/system/mothership-fire.service)
echo "ExecStart=$cmd"
[ -x "${cmd%% *}" ] || fail "ExecStart program ${cmd%% *} is not executable"
# Without the keyboard it exits after ~10 s; with one (a container on an Alienware host sees the
# host's sysfs) it keeps waiting for the fire effect until the timeout.
rc=0; out=$(cd / && timeout 30 $cmd 2>&1) || rc=$?
echo "$out"
case "$rc:$out" in
  0:*"nothing to do"*|124:*"waiting for the fire effect"*) ;;
  *) fail "fire service command exited $rc" ;;
esac
grep -q '^ExecStart=/usr/bin/mothership daemon$' /usr/lib/systemd/user/mothershipd.service || fail "daemon unit ExecStart"

step "dkms source"
src=$(ls -d /usr/src/alienware-wmi-mothership-*)
[ "$(echo "$src" | wc -l)" = 1 ] || fail "expected one DKMS source tree: $src"
ver=${src#/usr/src/alienware-wmi-mothership-}
grep -qx "PACKAGE_VERSION=\"$ver\"" "$src/dkms.conf" || fail "dkms.conf PACKAGE_VERSION is not $ver"
grep -qx 'PACKAGE_NAME="alienware-wmi-mothership"' "$src/dkms.conf" || fail "dkms.conf PACKAGE_NAME"
for f in Makefile alienware-wmi/Kbuild alienware-wmi/alienware-wmi-base.c alienware-wmi/alienware-wmi-legacy.c \
         alienware-wmi/alienware-wmi-wmax.c alienware-wmi/alienware-wmi.h; do
  [ -f "$src/$f" ] || fail "missing $src/$f"
done
dkms status -m alienware-wmi-mothership || true
if [ "$kind" != arch ]; then
  dkms status -m alienware-wmi-mothership -v "$ver" | grep -q . || fail "postinstall did not register the module with DKMS"
fi

# MOTHERSHIP_TEST_DKMS_BUILD=1 (rpm, arch): also compile the module against the distribution's
# current kernel headers (not the host's kernel, so it is built but never installed or loaded).
if [ "${MOTHERSHIP_TEST_DKMS_BUILD:-0}" = 1 ]; then
  step "dkms build"
  case $kind in
    rpm) dnf install -y -q kernel-devel >/dev/null
         kdir=$(ls -d /usr/src/kernels/* | sort -V | tail -1) ;;
    arch) pacman -S --noconfirm --needed linux-headers >/dev/null
          kdir=$(ls -d /usr/lib/modules/*/build | sort -V | tail -1); kdir=$(readlink -f "$kdir")
          dkms status -m alienware-wmi-mothership -v "$ver" | grep -q . || dkms add -m alienware-wmi-mothership -v "$ver" ;;
    *) fail "dkms build test is for rpm and arch" ;;
  esac
  kver=$(make -s -C "$kdir" kernelrelease 2>/dev/null || basename "$kdir")
  echo "building against $kver ($kdir)"
  dkms build -m alienware-wmi-mothership -v "$ver" -k "$kver" --kernelsourcedir "$kdir" ||
    { cat "/var/lib/dkms/alienware-wmi-mothership/$ver/build/make.log" 2>/dev/null; fail "dkms build"; }
  ls -l /var/lib/dkms/alienware-wmi-mothership/"$ver"/"$kver"/*/module/
fi

step "remove"
case $kind in
  deb) apt-get purge -y -qq mothership mothership-dkms ;;
  rpm) dnf remove -y -q --setopt=clean_requirements_on_remove=False mothership mothership-dkms ;;
  arch) pacman -R --noconfirm mothership mothership-dkms ;;
esac
[ ! -e /usr/bin/mothership ] || fail "/usr/bin/mothership left behind"
[ ! -e /usr/lib/mothership ] || fail "/usr/lib/mothership left behind: $(find /usr/lib/mothership | head)"
[ ! -e "$src" ] || fail "$src left behind"
command -v dkms >/dev/null || fail "dkms was removed too; can't check the registry"
[ -z "$(dkms status -m alienware-wmi-mothership)" ] || fail "module still registered with DKMS"
[ ! -e /var/lib/dkms/alienware-wmi-mothership/"$ver" ] || fail "/var/lib/dkms/alienware-wmi-mothership/$ver left behind"
echo "OK: $kind"
