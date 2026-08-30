"""画面・カメラなしで一通り動かす自己テスト。

  1) 合成映像でマーカー追跡の精度を確認
  2) ゲームロジックを 1 ゲーム分まわす
  3) 描画込みの 1 フレーム処理時間を測り、Pi 3 で何 FPS 出そうか見積もる
"""
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def synth_frame(w, h, t):
    """赤いマーカーが円を描いて動く合成カメラ映像。"""
    f = np.full((h, w, 3), 45, np.uint8)
    cv2.rectangle(f, (0, int(h * 0.7)), (w, h), (70, 70, 70), -1)   # 床っぽい模様
    cx = int(w * (0.5 + 0.32 * np.cos(t * 1.7)))
    cy = int(h * (0.5 + 0.32 * np.sin(t * 1.3)))
    cv2.circle(f, (cx, cy), 18, (35, 35, 210), -1)                  # BGR: 赤
    return f, (cx / w, cy / h)


def synth_hand(w, h, open_hand, cx=None, cy=None, R=34):
    """パー／グーの合成映像（赤い手袋を想定）。"""
    import math
    f = np.full((h, w, 3), 45, np.uint8)
    cx = int(w * 0.5) if cx is None else cx
    cy = int(h * 0.5) if cy is None else cy
    if not open_hand:
        cv2.circle(f, (cx, cy), int(R * 0.8), (35, 35, 210), -1)
    else:
        cv2.circle(f, (cx, cy), int(R * 0.55), (35, 35, 210), -1)
        for a in (-100, -70, -40, -10, 40):
            x2 = int(cx + R * 1.5 * math.cos(math.radians(a)))
            y2 = int(cy + R * 1.5 * math.sin(math.radians(a)))
            cv2.line(f, (cx, cy), (x2, y2), (35, 35, 210), 9)
    return f


def run_selftest(cfg):
    from colorcatch.tracker import ColorTracker
    from colorcatch.engine import GameEngine
    ok = True
    print("=" * 58)
    print(" カラーキャッチ！ 自己テスト")
    print("=" * 58)

    # 1) 追跡精度
    w, h = cfg["camera"]["width"], cfg["camera"]["height"]
    tr = ColorTracker(cfg["marker"])
    errs, t0 = [], time.time()
    for i in range(120):
        f, truth = synth_frame(w, h, i * 0.05)
        d = tr.update(f)
        if d.found and not d.held:
            errs.append(((d.x - truth[0]) ** 2 + (d.y - truth[1]) ** 2) ** 0.5)
    track_ms = (time.time() - t0) / 120 * 1000
    hit_rate = len(errs) / 120
    mean_err = float(np.mean(errs)) if errs else 1.0
    print(f"[1] 追跡        検出率 {hit_rate*100:5.1f}%   平均誤差 {mean_err*100:4.1f}%画面   "
          f"{track_ms:5.2f} ms/frame")
    if hit_rate < 0.9 or mean_err > 0.06:
        ok = False
        print("    → NG: 追跡が不安定です")

    # 2) キャリブレーション（青マーカーに変更できるか）
    g = np.full((h, w, 3), 40, np.uint8)
    cv2.rectangle(g, (int(w * .39), int(h * .39)), (int(w * .61), int(h * .61)),
                  (215, 70, 25), -1)
    tr2 = ColorTracker(dict(cfg["marker"]))
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
        app.frame, _ = synth_frame(w, h, i * 0.05)
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
    # 5) 掴む動作（グー／パー）の判定
    tg = ColorTracker(dict(cfg["marker"]))
    tg.calibrate(synth_hand(w, h, False))                    # 手袋の色を登録
    tg.calibrate_gesture(synth_hand(w, h, True), "open")
    okg, gmsg = tg.calibrate_gesture(synth_hand(w, h, False), "closed")
    seq = "".join("G" if tg.update(synth_hand(w, h, i % 6 < 3)).grab else "-"
                  for i in range(18))
    changes = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    print(f"[5] つかむ判定  {gmsg}")
    print(f"    パー3→グー3を3周: {seq}  (- =パー, G =グー / 切替 {changes} 回)")
    if not okg or changes < 4:
        ok = False
        print("    → NG: グー／パーの判定が追従していません")

    # 6) 掴むモードでは、触っただけでは取れないこと
    eng2 = GameEngine(cfg["game"], seed=3)
    eng2.reset(0.0)
    t = 0.0
    while not eng2.targets and t < 3:
        t += 1 / 30
        eng2.update(t, None, 0.05)
    tgt = eng2.targets[0]
    eng2.update(t + 0.03, (tgt.x, tgt.y), 0.05, can_take=False)
    touched_only = eng2.score
    eng2.update(t + 0.06, (tgt.x, tgt.y), 0.05, can_take=True)
    grabbed = eng2.score
    print(f"[6] 掴む条件    触れただけ={touched_only}点 → 握った={grabbed}点")
    if touched_only != 0 or grabbed <= 0:
        ok = False
        print("    → NG: 握らなくても取れてしまいます")

    print("-" * 58)
    print(" 結果:", "OK すべて通過" if ok else "NG 上の項目を確認してください")
    return 0 if ok else 1


if __name__ == "__main__":
    from colorcatch.config import Config
    sys.exit(run_selftest(Config(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json"))))
