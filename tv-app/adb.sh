# Sourced by deploy and screensaver: connect to the TV over Google TV's wireless debugging and set $ADB and $SERIAL.
#
# Wireless debugging listens on a random port that changes when it restarts, and announces it over Bonjour. Reuse a
# live connection if there is one, otherwise look the port up (adb's own discovery is unreliable on macOS, so ask
# dns-sd), and fall back to the classic 5555. TV_HOST in ../.env is the TV's address.
TV_HOST=$(sed -n 's/^TV_HOST=//p' ../.env 2>/dev/null | tr -d "\"'")
[[ -n $TV_HOST ]] || { echo "set TV_HOST=<the TV's address> in .env" >&2; exit 1; }
ADB="${ANDROID_HOME:-$HOME/Library/Android/sdk}/platform-tools/adb"

bonjour_port() {
  local out name
  out=$(mktemp)
  dns-sd -B _adb-tls-connect._tcp local. > "$out" 2>&1 & sleep 3; kill $! 2>/dev/null
  name=$(awk '/ Add / {print $NF; exit}' "$out")
  [[ -n $name ]] || return 1
  dns-sd -L "$name" _adb-tls-connect._tcp local. > "$out" 2>&1 & sleep 3; kill $! 2>/dev/null
  grep -o "reached at [^ ]*" "$out" | sed -E 's/.*:([0-9]+).*/\1/' | head -1
}

SERIAL=$("$ADB" devices | awk -v h="$TV_HOST" 'index($1, h ":") == 1 && $2 == "device" {print $1; exit}')
if [[ -z $SERIAL ]]; then
  PORT=$(bonjour_port || true)
  SERIAL="$TV_HOST:${PORT:-5555}"
  "$ADB" connect "$SERIAL" >/dev/null || true
  "$ADB" -s "$SERIAL" get-state >/dev/null 2>&1 || {
    echo "can't reach the TV. Turn on Developer options > Wireless debugging; the first time, pair with" >&2
    echo "  $ADB pair $TV_HOST:<pairing port> <6-digit code>   (Wireless debugging > Pair device with pairing code)" >&2
    exit 1
  }
fi
