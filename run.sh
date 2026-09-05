#!/usr/bin/env bash
# 通常起動。画面が消えないよう、スクリーンセーバーも止める
cd "$(dirname "$0")"
xset s off -dpms 2>/dev/null || true
exec python3 main.py "$@"
