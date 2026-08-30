"""画面・入力・状態遷移をまとめたアプリ本体。"""
import math
import os
import time

import cv2
import numpy as np
import pygame

from .engine import GameEngine, NORMAL, BONUS, BOMB
from .gpio_io import HardwareIO
from .ranking import Ranking
from .sound import SoundBank
from .text import Fonts
from .tracker import Camera, ColorTracker, SkinTracker

ATTRACT, CALIB, COUNTDOWN, PLAY, RESULT = "attract", "calib", "countdown", "play", "result"

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
CYAN = (60, 220, 235)
GOLD = (255, 205, 60)
RED = (235, 70, 70)
GREEN = (90, 225, 120)
DIM = (150, 160, 175)


def hsv_to_rgb(h, s=220, v=240):
    px = np.uint8([[[h % 180, s, v]]])
    b, g, r = cv2.cvtColor(px, cv2.COLOR_HSV2BGR)[0][0]
    return int(r), int(g), int(b)


class App:
    def __init__(self, cfg, use_camera=True, windowed=False, debug=False, headless=False):
        self.cfg = cfg
        self.debug = debug
        self.headless = headless
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        if headless:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

        self.snd = SoundBank(cfg["audio"])
        pygame.init()
        sc = cfg["screen"]
        flags = 0
        if sc.get("fullscreen", True) and not windowed and not headless:
            flags = pygame.FULLSCREEN | pygame.SCALED
        self.screen = pygame.display.set_mode((sc["width"], sc["height"]), flags)
        pygame.display.set_caption(cfg["ui"]["title"])
        if not headless:
            pygame.mouse.set_visible(False)
        self.W, self.H = self.screen.get_size()
        self.clock = pygame.time.Clock()
        self.fps_target = int(sc.get("fps", 30))
        self.fonts = Fonts(self.H, prefer_ja=(cfg["ui"].get("language", "ja") == "ja"))

        self.trackers = {
            "color": ColorTracker(cfg["marker"]),
            "skin": SkinTracker(cfg["marker"], cfg.data.get("skin", {})),
        }
        self.track_mode = cfg["marker"].get("mode", "color")
        if self.track_mode not in self.trackers:
            self.track_mode = "color"
        self.tracker = self.trackers[self.track_mode]
        self.cam = Camera(cfg["camera"]) if use_camera else None
        self.cam_ok = bool(self.cam and self.cam.ok)
        self.io = HardwareIO(cfg["gpio"])
        self.rank = Ranking(os.path.join(base, "scores.json"))
        self.engine = GameEngine(cfg["game"], aspect=self.W / self.H)

        self.mode = cfg["game"].get("mode", "touch")   # "grab" = 掴んで取る
        self.grab = False
        self.calib_step = 0
        self.state = ATTRACT
        self.state_t = time.time()
        self.frame = None
        self.det = None
        self.marker = None
        self.name = ""
        self.pending = None          # 保存待ちのスコア
        self.flash = 0.0
        self.msg = ""
        self.msg_t = 0.0
        self.running = True
        self.bg = pygame.Surface((self.W, self.H))
        self.dark = pygame.Surface((self.W, self.H))
        self.dark.set_alpha(115)
        self.dark.fill((5, 8, 20))
        self.cursor_r = float(cfg["marker"].get("cursor_radius", 46)) / self.H

        # ボタンが無い構成のための「マーカーをかざしてスタート」
        inp = cfg.data.get("input", {})
        self.hold_enabled = bool(inp.get("hold_to_start", True)) and (
            not self.io.available or inp.get("always_show", False))
        self.hold_sec = float(inp.get("hold_seconds", 1.8))
        self.hold_since = None
        self.io.led_blink(0.9)

    # ---------------- 入出力 ----------------
    def set_state(self, s):
        self.state = s
        self.state_t = time.time()
        self.hold_since = None
        if s == CALIB:
            self.calib_step = 0
        # 素手モード：プレイ中は背景の更新を止める（止めた手が背景に溶けないように）
        for tr in getattr(self, "trackers", {}).values():
            tr.freeze(s in (COUNTDOWN, PLAY))

    def switch_tracking(self, mode=None):
        """素手（肌色）と 色マーカー を切り替える。"""
        self.track_mode = mode or ("color" if self.track_mode == "skin" else "skin")
        self.tracker = self.trackers[self.track_mode]
        self.cfg.data["marker"]["mode"] = self.track_mode
        self.calib_step = 0
        self.toast(self.fonts.t("mode_switched") + self.tracker.label)
        self.snd.play("coin")

    def cursor_rgb(self):
        if self.tracker.name == "skin":
            return (255, 190, 120)
        return hsv_to_rgb(self.tracker.hue)

    def toast(self, text):
        self.msg, self.msg_t = text, time.time()

    def poll(self):
        """ボタン相当の入力があったら True。"""
        go = self.io.button_pressed()
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False
            elif e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_ESCAPE, pygame.K_q):
                    if self.state == CALIB:
                        self.set_state(ATTRACT)
                    else:
                        self.running = False
                elif e.key in (pygame.K_SPACE, pygame.K_RETURN):
                    go = True
                elif e.key == pygame.K_c:
                    self.set_state(CALIB)
                elif e.key == pygame.K_d:
                    self.debug = not self.debug
                elif e.key == pygame.K_m:
                    self.switch_tracking()
                elif e.key == pygame.K_LEFTBRACKET:
                    self.tracker.hue_tol = max(4, self.tracker.hue_tol - 2)
                elif e.key == pygame.K_RIGHTBRACKET:
                    self.tracker.hue_tol = min(40, self.tracker.hue_tol + 2)
                elif e.key == pygame.K_MINUS:
                    self.tracker.val_min = max(20, self.tracker.val_min - 10)
                elif e.key == pygame.K_EQUALS:
                    self.tracker.val_min = min(230, self.tracker.val_min + 10)
                elif self.state == RESULT:
                    if e.key == pygame.K_BACKSPACE:
                        self.name = self.name[:-1]
                    elif (e.unicode and e.unicode.isprintable() and e.unicode.isascii()
                          and len(self.name) < 8):
                        self.name += e.unicode
            elif e.type == pygame.MOUSEBUTTONDOWN:
                go = True
        return go

    def capture(self):
        """カメラを 1 フレーム読み、マーカー位置を更新する。"""
        if self.cam_ok:
            f = self.cam.read()
            if f is not None:
                self.frame = f
                self.det = self.tracker.update(f)
                self.marker = (self.det.x, self.det.y) if self.det.found else None
                self.grab = bool(self.det.grab) if self.mode == "grab" else True
                return
        # カメラが無い場合はマウスで代用（PC での動作確認・非常時用）
        mx, my = pygame.mouse.get_pos()
        self.marker = (mx / self.W, my / self.H)
        self.det = None
        # カメラなしのときは左クリックを「握り」として扱う（動作確認用）
        self.grab = pygame.mouse.get_pressed()[0] if self.mode == "grab" else True

    # ---------------- 描画部品 ----------------
    def draw_camera_bg(self):
        if self.frame is None:
            self.screen.fill((12, 14, 24))
        else:
            rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
            surf = pygame.surfarray.make_surface(rgb.swapaxes(0, 1))
            pygame.transform.scale(surf, (self.W, self.H), self.bg)
            self.screen.blit(self.bg, (0, 0))
        self.screen.blit(self.dark, (0, 0))

    def text(self, s, font, color, cx=None, y=0, x=None, shadow=True):
        img = font.render(s, True, color)
        r = img.get_rect()
        if x is not None:
            r.left = x
        else:
            r.centerx = cx if cx is not None else self.W // 2
        r.top = y
        if shadow:
            sh = font.render(s, True, (0, 0, 0))
            self.screen.blit(sh, (r.left + 2, r.top + 3))
        self.screen.blit(img, r)
        return r

    def hold_button(self, nx, ny, label, now=None):
        """円の上にマーカーを一定時間置いたらスタート扱いにする。

        物理ボタンが無くても、係の人がキーを押さなくても回せるようにするため。
        """
        if not self.hold_enabled:
            return False
        now = now or time.time()
        # 握って始める場合は短くてよい（狙って握る動作自体が意思表示になる）
        hold_sec = 0.7 if self.mode == "grab" else self.hold_sec
        x, y = int(nx * self.W), int(ny * self.H)
        r = int(self.H * 0.085)
        inside = False
        if self.marker:
            dx = (self.marker[0] - nx) * self.W
            dy = (self.marker[1] - ny) * self.H
            inside = (dx * dx + dy * dy) ** 0.5 < r + self.cursor_r * self.H * 0.5
        if inside and self.mode == "grab":
            inside = self.grab            # 的の上で手を握ったときだけ溜まる
        if inside:
            if self.hold_since is None:
                self.hold_since = now
                self.snd.play("beep")
            frac = min(1.0, (now - self.hold_since) / hold_sec)
        else:
            self.hold_since = None
            frac = 0.0

        col = GREEN if inside else WHITE
        pygame.draw.circle(self.screen, (12, 30, 24), (x, y), r)
        pygame.draw.circle(self.screen, col, (x, y), r, 5)
        if frac > 0:
            rect = pygame.Rect(x - r + 8, y - r + 8, 2 * (r - 8), 2 * (r - 8))
            pygame.draw.arc(self.screen, GOLD, rect, math.pi / 2,
                            math.pi / 2 + 2 * math.pi * frac, 12)
        img = self.fonts.small.render(label, True, col)
        self.screen.blit(img, img.get_rect(center=(x, y + r + 30)))
        if inside:      # 溜まっている間だけ秒数を出す（普段は的だけ見せる）
            left = max(0.0, hold_sec - (now - self.hold_since))
            cnt = self.fonts.big.render(str(max(1, math.ceil(left))), True, GOLD)
        else:
            cnt = self.fonts.big.render("◎", True, DIM)
        self.screen.blit(cnt, cnt.get_rect(center=(x, y)))

        if frac >= 1.0:
            self.hold_since = None
            return True
        return False

    def draw_cursor(self):
        if not self.marker:
            return
        x, y = int(self.marker[0] * self.W), int(self.marker[1] * self.H)
        r = int(self.cursor_r * self.H)
        col = self.cursor_rgb()
        held = bool(self.det and self.det.held)
        grabbing = self.mode == "grab" and self.grab
        if grabbing:
            # 握っている間は塗りつぶし＋金色のふちで「掴んでいる」ことを伝える
            pygame.draw.circle(self.screen, col, (x, y), int(r * 0.8))
            pygame.draw.circle(self.screen, GOLD, (x, y), int(r * 0.8), 6)
            for a in (-2.2, -0.9, 0.4, 1.7, 2.9):
                pygame.draw.line(self.screen, GOLD,
                                 (x + int(r * 0.8 * math.cos(a)), y + int(r * 0.8 * math.sin(a))),
                                 (x + int(r * 1.15 * math.cos(a)), y + int(r * 1.15 * math.sin(a))), 4)
        else:
            pygame.draw.circle(self.screen, col, (x, y), r, 4 if not held else 2)
            pygame.draw.circle(self.screen, WHITE, (x, y), max(3, r // 8))
            pygame.draw.line(self.screen, col, (x - r - 10, y), (x - r + 4, y), 3)
            pygame.draw.line(self.screen, col, (x + r - 4, y), (x + r + 10, y), 3)

    def draw_target(self, t, now):
        x, y = int(t.x * self.W), int(t.y * self.H)
        r = int(t.r * self.H)
        life = t.life(now)
        if t.kind == NORMAL:
            pygame.draw.circle(self.screen, (25, 90, 130), (x, y), r)
            pygame.draw.circle(self.screen, CYAN, (x, y), r, 5)
            pygame.draw.circle(self.screen, WHITE, (x, y), max(4, r // 5))
        elif t.kind == BONUS:
            pts = []
            for i in range(10):
                rr = r * 1.5 if i % 2 == 0 else r * 0.7
                a = -math.pi / 2 + i * math.pi / 5
                pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
            pygame.draw.polygon(self.screen, GOLD, pts)
            pygame.draw.polygon(self.screen, WHITE, pts, 3)
        else:
            pygame.draw.circle(self.screen, (35, 20, 30), (x, y), r)
            pygame.draw.circle(self.screen, RED, (x, y), r, 6)
            d = int(r * 0.55)
            pygame.draw.line(self.screen, RED, (x - d, y - d), (x + d, y + d), 8)
            pygame.draw.line(self.screen, RED, (x + d, y - d), (x - d, y + d), 8)
        # 残り時間のリング
        if t.kind != BOMB:
            rect = pygame.Rect(x - r - 12, y - r - 12, 2 * (r + 12), 2 * (r + 12))
            pygame.draw.arc(self.screen, WHITE, rect, math.pi / 2,
                            math.pi / 2 + 2 * math.pi * life, 4)

    def draw_pops(self, now):
        for p in self.engine.pops:
            age = (now - p.t) / 0.8
            col = RED if p.kind == BOMB else (GOLD if p.kind == BONUS else GREEN)
            img = self.fonts.mid.render(p.text, True, col)
            img.set_alpha(int(255 * (1 - age)))
            self.screen.blit(img, img.get_rect(
                center=(int(p.x * self.W), int(p.y * self.H - 60 * age))))

    def draw_debug(self, extra=""):
        if not self.debug:
            return
        lines = [f"FPS {self.clock.get_fps():4.1f}",
                 f"H{self.tracker.hue} tol{self.tracker.hue_tol} "
                 f"S>{self.tracker.sat_min} V>{self.tracker.val_min}",
                 f"cam={'ok' if self.cam_ok else 'none'} gpio={'ok' if self.io.available else 'none'}",
                 extra]
        y0 = self.H - 26 * len([s for s in lines if s]) - 10
        for i, s in enumerate([s for s in lines if s]):
            self.text(s, self.fonts.tiny, GREEN, x=12, y=y0 + i * 26)
        if self.tracker.last_mask is not None:
            m = cv2.cvtColor(self.tracker.last_mask, cv2.COLOR_GRAY2RGB)
            m = cv2.resize(m, (200, 150))
            self.screen.blit(pygame.surfarray.make_surface(m.swapaxes(0, 1)),
                             (self.W - 210, self.H - 160))

    # ---------------- 各画面 ----------------
    def screen_attract(self, go):
        now = time.time()
        self.draw_camera_bg()
        T = self.fonts.t
        self.text(self.cfg["ui"]["title"], self.fonts.big, GOLD, y=int(self.H * 0.06))
        g = self.mode == "grab"
        if g:
            k1 = "howto1_skin" if self.tracker.name == "skin" else "howto1_grab"
        else:
            k1 = "howto1"
        self.text(T(k1), self.fonts.small, WHITE, y=int(self.H * 0.22))
        self.text(T("howto2_grab" if g else "howto2"), self.fonts.small, WHITE,
                  y=int(self.H * 0.28))
        self.text(T("howto3", sec=self.cfg["game"]["duration"]), self.fonts.small,
                  DIM, y=int(self.H * 0.34))

        top = self.rank.top(6)
        y = int(self.H * 0.42)
        self.text(T("ranking"), self.fonts.mid, CYAN, cx=int(self.W * 0.5), y=y)
        cx = int(self.W * 0.5)
        for i, r in enumerate(top):
            col = GOLD if i == 0 else WHITE
            yy = y + 62 + i * 36
            self.text(f"{i + 1}", self.fonts.small, col, x=cx - 260, y=yy)
            self.text(r["name"], self.fonts.small, col, x=cx - 200, y=yy)
            img = self.fonts.small.render(str(r["score"]), True, col)
            self.screen.blit(self.fonts.small.render(str(r["score"]), True, (0, 0, 0)),
                             (cx + 262 - img.get_width(), yy + 3))
            self.screen.blit(img, (cx + 260 - img.get_width(), yy))
        st = self.rank.stats()
        self.text(T("plays", n=st["plays"]), self.fonts.tiny, DIM, y=int(self.H * 0.95))
        if not self.cam_ok:
            self.text(T("nocam"), self.fonts.tiny, RED, x=14, y=int(self.H * 0.95))
        if self.hold_button(0.135, 0.60, T("hold_start_grab" if g else "hold_start")):
            go = True
        key = "press" if not self.hold_enabled else (
            "press_or_grab" if g else "press_or_hold")
        if int(now * 2) % 2 == 0:
            self.text(T(key), self.fonts.mid, GREEN, y=int(self.H * 0.865))
        self.draw_cursor()
        self.draw_debug()
        if go:
            self.snd.play("start")
            self.name = ""
            self.set_state(COUNTDOWN)

    def calib_steps(self):
        """追跡方式とゲームモードに応じた手順を組み立てる。"""
        if self.tracker.name == "skin":
            steps = ["bg", "skin"]       # 背景を覚える → 肌の色にあわせる
        else:
            steps = ["color"]
        if self.mode == "grab":
            steps += ["open", "closed"]  # パー → グー
        return steps

    def screen_calib(self, go):
        """手順を1つずつ進める。ボタン（スペース）で次へ。"""
        self.draw_camera_bg()
        T = self.fonts.t
        steps = self.calib_steps()
        step = self.calib_step
        done = step >= len(steps)
        self.text(T("calib_title") + f"  [{self.tracker.label}]",
                  self.fonts.mid, GOLD, y=int(self.H * 0.06))

        if not done:
            key = steps[step]
            self.text(f"{step + 1}/{len(steps)}   {T('calib_l_' + key)}",
                      self.fonts.small, WHITE, y=int(self.H * 0.16))
            if key in ("color", "skin"):
                w, h = int(self.W * 0.22), int(self.H * 0.22)
                pygame.draw.rect(self.screen, GOLD,
                                 pygame.Rect((self.W - w) // 2, (self.H - h) // 2, w, h), 5)
        else:
            self.text(T("calib_done"), self.fonts.small, GREEN, y=int(self.H * 0.16))

        # いま何が見えているかを数字で出す（当日の調整はこれを見ながら）
        if self.det is not None and self.det.found:
            self.text(f"fill {self.det.fill:.2f}   solidity {self.det.solidity:.2f}"
                      f"   しきい値 {self.tracker.grab_off:.2f}/{self.tracker.grab_on:.2f}",
                      self.fonts.tiny, DIM, y=int(self.H * 0.24))
            if self.mode == "grab" and (done or steps[step] == "closed"):
                self.text("グー" if self.grab else "パー", self.fonts.big,
                          GOLD if self.grab else CYAN, y=int(self.H * 0.60))
        if self.tracker.name == "skin":
            self.text(f"Cr {self.tracker.cr[0]}-{self.tracker.cr[1]}   "
                      f"Cb {self.tracker.cb[0]}-{self.tracker.cb[1]}",
                      self.fonts.tiny, DIM, y=int(self.H * 0.78))
        else:
            sw = pygame.Surface((80, 80))
            sw.fill(self.cursor_rgb())
            self.screen.blit(sw, (self.W // 2 - 40, int(self.H * 0.74)))
        self.text(T("calib_keys"), self.fonts.tiny, DIM, y=int(self.H * 0.90))
        if time.time() - self.msg_t < 5:
            self.text(self.msg, self.fonts.small, GREEN, y=int(self.H * 0.84))
        self.draw_cursor()
        dbg, self.debug = self.debug, True
        self.draw_debug()
        self.debug = dbg

        if not go:
            return
        if done:
            self.set_state(ATTRACT)
            return
        if self.frame is None:
            self.toast("カメラ映像がありません")
            return

        key = steps[step]
        if key == "bg":
            ok, msg = self.tracker.learn_background(self.frame)
        elif key in ("color", "skin"):
            ok, msg = self.tracker.calibrate(self.frame)
        else:
            ok, msg = self.tracker.calibrate_gesture(
                self.frame, "open" if key == "open" else "closed")
        self.toast(msg)
        self.snd.play("coin" if ok else "miss")
        if ok:
            self.calib_step = step + 1
            if self.calib_step >= len(steps):
                self._save_marker()

    def _save_marker(self):
        """色あわせ・握り判定の結果を config.json に書き戻す。"""
        self.cfg.data["marker"].update(self.tracker.export())
        self.cfg.data["marker"]["mode"] = self.track_mode
        if hasattr(self.tracker, "export_skin"):
            self.cfg.data.setdefault("skin", {}).update(self.tracker.export_skin())
        self.cfg.save()

    def screen_countdown(self, go):
        self.draw_camera_bg()
        el = time.time() - self.state_t
        n = 3 - int(el)
        T = self.fonts.t
        if n > 0:
            if not hasattr(self, "_beep_at") or self._beep_at != n:
                self._beep_at = n
                self.snd.play("beep")
                self.io.led(n % 2 == 0)
            self.text(str(n), self.fonts.huge, GOLD, y=int(self.H * 0.30))
            self.text(T("ready"), self.fonts.mid, WHITE, y=int(self.H * 0.62))
        else:
            self.text(T("go"), self.fonts.huge, GREEN, y=int(self.H * 0.30))
        self.draw_cursor()
        self.draw_debug()
        if el > 3.6:
            self._beep_at = None
            self.io.led(True)
            self.engine.reset(time.time())
            self.set_state(PLAY)

    def screen_play(self, go):
        now = time.time()
        self.draw_camera_bg()
        events = self.engine.update(now, self.marker, self.cursor_r,
                                    can_take=(self.grab or self.mode != "grab"))
        for name, t, pts in events:
            if name == "hit":
                self.snd.play("hit")
            elif name == "bonus":
                self.snd.play("bonus")
            elif name == "bomb":
                self.snd.play("bomb")
                self.flash = now
            elif name == "expire":
                self.snd.play("miss")
            elif name == "finish":
                self.snd.play("end")
                self.io.led(False)
                s = self.engine.summary()
                self.pending = s
                self.rank_preview = self.rank.rank_of(
                    {"score": s["score"], "date": time.strftime("%Y-%m-%d")})
                self.set_state(RESULT)
                return
        for t in self.engine.targets:
            self.draw_target(t, now)
        # 手が◯に重なっているのに握っていない人へのヒント
        if self.mode == "grab" and self.marker and not self.grab:
            for t in self.engine.targets:
                if t.kind != BOMB and self.engine._dist(
                        self.marker[0], self.marker[1], t.x, t.y) <= t.r + self.cursor_r * 1.6:
                    img = self.fonts.small.render(self.fonts.t("grab_now"), True, GOLD)
                    self.screen.blit(img, img.get_rect(
                        center=(int(t.x * self.W), int(t.y * self.H - t.r * self.H - 34))))
                    break
        self.draw_cursor()
        self.draw_pops(now)      # 得点表示はカーソルより手前に

        # HUD
        T = self.fonts.t
        left = self.engine.time_left(now)
        bar_w = int(self.W * 0.6)
        pygame.draw.rect(self.screen, (40, 45, 60),
                         (self.W // 2 - bar_w // 2, 22, bar_w, 20), border_radius=10)
        frac = left / self.cfg["game"]["duration"]
        col = GREEN if frac > 0.33 else RED
        pygame.draw.rect(self.screen, col,
                         (self.W // 2 - bar_w // 2, 22, int(bar_w * frac), 20),
                         border_radius=10)
        self.text(f"{T('score')} {self.engine.score}", self.fonts.mid, WHITE, x=24, y=14)
        self.text(f"{left:4.1f}", self.fonts.mid, col, x=self.W - 170, y=14)
        if self.engine.combo >= 2:
            self.text(f"{T('combo')} {self.engine.combo}  x{self.engine.multiplier()}",
                      self.fonts.mid, GOLD, y=int(self.H * 0.09))
        if now - self.flash < 0.25:      # 爆弾を取ったときの赤フラッシュ
            ov = pygame.Surface((self.W, self.H))
            ov.set_alpha(int(150 * (1 - (now - self.flash) / 0.25)))
            ov.fill((200, 0, 0))
            self.screen.blit(ov, (0, 0))
        self.draw_debug()

    def screen_result(self, go):
        now = time.time()
        self.draw_camera_bg()
        T = self.fonts.t
        s = self.pending or self.engine.summary()
        rank, total = getattr(self, "rank_preview", (1, 1))
        self.text(T("result"), self.fonts.mid, CYAN, y=int(self.H * 0.08))
        self.text(str(s["score"]), self.fonts.huge, GOLD, y=int(self.H * 0.16))
        if rank == 1 and total > 1:
            self.text(T("newrecord"), self.fonts.mid, RED, y=int(self.H * 0.44))
        self.text(T("rank_line", rank=rank, total=max(total, 1)),
                  self.fonts.mid, WHITE, y=int(self.H * 0.52))
        self.text(f"{T('acc')} {s['accuracy']}%   {T('bestcombo')} {s['best_combo']}",
                  self.fonts.small, DIM, y=int(self.H * 0.62))
        self.text(f"{T('name')} {self.name or '____'}", self.fonts.small,
                  WHITE, y=int(self.H * 0.70))
        g = self.mode == "grab"
        if self.hold_button(0.135, 0.60, T("hold_again_grab" if g else "hold_again")):
            go = True
        if int(now * 2) % 2 == 0:
            self.text(T("again" if not self.hold_enabled else
                        ("again_or_grab" if g else "again_or_hold")),
                      self.fonts.mid, GREEN, y=int(self.H * 0.82))
        self.draw_cursor()
        self.draw_debug()
        # ボタンか一定時間でランキング保存 → 待機画面へ
        if go or now - self.state_t > 25:
            self.rank.add(s["score"], self.name.strip() or "GUEST")
            self.pending = None
            self.io.led_blink(0.9)
            self.set_state(ATTRACT)

    # ---------------- メインループ ----------------
    def step(self):
        go = self.poll()
        self.capture()
        {ATTRACT: self.screen_attract, CALIB: self.screen_calib,
         COUNTDOWN: self.screen_countdown, PLAY: self.screen_play,
         RESULT: self.screen_result}[self.state](go)
        pygame.display.flip()
        self.clock.tick(self.fps_target)

    def run(self):
        try:
            while self.running:
                self.step()
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    def close(self):
        self.io.cleanup()
        if self.cam:
            self.cam.release()
        pygame.quit()
