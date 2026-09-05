#!/usr/bin/env bash
# 電源を入れたら自動でゲームが立ち上がるようにする（Raspberry Pi OS デスクトップ版）
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/colorcatch.desktop <<DESK
[Desktop Entry]
Type=Application
Name=ColorCatch
Exec=lxterminal -e "$DIR/run.sh"
X-GNOME-Autostart-enabled=true
DESK
# 画面が勝手に暗くならないようにする
mkdir -p ~/.config/lxsession/LXDE-pi
grep -q xset ~/.config/lxsession/LXDE-pi/autostart 2>/dev/null || {
  cp /etc/xdg/lxsession/LXDE-pi/autostart ~/.config/lxsession/LXDE-pi/autostart 2>/dev/null || true
  echo "@xset s off"     >> ~/.config/lxsession/LXDE-pi/autostart
  echo "@xset -dpms"     >> ~/.config/lxsession/LXDE-pi/autostart
  echo "@xset s noblank" >> ~/.config/lxsession/LXDE-pi/autostart
}
echo "自動起動を設定しました。解除は rm ~/.config/autostart/colorcatch.desktop"
