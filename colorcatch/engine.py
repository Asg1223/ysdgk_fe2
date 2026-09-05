"""ゲームロジック本体（描画から独立させ、単体テストできるようにしてある）。

座標は 0.0-1.0 の正規化座標。当たり判定だけは画面の縦横比を補正して
「見た目どおりの円」になるようにしている。
"""
import random

NORMAL, BONUS, BOMB = "normal", "bonus", "bomb"


class Target:
    __slots__ = ("kind", "x", "y", "r", "born", "ttl", "points")

    def __init__(self, kind, x, y, r, born, ttl, points):
        self.kind, self.x, self.y, self.r = kind, x, y, r
        self.born, self.ttl, self.points = born, ttl, points

    def life(self, now):
        return max(0.0, 1.0 - (now - self.born) / self.ttl)


class Pop:
    """当たった瞬間の演出用（ロジックには影響しない）。"""
    __slots__ = ("x", "y", "t", "kind", "text")

    def __init__(self, x, y, t, kind, text):
        self.x, self.y, self.t, self.kind, self.text = x, y, t, kind, text


class GameEngine:
    X_MIN, X_MAX = 0.08, 0.92
    Y_MIN, Y_MAX = 0.18, 0.90

    def __init__(self, gcfg, aspect=16 / 9, seed=None):
        self.c = gcfg
        self.aspect = aspect
        self.rng = random.Random(seed)
        self.reset(0.0)

    def reset(self, now):
        self.t0 = now
        self.score = 0
        self.hits = 0
        self.misses = 0
        self.bombs = 0
        self.combo = 0
        self.best_combo = 0
        self.last_hit_t = -99.0
        self.targets = []
        self.pops = []
        self.next_spawn = now + 0.35
        self.running = True

    # ---------- 情報 ----------
    def time_left(self, now):
        return max(0.0, self.c["duration"] - (now - self.t0))

    def progress(self, now):
        return min(1.0, (now - self.t0) / max(0.001, self.c["duration"]))

    def multiplier(self):
        return min(int(self.c["combo_max"]), 1 + self.combo // 3)

    # ---------- 進行 ----------
    def _spawn(self, now, marker):
        p = self.rng.random()
        if p < self.c["bomb_rate"]:
            kind, r, pts, ttl = BOMB, 0.085, self.c["score_bomb"], self.c["target_ttl"] * 1.3
        elif p < self.c["bomb_rate"] + self.c["bonus_rate"]:
            kind, r, pts, ttl = BONUS, 0.050, self.c["score_bonus"], self.c["target_ttl"] * 0.65
        else:
            kind, r, pts, ttl = NORMAL, 0.072, self.c["score_normal"], self.c["target_ttl"]

        for _ in range(12):
            x = self.rng.uniform(self.X_MIN, self.X_MAX)
            y = self.rng.uniform(self.Y_MIN, self.Y_MAX)
            # 既存ターゲットと重ならない位置を探す
            if any(self._dist(x, y, t.x, t.y) < (r + t.r) * 1.15 for t in self.targets):
                continue
            # 爆弾がカーソル直下に湧くのは理不尽なので避ける
            if kind == BOMB and marker and self._dist(x, y, marker[0], marker[1]) < 0.22:
                continue
            self.targets.append(Target(kind, x, y, r, now, ttl, pts))
            return

    def _dist(self, x1, y1, x2, y2):
        dx = (x1 - x2) * self.aspect
        dy = y1 - y2
        return (dx * dx + dy * dy) ** 0.5

    def update(self, now, marker, cursor_r=0.05):
        """marker は (x, y) または None。発生したイベントのリストを返す。"""
        events = []
        if not self.running:
            return events
        if self.time_left(now) <= 0:
            self.running = False
            events.append(("finish", None, 0))
            return events

        # 出現ペースは時間とともに速くなる
        s, e = self.c["spawn_interval_start"], self.c["spawn_interval_end"]
        interval = s + (e - s) * self.progress(now)
        if now >= self.next_spawn and len(self.targets) < self.c["max_targets"]:
            self._spawn(now, marker)
            self.next_spawn = now + interval

        # 寿命切れ
        alive = []
        for t in self.targets:
            if t.life(now) <= 0:
                if t.kind != BOMB:
                    self.misses += 1
                    self.combo = 0
                    events.append(("expire", t, 0))
            else:
                alive.append(t)
        self.targets = alive

        # 当たり判定
        if marker is not None:
            mx, my = marker
            remain = []
            for t in self.targets:
                if self._dist(mx, my, t.x, t.y) <= t.r + cursor_r:
                    if t.kind == BOMB:
                        self.bombs += 1
                        self.combo = 0
                        self.score = max(0, self.score + t.points)
                        self.pops.append(Pop(t.x, t.y, now, BOMB, str(t.points)))
                        events.append(("bomb", t, t.points))
                    else:
                        if now - self.last_hit_t <= self.c["combo_window"]:
                            self.combo += 1
                        else:
                            self.combo = 1
                        self.best_combo = max(self.best_combo, self.combo)
                        self.last_hit_t = now
                        gained = t.points * self.multiplier()
                        self.score += gained
                        self.hits += 1
                        self.pops.append(Pop(t.x, t.y, now, t.kind, f"+{gained}"))
                        events.append(("hit" if t.kind == NORMAL else "bonus", t, gained))
                else:
                    remain.append(t)
            self.targets = remain

        # コンボは時間が空いたら切れる
        if self.combo and now - self.last_hit_t > self.c["combo_window"]:
            self.combo = 0
        self.pops = [p for p in self.pops if now - p.t < 0.8]
        return events

    def summary(self):
        total = self.hits + self.misses
        return {"score": self.score, "hits": self.hits, "misses": self.misses,
                "bombs": self.bombs, "best_combo": self.best_combo,
                "accuracy": round(100.0 * self.hits / total, 1) if total else 0.0}
