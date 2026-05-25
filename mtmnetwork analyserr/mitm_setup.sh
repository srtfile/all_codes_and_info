#!/usr/bin/env bash
# =============================================================================
#  mitm_setup.sh  –  System setup for mitmproxy transparent & reverse proxy
# =============================================================================
# Supports:
#   transparent   – intercept all TCP traffic via iptables (Linux, requires root)
#   reverse       – reverse-proxy a single upstream host on localhost:8080
#   browser       – configure system proxy for browser/mobile intercept
#   install-ca    – install the mitmproxy CA into the OS trust store
#   mobile-qr     – print QR code pointing to the mitmproxy CA download URL
# =============================================================================
set -euo pipefail

PROXY_HOST="127.0.0.1"
PROXY_PORT="${MITM_PORT:-8080}"
UPSTREAM="${MITM_UPSTREAM:-}"       # e.g. https://api.example.com
ADDON_FILE="${MITM_ADDON:-mitm_toolkit.py}"

# ─── Helpers ─────────────────────────────────────────────────────────────────

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

require() {
    command -v "$1" &>/dev/null || error "'$1' is not installed. Install it first."
}

# ─── Modes ───────────────────────────────────────────────────────────────────

mode_transparent() {
    [[ $EUID -eq 0 ]] || error "Transparent proxy requires root (sudo $0 transparent)"
    require iptables
    info "Setting up iptables transparent proxy on port $PROXY_PORT …"

    # Redirect all outgoing HTTP/HTTPS (except from mitmproxy itself)
    iptables -t nat -N MITMPROXY 2>/dev/null || true
    iptables -t nat -F MITMPROXY

    # Don't intercept mitmproxy's own traffic
    iptables -t nat -A MITMPROXY -m owner --uid-owner "$(id -u)" -j RETURN

    # Redirect 80 and 443 to the proxy port
    iptables -t nat -A MITMPROXY -p tcp --dport 80  -j REDIRECT --to-port "$PROXY_PORT"
    iptables -t nat -A MITMPROXY -p tcp --dport 443 -j REDIRECT --to-port "$PROXY_PORT"

    iptables -t nat -A OUTPUT -p tcp -j MITMPROXY

    info "iptables rules installed."
    info "Starting mitmproxy in transparent mode …"
    mitmproxy --mode transparent \
              --listen-host "$PROXY_HOST" \
              --listen-port "$PROXY_PORT" \
              --ssl-insecure \
              -s "$ADDON_FILE"
}

mode_transparent_cleanup() {
    [[ $EUID -eq 0 ]] || error "Requires root"
    iptables -t nat -D OUTPUT -p tcp -j MITMPROXY 2>/dev/null || true
    iptables -t nat -F MITMPROXY 2>/dev/null || true
    iptables -t nat -X MITMPROXY 2>/dev/null || true
    info "iptables transparent-proxy rules removed."
}

mode_reverse() {
    [[ -n "$UPSTREAM" ]] || error "Set MITM_UPSTREAM=https://api.example.com"
    info "Starting mitmproxy in reverse-proxy mode → $UPSTREAM"
    mitmweb --mode "reverse:$UPSTREAM" \
            --listen-host "$PROXY_HOST" \
            --listen-port "$PROXY_PORT" \
            -s "$ADDON_FILE"
}

mode_browser() {
    info "Starting mitmproxy for browser / mobile intercept …"
    info "Set your device proxy to: $PROXY_HOST:$PROXY_PORT"
    info "Download CA cert at:      http://mitm.it  (while proxy is running)"
    mitmweb --listen-host "$PROXY_HOST" \
            --listen-port "$PROXY_PORT" \
            -s "$ADDON_FILE"
}

mode_install_ca() {
    CA_DIR="$HOME/.mitmproxy"
    CA_PEM="$CA_DIR/mitmproxy-ca-cert.pem"
    [[ -f "$CA_PEM" ]] || error "CA not found at $CA_PEM. Run mitmproxy once to generate it."

    if command -v update-ca-certificates &>/dev/null; then
        # Debian / Ubuntu
        sudo cp "$CA_PEM" /usr/local/share/ca-certificates/mitmproxy.crt
        sudo update-ca-certificates
        info "CA installed (Debian/Ubuntu)"
    elif command -v trust &>/dev/null; then
        # Fedora / RHEL
        sudo trust anchor --store "$CA_PEM"
        info "CA installed (Fedora/RHEL)"
    elif [[ "$(uname)" == "Darwin" ]]; then
        sudo security add-trusted-cert -d -r trustRoot \
             -k /Library/Keychains/System.keychain "$CA_PEM"
        info "CA installed (macOS)"
    else
        warn "Unknown OS – copy $CA_PEM to your trust store manually."
    fi
}

mode_mobile_qr() {
    require qrencode
    LOCAL_IP=$(ip -4 route get 1 2>/dev/null | awk '{print $7;exit}' || echo "192.168.x.x")
    QR_URL="http://$LOCAL_IP:$PROXY_PORT/cert/pem"
    info "Scan this QR code on your mobile device to install the CA:"
    echo ""
    qrencode -t UTF8 "$QR_URL"
    echo ""
    info "URL: $QR_URL"
    info "(mitmproxy must already be running)"
}

mode_headless() {
    info "Starting mitmdump (headless) …"
    mitmdump --listen-host "$PROXY_HOST" \
             --listen-port "$PROXY_PORT" \
             -s "$ADDON_FILE"
}

# ─── Entry point ─────────────────────────────────────────────────────────────

MODE="${1:-browser}"
case "$MODE" in
    transparent)        mode_transparent ;;
    transparent-clean)  mode_transparent_cleanup ;;
    reverse)            mode_reverse ;;
    browser)            mode_browser ;;
    install-ca)         mode_install_ca ;;
    mobile-qr)          mode_mobile_qr ;;
    headless)           mode_headless ;;
    *)
        echo "Usage: $0 {transparent|transparent-clean|reverse|browser|install-ca|mobile-qr|headless}"
        exit 1
        ;;
esac
