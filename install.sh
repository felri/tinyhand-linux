#!/usr/bin/env bash
# Installs TinyHand for the current user: ~/.local/bin/tinyhand and an app-menu entry.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

missing=()
for pkg in python-gobject gtk4 gtk4-layer-shell python-numpy python-pillow gst-plugins-base gst-plugins-good; do
  pacman -Q "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if ((${#missing[@]})); then
  echo "Missing packages: ${missing[*]}"
  echo "Install them with: sudo pacman -S --needed ${missing[*]}"
  exit 1
fi

mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons/hicolor/256x256/apps
ln -sf "$ROOT/bin/tinyhand" ~/.local/bin/tinyhand
cp "$ROOT/assets/icons/tinyhand.png" ~/.local/share/icons/hicolor/256x256/apps/io.github.tinyhand.Linux.png
cat > ~/.local/share/applications/io.github.tinyhand.Linux.desktop <<EOF
[Desktop Entry]
Type=Application
Name=TinyHand
Comment=A tiny hand on a stick that points at things on your screen
Exec=$HOME/.local/bin/tinyhand
Icon=io.github.tinyhand.Linux
Categories=Utility;Presentation;
Keywords=pointer;presentation;laser;draw;screen;
StartupNotify=false
Actions=Toggle;Settings;Quit;

[Desktop Action Toggle]
Name=Turn pointer on/off
Exec=$HOME/.local/bin/tinyhand toggle

[Desktop Action Settings]
Name=Settings
Exec=$HOME/.local/bin/tinyhand settings

[Desktop Action Quit]
Name=Quit
Exec=$HOME/.local/bin/tinyhand quit
EOF

echo "Installed: ~/.local/bin/tinyhand"
echo
echo "For niri, add to ~/.config/niri/config.kdl:"
cat <<'EOF'
    spawn-at-startup "~/.local/bin/tinyhand"

    binds {
        Ctrl+Alt+H hotkey-overlay-title="TinyHand: toggle pointer" { spawn "~/.local/bin/tinyhand" "toggle"; }
        Ctrl+Alt+X hotkey-overlay-title="TinyHand: clear drawing" { spawn "~/.local/bin/tinyhand" "clear"; }
    }
EOF
