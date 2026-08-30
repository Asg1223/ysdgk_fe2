"""画面文言。日本語フォントが無い環境では自動で英語に落とす。"""
import os
import pygame

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/vlgothic/VL-PGothic-Regular.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
]

JA = {
    "howto1": "赤いカードをカメラに向けて動かそう",
    "howto2": "◯を触るとスコア　★はボーナス　×は減点",
    "howto3": "制限時間 {sec} 秒 ・ 連続ヒットで倍率アップ",
    "press": "ボタンを押してスタート！",
    "ranking": "本日のランキング",
    "plays": "本日 {n} 人がプレイ",
    "calib_title": "色あわせ（キャリブレーション）",
    "calib_msg": "枠の中にマーカーを入れてボタン（またはスペース）",
    "calib_keys": "[ ] 許容幅  - = 明るさしきい値  ESC 戻る",
    "ready": "よういして！",
    "go": "スタート！",
    "score": "スコア",
    "time": "のこり",
    "combo": "コンボ",
    "result": "結果",
    "rank_line": "本日 {rank} 位 / {total} 人中",
    "acc": "命中率",
    "bestcombo": "最大コンボ",
    "again": "ボタンでもう一度",
    "name": "名前(英数字・任意)：",
    "nocam": "カメラが見つかりません → マウスで操作できます",
    "newrecord": "本日の新記録！",
}
EN = {
    "howto1": "Move the red card in front of the camera",
    "howto2": "Touch O to score, * is bonus, X is penalty",
    "howto3": "{sec} seconds - chain hits to raise the multiplier",
    "press": "PRESS THE BUTTON TO START",
    "ranking": "TODAY'S RANKING",
    "plays": "{n} plays today",
    "calib_title": "COLOR CALIBRATION",
    "calib_msg": "Put the marker in the box, then press the button/space",
    "calib_keys": "[ ] tolerance   - = brightness   ESC back",
    "ready": "READY",
    "go": "GO!",
    "score": "SCORE",
    "time": "TIME",
    "combo": "COMBO",
    "result": "RESULT",
    "rank_line": "RANK {rank} / {total} today",
    "acc": "ACCURACY",
    "bestcombo": "BEST COMBO",
    "again": "PRESS BUTTON TO PLAY AGAIN",
    "name": "NAME (A-Z):",
    "nocam": "No camera found - use the mouse instead",
    "newrecord": "NEW RECORD!",
}


class Fonts:
    def __init__(self, screen_h, prefer_ja=True):
        pygame.font.init()
        self.path = None
        if prefer_ja:
            for p in FONT_CANDIDATES:
                if os.path.exists(p):
                    self.path = p
                    break
            if self.path is None:
                for name in ("notosanscjkjp", "notosansmonocjkjp", "vlgothic",
                             "ipagothic", "takaogothic", "hiraginosansgb"):
                    got = pygame.font.match_font(name)
                    if got:
                        self.path = got
                        break
        self.japanese = self.path is not None
        self.T = JA if self.japanese else EN
        s = screen_h / 720.0
        self.huge = self._f(int(150 * s))
        self.big = self._f(int(78 * s))
        self.mid = self._f(int(46 * s))
        self.small = self._f(int(30 * s))
        self.tiny = self._f(int(22 * s))
        if not self.japanese:
            print("[font] 日本語フォントが見つからないため英語表示にします "
                  "(sudo apt install fonts-noto-cjk で日本語化できます)")

    def _f(self, size):
        if self.path:
            return pygame.font.Font(self.path, size)
        return pygame.font.SysFont("dejavusans,freesans", size, bold=True)

    def t(self, key, **kw):
        return self.T[key].format(**kw)
