#!/bin/sh
# Builds the Arch packages from packaging/arch/PKGBUILD in an archlinux:base-devel container
# (run as root; makepkg itself runs as an unprivileged "builder" user).
#   packaging/ci/arch-build.sh <repository> <commit> <output directory>
set -eu
repo=$(cd "$1" && pwd)
ref=$2
out=$3
pacman -Syu --noconfirm --needed git python dkms >/dev/null
id builder >/dev/null 2>&1 || useradd -m builder
mkdir -p "$out"
work=/home/builder/build
rm -rf "$work"
install -d -o builder -g builder "$work" /home/builder/pkg
install -m644 -o builder -g builder "$repo"/packaging/arch/PKGBUILD "$repo"/packaging/arch/mothership.install "$work"/
su builder -c "git config --global --add safe.directory '*' && cd '$work' && \
  MOTHERSHIP_GIT='file://$repo' MOTHERSHIP_REF='$ref' PKGDEST=/home/builder/pkg makepkg --noconfirm --cleanbuild"
cp /home/builder/pkg/*.pkg.tar.zst "$out"/
ls -l "$out"/*.pkg.tar.zst
