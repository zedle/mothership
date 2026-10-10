# mothership: install without network or a Python build backend (plain copies).
#   make install [PREFIX=/usr] [DESTDIR=...] [LAYOUT=site|private] [COMPILE=1|0]
#   make uninstall [PREFIX=/usr] [DESTDIR=...] [LAYOUT=site|private]
#   make install-dkms [PREFIX=/usr] [DESTDIR=...] [VERSION=...]
#   make test
#
# LAYOUT=site (default, Arch): the package goes to the system Python's site-packages.
# LAYOUT=private (deb/rpm): it goes to $(PREFIX)/lib/mothership/python, which doesn't depend
#   on the Python version, and /usr/bin/mothership and $(PREFIX)/lib/mothership/mothership-fire
#   are launchers that add that directory to sys.path.
# COMPILE=0 skips byte-compilation (distribution packages compile on the target instead).

PREFIX ?= /usr
DESTDIR ?=
PYTHON ?= /usr/bin/python3
LAYOUT ?= site
COMPILE ?= 1
VERSION ?= $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' mothership/__init__.py)

PYVER := $(shell $(PYTHON) -c 'import sys; print("%d.%d" % sys.version_info[:2])')
BINDIR = $(PREFIX)/bin
LIBDIR = $(PREFIX)/lib/mothership
ifeq ($(LAYOUT),private)
SITEDIR = $(LIBDIR)/python
else ifeq ($(LAYOUT),site)
SITEDIR = $(PREFIX)/lib/python$(PYVER)/site-packages
else
$(error LAYOUT must be site or private)
endif
PKGDIR = $(SITEDIR)/mothership
UDEVDIR = $(PREFIX)/lib/udev/rules.d
SYSUSERSDIR = $(PREFIX)/lib/sysusers.d
TMPFILESDIR = $(PREFIX)/lib/tmpfiles.d
USERUNITDIR = $(PREFIX)/lib/systemd/user
SYSUNITDIR = $(PREFIX)/lib/systemd/system
SHAREDIR = $(PREFIX)/share/mothership
DKMSDIR = $(PREFIX)/src/alienware-wmi-mothership-$(VERSION)

PYFILES := $(shell find mothership \( -name '*.py' -o -name '*.json' \) -not -path '*/__pycache__/*' | sort)

# A launcher that finds the package even when it is not on the system Python's path
# (PREFIX elsewhere, or LAYOUT=private). Isolated mode: no user site, no PYTHON* variables.
define launcher
	printf '%s\n' '#!$(PYTHON) -I' 'import sys' \
	  'if "$(SITEDIR)" not in sys.path:' '    sys.path.insert(0, "$(SITEDIR)")' \
	  'from mothership.$(1) import main' 'sys.exit(main())' > $(2)
	chmod 755 $(2)
endef

.PHONY: all install install-dkms uninstall test

all:
	@echo "nothing to build; try: make test | make install [PREFIX=/usr DESTDIR=...]"

install:
	@test -n "$(PYVER)" || { echo "cannot run $(PYTHON)"; exit 1; }
	for f in $(PYFILES); do install -Dm644 "$$f" "$(DESTDIR)$(SITEDIR)/$$f"; done
ifeq ($(COMPILE),1)
	$(PYTHON) -m compileall -q -o 0 -o 1 -d "$(PKGDIR)" "$(DESTDIR)$(PKGDIR)"
endif
	install -d "$(DESTDIR)$(BINDIR)"
	$(call launcher,cli,"$(DESTDIR)$(BINDIR)/mothership")
	install -Dm644 data/udev/70-mothership.rules "$(DESTDIR)$(UDEVDIR)/70-mothership.rules"
	install -Dm644 data/sysusers.d/mothership.conf "$(DESTDIR)$(SYSUSERSDIR)/mothership.conf"
	install -Dm644 data/tmpfiles.d/mothership.conf "$(DESTDIR)$(TMPFILESDIR)/mothership.conf"
	install -d "$(DESTDIR)$(USERUNITDIR)" "$(DESTDIR)$(SYSUNITDIR)"
	sed 's|/usr/bin/mothership|$(BINDIR)/mothership|' data/systemd/user/mothershipd.service \
	  > "$(DESTDIR)$(USERUNITDIR)/mothershipd.service"
ifeq ($(PREFIX)$(LAYOUT),/usrsite)
	install -m644 data/systemd/system/mothership-fire.service "$(DESTDIR)$(SYSUNITDIR)/mothership-fire.service"
else
	install -d "$(DESTDIR)$(LIBDIR)"
	$(call launcher,fire,"$(DESTDIR)$(LIBDIR)/mothership-fire")
	sed 's|^ExecStart=.*|ExecStart=$(LIBDIR)/mothership-fire|' data/systemd/system/mothership-fire.service \
	  > "$(DESTDIR)$(SYSUNITDIR)/mothership-fire.service"
endif
	chmod 644 "$(DESTDIR)$(USERUNITDIR)/mothershipd.service" "$(DESTDIR)$(SYSUNITDIR)/mothership-fire.service"
	# Claude Code / Codex skill: link ~/.claude/skills/mothership (or ~/.agents/skills/mothership) to it.
	if [ -d integrations/claude/skills/mothership ]; then \
	  find integrations/claude/skills/mothership -type f | while read -r f; do \
	    install -Dm644 "$$f" "$(DESTDIR)$(SHAREDIR)/claude/skills/$${f#integrations/claude/skills/}"; done; \
	fi
	# Omarchy bar widget: link ~/.config/omarchy/plugins/mothership to it.
	if [ -d ui/omarchy/mothership ]; then \
	  find ui/omarchy/mothership -type f | while read -r f; do \
	    install -Dm644 "$$f" "$(DESTDIR)$(SHAREDIR)/omarchy/$${f#ui/omarchy/}"; done; \
	  [ ! -f ui/omarchy/mothership/mothership-cli ] || chmod 755 "$(DESTDIR)$(SHAREDIR)/omarchy/mothership/mothership-cli"; \
	fi

# DKMS source tree of the kernel module (what the mothership-dkms packages ship).
install-dkms:
	@test -n "$(VERSION)" || { echo "no VERSION"; exit 1; }
	install -Dm644 kernel/dkms.conf "$(DESTDIR)$(DKMSDIR)/dkms.conf"
	sed -i 's/^PACKAGE_VERSION=.*/PACKAGE_VERSION="$(VERSION)"/' "$(DESTDIR)$(DKMSDIR)/dkms.conf"
	install -Dm644 kernel/Makefile "$(DESTDIR)$(DKMSDIR)/Makefile"
	for f in kernel/alienware-wmi/*.c kernel/alienware-wmi/*.h kernel/alienware-wmi/Kbuild kernel/alienware-wmi/Makefile; do \
	  [ ! -e "$$f" ] || install -Dm644 "$$f" "$(DESTDIR)$(DKMSDIR)/$${f#kernel/}"; done

uninstall:
	rm -rf "$(DESTDIR)$(PKGDIR)" "$(DESTDIR)$(LIBDIR)" "$(DESTDIR)$(SHAREDIR)"
	rm -f "$(DESTDIR)$(BINDIR)/mothership" \
	  "$(DESTDIR)$(UDEVDIR)/70-mothership.rules" \
	  "$(DESTDIR)$(SYSUSERSDIR)/mothership.conf" \
	  "$(DESTDIR)$(TMPFILESDIR)/mothership.conf" \
	  "$(DESTDIR)$(USERUNITDIR)/mothershipd.service" \
	  "$(DESTDIR)$(SYSUNITDIR)/mothership-fire.service"

test:
	$(PYTHON) -m unittest -q
