#!/usr/bin/env bash
# Installs anumati root-owned, so an AI agent running as your user can't
# edit what the approval window shows or what runs as root. Run it as your
# user from a clone of this repo; it calls sudo.
#
#   ./install.sh            install whatever differs
#   ./install.sh --check    list what differs, exit 1 if anything does
#   ./install.sh --uninstall
#
# Installs:
#   /usr/local/bin/anumati                 the CLI / MCP server agents call
#   /usr/local/lib/anumati/dialog.py       the approval window (GTK 4)
#   /usr/local/lib/anumati/theme.py        its look and the theme readability check
#   /usr/local/lib/anumati/remote.py       answering from the phone, through ekatva
#   /usr/local/lib/anumati/runner.py       runs the approved commands as root
#   /usr/local/lib/anumati/userrun.py      runs the approved commands as you
#   /usr/local/lib/anumati/{config,data}/  empty XDG dirs for the window, so
#                                          your GTK CSS can't restyle it
#   /usr/local/bin/vayu-elevate            -> anumati (its old name, kept working)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
lib=/usr/local/lib/anumati
mode=${1:-install}

if [ "$mode" = "--uninstall" ]; then
  sudo rm -rf /usr/local/bin/anumati "$lib"
  [ -L /usr/local/bin/vayu-elevate ] && sudo rm -f /usr/local/bin/vayu-elevate
  echo "anumati removed (the audit log /var/log/anumati.log is kept)"
  exit 0
fi
check=false
[ "$mode" = "--check" ] && check=true

n=0
differs() { n=$((n + 1)); if $check; then echo "differs: $1"; fi; }

# Dependencies: Arch package names; other distributions, see the README.
if command -v pacman >/dev/null; then
  missing=()
  for p in python python-gobject gtk4 libadwaita libnotify sudo; do
    pacman -Q "$p" >/dev/null 2>&1 || missing+=("$p")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    differs "packages not installed: ${missing[*]}"
    $check || sudo pacman -S --needed --noconfirm "${missing[@]}"
  fi
fi

files=(
  "bin/anumati:/usr/local/bin/anumati"
  "lib/dialog.py:$lib/dialog.py"
  "lib/theme.py:$lib/theme.py"
  "lib/remote.py:$lib/remote.py"
  "lib/runner.py:$lib/runner.py"
  "lib/userrun.py:$lib/userrun.py"
)
for pair in "${files[@]}"; do
  src=$here/${pair%%:*} dst=${pair#*:}
  if cmp -s "$src" "$dst" 2>/dev/null && [ "$(stat -c '%U %a' "$dst")" = "root 755" ]; then continue; fi
  differs "$dst"
  $check || sudo install -Dm755 -o root -g root "$src" "$dst"
done
for d in "$lib" "$lib/config" "$lib/data"; do
  if [ -d "$d" ] && [ "$(stat -c '%U %a' "$d")" = "root 755" ]; then continue; fi
  differs "$d (root-owned directory)"
  $check || sudo install -d -m755 -o root -g root "$d"
done

# The old name: a root-owned link, so agents and notes that still say
# vayu-elevate keep working. The old install's files go.
if [ "$(readlink /usr/local/bin/vayu-elevate 2>/dev/null)" != /usr/local/bin/anumati ]; then
  differs "/usr/local/bin/vayu-elevate (link to anumati)"
  $check || sudo ln -sfn /usr/local/bin/anumati /usr/local/bin/vayu-elevate
fi
if [ -e /usr/local/lib/vayu-elevate ]; then
  differs "/usr/local/lib/vayu-elevate (old install, to remove)"
  $check || sudo rm -rf /usr/local/lib/vayu-elevate
fi

if $check; then
  [ "$n" -eq 0 ] && echo "anumati is installed and matches this repo"
  [ "$n" -eq 0 ]
  exit
fi
[ "$n" -eq 0 ] && { echo "anumati already up to date"; exit 0; }
echo "anumati installed: $n change(s). Try: anumati --why 'Test' --cmd 'id'"
