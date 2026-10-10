# SPDX-License-Identifier: GPL-2.0-only
#
# Builds the extended alienware-wmi module against a kernel's build tree.
#   make                    build for the running kernel
#   make KVER=<release>     build for another installed kernel
#   make KDIR=<build dir>   build against any kernel build tree
#   make W=1                extra compiler warnings
#   make clean
# DKMS calls this with KVER and KDIR set (see dkms.conf).

KVER ?= $(shell uname -r)
KDIR ?= /usr/lib/modules/$(KVER)/build
SRC  := $(CURDIR)/alienware-wmi

.PHONY: all modules clean

all: modules

modules:
	$(MAKE) -C $(KDIR) M=$(SRC) modules

clean:
	$(MAKE) -C $(KDIR) M=$(SRC) clean
