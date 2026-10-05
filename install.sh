#!/bin/bash
# Install DFX Agent Enhancer:
#   curl -fsSL https://raw.githubusercontent.com/orenyomtov/dfx-agent-enhancer/main/install.sh | bash
# Uninstall:
#   curl -fsSL https://raw.githubusercontent.com/orenyomtov/dfx-agent-enhancer/main/install.sh | bash -s -- --uninstall
#
# Downloads the DMG from the latest GitHub release, copies the app to /Applications, turns on
# launch at login and starts it. No sudo.
#
# Overrides: DFX_INSTALL_DIR (default /Applications), DFX_DMG (a local DMG path or another URL).
set -euo pipefail

NAME="DFX Agent Enhancer"
LABEL="com.orenyomtov.dfx-agent-enhancer"
DMG_URL="https://github.com/orenyomtov/dfx-agent-enhancer/releases/latest/download/DFX-Agent-Enhancer.dmg"
DIR=${DFX_INSTALL_DIR:-/Applications}
APP="$DIR/$NAME.app"
AGENT="${DFX_LAUNCH_AGENTS:-$HOME/Library/LaunchAgents}/$LABEL.plist"
TMP=""
MNT=""

say() { printf '%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

cleanup() {
    if [ -n "$MNT" ]; then hdiutil detach -quiet "$MNT" 2>/dev/null || hdiutil detach -quiet -force "$MNT" 2>/dev/null || true; fi
    if [ -n "$TMP" ]; then rm -rf "$TMP"; fi
}

quit_app() {
    # every running copy, wherever it was started from
    local pat="$NAME.app/Contents/MacOS/$NAME"
    pgrep -f "$pat" >/dev/null || return 0
    say "Quitting the running $NAME..."
    pkill -f "$pat" || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        pgrep -f "$pat" >/dev/null || return 0
        sleep 0.5
    done
    pkill -9 -f "$pat" || true
}

uninstall() {
    quit_app
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$AGENT"
    rm -rf "$HOME/Library/WebKit/$LABEL" "$HOME/Library/Caches/$LABEL"   # pywebview caches
    if [ -d "$APP" ]; then
        rm -rf "$APP" || die "could not remove $APP"
        say "Removed $APP"
    else
        say "$APP was not installed"
    fi
    say "Launch at login is off. Your settings are in ~/Library/Application Support/$NAME (delete that folder to remove them)."
}

install() {
    [ -d "$DIR" ] || mkdir -p "$DIR" || die "could not create $DIR"
    [ -w "$DIR" ] || die "$DIR is not writable by $(id -un). Try: DFX_INSTALL_DIR=~/Applications, or use an admin account."

    TMP=$(mktemp -d)
    trap cleanup EXIT
    local src=${DFX_DMG:-$DMG_URL}
    if [ -f "$src" ]; then
        cp "$src" "$TMP/app.dmg"
    else
        say "Downloading $src"
        curl -fL --progress-bar -o "$TMP/app.dmg" "$src" || die "download failed"
    fi

    MNT="$TMP/mnt"
    mkdir "$MNT"
    hdiutil attach -quiet -nobrowse -readonly -noautoopen -mountpoint "$MNT" "$TMP/app.dmg" </dev/null ||
        { MNT=""; die "could not open the DMG"; }
    [ -d "$MNT/$NAME.app" ] || die "the DMG has no $NAME.app"

    quit_app
    if [ -e "$APP" ]; then
        say "Replacing $APP"
        rm -rf "$APP" || die "could not remove the old $APP"
    fi
    ditto "$MNT/$NAME.app" "$APP" || die "could not copy the app to $DIR"
    hdiutil detach -quiet "$MNT" 2>/dev/null || true
    MNT=""
    # curl does not quarantine, but a DMG copied from a browser download would be
    xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
    say "Installed $APP"

    "$APP/Contents/MacOS/$NAME" --launch-at-login on </dev/null >/dev/null || say "Warning: could not turn on launch at login (use the menu)"
    say "Launch at login is on (turn it off with Launch at Login in the menu-bar menu)."

    if [ -n "${DFX_CONFIG:-}" ]; then     # a test install with its own settings file
        open --env "DFX_CONFIG=$DFX_CONFIG" -a "$APP"
    else
        open -a "$APP"
    fi
    say "$NAME is running: look for its graph icon in the menu bar."
}

main() {
    [ "$(uname -s)" = Darwin ] || die "$NAME runs on macOS only."
    [ "$(id -u)" != 0 ] || die "run this as yourself, not with sudo."
    case "${1:-}" in
        "") install ;;
        --uninstall|uninstall) uninstall ;;
        *) die "usage: install.sh [--uninstall]" ;;
    esac
}

main "$@"
