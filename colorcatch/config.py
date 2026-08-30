"""設定の読み込み・保存（キャリブレーション結果の永続化に使う）"""
import json
import os

DEFAULT = {
    "screen": {"width": 1280, "height": 720, "fullscreen": True, "fps": 30},
    "camera": {"index": 0, "width": 320, "height": 240, "mirror": True, "use_picamera": False},
    "marker": {"hue": 0, "hue_tol": 12, "sat_min": 120, "val_min": 70,
               "min_area": 250, "smooth": 0.45, "hold_frames": 6, "cursor_radius": 46},
    "game": {"mode": "grab", "duration": 30, "spawn_interval_start": 1.10, "spawn_interval_end": 0.55,
             "target_ttl": 3.2, "max_targets": 5, "bonus_rate": 0.16, "bomb_rate": 0.18,
             "score_normal": 10, "score_bonus": 30, "score_bomb": -20,
             "combo_window": 2.0, "combo_max": 5},
    "input": {"hold_to_start": True, "hold_seconds": 1.8, "always_show": False},
    "gpio": {"enabled": True, "button_pin": 17, "led_pin": 27, "active_low": True},
    "audio": {"enabled": True, "volume": 0.7},
    "ui": {"language": "ja", "team_name": "3-B", "title": "カラーキャッチ！"},
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path):
        self.path = path
        data = {}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:  # 壊れた設定でも起動できるようにする
                print(f"[config] 読み込み失敗 ({e}) → 既定値を使います")
        self.data = _merge(DEFAULT, data)

    def __getitem__(self, key):
        return self.data[key]

    def save(self):
        """キャリブレーション結果などを書き戻す。失敗しても致命傷にしない。"""
        if not self.path:
            return False
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except Exception as e:
            print(f"[config] 保存失敗: {e}")
            return False
