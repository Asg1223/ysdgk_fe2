"""スコアの保存と集計（当日の TOP10 を出すため）。"""
import json
import os
import time


class Ranking:
    def __init__(self, path):
        self.path = path
        self.records = []
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.records = json.load(f)
            except Exception as e:
                print(f"[rank] 読み込み失敗: {e}")
                self.records = []

    def add(self, score, name="GUEST"):
        rec = {"score": int(score), "name": (name or "GUEST")[:8],
               "ts": time.time(), "date": time.strftime("%Y-%m-%d")}
        self.records.append(rec)
        self._save()
        return self.rank_of(rec)

    def rank_of(self, rec):
        today = [r for r in self.records if r.get("date") == rec["date"]]
        higher = sum(1 for r in today if r["score"] > rec["score"])
        return higher + 1, len(today)

    def top(self, n=10, today_only=True):
        d = time.strftime("%Y-%m-%d")
        rs = [r for r in self.records if (not today_only or r.get("date") == d)]
        return sorted(rs, key=lambda r: -r["score"])[:n]

    def stats(self):
        d = time.strftime("%Y-%m-%d")
        rs = [r for r in self.records if r.get("date") == d]
        if not rs:
            return {"plays": 0, "avg": 0, "best": 0}
        return {"plays": len(rs),
                "avg": round(sum(r["score"] for r in rs) / len(rs), 1),
                "best": max(r["score"] for r in rs)}

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.records[-2000:], f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception as e:
            print(f"[rank] 保存失敗: {e}")
