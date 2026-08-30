"""物理ボタン／LED。RPi.GPIO が無い環境（PC でのテスト）でも落ちない。"""
import threading
import time


class HardwareIO:
    def __init__(self, gpio_cfg):
        self.cfg = gpio_cfg
        self.available = False
        self._pressed = False
        self._lock = threading.Lock()
        self._blink = None
        self._stop = threading.Event()
        if not gpio_cfg.get("enabled", True):
            return
        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            pull = GPIO.PUD_UP if gpio_cfg.get("active_low", True) else GPIO.PUD_DOWN
            GPIO.setup(int(gpio_cfg["button_pin"]), GPIO.IN, pull_up_down=pull)
            GPIO.setup(int(gpio_cfg["led_pin"]), GPIO.OUT, initial=GPIO.LOW)
            edge = GPIO.FALLING if gpio_cfg.get("active_low", True) else GPIO.RISING
            GPIO.add_event_detect(int(gpio_cfg["button_pin"]), edge,
                                  callback=self._on_edge, bouncetime=250)
            self.available = True
            print("[gpio] ボタン/LED を初期化しました")
        except Exception as e:
            print(f"[gpio] 使用しません ({e}) → キーボード/マウスで操作できます")

    def _on_edge(self, _pin):
        with self._lock:
            self._pressed = True

    def button_pressed(self):
        """押されていれば True を 1 回だけ返す（押しっぱなし対策）。"""
        with self._lock:
            p, self._pressed = self._pressed, False
        return p

    # ---- LED ----
    def led(self, on):
        if not self.available:
            return
        self._stop_blink()
        self.GPIO.output(int(self.cfg["led_pin"]),
                         self.GPIO.HIGH if on else self.GPIO.LOW)

    def led_blink(self, period=0.5):
        if not self.available or self._blink is not None:
            return
        self._stop.clear()

        def loop():
            state = False
            while not self._stop.is_set():
                state = not state
                self.GPIO.output(int(self.cfg["led_pin"]),
                                 self.GPIO.HIGH if state else self.GPIO.LOW)
                time.sleep(period / 2)
        self._blink = threading.Thread(target=loop, daemon=True)
        self._blink.start()

    def _stop_blink(self):
        if self._blink is not None:
            self._stop.set()
            self._blink.join(timeout=1.0)
            self._blink = None

    def cleanup(self):
        if not self.available:
            return
        self._stop_blink()
        try:
            self.GPIO.output(int(self.cfg["led_pin"]), self.GPIO.LOW)
            self.GPIO.cleanup()
        except Exception:
            pass
