#!/usr/bin/env bash
# カラーキャッチ！ セットアップ（Raspberry Pi OS Bullseye / Bookworm 用）
set -e
echo "== 必要なパッケージを入れます（10分ほどかかります）=="
sudo apt-get update
# pip でビルドすると Pi 3 では30分以上かかるため、必ず apt 版を使う
sudo apt-get install -y \
  python3-opencv python3-pygame python3-numpy \
  fonts-noto-cjk python3-rpi.gpio v4l-utils

# Pi カメラ（リボンケーブル接続）を使う場合のみ
if [ "$1" = "--picamera" ]; then
  sudo apt-get install -y python3-picamera2 || echo "picamera2 は入りませんでした（USBカメラを使ってください）"
  sed -i 's/"use_picamera": false/"use_picamera": true/' config.json
fi

echo
echo "== 接続確認 =="
python3 - <<'PY'
import importlib
for m in ("cv2", "pygame", "numpy"):
    try:
        mod = importlib.import_module(m)
        print(f"  {m:8s} OK  {getattr(mod, '__version__', '')}")
    except Exception as e:
        print(f"  {m:8s} NG  {e}")
try:
    import RPi.GPIO
    print("  RPi.GPIO OK")
except Exception as e:
    print(f"  RPi.GPIO NG  {e}（ボタンなしでも遊べます）")
PY
echo
echo "== カメラ一覧 =="
v4l2-ctl --list-devices 2>/dev/null || echo "  （USBカメラが刺さっていないかもしれません）"
echo
echo "== 自己テスト =="
python3 selftest.py
echo
echo "完了。次のコマンドで起動できます:  ./run.sh"
