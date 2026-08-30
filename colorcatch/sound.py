"""効果音。音源ファイルを配らなくて済むよう、numpy で波形を合成する。"""
import numpy as np

SR = 22050  # Pi 3 の負荷を考えて 22.05kHz


def _env(n, attack=0.01, release=0.25):
    a = max(1, int(SR * attack))
    r = max(1, int(SR * release))
    e = np.ones(n, dtype=np.float32)
    a = min(a, n)
    r = min(r, n - a) if n - a > 0 else 0
    e[:a] = np.linspace(0, 1, a, dtype=np.float32)
    if r:
        e[n - r:] = np.linspace(1, 0, r, dtype=np.float32)
    return e


def _tone(freqs, dur, vol=0.5, wave="sine"):
    n = int(SR * dur)
    t = np.arange(n, dtype=np.float32) / SR
    buf = np.zeros(n, dtype=np.float32)
    for f in np.atleast_1d(freqs).astype(np.float32):
        if wave == "square":
            buf += np.sign(np.sin(2 * np.pi * f * t))
        else:
            buf += np.sin(2 * np.pi * f * t)
    buf /= max(1, len(np.atleast_1d(freqs)))
    return buf * _env(n) * vol


def _sweep(f0, f1, dur, vol=0.5, wave="sine"):
    n = int(SR * dur)
    t = np.arange(n, dtype=np.float32) / SR
    f = np.linspace(f0, f1, n, dtype=np.float32)
    ph = 2 * np.pi * np.cumsum(f) / SR
    buf = np.sign(np.sin(ph)) if wave == "square" else np.sin(ph)
    return buf.astype(np.float32) * _env(n) * vol


def _seq(parts):
    return np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)


class SoundBank:
    def __init__(self, audio_cfg):
        self.enabled = bool(audio_cfg.get("enabled", True))
        self.sounds = {}
        if not self.enabled:
            return
        try:
            import pygame
            pygame.mixer.pre_init(SR, -16, 2, 512)
            pygame.mixer.init()
            self.pygame = pygame
            vol = float(audio_cfg.get("volume", 0.7))
            for name, wav in self._build().items():
                s = pygame.sndarray.make_sound(self._to_stereo(wav))
                s.set_volume(vol)
                self.sounds[name] = s
            print("[audio] 効果音を生成しました")
        except Exception as e:
            print(f"[audio] 無効化します ({e})")
            self.enabled = False

    @staticmethod
    def _to_stereo(mono):
        mono = np.clip(mono, -1, 1)
        i16 = (mono * 32000).astype(np.int16)
        return np.ascontiguousarray(np.stack([i16, i16], axis=1))

    def _build(self):
        return {
            "hit":   _sweep(700, 1400, 0.09, 0.45),
            "bonus": _seq([_tone(880, 0.07, .45), _tone(1175, 0.07, .45), _tone(1568, 0.14, .5)]),
            "bomb":  _sweep(400, 70, 0.35, 0.55, "square"),
            "beep":  _tone(880, 0.10, 0.4),
            "start": _seq([_tone(523, 0.10, .5), _tone(784, 0.22, .55)]),
            "end":   _seq([_tone(784, 0.14, .5), _tone(659, 0.14, .5),
                           _tone([523, 659, 784], 0.45, .55)]),
            "miss":  _tone(220, 0.10, 0.35, "square"),
            "coin":  _seq([_tone(1319, 0.05, .4), _tone(1976, 0.18, .45)]),
        }

    def play(self, name):
        if not self.enabled:
            return
        s = self.sounds.get(name)
        if s is not None:
            try:
                s.play()
            except Exception:
                pass
