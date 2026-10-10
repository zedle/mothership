# Changelog

All notable changes. Versions follow the git tags; each release on GitHub carries its section.

## 0.1.1 (2026-10-09)

### Added
- Packages for Debian 12+/Ubuntu 24.04+ (`.deb`), Fedora and openSUSE Tumbleweed (`.rpm`) and Arch
  (`.pkg.tar.zst`), each as `mothership` and `mothership-dkms`, built and install-tested in CI on every
  tagged release and attached to the GitHub release with `SHA256SUMS`.
- A version-independent install layout (`make install LAYOUT=private`) used by the deb and rpm packages.
- CI runs the unit tests on Python 3.11 and 3.13 for every push and pull request.

## 0.1.0 (2026-10-09)

First public release.

- Keyboard lighting on per-key Darfon keyboards: firmware effects (static, breathing, wave, spectrum,
  scanner, aurora, gradient), hardware brightness, per-key colours and the Fire effect, whose key flares
  come from a sandboxed system service that is the only process reading keystrokes.
- Chassis lighting on AW-ELC controllers (lid logo, rear lights, touchpad on models that have it):
  colours per zone, effects, brightness; power-button colours per power state (`--write-flash`).
- Thermal: modes, G-Mode, fan boost, automatic rules, CPU power limits re-applied after mode changes,
  TCC offset where the BIOS allows it, adapter warnings; writes are rate-limited because some BIOSes
  store every thermal change in flash.
- Firmware macros on the macro keys, per-app profiles (Hyprland), graphics mode with a restart into
  firmware setup, and validated, backed-up AW-ELC firmware updates.
- An extended `alienware-wmi` kernel module (DKMS): G-Mode, power adapter information, thermal
  information, touchpad lighting presence.
- An Omarchy bar widget with a live mirror of the machine's lights, a terminal UI (`mothership tui`),
  rendered `mothership status`, `mothership probe` for mapping unknown models, and an agent skill.
