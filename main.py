#!/usr/bin/env python3
"""カラーキャッチ！  Raspberry Pi 3 用 体験型ゲーム

  python3 main.py                 通常起動（フルスクリーン）
  python3 main.py --windowed      ウィンドウ表示（開発用）
  python3 main.py --no-camera     カメラを使わずマウスで操作
  python3 main.py --debug         FPS・マスク表示つき
  python3 main.py --selftest      画面なしで動作テスト
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from colorcatch.config import Config          # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json"))
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--no-camera", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--calibrate", action="store_true", help="色あわせ画面から始める")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    cfg = Config(args.config)
    if args.selftest:
        from selftest import run_selftest
        return run_selftest(cfg)

    from colorcatch.app import App, CALIB
    app = App(cfg, use_camera=not args.no_camera,
              windowed=args.windowed, debug=args.debug)
    if args.calibrate:
        app.set_state(CALIB)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
