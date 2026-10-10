# mothership: install without network or a Python build backend (plain copies).
#   make install [PREFIX=/usr] [DESTDIR=...]
#   make uninstall [PREFIX=/usr] [DESTDIR=...]
#   make test

PREFIX ?= /usr
DESTDIR ?=
PYTHON ?= /usr/bin/python3

PYVER := $(shell $(PYTHON) -c 'import sys; print("%d.%d" % sys.version_info[:2])')
BINDIR = $(PREFIX)/bin
SITEDIR = $(PREFIX)/lib/python$(PYVER)/site-packages
PKGDIR = $(SITEDIR)/mothership
LIBDIR = $(PREFIX)/lib/mothership
UDEVDIR = $(PREFIX)/lib/udev/rules.d
SYSUSERSDIR = $(PREFIX)/lib/sysusers.d
TMPFILESDIR = $(PREFIX)/lib/tmpfiles.d
USERUNITDIR = $(PREFIX)/lib/systemd/user
SYSUNITDIR = $(PREFIX)/lib/systemd/system
SHAREDIR = $(PREFIX)/share/mothership

PYFILES := $(shell find mothership \( -name '*.py' -o -name '*.json' \) -not -path '*/__pycache__/*' | sort)

# A launcher that finds the package even when PREFIX is not on the system Python's path.
define launcher
	printf '%s\n' '#!$(PYTHON) -I' 'import sys' \
	  'if "$(SITEDIR)" not in sys.path:' '    sys.path.append("$(SITEDIR)")' \
	  'from mothership.$(1) import main' 'sys.exit(main())' > $(2)
	chmod 755 $(2)
endef

.PHONY: all install uninstall test

all:
	@echo "nothing to build; try: make test | make install [PREFIX=/usr DESTDIR=...]"

install:
	@test -n "$(PYVER)" || { echo "cannot run $(PYTHON)"; exit 1; }
	for f in $(PYFILES); do install -Dm644 "$$f" "$(DESTDIR)$(SITEDIR)/$$f"; done
	$(PYTHON) -m compileall -q -o 0 -o 1 -d "$(PKGDIR)" "$(DESTDIR)$(PKGDIR)"
	install -d "$(DESTDIR)$(BINDIR)"
	$(call launcher,cli,"$(DESTDIR)$(BINDIR)/mothership")
	install -Dm644 data/udev/70-mothership.rules "$(DESTDIR)$(UDEVDIR)/70-mothership.rules"
	install -Dm644 data/sysusers.d/mothership.conf "$(DESTDIR)$(SYSUSERSDIR)/mothership.conf"
	install -Dm644 data/tmpfiles.d/mothership.conf "$(DESTDIR)$(TMPFILESDIR)/mothership.conf"
	install -d "$(DESTDIR)$(USERUNITDIR)" "$(DESTDIR)$(SYSUNITDIR)"
	sed 's|/usr/bin/mothership|$(BINDIR)/mothership|' data/systemd/user/mothershipd.service \
	  > "$(DESTDIR)$(USERUNITDIR)/mothershipd.service"
ifeq ($(PREFIX),/usr)
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
