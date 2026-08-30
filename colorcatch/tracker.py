"""色マーカー追跡。

会場の照明は当日まで分からないので、HSV の色相中心＋許容幅を
実物から採り直せる（キャリブレーション）作りにしてある。
Pi 3 が非力なので処理は 320x240 のまま行い、拡大は描画側に任せる。
"""
import cv2
import numpy as np


class Detection:
    __slots__ = ("found", "x", "y", "area", "radius", "held", "fill", "solidity", "grab")

    def __init__(self, found=False, x=0.5, y=0.5, area=0.0, radius=0.0, held=False,
                 fill=0.0, solidity=0.0, grab=False):
        self.found = found
        self.x = x          # 0.0-1.0（画面左→右）
        self.y = y          # 0.0-1.0（画面上→下）
        self.area = area    # ピクセル数
        self.radius = radius
        self.held = held    # 直前位置で補間中か
        # ↓ 手の開閉判定用。どちらも面積比なので、カメラからの距離が変わっても値が動かない
        self.fill = fill            # 輪郭面積 / 最小外接円の面積（グーで大、パーで小）
        self.solidity = solidity    # 輪郭面積 / 凸包面積（指の間の隙間が減ると大）
        self.grab = grab            # 掴んでいるか


class ColorTracker:
    """色マーカー（赤いカード・軍手など）を追う。"""

    name = "color"
    label = "色マーカー"

    def __init__(self, marker_cfg):
        self.cfg = marker_cfg
        self.hue = int(marker_cfg["hue"])
        self.hue_tol = int(marker_cfg["hue_tol"])
        self.sat_min = int(marker_cfg["sat_min"])
        self.val_min = int(marker_cfg["val_min"])
        self.min_area = int(marker_cfg["min_area"])
        self.smooth = float(marker_cfg["smooth"])
        self.hold_frames = int(marker_cfg["hold_frames"])
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self._last = None       # (x, y)
        self._lost = 999
        self.last_mask = None
        # 握り判定のしきい値（ヒステリシス付き。calibrate_gesture で上書きされる）
        self.grab_on = float(marker_cfg.get("grab_on", 0.62))
        self.grab_off = float(marker_cfg.get("grab_off", 0.52))
        self._grab = False
        self._grab_frames = 0
        self.open_fill = float(marker_cfg.get("open_fill", 0.0)) or None
        self.closed_fill = float(marker_cfg.get("closed_fill", 0.0)) or None

    # ---------- 内部 ----------
    def _mask(self, bgr):
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        lo, hi = self.hue - self.hue_tol, self.hue + self.hue_tol
        if lo < 0 or hi > 179:
            # 赤のように 0/179 をまたぐ色は 2 本の範囲に割る
            m1 = cv2.inRange(hsv, np.array([max(lo, 0), self.sat_min, self.val_min], np.uint8),
                             np.array([min(hi, 179), 255, 255], np.uint8))
            if lo < 0:
                m2 = cv2.inRange(hsv, np.array([180 + lo, self.sat_min, self.val_min], np.uint8),
                                 np.array([179, 255, 255], np.uint8))
            else:
                m2 = cv2.inRange(hsv, np.array([0, self.sat_min, self.val_min], np.uint8),
                                 np.array([hi - 180, 255, 255], np.uint8))
            mask = cv2.bitwise_or(m1, m2)
        else:
            mask = cv2.inRange(hsv, np.array([lo, self.sat_min, self.val_min], np.uint8),
                               np.array([hi, 255, 255], np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel)
        mask = cv2.dilate(mask, self._kernel, iterations=1)
        return mask

    # ---------- 公開 ----------
    def update(self, bgr):
        """1 フレーム処理して Detection を返す。"""
        h, w = bgr.shape[:2]
        mask = self._mask(bgr)
        self.last_mask = mask
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best, best_area = None, 0.0
        for c in cnts:
            a = cv2.contourArea(c)
            if a > best_area:
                best, best_area = c, a

        if best is not None and best_area >= self.min_area:
            M = cv2.moments(best)
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
            nx, ny = cx / w, cy / h
            if self._last is not None and self._lost <= 2:
                s = self.smooth
                nx = self._last[0] * s + nx * (1 - s)
                ny = self._last[1] * s + ny * (1 - s)
            self._last = (nx, ny)
            self._lost = 0
            fill, sol = self._shape(best, best_area)
            grab = self._update_grab(fill)
            return Detection(True, nx, ny, best_area,
                             float(np.sqrt(best_area / np.pi)),
                             fill=fill, solidity=sol, grab=grab)

        # 見失った直後は数フレームだけ直前位置を保持（ちらつき防止）
        self._lost += 1
        if self._last is not None and self._lost <= self.hold_frames:
            return Detection(True, self._last[0], self._last[1], 0.0, 0.0,
                             held=True, grab=self._grab)
        self._grab, self._grab_frames = False, 0
        return Detection(False)

    @staticmethod
    def _shape(contour, area):
        """輪郭の「詰まり具合」を2通りで測る。どちらも 0-1 で距離に依存しない。"""
        (_, _), r = cv2.minEnclosingCircle(contour)
        circ = np.pi * r * r
        fill = float(area / circ) if circ > 1 else 0.0
        hull = cv2.convexHull(contour)
        ha = cv2.contourArea(hull)
        sol = float(area / ha) if ha > 1 else 0.0
        return fill, sol

    def _update_grab(self, fill):
        """しきい値を2つ使い、2フレーム続いて初めて状態を変える（誤判定防止）。"""
        want = self._grab
        if not self._grab and fill >= self.grab_on:
            want = True
        elif self._grab and fill <= self.grab_off:
            want = False
        if want != self._grab:
            self._grab_frames += 1
            if self._grab_frames >= 2:
                self._grab = want
                self._grab_frames = 0
        else:
            self._grab_frames = 0
        return self._grab

    def _mask_for_calib(self, bgr):
        """登録用のマスク。静止した1枚でも手が写るようにする。"""
        return self._mask(bgr)

    def freeze(self, on=True):
        """色マーカー方式では背景を使わないので何もしない。"""
        return None

    def calibrate_gesture(self, bgr, which):
        """パー(open)／グー(closed)の見え方を登録し、しきい値を自動で決める。"""
        mask = self._mask_for_calib(bgr)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h, w = bgr.shape[:2]
        best, ba, bd = None, 0.0, 1e9
        for c in cnts:
            a = cv2.contourArea(c)
            if a < self.min_area:
                continue
            if self._last is None:          # 追跡前なら単純にいちばん大きい塊
                if a > ba:
                    best, ba = c, a
            else:                           # 追跡中なら、いま追っている手に近い塊を選ぶ
                M = cv2.moments(c)          # （顔や腕を間違って測らないため）
                if M["m00"] <= 0:
                    continue
                d = ((M["m10"] / M["m00"] / w - self._last[0]) ** 2 +
                     (M["m01"] / M["m00"] / h - self._last[1]) ** 2) ** 0.5
                if d < bd:
                    best, ba, bd = c, a, d
        if best is None or ba < self.min_area:
            return False, "手が見つかりません（色あわせをやり直してください）"
        fill, _ = self._shape(best, ba)
        if which == "open":
            self.open_fill = fill
        else:
            self.closed_fill = fill
        if self.open_fill and self.closed_fill:
            lo, hi = self.open_fill, self.closed_fill
            if hi - lo < 0.06:
                return False, "パーとグーの差が小さすぎます（指をしっかり開いて）"
            self.grab_on = lo + (hi - lo) * 0.60
            self.grab_off = lo + (hi - lo) * 0.35
            return True, (f"登録しました パー={lo:.2f} グー={hi:.2f} "
                          f"→ しきい値 {self.grab_off:.2f}/{self.grab_on:.2f}")
        return True, f"{'パー' if which == 'open' else 'グー'}を登録 (fill={fill:.2f})"

    def calibrate(self, bgr, roi_ratio=0.22):
        """画面中央の四角に写っているものの色を新しいマーカー色として採用する。"""
        h, w = bgr.shape[:2]
        rw, rh = int(w * roi_ratio), int(h * roi_ratio)
        x0, y0 = (w - rw) // 2, (h - rh) // 2
        roi = bgr[y0:y0 + rh, x0:x0 + rw]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).reshape(-1, 3)
        # 彩度・明度が低い画素（背景・影）は色相が不安定なので捨てる
        good = hsv[(hsv[:, 1] > 70) & (hsv[:, 2] > 50)]
        if len(good) < roi.size * 0.02:
            return False, "マーカーが暗すぎます（照明を当ててください）"
        hues = good[:, 0].astype(np.int32)
        # 色相は循環量なので単位ベクトルの平均で中心を出す
        ang = hues * (2 * np.pi / 180.0)
        mh = int(round((np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) % (2 * np.pi))
                       * 180.0 / (2 * np.pi))) % 180
        sat = int(np.percentile(good[:, 1], 20))
        val = int(np.percentile(good[:, 2], 20))
        self.hue = mh
        self.sat_min = max(60, min(200, int(sat * 0.75)))
        self.val_min = max(40, min(200, int(val * 0.6)))
        self.hue_tol = int(self.cfg.get("hue_tol", 12))
        self._last, self._lost = None, 999
        return True, f"色を登録しました (H={self.hue} S>{self.sat_min} V>{self.val_min})"

    def export(self):
        return {"hue": self.hue, "hue_tol": self.hue_tol,
                "sat_min": self.sat_min, "val_min": self.val_min,
                "min_area": self.min_area, "smooth": self.smooth,
                "hold_frames": self.hold_frames,
                "cursor_radius": self.cfg.get("cursor_radius", 46),
                "grab_on": round(self.grab_on, 3), "grab_off": round(self.grab_off, 3),
                "open_fill": round(self.open_fill or 0.0, 3),
                "closed_fill": round(self.closed_fill or 0.0, 3)}


class SkinTracker(ColorTracker):
    """素手（肌色）を追う。手袋なしで遊べるようにするためのモード。

    肌色だけで探すと木の机・段ボール・壁・顔まで拾ってしまうので、
      肌色(YCrCb) ∩ 動いている領域 ― 顔の位置
    という3段構えで絞り込む。動きの判定には背景差分を使い、
    手を止めたときのために直前位置の周りだけは肌色のみで拾う。
    """

    name = "skin"
    label = "素手（肌色）"

    def __init__(self, marker_cfg, skin_cfg=None):
        super().__init__(marker_cfg)
        c = dict(skin_cfg or {})
        self.cr = list(c.get("cr", [133, 177]))
        self.cb = list(c.get("cb", [77, 127]))
        self.skin_sat_min = int(c.get("sat_min", 25))
        self.skin_val_min = int(c.get("val_min", 40))
        self.motion_gate = bool(c.get("motion_gate", True))
        self.face_filter = bool(c.get("face_filter", True))
        self.face_every = int(c.get("face_every", 15))
        self.learn_rate = float(c.get("learn_rate", 0.0015))
        self.min_area = int(c.get("min_area", marker_cfg.get("min_area", 250)))
        self._bg = None
        self._motion = None        # 動きの残像（少しの間だけ覚えておく）
        self._decay = float(c.get("motion_decay", 0.90))
        self.diff_th = int(c.get("diff_threshold", 28))   # 背景画像との差の判定
        self.frozen = False    # True の間は背景を更新しない（プレイ中に使う）
        self._face = None          # (x, y, w, h) 直近に見つけた顔
        self._face_age = 999
        self._cascade = None
        self._frames = 0
        self._reset_bg()

    def _reset_bg(self):
        try:
            self._bg = cv2.createBackgroundSubtractorMOG2(
                history=250, varThreshold=28, detectShadows=False)
        except Exception as e:
            print(f"[skin] 背景差分が使えません ({e}) → 肌色のみで判定します")
            self._bg = None
            self.motion_gate = False

    def freeze(self, on=True):
        """プレイ中は背景の更新を止める（止めた手が背景に溶けるのを防ぐ）。"""
        self.frozen = bool(on)

    def learn_background(self, bgr, frames=25):
        """手を画面から出した状態で呼ぶと、背景を覚え直す。"""
        self._reset_bg()
        self._motion = None
        if self._bg is None:
            return False, "背景差分が使えない環境です（肌色のみで動きます）"
        for _ in range(frames):
            self._bg.apply(bgr, learningRate=0.5)
        self._last, self._lost = None, 999
        return True, "背景を覚えました"

    # --- 顔を避ける（顔は肌色で、しかも画面の上のほうでよく動く） ---
    def _find_face(self, bgr):
        if not self.face_filter:
            return
        self._face_age += 1
        if self._face_age < self.face_every:
            return
        self._face_age = 0
        if self._cascade is None:
            try:
                path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                self._cascade = cv2.CascadeClassifier(path)
                if self._cascade.empty():
                    raise RuntimeError("cascade が読めません")
            except Exception as e:
                print(f"[skin] 顔検出は使いません ({e})")
                self.face_filter = False
                return
        # Pi 3 では顔検出が重いので、半分に縮めた白黒画像で探して座標を2倍に戻す
        small = cv2.cvtColor(cv2.resize(bgr, None, fx=0.5, fy=0.5), cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(small, 1.25, 4, minSize=(24, 24))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            self._face = (x * 2, y * 2, w * 2, h * 2)

    def _skin_mask(self, bgr):
        ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
        m = cv2.inRange(ycrcb,
                        np.array([0, self.cr[0], self.cb[0]], np.uint8),
                        np.array([255, self.cr[1], self.cb[1]], np.uint8))
        # 彩度・明度が極端に低い灰色の壁などを落とす
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        m = cv2.bitwise_and(m, cv2.inRange(
            hsv, np.array([0, self.skin_sat_min, self.skin_val_min], np.uint8),
            np.array([179, 255, 255], np.uint8)))
        return m

    def _mask(self, bgr):
        """肌色のうち「覚えた背景と違うところ」だけを残す。

        瞬間的な動き(fg)だけで絞ると手を止めた瞬間に消えてしまい、
        逆に肌色だけだと木の机や段ボールを拾ってしまう。そこで
          ・fg          : いま動いた場所
          ・motion      : 少し前に動いた場所（減衰つき）
          ・diff        : 覚えた背景画像との差（止まっていても残る）
        の和집合を「背景ではない場所」として使う。
        """
        skin = self._skin_mask(bgr)
        self._frames += 1

        if self.motion_gate and self._bg is not None:
            lr = 0.0 if self.frozen else self.learn_rate
            fg = self._bg.apply(bgr, learningRate=lr)
            bg_img = self._bg.getBackgroundImage()
            if bg_img is not None and bg_img.shape == bgr.shape:
                # 覚えた背景画像との差。手を止めても残り、形も正確に出るのでこれを主に使う
                d = cv2.absdiff(bgr, bg_img)          # numpy の max より cv2 の方が6倍速い
                b, g, r = cv2.split(d)
                diff = cv2.max(cv2.max(b, g), r)
                _, active = cv2.threshold(diff, self.diff_th, 255, cv2.THRESH_BINARY)
            else:
                # 背景画像がまだ作れていない最初の数フレームだけ、動きの残像で代用する
                f32 = (cv2.dilate(fg, self._kernel, iterations=1) > 0).astype(np.float32)
                if self._motion is None or self._motion.shape != f32.shape:
                    self._motion = f32
                else:
                    self._motion = np.maximum(f32, self._motion * self._decay)
                active = (self._motion > 0.35).astype(np.uint8) * 255
            # 外へ広げず内側の穴だけ埋める（広げると隣の机まで巻き込むため）
            cnts, _ = cv2.findContours(active, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cnts:
                filled = np.zeros_like(active)
                cv2.drawContours(filled, cnts, -1, 255, -1)
                active = filled
            mask = cv2.bitwise_and(skin, active)
        else:
            mask = skin

        self._find_face(bgr)
        if self._face is not None:
            x, y, fw, fh = self._face
            pad = int(fw * 0.35)
            cv2.rectangle(mask, (x - pad, y - pad),
                          (x + fw + pad, y + fh + int(fh * 0.9)), 0, -1)

        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel)
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel, iterations=2)

    DEF_CR = (133, 177)      # 一般的な肌色の範囲（YCrCb）。ここから外れる値は拾わない
    DEF_CB = (77, 127)

    def calibrate(self, bgr, roi_ratio=0.22):
        """枠に手を入れて押す → その人の肌の色みに範囲を寄せる。

        枠の中には壁や机も写り込むので、いったん一般的な肌色の範囲で
        ふるいにかけてから中央値を取る（そうしないと壁の灰色に引っ張られる）。
        """
        h, w = bgr.shape[:2]
        rw, rh = int(w * roi_ratio), int(h * roi_ratio)
        x0, y0 = (w - rw) // 2, (h - rh) // 2
        roi = bgr[y0:y0 + rh, x0:x0 + rw]
        ycrcb = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb).reshape(-1, 3)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).reshape(-1, 3)
        good = ycrcb[(ycrcb[:, 0] > 40) &
                     (ycrcb[:, 1] >= self.DEF_CR[0]) & (ycrcb[:, 1] <= self.DEF_CR[1]) &
                     (ycrcb[:, 2] >= self.DEF_CB[0]) & (ycrcb[:, 2] <= self.DEF_CB[1]) &
                     (hsv[:, 1] >= self.skin_sat_min) & (hsv[:, 2] >= self.skin_val_min)]
        if len(good) < len(ycrcb) * 0.15:
            return False, "枠いっぱいに手を入れてください（手が小さすぎます）"
        cr = int(np.median(good[:, 1]))
        cb = int(np.median(good[:, 2]))
        tol_cr = int(self.cfg.get("skin_tol_cr", 18))
        tol_cb = int(self.cfg.get("skin_tol_cb", 16))
        # 一般的な肌色の範囲からはみ出さないように収める（他の人も遊べるように）
        self.cr = [max(self.DEF_CR[0], cr - tol_cr), min(self.DEF_CR[1], cr + tol_cr)]
        self.cb = [max(self.DEF_CB[0], cb - tol_cb), min(self.DEF_CB[1], cb + tol_cb)]
        self._last, self._lost = None, 999
        return True, f"肌の色を登録しました (Cr {self.cr[0]}-{self.cr[1]} / Cb {self.cb[0]}-{self.cb[1]})"

    def export_skin(self):
        return {"cr": self.cr, "cb": self.cb, "motion_decay": self._decay,
                "diff_threshold": self.diff_th,
                "sat_min": self.skin_sat_min,
                "val_min": self.skin_val_min, "motion_gate": self.motion_gate,
                "face_filter": self.face_filter, "face_every": self.face_every,
                "learn_rate": self.learn_rate, "min_area": self.min_area}


class Camera:
    """USB カメラ / Pi カメラのどちらでも開けるようにした薄いラッパ。"""

    def __init__(self, cam_cfg):
        self.cfg = cam_cfg
        self.mirror = bool(cam_cfg.get("mirror", True))
        self.cap = None
        self.picam = None
        self.ok = False
        self._open()

    def _open(self):
        w, h = int(self.cfg["width"]), int(self.cfg["height"])
        if self.cfg.get("use_picamera"):
            try:  # Pi カメラ（libcamera 系）
                from picamera2 import Picamera2
                self.picam = Picamera2()
                cfgp = self.picam.create_preview_configuration(
                    main={"size": (w, h), "format": "RGB888"})
                self.picam.configure(cfgp)
                self.picam.start()
                self.ok = True
                return
            except Exception as e:
                print(f"[camera] picamera2 が使えません: {e} → USB カメラを試します")
        try:
            self.cap = cv2.VideoCapture(int(self.cfg["index"]))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # 遅延を減らす
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            self.ok = self.cap.isOpened()
        except Exception as e:
            print(f"[camera] オープン失敗: {e}")
            self.ok = False

    def read(self):
        frame = None
        if self.picam is not None:
            try:
                rgb = self.picam.capture_array()
                frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            except Exception:
                frame = None
        elif self.cap is not None:
            got, f = self.cap.read()
            frame = f if got else None
        if frame is None:
            return None
        if self.mirror:                 # 鏡像にしないと左右が逆で操作できない
            frame = cv2.flip(frame, 1)
        return frame

    def release(self):
        if self.cap is not None:
            self.cap.release()
        if self.picam is not None:
            try:
                self.picam.stop()
            except Exception:
                pass
