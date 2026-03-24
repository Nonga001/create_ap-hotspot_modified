PREFIX=/usr
MANDIR=$(PREFIX)/share/man
BINDIR=$(PREFIX)/bin

all:
	@echo "Run 'make install' for installation."
	@echo "Run 'make install-gui' for GUI installation."
	@echo "Run 'make uninstall' for uninstallation."
	@echo "Run 'make uninstall-gui' for GUI uninstallation."

install:
	install -Dm755 create_ap $(DESTDIR)$(BINDIR)/create_ap
	install -Dm644 create_ap.conf $(DESTDIR)/etc/create_ap.conf
	[ ! -d /lib/systemd/system ] || install -Dm644 create_ap.service $(DESTDIR)$(PREFIX)/lib/systemd/system/create_ap.service
	[ ! -e /sbin/openrc-run ] || install -Dm755 create_ap.openrc $(DESTDIR)/etc/init.d/create_ap
	install -Dm644 bash_completion $(DESTDIR)$(PREFIX)/share/bash-completion/completions/create_ap
	install -Dm644 README.md $(DESTDIR)$(PREFIX)/share/doc/create_ap/README.md

install-gui: install
	install -Dm755 create_ap_gui.py $(DESTDIR)$(BINDIR)/create_ap_gui
	install -Dm644 create_ap_gui.desktop $(DESTDIR)$(PREFIX)/share/applications/create_ap_gui.desktop
	install -Dm644 create_ap_gui.svg $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/create_ap_gui.svg
	install -Dm644 create_ap_gui.png $(DESTDIR)$(PREFIX)/share/icons/hicolor/128x128/apps/create_ap_gui.png

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/create_ap
	rm -f $(DESTDIR)/etc/create_ap.conf
	[ ! -f /lib/systemd/system/create_ap.service ] || rm -f $(DESTDIR)$(PREFIX)/lib/systemd/system/create_ap.service
	[ ! -e /sbin/openrc-run ] || rm -f $(DESTDIR)/etc/init.d/create_ap
	rm -f $(DESTDIR)$(PREFIX)/share/bash-completion/completions/create_ap
	rm -f $(DESTDIR)$(PREFIX)/share/doc/create_ap/README.md

uninstall-gui:
	rm -f $(DESTDIR)$(BINDIR)/create_ap_gui
	rm -f $(DESTDIR)$(PREFIX)/share/applications/create_ap_gui.desktop
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/create_ap_gui.svg
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/128x128/apps/create_ap_gui.png
