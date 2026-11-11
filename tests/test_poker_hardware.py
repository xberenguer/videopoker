"""The established display's bounds, timing, colors and release ownership."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("poker_hardware", ROOT / "payload/opt/dino/hardware.py")
hardware = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hardware)
LAUNCHER_SPEC = importlib.util.spec_from_file_location("poker_control_launcher", ROOT / "payload/opt/dino/launcher.py")
launcher = importlib.util.module_from_spec(LAUNCHER_SPEC)
LAUNCHER_SPEC.loader.exec_module(launcher)
try:
    from PIL import Image
except ImportError:
    Image = None


class HardwareTests(unittest.TestCase):
    def test_all_physical_pins_map_to_the_intended_poker_actions(self):
        active = set()
        owner = hardware.PlusHardware()
        owner.gpio = SimpleNamespace(LOW=0, input=lambda pin: 0 if pin in active else 1)
        # Board pin numbers are the physical wiring, independent of the
        # implementation's ordered tuple and the display's orientation.
        expected = {31: "UP", 35: "DOWN", 29: "LEFT", 37: "RIGHT",
                    33: "CENTER", 40: "KEY1", 38: "KEY2", 36: "KEY3"}
        self.assertEqual(set(owner.BUTTON_PINS), set(expected))
        self.assertEqual(len(owner.BUTTON_PINS), len(expected))
        self.assertEqual(owner.read_mask(), 0)
        for pin, action in expected.items():
            with self.subTest(pin=pin, action=action):
                active.clear()
                active.add(pin)
                self.assertEqual(owner.read_mask(), 1 << launcher.BUTTONS.index(action))
        active.update(expected)
        self.assertEqual(owner.read_mask(), 255)

    def test_physical_down_and_both_middles_route_without_changing_outer_chord(self):
        active = set()
        owner = hardware.PlusHardware()
        owner.gpio = SimpleNamespace(LOW=0, input=lambda pin: 0 if pin in active else 1)
        router = launcher.InputRouter()
        actions = []
        entered = False
        def sample(now, pins):
            nonlocal entered
            active.clear()
            active.update(pins)
            entered, emitted = router.update(now, owner.read_mask())
            actions.extend(emitted)
        sample(0, ())
        sample(.081, ())
        # A held physical D-pad Down emits the primary Deal action once.
        for now in (.1, .12, .15, .4): sample(now, (35,))
        sample(.5, ())
        sample(.52, ())
        # Both physical middle buttons retain their standard logical names;
        # the poker UI assigns both to Hold / confirm and next-hand Deal.
        sample(.54, (33,))
        sample(.56, (33,))
        sample(.58, ())
        sample(.595, ())
        sample(.6, (38,))
        sample(.62, (38,))
        sample(.7, ())
        sample(.72, ())
        self.assertEqual(actions, ["DOWN", "CENTER", "KEY2"])
        self.assertFalse(entered)
        # The same two outer physical action buttons still reserve entry;
        # neither produces a hold/menu action while forming the chord.
        sample(.8, (40,))
        sample(.82, (40,))
        sample(.9, (40, 36))
        self.assertEqual(owner.read_mask(), launcher.SIGNER_CHORD)
        sample(2.91, (40, 36))
        sample(3.0, ())
        sample(3.081, ())
        self.assertTrue(entered)
        self.assertEqual(actions, ["DOWN", "CENTER", "KEY2"])

    @unittest.skipUnless(Image, "Pillow is required for dirty-frame verification")
    def test_only_changed_pixels_are_sent_and_equal_frames_do_not_write(self):
        events = []
        owner = hardware.PlusHardware()
        owner.display = SimpleNamespace(
            show_image=lambda image: events.append(("full", image.size)),
            blit_buffer=lambda data,x,y,w,h: events.append(("rectangle", data,x,y,w,h)))
        frame = Image.new("RGB", (320, 240), "black")
        self.assertTrue(owner.present(frame))
        self.assertFalse(owner.present(frame))
        # Mutating the caller's earlier frame cannot mutate the last LCD frame.
        frame.putpixel((11, 23), (255, 0, 0))
        frame.putpixel((13, 24), (0, 0, 255))
        self.assertTrue(owner.present(frame))
        self.assertEqual(events[0], ("full", (320, 240)))
        self.assertEqual(len(events), 2)
        rectangle = events[1]
        self.assertEqual(rectangle[2:], (11, 23, 3, 2))
        self.assertEqual(len(rectangle[1]), 12)
        self.assertEqual(rectangle[1][:2], bytes.fromhex("f800"))
        self.assertEqual(rectangle[1][-2:], bytes.fromhex("001f"))

    @unittest.skipUnless(Image, "Pillow is required for failed-write verification")
    def test_failed_write_does_not_advance_the_lcd_frame_cache(self):
        owner = hardware.PlusHardware()
        calls = []
        def write(data, x, y, width, height):
            calls.append((x, y, width, height))
            if len(calls) == 1:
                raise OSError("temporary SPI failure")
        owner.display = SimpleNamespace(show_image=lambda image: None, blit_buffer=write)
        owner.present(Image.new("RGB", (320, 240), "black"))
        changed = Image.new("RGB", (320, 240), "black")
        changed.putpixel((4, 5), (0, 255, 0))
        with self.assertRaises(OSError):
            owner.present(changed)
        self.assertTrue(owner.present(changed))
        self.assertEqual(calls, [(4, 5, 1, 1), (4, 5, 1, 1)])

    @unittest.skipUnless(Image, "Pillow is required for color packing verification")
    def test_spi_byte_order_and_rgb565_colors(self):
        frame = Image.new("RGB", (6, 1))
        frame.putdata(((255, 0, 0), (0, 255, 0), (0, 0, 255),
                       (255, 255, 255), (0, 0, 0), (128, 128, 128)))
        self.assertEqual(hardware.rgb565_bytes(frame),
                         bytes.fromhex("f80007e0001fffff00008410"))

    @unittest.skipUnless(Image, "Pillow is required for full-frame verification")
    def test_plus_patch_retains_safe_clock_real_delay_and_exact_frame_bounds(self):
        events = []
        class Driver:
            def __init__(self):
                self.width, self.height = 320, 240
                self.spi = SimpleNamespace(max_speed_hz=125_000_000)
            def init(self, commands):
                events.append(("init", self.spi.max_speed_hz, commands))
            def blit_buffer(self, data, x, y, width, height):
                events.append(("blit", len(data), x, y, width, height))
        module = SimpleNamespace(ST7789=Driver)
        settings = SimpleNamespace(_data={})
        constants = SimpleNamespace(SETTING__DISPLAY_CONFIGURATION="display_config")
        hardware.configure_plus_display(settings, constants, module, sleep=lambda value: events.append(("sleep", value)))
        instance = Driver()
        instance.init(["commands"])
        module.sleep_ms(120)
        instance.show_image(Image.new("RGB", (320, 240)))
        self.assertEqual(settings._data, {"display_config": "st7789_320x240"})
        self.assertEqual(events[0], ("init", 25_000_000, ["commands"]))
        self.assertEqual(events[1], ("sleep", .12))
        self.assertEqual(events[2], ("blit", 153600, 0, 0, 320, 240))
        with self.assertRaises(ValueError):
            instance.show_image(Image.new("RGB", (319, 240)))
        with self.assertRaises(ValueError):
            instance.show_image(Image.new("RGB", (320, 240)), 1, 0)

    def test_ownership_release_is_complete_and_idempotent(self):
        events = []
        owner = hardware.PlusHardware()
        owner.display = SimpleNamespace(spi=SimpleNamespace(close=lambda: events.append("spi-close")))
        owner.gpio = SimpleNamespace(LOW=0, output=lambda pin, value: events.append(("output", pin, value)),
                                     cleanup=lambda pins: events.append(("cleanup", pins)))
        owner.close()
        owner.close()
        self.assertEqual(events, ["spi-close", ("output", 18, 0),
                                  ("cleanup", owner.BUTTON_PINS + owner.OUTPUT_PINS)])

    def test_present_rejects_wrong_frame_before_hardware_access(self):
        owner = hardware.PlusHardware()
        for size, mode in (((240, 240), "RGB"), ((320, 240), "RGBA")):
            with self.assertRaises(ValueError):
                owner.present(SimpleNamespace(size=size, mode=mode))


if __name__ == "__main__":
    unittest.main()
