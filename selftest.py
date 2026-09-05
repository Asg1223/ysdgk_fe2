"""画面・カメラなしで一通り動かす自己テスト。

  1) 合成映像でマーカー追跡の精度を確認
  2) 別の色に登録し直せるか（キャリブレーション）
  3) ゲームロジックを 1 ゲーム分まわす
  4) 描画込みの 1 フレーム処理時間を測り、Pi 3 で何 FPS 出そうか見積もる
  5) 色プリセットが自分の色だけに反応するか
  6) 教室にありがちな物に誤反応しないか
"""
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# プリセット色ごとの、印刷物や軍手を想定した BGR
SAMPLE_BGR = {"green": (60, 190, 70), "pink": (190, 60, 220), "blue": (215, 80, 30),
              "purple": (180, 50, 120), "cyan": (220, 200, 40),
              "yellow": (40, 215, 235), "red": (35, 35, 215)}


def synth_frame(w, h, t, color=(35, 35, 215)):
    """マーカーが円を描いて動く合成カメラ映像。"""
    f = np.full((h, w, 3), 45, np.uint8)
    cv2.rectangle(f, (0, int(h * 0.7)), (w, h), (70, 70, 70), -1)   # 床っぽい模様
    cx = int(w * (0.5 + 0.32 * np.cos(t * 1.7)))
    cy = int(h * (0.5 + 0.32 * np.sin(t * 1.3)))
    cv2.circle(f, (cx, cy), 18, color, -1)
    return f, (cx / w, cy / h)


def run_selftest(cfg):
    from colorcatch.tracker import ColorTracker
    from colorcatch.engine import GameEngine
    ok = True
    print("=" * 58)
    print(" カラーキャッチ！ 自己テスト")
    print("=" * 58)

    # 1) 追跡精度
    w, h = cfg["camera"]["width"], cfg["camera"]["height"]
    cname = cfg["marker"].get("color", "red")
    mark = SAMPLE_BGR.get(cname, (35, 35, 215))
    label = cfg.data.get("presets", {}).get(cname, {}).get("label", cname)
    tr = ColorTracker(cfg["marker"], cfg.data.get("presets", {}))
    errs, t0 = [], time.time()
    for i in range(120):
        f, truth = synth_frame(w, h, i * 0.05, mark)
        d = tr.update(f)
        if d.found and not d.held:
            errs.append(((d.x - truth[0]) ** 2 + (d.y - truth[1]) ** 2) ** 0.5)
    track_ms = (time.time() - t0) / 120 * 1000
    hit_rate = len(errs) / 120
    mean_err = float(np.mean(errs)) if errs else 1.0
    print(f"[1] 追跡({label})  検出率 {hit_rate*100:5.1f}%   平均誤差 {mean_err*100:4.1f}%画面   "
          f"{track_ms:5.2f} ms/frame")
    if hit_rate < 0.9 or mean_err > 0.06:
        ok = False
        print("    → NG: 追跡が不安定です")

    # 2) キャリブレーション（青マーカーに変更できるか）
    other = (215, 70, 25) if cname != "blue" else (60, 190, 70)
    g = np.full((h, w, 3), 40, np.uint8)
    cv2.rectangle(g, (int(w * .39), int(h * .39)), (int(w * .61), int(h * .61)),
                  other, -1)
    tr2 = ColorTracker(dict(cfg["marker"]), cfg.data.get("presets", {}))
    okc, msg = tr2.calibrate(g)
    d = tr2.update(g)
    print(f"[2] 色あわせ    {msg} / 再検出={'OK' if d.found else 'NG'}")
    ok = ok and okc and d.found

    # 3) ゲーム 1 本
    eng = GameEngine(cfg["game"], seed=7)
    eng.reset(0.0)
    t, counts = 0.0, {}
    while eng.running and t < cfg["game"]["duration"] + 5:
        t += 1 / 30
        m = None
        if eng.targets:
            tg = sorted(eng.targets, key=lambda x: x.life(t))[0]
            m = (tg.x, tg.y) if tg.kind != "bomb" else (0.05, 0.05)
        for name, _, _ in eng.update(t, m, 0.05):
            counts[name] = counts.get(name, 0) + 1
    s = eng.summary()
    print(f"[3] ゲーム進行  {counts}")
    print(f"    結果 score={s['score']} hits={s['hits']} miss={s['misses']} "
          f"combo={s['best_combo']} acc={s['accuracy']}%")
    if s["score"] <= 0 or "finish" not in counts:
        ok = False
        print("    → NG: 得点または終了処理に問題あり")

    # 4) 描画込みの実測
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    from colorcatch.app import App, PLAY
    cfg.data["audio"]["enabled"] = False
    cfg.data["gpio"]["enabled"] = False
    cfg.path = None                      # テスト中に設定を書き換えない
    app = App(cfg, use_camera=False, windowed=True, headless=True)
    app.fps_target = 1000
    app.set_state(PLAY)
    app.engine.reset(time.time())
    t0, N = time.time(), 90
    for i in range(N):
        app.frame, _ = synth_frame(w, h, i * 0.05, mark)
        app.det = app.tracker.update(app.frame)
        app.marker = (app.det.x, app.det.y) if app.det.found else None
        app.screen_play(False)
        import pygame
        pygame.display.flip()
        if not app.engine.running:
            app.engine.reset(time.time())
    ms = (time.time() - t0) / N * 1000
    app.close()
    print(f"[4] 1フレーム   {ms:5.2f} ms  → この PC で約 {1000/ms:4.0f} fps")
    print(f"    Pi 3 は概ね 5-8 倍遅いので実機で 約 {1000/(ms*6):4.0f} fps 前後の見込み")
    # 5) 色プリセット：自分の色だけに反応し、他の色や黒板を無視するか
    P = cfg.data.get("presets", {})
    sample = {"green": (60, 190, 70), "pink": (190, 60, 220), "blue": (215, 80, 30),
              "purple": (180, 50, 120), "cyan": (220, 200, 40),
              "yellow": (40, 215, 235), "red": (35, 35, 215)}
    bad = []
    for pname in P:
        tp = ColorTracker(dict(cfg["marker"]), P)
        tp.set_preset(pname)
        for cname in P:
            f = np.full((h, w, 3), (60, 60, 60), np.uint8)
            cv2.circle(f, (w // 2, h // 2), 26, sample[cname], -1)
            tp._last, tp._lost = None, 999
            got = tp.update(f).found
            if got != (cname == pname):
                bad.append(f"{P[pname]['label']}→{P[cname]['label']}")
    print(f"[5] 色プリセット {len(P)}色 × {len(P)}色の総当たり: "
          f"{'すべて正しく判定' if not bad else 'NG ' + ', '.join(bad)}")
    if bad:
        ok = False

    tg2 = ColorTracker(dict(cfg["marker"]), P)
    tg2.set_preset(cfg["marker"].get("color", "green"))
    envs = {"黒板(濃い緑)": (54, 79, 38), "黒板の照り返し": (90, 120, 80),
            "観葉植物": (60, 110, 55), "木の机": (55, 105, 160),
            "肌色": (95, 130, 175)}
    ng = []
    for label, bgr in envs.items():
        f = np.full((h, w, 3), (60, 60, 60), np.uint8)
        cv2.rectangle(f, (40, 40), (w - 40, h - 40), bgr, -1)
        tg2._last, tg2._lost = None, 999
        if tg2.update(f).found:
            ng.append(label)
    print(f"[6] 誤反応チェック 教室にありがちな物({len(envs)}種): "
          f"{'すべて無視できた' if not ng else 'NG 反応した→' + ', '.join(ng)}")
    if ng:
        ok = False

    print("-" * 58)
    print(" 結果:", "OK すべて通過" if ok else "NG 上の項目を確認してください")
    return 0 if ok else 1


if __name__ == "__main__":
    from colorcatch.config import Config
    sys.exit(run_selftest(Config(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json"))))
