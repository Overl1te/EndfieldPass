#!/usr/bin/env bash
set -euo pipefail

LOG_PATH="${HOME}/.local/share/Gryphline/Endfield/Player.log"
TAIL_LINES=50000
NO_CLIPBOARD=0

usage() {
  cat <<'EOF'
endfieldpass.sh - extract last Endfield gacha history URL from log

Usage:
  endfieldpass.sh [--log PATH] [--tail N] [--no-clipboard] [--quiet] [--help]

Options:
  --log PATH         Path to Player.log
                     Default: ~/.local/share/Gryphline/Endfield/Player.log
  --tail N           How many last lines to scan (default: 50000)
  --no-clipboard     Do not copy URL to clipboard
  --quiet            Print only the URL (no extra text)
  --help             Show this help

Exit codes:
  0 success
  1 error (log not found / url not found / invalid args)
EOF
}

QUIET=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --log)
      [[ $# -ge 2 ]] || { echo "[ERROR] --log requires a path" >&2; exit 1; }
      LOG_PATH="$2"; shift 2 ;;
    --tail)
      [[ $# -ge 2 ]] || { echo "[ERROR] --tail requires a number" >&2; exit 1; }
      TAIL_LINES="$2"; shift 2 ;;
    --no-clipboard)
      NO_CLIPBOARD=1; shift ;;
    --quiet)
      QUIET=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "[ERROR] Unknown option: $1" >&2
      usage
      exit 1 ;;
  esac
done

if [[ ! "$TAIL_LINES" =~ ^[0-9]+$ ]] || [[ "$TAIL_LINES" -lt 1 ]]; then
  echo "[ERROR] --tail must be a positive integer" >&2
  exit 1
fi

if [[ ! -f "$LOG_PATH" ]]; then
  echo "[ERROR] Log file not found: $LOG_PATH" >&2
  exit 1
fi

# Extract last URL of the form:
# https://ef-webview.gryphline.com/page/gacha_char?... (last occurrence)
URL="$(
  tail -n "$TAIL_LINES" "$LOG_PATH" \
  | grep -Eo 'https://ef-webview\.gryphline\.com/page/gacha_char\?[^[:space:]"<>]+' \
  | tail -n 1 || true
)"

if [[ -z "${URL}" ]]; then
  echo "[ERROR] Gacha history URL not found in the log." >&2
  echo "Open the gacha history page in-game, then run this again." >&2
  exit 1
fi

# Always print the URL (so it can be piped or captured).
echo "$URL"

if [[ "$NO_CLIPBOARD" -eq 1 ]]; then
  exit 0
fi

copy_ok=0
if command -v wl-copy >/dev/null 2>&1; then
  printf '%s' "$URL" | wl-copy
  copy_ok=1
elif command -v xclip >/dev/null 2>&1; then
  printf '%s' "$URL" | xclip -selection clipboard
  copy_ok=1
elif command -v xsel >/dev/null 2>&1; then
  printf '%s' "$URL" | xsel --clipboard --input
  copy_ok=1
fi

if [[ "$QUIET" -eq 1 ]]; then
  exit 0
fi

if [[ "$copy_ok" -eq 1 ]]; then
  echo "========================================"
  echo "URL copied to clipboard."
  echo "Paste it here: https://endfieldpass.com"
  echo "========================================"
else
  echo "========================================"
  echo "URL extracted, but no clipboard tool found."
  echo "Install: wl-clipboard (Wayland) or xclip/xsel (X11)."
  echo "Paste it here: https://endfieldpass.com"
  echo "========================================"
fi
