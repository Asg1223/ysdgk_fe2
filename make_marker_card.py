#!/usr/bin/env python3
"""印刷用マーカーカードを作る。

  python3 make_marker_card.py             # config.json の色で作る
  python3 make_marker_card.py --color pink
  python3 make_marker_card.py --all       # 全色を1つのPDFに
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from colorcatch.config import Config  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
W, H = 1240, 1754                      # A4 @150dpi
FONTS = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
         "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
         "/usr/share/fonts/truetype/vlgothic/VL-PGothic-Regular.ttf"]

# 印刷したときに、そのプリセットで拾いやすくなる RGB
INK = {"green": (40, 175, 70), "pink": (225, 55, 170), "blue": (25, 90, 210),
       "purple": (130, 55, 190), "cyan": (30, 190, 210), "yellow": (240, 205, 30),
       "red": (220, 20, 25)}


def font(sz):
    for f in FONTS:
        if os.path.exists(f):
            return ImageFont.truetype(f, sz)
    return ImageFont.load_default()


def page(color, label):
    ink = INK.get(color, (40, 175, 70))
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((W // 2, 70), "カラーキャッチ！ マーカーカード",
           font=font(46), fill=(20, 20, 20), anchor="mm")
    d.text((W // 2, 130), f"{label}のマーカー ／ 厚紙に貼って切り取り、色の面をカメラに向けます（2枚分）",
           font=font(24), fill=(90, 90, 90), anchor="mm")
    for cy in (560, 1290):
        r = 300
        d.ellipse((W // 2 - r, cy - r, W // 2 + r, cy + r), fill=ink,
                  outline=(30, 30, 30), width=4)
        d.ellipse((W // 2 - r - 16, cy - r - 16, W // 2 + r + 16, cy + r + 16),
                  outline=(30, 30, 30), width=3)
        d.text((W // 2, cy), "CATCH!", font=font(90), fill=(255, 255, 255), anchor="mm")
        d.text((W // 2, cy + r + 50), "— 切り取り線 —", font=font(24),
               fill=(150, 150, 150), anchor="mm")
    d.text((W // 2, H - 40),
           "色を変えるときは、ゲーム画面で K キー（またはCキーの色あわせ）",
           font=font(22), fill=(120, 120, 120), anchor="mm")
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--color")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=os.path.join(BASE, "marker_card.pdf"))
    a = ap.parse_args()
    cfg = Config(os.path.join(BASE, "config.json"))
    presets = cfg.data.get("presets", {})
    if a.all:
        names = list(presets)
    else:
        names = [a.color or cfg["marker"].get("color", "green")]
    pages = [page(n, presets.get(n, {}).get("label", n)) for n in names]
    pages[0].save(a.out, "PDF", resolution=150.0,
                  save_all=True, append_images=pages[1:])
    print(f"{a.out} を作りました（{', '.join(names)}）")


if __name__ == "__main__":
    main()
