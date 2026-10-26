PREFIX  ?= /usr
DESTDIR ?=
LIBDIR   = $(PREFIX)/lib/kerio-vpn
SHAREDIR = $(PREFIX)/share
VERSION  = $(shell python3 -c "import kerio_vpn; print(kerio_vpn.VERSION)")

.PHONY: all test lint install uninstall deb appimage macos clean

all: test

test:
	python3 -m unittest discover -s tests

lint:
	python3 -m pyflakes kerio_vpn bin/kerio-vpn libexec/* tests

install:
	install -d $(DESTDIR)$(LIBDIR)/kerio_vpn/ui $(DESTDIR)$(LIBDIR)/libexec $(DESTDIR)$(LIBDIR)/bin
	install -m 644 kerio_vpn/*.py $(DESTDIR)$(LIBDIR)/kerio_vpn/
	install -D -m 644 data/org.keriovpn.KerioVpn.metainfo.xml $(DESTDIR)$(SHAREDIR)/metainfo/kerio-vpn.metainfo.xml
	install -m 644 kerio_vpn/ui/*.py kerio_vpn/ui/style.css $(DESTDIR)$(LIBDIR)/kerio_vpn/ui/
	install -m 755 libexec/kerio-vpn-control libexec/kerio-vpn-configure $(DESTDIR)$(LIBDIR)/libexec/
	install -m 755 bin/kerio-vpn $(DESTDIR)$(LIBDIR)/bin/
	install -d $(DESTDIR)$(PREFIX)/bin
	ln -sf ../lib/kerio-vpn/bin/kerio-vpn $(DESTDIR)$(PREFIX)/bin/kerio-vpn
	install -d $(DESTDIR)$(SHAREDIR)/kerio-vpn/icons
	install -m 644 data/icons/*.svg $(DESTDIR)$(SHAREDIR)/kerio-vpn/icons/
	install -D -m 644 data/icons/kerio-vpn.svg $(DESTDIR)$(SHAREDIR)/icons/hicolor/scalable/apps/kerio-vpn.svg
	install -D -m 644 data/kerio-vpn.desktop $(DESTDIR)$(SHAREDIR)/applications/kerio-vpn.desktop
	install -D -m 644 data/org.keriovpn.KerioVpn.policy $(DESTDIR)$(SHAREDIR)/polkit-1/actions/org.keriovpn.KerioVpn.policy

uninstall:
	rm -rf $(DESTDIR)$(LIBDIR) $(DESTDIR)$(SHAREDIR)/kerio-vpn
	rm -f $(DESTDIR)$(PREFIX)/bin/kerio-vpn
	rm -f $(DESTDIR)$(SHAREDIR)/icons/hicolor/scalable/apps/kerio-vpn.svg
	rm -f $(DESTDIR)$(SHAREDIR)/applications/kerio-vpn.desktop
	rm -f $(DESTDIR)$(SHAREDIR)/metainfo/kerio-vpn.metainfo.xml
	rm -f $(DESTDIR)$(SHAREDIR)/polkit-1/actions/org.keriovpn.KerioVpn.policy

deb: test
	packaging/build-deb.sh

appimage: test
	packaging/build-appimage.sh

macos: test
	packaging/build-macos.sh

clean:
	rm -rf build dist
	find . -name __pycache__ -type d -exec rm -rf {} +
