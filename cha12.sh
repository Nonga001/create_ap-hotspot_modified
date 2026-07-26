#!/bin/bash
# Manual BSSID lock helper for a selected SSID/BSSID.
# Usage: ./cha12.sh [iface] [ssid] [bssid]
# Example: ./cha12.sh wlp2s0 KONNECT 28:80:8A:2E:74:D8

set -euo pipefail

IFACE="${1:-wlp2s0}"
SSID="${2:-KONNECT}"
BSSID="${3:-}"

if [[ -z "$BSSID" ]]; then
    echo "Usage: $0 [iface] [ssid] [bssid]"
    echo "Example: $0 wlp2s0 KONNECT 28:80:8A:2E:74:D8"
    exit 1
fi

ACTIVE_CONN=$(nmcli -t -e no -f NAME,DEVICE connection show --active | awk -F: -v d="$IFACE" '$NF==d{sub(/:[^:]*$/, "", $0); print; exit}')
if [[ -z "$ACTIVE_CONN" ]]; then
    echo "[-] No active NetworkManager connection on $IFACE"
    exit 1
fi

echo "[+] Locking $IFACE to BSSID $BSSID (SSID: $SSID) using profile '$ACTIVE_CONN'..."

nmcli connection modify "$ACTIVE_CONN" 802-11-wireless.bssid "$BSSID"
nmcli connection down "$ACTIVE_CONN" 2>/dev/null || true
sleep 1
nmcli dev wifi connect "$SSID" bssid "$BSSID" ifname "$IFACE"

cleanup() {
    echo
    echo "[+] Releasing BSSID lock on profile '$ACTIVE_CONN'..."
    nmcli dev disconnect "$IFACE" || true
    nmcli connection modify "$ACTIVE_CONN" 802-11-wireless.bssid ""
    nmcli connection up "$ACTIVE_CONN" || true
    echo "[+] Wi-Fi reset to roaming mode."
}

trap cleanup INT TERM

echo "[*] BSSID lock active. Press Ctrl+C to unlock and exit."
while true; do
    sleep 2
done
