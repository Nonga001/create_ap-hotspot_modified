## NOT MAINTAINED

This project is no longer maintained.


## Forks and continuation of this project

* [linux-wifi-hotspot] - Fork that is focused on providing GUI and improvements.
* [linux-router] - Fork that is focused on providing new features and
    improvements which are not limited to WiFi. Some interesting features are:
    sharing Internet to a wired interface and sharing Internet via a transparent
    proxy using redsocks.


## Features

* Create an AP (Access Point) at any channel.
* Choose one of the following encryptions: WPA, WPA2, WPA/WPA2, Open (no encryption).
* Hide your SSID.
* Disable communication between clients (client isolation).
* IEEE 802.11n & 802.11ac support
* Internet sharing methods: NATed or Bridged or None (no Internet sharing).
* Choose the AP Gateway IP (only for 'NATed' and 'None' Internet sharing methods).
* You can create an AP with the same interface you are getting your Internet connection.
* You can pass your SSID and password through pipe or through arguments (see examples).


## Dependencies

### General

* bash (to run this script)
* util-linux (for getopt)
* procps or procps-ng
* hostapd
* iproute2
* iw
* iwconfig (you only need this if 'iw' can not recognize your adapter)
* haveged (optional)

### For 'NATed' or 'None' Internet sharing method

* dnsmasq
* iptables


## Installation

### Generic
    git clone https://github.com/Nonga001/create_ap-hotspot_modified.git
    cd create_ap
    make install

If you want the GUI launcher and desktop app entry/icon as well:

    make install-gui

### ArchLinux
    pacman -S create_ap

### Gentoo
    emerge layman
    layman -f -a jorgicio
    emerge net-wireless/create_ap

## Examples
### No passphrase (open network):
    create_ap wlan0 eth0 MyAccessPoint

### WPA + WPA2 passphrase:
    create_ap wlan0 eth0 MyAccessPoint MyPassPhrase

### AP without Internet sharing:
    create_ap -n wlan0 MyAccessPoint MyPassPhrase

### Bridged Internet sharing:
    create_ap -m bridge wlan0 eth0 MyAccessPoint MyPassPhrase

### Bridged Internet sharing (pre-configured bridge interface):
    create_ap -m bridge wlan0 br0 MyAccessPoint MyPassPhrase

### Internet sharing from the same WiFi interface:
    create_ap wlan0 wlan0 MyAccessPoint MyPassPhrase

### Choose a different WiFi adapter driver
    create_ap --driver rtl871xdrv wlan0 eth0 MyAccessPoint MyPassPhrase

### No passphrase (open network) using pipe:
    echo -e "MyAccessPoint" | create_ap wlan0 eth0

### WPA + WPA2 passphrase using pipe:
    echo -e "MyAccessPoint\nMyPassPhrase" | create_ap wlan0 eth0

### Enable IEEE 802.11n
    create_ap --ieee80211n --ht_capab '[HT40+]' wlan0 eth0 MyAccessPoint MyPassPhrase

### Client Isolation:
    create_ap --isolate-clients wlan0 eth0 MyAccessPoint MyPassPhrase

## Systemd service
Using the persistent [systemd](https://wiki.archlinux.org/index.php/systemd#Basic_systemctl_usage) service
### Start service immediately:
    systemctl start create_ap

### Start on boot:
    systemctl enable create_ap

## GUI (recommended)
For this fork, the GUI is the recommended way to use `create_ap` for daily hotspot management.

This repository includes a GUI launcher script:

    python3 create_ap_gui.py

You can also install the launcher, desktop entry, and app icon with:

    make install-gui

The GUI is a wrapper around `create_ap` and lets you:

* Select WiFi and Internet interfaces
* Set SSID/passphrase and common AP options
* Start/stop hotspot
* Apply changed settings by restarting the AP from the GUI
* Show currently running `create_ap` instances
* Load active hotspot settings into the form when an AP is already running
* Show connected clients (MAC/IP/name when available)
* Generate a Wi-Fi QR code for quick hotspot sharing using the running hotspot details when available
* Run dependency/interface preflight checks before startup
* Manage multiple named profiles from the GUI profile list (save/update, load, delete)
* Retry automatically with `--no-virt` after virtual-interface related failures
* Toggle passphrase visibility while editing
* Requires an instance check before Start/Stop is enabled

### GUI setup

Requirements:

* Python 3
* Tkinter (`python3-tk` package on many distributions)
* `qrencode` for QR code generation
* The normal `create_ap` runtime dependencies (`hostapd`, `iw`, `iproute2`, and for NAT mode also `dnsmasq` and `iptables`)

Run from the repository root:

    python3 create_ap_gui.py

Or after installation:

    create_ap_gui

### How the GUI works

When the GUI opens, it first checks whether another `create_ap` instance is already running.

* Start/Stop is disabled until that check completes.
* If another instance is found, the GUI shows it in the status line and prevents starting a second one by mistake.
* Detected defaults are taken from the current system when possible:
* WiFi interface: current connected wireless interface, or first wireless interface found
* Internet interface: default route interface, or first non-loopback interface found
* Driver: value from `create_ap.conf` if available, otherwise `nl80211`

### Main controls

* `Start AP`: starts the hotspot with the current form values.
* `Stop AP`: stops the running hotspot for the selected WiFi interface.
* `Apply changes`: only becomes active when settings changed from the last applied state. It restarts the AP so changes such as SSID or passphrase take effect.
* `Preflight`: checks required commands and selected interfaces before startup.
* `Check instances`: refreshes the running-instance detection.
* `Show running`: prints running `create_ap` sessions into the log area.
* `Show clients`: lists connected devices with MAC, IP, and hostname when available.
* `Show QR`: creates a standard Wi-Fi QR code (uses running AP settings when available).
* `Load Running AP`: loads settings from the currently active `create_ap` instance into the form.
* `Saved Profiles`: save/update, load, delete, and refresh named profiles.

### Field notes

* `SSID`: hotspot name clients will see.
* `Passphrase`: hotspot password. Use the toggle to show/hide it while typing.
* `Country`: two-letter regulatory domain such as `US`, `DE`, or `UG`. This affects wireless regulatory behavior, not SSID or password.
* `No virtual interface`: useful for adapters that fail when `create_ap` tries to create a separate AP interface.

### What preflight means

Preflight is a safety check before hotspot startup. It verifies:

* `create_ap` is available
* selected network interfaces exist
* required tools are installed for the chosen mode

If preflight fails, the GUI shows what is missing so you can fix it before trying to start the hotspot.

### Profile storage

* Profiles are stored at `~/.config/create_ap/profiles/<profile-name>.json`.
* If `~/.config/create_ap/gui_profile.json` exists from older versions, it is auto-migrated to `default.json`.

Notes:

* The GUI requires Python 3 with Tkinter.
* Running `create_ap` needs root privileges. The GUI will try `pkexec` first, then `sudo`.
* If `create_ap` is not installed system-wide, make sure the local `create_ap` script is executable.
* `make install-gui` installs the launcher (`create_ap_gui`), desktop entry (`create_ap_gui.desktop`), and icon (`create_ap_gui`).


## License
FreeBSD


[linux-wifi-hotspot]: https://github.com/lakinduakash/linux-wifi-hotspot
[linux-router]: https://github.com/garywill/linux-router
