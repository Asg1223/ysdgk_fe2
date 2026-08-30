"""色マーカー追跡。

会場の照明は当日まで分からないので、HSV の色相中心＋許容幅を
実物から採り直せる（キャリブレーション）作りにしてある。
Pi 3 が非力なので処理は 320x240 のまま行い、拡大は描画側に任せる。
"""
import cv2
import numpy as np


class Detection:
    __slots__ = ("found", "x", "y", "area", "radius", "held")

    def __init__(self, found=False, x=0.5, y=0.5, area=0.0, radius=0.0, held=False):
        self.found = found
        self.x = x          # 0.0-1.0（画面左→右）
        self.y = y          # 0.0-1.0（画面上→下）
        self.area = area    # ピクセル数
        self.radius = radius
        self.held = held    # 直前位置で補間中か


class ColorTracker:
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
            return Detection(True, nx, ny, best_area, float(np.sqrt(best_area / np.pi)))

        # 見失った直後は数フレームだけ直前位置を保持（ちらつき防止）
        self._lost += 1
        if self._last is not None and self._lost <= self.hold_frames:
            return Detection(True, self._last[0], self._last[1], 0.0, 0.0, held=True)
        return Detection(False)

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
                "cursor_radius": self.cfg.get("cursor_radius", 46)}


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
