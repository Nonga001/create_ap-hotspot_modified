#!/bin/bash
# Fix Wi-Fi channel conflict for create_ap
# Usage: ./fix_channel.sh [wifi_iface] [ssid] [target_channel] [hotspot_ssid] [hotspot_pass]
# Example: ./fix_channel.sh wlp2s0 KONNECT 149 MyHotspot MyPassword123

set -euo pipefail

IFACE="${1:-wlp2s0}"
SSID_FILTER="${2:-KONNECT}"
TARGET_CHANNEL="${3:-149}"
HOTSPOT_SSID="${4:-Lantana}"
HOTSPOT_PASS="${5:-987654321...}"
LOCK_APPLIED=false

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

freq_to_channel() {
    local freq_raw="$1"
    local freq="${freq_raw%%.*}"
    case "$freq" in
        2412) echo 1 ;;
        2417) echo 2 ;;
        2422) echo 3 ;;
        2427) echo 4 ;;
        2432) echo 5 ;;
        2437) echo 6 ;;
        2442) echo 7 ;;
        2447) echo 8 ;;
        2452) echo 9 ;;
        2457) echo 10 ;;
        2462) echo 11 ;;
        2467) echo 12 ;;
        2472) echo 13 ;;
        2484) echo 14 ;;
        *)
            if [[ "$freq" =~ ^[0-9]+$ ]] && (( freq >= 5000 && freq <= 5895 )); then
                echo $(((freq - 5000) / 5))
            else
                echo unknown
            fi
            ;;
    esac
}

channel_band() {
    local ch="$1"
    if [[ "$ch" =~ ^[0-9]+$ ]] && (( ch >= 36 )); then
        echo 5
    else
        echo 2.4
    fi
}

auto_unlock() {
    if [[ "$LOCK_APPLIED" != "true" ]]; then
        return
    fi

    set +e
    echo
    echo -e "${YELLOW}[auto-unlock] Releasing BSSID lock and restoring roaming...${NC}"
    nmcli connection modify "$ACTIVE_CONN" 802-11-wireless.bssid ""
    nmcli connection down "$ACTIVE_CONN" >/dev/null 2>&1
    sleep 1
    nmcli connection up "$ACTIVE_CONN" >/dev/null 2>&1
    echo -e "${GREEN}[auto-unlock] Done.${NC}"
}

echo -e "${BLUE}=== Wi-Fi Channel Conflict Fix for create_ap ===${NC}"
echo -e "Interface: ${YELLOW}${IFACE}${NC} | SSID filter: ${YELLOW}${SSID_FILTER}${NC} | Target channel: ${YELLOW}${TARGET_CHANNEL}${NC}\n"

# Step 1: Current link state
echo -e "${YELLOW}[1] Checking current Wi-Fi link...${NC}"
CURRENT_BSSID=$(iw dev "$IFACE" link 2>/dev/null | awk '/Connected to/ {print $3; exit}' || true)
CURRENT_FREQ=$(iw dev "$IFACE" link 2>/dev/null | awk '/freq:/ {print $2; exit}' || true)
CURRENT_SSID=$(iw dev "$IFACE" link 2>/dev/null | awk -F': ' '/SSID:/ {print $2; exit}' || true)
CURRENT_CH=$(freq_to_channel "${CURRENT_FREQ:-}")

ACTIVE_CONN=$(nmcli -t -e no -f NAME,DEVICE connection show --active | awk -F: -v d="$IFACE" '$NF==d{sub(/:[^:]*$/, "", $0); print; exit}')

if [[ -z "$ACTIVE_CONN" ]]; then
    echo -e "${RED}No active NetworkManager connection found on ${IFACE}.${NC}"
    echo -e "${YELLOW}Connect to your uplink first, then rerun.${NC}"
    exit 1
fi

if [[ -z "$CURRENT_SSID" ]]; then
    echo -e "${RED}Not connected to any Wi-Fi network.${NC}"
else
    echo -e "${GREEN}Connected: SSID ${CURRENT_SSID}, BSSID ${CURRENT_BSSID}, Channel ${CURRENT_CH}${NC}"
fi

if [[ "$CURRENT_CH" != "$TARGET_CHANNEL" ]]; then
    echo -e "${YELLOW}Note: current channel is ${CURRENT_CH}, target is ${TARGET_CHANNEL}.${NC}"
    echo -e "${YELLOW}For one-radio AP+STA, uplink and AP should stay on same channel.${NC}"
fi

echo -e "${GREEN}Using active connection profile: ${ACTIVE_CONN}${NC}\n"
trap auto_unlock EXIT INT TERM

# Step 2: Scan APs
echo -e "${YELLOW}[2] Scanning APs for ${SSID_FILTER}...${NC}"
nmcli dev wifi rescan >/dev/null 2>&1 || true
sleep 2

SCAN_LINES=$(nmcli -t -e no -f BSSID,SSID,CHAN,SIGNAL dev wifi list --rescan no | grep ":${SSID_FILTER}:" || true)
if [[ -z "$SCAN_LINES" ]]; then
    echo -e "${RED}No APs found for SSID '${SSID_FILTER}'.${NC}"
    exit 1
fi

echo -e "${BLUE}Available APs:${NC}"
echo "------------------------------------------------------------"

mapfile -t AP_LIST < <(echo "$SCAN_LINES")
PREFERRED_INDEX=-1
BEST_SIGNAL=-1
BEST_ANY_INDEX=0
BEST_ANY_SIGNAL=-1
for i in "${!AP_LIST[@]}"; do
    line="${AP_LIST[$i]}"
    signal="${line##*:}"
    tmp="${line%:*}"
    chan="${tmp##*:}"
    left="${tmp%:*}"
    bssid="${left:0:17}"
    ssid="${left:18}"
    band=$(channel_band "$chan")

    if [[ "$signal" =~ ^[0-9]+$ ]] && (( signal > BEST_ANY_SIGNAL )); then
        BEST_ANY_SIGNAL=$signal
        BEST_ANY_INDEX=$i
    fi

    status="${YELLOW}[other channel]${NC}"
    if [[ "$chan" == "$TARGET_CHANNEL" ]]; then
        status="${GREEN}[preferred]${NC}"
        if [[ "$signal" =~ ^[0-9]+$ ]] && (( signal > BEST_SIGNAL )); then
            BEST_SIGNAL=$signal
            PREFERRED_INDEX=$i
        fi
    fi

    echo -e "[$((i + 1))] ${bssid}  SSID:${ssid}  CH:${chan} (${band}GHz)  SIG:${signal}%  ${status}"
done

echo "------------------------------------------------------------"
echo "[a] Auto-pick (target channel ${TARGET_CHANNEL}, or strongest available)"
echo "[u] Unlock BSSID (roaming mode)"
echo "[q] Quit"
echo -e "${YELLOW}Tip:${NC} You can choose channel 11 (2.4GHz) or 149 (5GHz) directly by number."

echo
read -rp "Choose number/a/u/q: " CHOICE

if [[ "$CHOICE" == "q" ]]; then
    echo "Exiting."
    exit 0
fi

if [[ "$CHOICE" == "u" ]]; then
    echo -e "${YELLOW}Unlocking BSSID on profile ${ACTIVE_CONN}...${NC}"
    nmcli connection modify "$ACTIVE_CONN" 802-11-wireless.bssid ""
    nmcli connection down "$ACTIVE_CONN" 2>/dev/null || true
    sleep 1
    nmcli connection up "$ACTIVE_CONN"
    echo -e "${GREEN}Unlocked. Roaming restored.${NC}"
    exit 0
fi

if [[ "$CHOICE" == "a" ]]; then
    if (( PREFERRED_INDEX >= 0 )); then
        SELECTED_LINE="${AP_LIST[$PREFERRED_INDEX]}"
    else
        SELECTED_LINE="${AP_LIST[$BEST_ANY_INDEX]}"
        echo -e "${YELLOW}No AP found on target channel ${TARGET_CHANNEL}; using strongest available AP instead.${NC}"
    fi
else
    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]]; then
        echo -e "${RED}Invalid choice.${NC}"
        exit 1
    fi
    INDEX=$((CHOICE - 1))
    if (( INDEX < 0 || INDEX >= ${#AP_LIST[@]} )); then
        echo -e "${RED}Choice out of range.${NC}"
        exit 1
    fi
    SELECTED_LINE="${AP_LIST[$INDEX]}"
fi

selected_signal="${SELECTED_LINE##*:}"
selected_tmp="${SELECTED_LINE%:*}"
SELECTED_CH="${selected_tmp##*:}"
selected_left="${selected_tmp%:*}"
SELECTED_BSSID="${selected_left:0:17}"

if [[ "$SELECTED_CH" != "$TARGET_CHANNEL" ]]; then
    echo -e "${YELLOW}Warning: selected AP is on channel ${SELECTED_CH}, not ${TARGET_CHANNEL}.${NC}"
fi

echo -e "\n${YELLOW}[3] Locking connection to BSSID ${SELECTED_BSSID} (CH ${SELECTED_CH})...${NC}"
nmcli connection modify "$ACTIVE_CONN" 802-11-wireless.bssid "$SELECTED_BSSID"
LOCK_APPLIED=true
nmcli connection down "$ACTIVE_CONN" 2>/dev/null || true
sleep 1
nmcli connection up "$ACTIVE_CONN"
sleep 3

# Step 4: Verify link
LINK_FREQ=$(iw dev "$IFACE" link 2>/dev/null | awk '/freq:/ {print $2}' | head -n1 || true)
LINK_BSSID=$(iw dev "$IFACE" link 2>/dev/null | awk '/Connected to/ {print $3}' | head -n1 || true)
LINK_CH=$(freq_to_channel "$LINK_FREQ")

echo -e "\n${YELLOW}[4] Verification${NC}"
echo -e "Now connected to: ${GREEN}${LINK_BSSID:-unknown}${NC} on channel ${GREEN}${LINK_CH}${NC}"

if [[ "${LINK_BSSID,,}" == "${SELECTED_BSSID,,}" ]]; then
    echo -e "${GREEN}BSSID lock applied successfully.${NC}"
else
    echo -e "${YELLOW}BSSID differs from selected. Driver/roaming may have overridden lock.${NC}"
fi

# Step 5: Ready command for create_ap
USE_CHANNEL="$TARGET_CHANNEL"
if [[ "$LINK_CH" =~ ^[0-9]+$ ]]; then
    USE_CHANNEL="$LINK_CH"
fi

BAND=$(channel_band "$USE_CHANNEL")
HOTSPOT_CMD=(pkexec /home/shalekami/create_ap/create_ap -m nat -w 2 --freq-band "$BAND" -c "$USE_CHANNEL" --driver nl80211 "$IFACE" "$IFACE" "$HOTSPOT_SSID" "$HOTSPOT_PASS")

echo
echo -e "${BLUE}=== Run create_ap with matching channel ===${NC}"
printf "%b" "${YELLOW}"
printf '%q ' "${HOTSPOT_CMD[@]}"
printf "%b\n" "${NC}"
echo
echo -e "${YELLOW}Tip:${NC} if channel conflict still appears, use a second USB Wi-Fi adapter for AP mode."

echo
read -rp "Start hotspot now with this channel/band? (y/N): " START_NOW
if [[ "${START_NOW,,}" == "y" ]]; then
    echo -e "${GREEN}Starting hotspot now...${NC}"
    "${HOTSPOT_CMD[@]}"
else
    echo "Hotspot not started. Use the printed command when ready."
fi
