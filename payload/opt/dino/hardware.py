"""Known-working Plus ST7789 / GPIO owner, adapted from the Dino launcher.

No emulator, ROM, signer controller or renderer is initialized for the poker game.
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

DISPLAY_PROFILE = "st7789_320x240"
SPI_SPEED_HZ = 25_000_000

class PlusHardware:
    """Own the established Plus GPIO/SPI path until deliberate signer entry."""

    # Logical order: UP, DOWN, LEFT, RIGHT, CENTER, KEY1, KEY2, KEY3.
    # Preserve the standard physical layout. Poker assigns both middle
    # buttons to Hold / confirm and the D-pad Down button to Deal / Draw.
    BUTTON_PINS = (31, 35, 29, 37, 33, 40, 38, 36)
    OUTPUT_PINS = (22, 13, 18)

    def __init__(self):
        self.display, self.gpio = None, None
        self._last_frame = None
        self._backlight_pwm = None
        self._brightness = 100

    def __enter__(self):
        upstream_path = "/opt/src"
        if upstream_path not in sys.path:
            sys.path.insert(0, upstream_path)
        from seedsigner.hardware.displays import st7789_mpy as driver_module
        configure_plus_display(
            SimpleNamespace(_data={}),
            SimpleNamespace(SETTING__DISPLAY_CONFIGURATION="display_config"),
            driver_module)
        self.gpio = driver_module.GPIO
        try:
            self.display = driver_module.ST7789(_width=240, _height=320)
            self.gpio.setup(self.BUTTON_PINS, self.gpio.IN,
                            pull_up_down=self.gpio.PUD_UP)
            return self
        except BaseException:
            self.close()
            raise

    def read_mask(self):
        return sum(1 << bit for bit, pin in enumerate(self.BUTTON_PINS)
                   if self.gpio.input(pin) == self.gpio.LOW)

    def set_brightness(self, value):
        if type(value) is not int or value not in range(10,101,10):
            raise ValueError('Brightness must be 10..100 in 10% steps')
        if value == self._brightness:return False
        if self._backlight_pwm is None:
            self._backlight_pwm=self.gpio.PWM(self.display.backlight,1000)
            self._backlight_pwm.start(value)
        else:self._backlight_pwm.ChangeDutyCycle(value)
        self._brightness=value
        return True

    def present(self, image):
        if image.mode != "RGB" or image.size != (320, 240):
            raise ValueError("Poker frame must be RGB 320x240")
        # The poker clock and GPIO polling must not wait for unchanged pixels.
        # Pillow performs the comparison/crop in C; only the changed rectangle
        # is converted and transferred through the established RGB565 driver.
        if self._last_frame is None:
            self.display.show_image(image)
        else:
            from PIL import ImageChops
            bounds = ImageChops.difference(image, self._last_frame).getbbox()
            if bounds is None:
                return False
            left, top, right, bottom = bounds
            self.display.blit_buffer(rgb565_bytes(image.crop(bounds)),
                                     left, top, right-left, bottom-top)
        # Keep a detached snapshot. A caller can reuse or mutate its PIL frame.
        # A failed SPI write leaves the previous transmitted frame intact.
        self._last_frame = image.copy()
        return True

    def show_message(self, message, detail=None):
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (320, 240), "black")
        draw = ImageDraw.Draw(image)
        draw.text((24, 96), message, fill="white")
        if detail:
            draw.text((24, 120), detail, fill="white")
        self.present(image)

    def close(self):
        self._last_frame = None
        if self._backlight_pwm is not None:
            self._backlight_pwm.stop()
            self._backlight_pwm=None
        if self.display is not None:
            try:
                self.display.spi.close()
            except Exception:
                pass
            self.display = None
        if self.gpio is not None:
            try:
                self.gpio.output(18, self.gpio.LOW)
            except Exception:
                pass
            try:
                self.gpio.cleanup(self.BUTTON_PINS + self.OUTPUT_PINS)
            except Exception:
                pass
            self.gpio = None

    def __exit__(self, exc_type, exc, traceback):
        self.close()

def rgb565_bytes(image):
    """Pack RGB565 in SPI byte order using native Pillow operations.

    The deprecated BGR;16 image mode is unavailable in newer Pillow releases.
    Lookup tables avoid both that dependency and a slow Python per-pixel loop.
    """
    from PIL import Image, ImageChops
    red, green, blue = image.split()
    high = ImageChops.add(red.point(_RED_HIGH), green.point(_GREEN_HIGH))
    low = ImageChops.add(green.point(_GREEN_LOW), blue.point(_BLUE_LOW))
    return Image.merge("LA", (high, low)).tobytes()


_RED_HIGH = [value & 0xf8 for value in range(256)]
_GREEN_HIGH = [value >> 5 for value in range(256)]
_GREEN_LOW = [(value & 0x1c) << 3 for value in range(256)]
_BLUE_LOW = [value >> 3 for value in range(256)]


def configure_plus_display(settings, settings_constants, driver_module, sleep=time.sleep):
    # Override only RAM, before Renderer construction. set_value() would write settings.
    settings._data[settings_constants.SETTING__DISPLAY_CONFIGURATION] = DISPLAY_PROFILE
    # The upstream CPython compatibility fallback is a no-op, including the documented
    # 120ms reset delay. Restore actual hardware timing before initialization.
    driver_module.sleep_ms = lambda milliseconds: sleep(milliseconds / 1000.0)
    driver = driver_module.ST7789
    if not getattr(driver, "_poker_timing_installed", False):
        original_init = driver.init

        def initialize_at_safe_speed(self, commands):
            # __post_init__ creates SPI before hard_reset and calls init twice. This
            # assignment precedes its first SPI command and retains the existing driver.
            self.spi.max_speed_hz = SPI_SPEED_HZ
            return original_init(self, commands)

        def show_full_image(self, image, x_start=0, y_start=0):
            if image.size != (self.width, self.height):
                raise ValueError("Image must match display dimensions")
            if x_start != 0 or y_start != 0:
                raise ValueError("Full display image must start at the origin")
            # Original show_image passes width/height as inclusive end coordinates,
            # selecting 321x241 pixels for a 320x240 frame. blit_buffer correctly
            # subtracts one and is already used for the game's rectangular updates.
            self.blit_buffer(rgb565_bytes(image.convert("RGB")),
                             x_start, y_start, self.width, self.height)

        driver.init = initialize_at_safe_speed
        driver.show_image = show_full_image
        driver._poker_timing_installed = True


