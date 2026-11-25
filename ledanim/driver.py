"""
Matrix output thread. Shows one Scene at a time (see scenes.py).

If the `rgbmatrix` module (hzeller/rpi-rgb-led-matrix) isn't installed, the
driver runs as a simulator so the web UI can be tested on a normal PC.
"""
import threading
import time
import traceback

from PIL import Image

from .scenes import BlankScene

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
    HARDWARE = True
except ImportError:
    HARDWARE = False


class MatrixDriver:
    def __init__(self, rows=32, cols=32, chain=3, parallel=1,
                 hardware_mapping="adafruit-hat", gpio_slowdown=2,
                 brightness=60, pwm_bits=11, no_hardware_pulse=False,
                 force_simulator=False, panel_options=None):
        """panel_options: extra RGBMatrixOptions for unusual panels, e.g.
        {"led_rgb_sequence": "RBG", "multiplexing": 1, "row_address_type": 0,
         "scan_mode": 0, "panel_type": "FM6126A", "pixel_mapper_config": "Rotate:180"}"""
        self.width = cols * chain
        self.height = rows * parallel
        self.hardware = HARDWARE and not force_simulator
        self._brightness = max(1, min(100, int(brightness)))

        if self.hardware:
            o = RGBMatrixOptions()
            o.rows = rows
            o.cols = cols
            o.chain_length = chain
            o.parallel = parallel
            o.hardware_mapping = hardware_mapping
            o.gpio_slowdown = gpio_slowdown
            o.brightness = self._brightness
            o.pwm_bits = pwm_bits
            o.disable_hardware_pulsing = no_hardware_pulse
            o.drop_privileges = False  # keep root so we can still save files
            for key, value in (panel_options or {}).items():
                if value not in (None, ""):
                    setattr(o, key, value)
            self.matrix = RGBMatrix(options=o)
            # a pixel mapper (e.g. rotation) can change the visible size
            self.width, self.height = self.matrix.width, self.matrix.height
            self.canvas = self.matrix.CreateFrameCanvas()

        self._black = Image.new("RGB", (self.width, self.height))
        self.current_image = self._black

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._generation = 0
        self._scene = BlankScene(self.width, self.height)
        self._spec = {"type": "off"}

        self._running = True
        self._thread = threading.Thread(target=self._run, name="matrix", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ API
    def show(self, scene, spec):
        """Switch to a new scene. `spec` describes it (for status / restore)."""
        with self._lock:
            self._scene, self._spec = scene, dict(spec)
            self._generation += 1
        self._wake.set()

    def stop(self):
        self.show(BlankScene(self.width, self.height), {"type": "off"})

    @property
    def spec(self):
        with self._lock:
            return dict(self._spec)

    @property
    def brightness(self):
        return self._brightness

    def set_brightness(self, value):
        self._brightness = max(1, min(100, int(value)))
        if self.hardware:
            self.matrix.brightness = self._brightness
        self._wake.set()  # redraw static content with the new brightness

    def status(self):
        return {"spec": self.spec, "brightness": self._brightness,
                "hardware": self.hardware, "width": self.width, "height": self.height}

    def shutdown(self):
        self._running = False
        self._wake.set()
        self._thread.join(timeout=2)
        if self.hardware:
            self.matrix.Clear()

    # ------------------------------------------------------------ internals
    def _show(self, img):
        self.current_image = img
        if self.hardware:
            self.canvas.SetImage(img)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def _wait_until(self, deadline, gen):
        """Sleep until `deadline` (monotonic) or a scene change.
        deadline=None waits for any wake-up (scene change or redraw request)."""
        while self._running:
            timeout = None if deadline is None else deadline - time.monotonic()
            if timeout is not None and timeout <= 0:
                return
            if self._wake.wait(timeout):
                self._wake.clear()
                if deadline is None or self._generation != gen:
                    return

    def _run(self):
        last_gen = -1
        while self._running:
            with self._lock:
                gen, scene = self._generation, self._scene
            t0 = time.monotonic()
            try:
                if gen != last_gen:
                    last_gen = gen
                    scene.start()
                img, delay = scene.next()
            except Exception:
                traceback.print_exc()
                img, delay = self._black, 1.0
            self._show(img)
            self._wait_until(None if delay is None else t0 + delay, gen)
