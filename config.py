import os
import sys

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("[ERROR] Python 3.11+ is required, OR install 'tomli':")
        sys.exit(1)

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

if not IS_WINDOWS and not IS_LINUX:
    print("[ERROR] This script only supports Windows and Linux")
    sys.exit(1)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_SCRIPT_DIR, "config.toml")

DEFAULT_CONFIG_TOML = """
[hotkeys]
toggle = "`"

[paths]
bar_image = "./images/result.png"
hooked_image = "./images/fish_hooked.png"

[screen]
base_width = 1920
base_height = 1080
manual_resolution = ""

[regions]
result_search = { left = 0.4036, top = 0.8889, width = 0.1927, height = 0.0417 }
hooked_search = { left = 0.8990, top = 0.8528, width = 0.0521, height = 0.0926 }
f_btn = { left = 0.8990, top = 0.8528, width = 0.0521, height = 0.0926 }
bar = { left = 0.3167, top = 0.0620, width = 0.3708, height = 0.0157 }

[colors.blue]
low = [95, 150, 150]
high = [125, 255, 255]
pixel_threshold = 50

[colors.green]
low = [75, 180, 180]
high = [92, 255, 255]

[colors.yellow]
low = [18, 50, 220]
high = [38, 180, 255]

[colors.hooked_blue]
low = [103, 190, 200]
high = [113, 255, 255]
pixel_threshold = 30

[detection]
result_confidence = 0.60
hooked_confidence = 0.60
hooked_r_inner = 35
hooked_r_outer = 40
hooked_arc_min_size = 25
hooked_ring_min_pixels = 15

[timing]
poll_interval = 0.05
key_tap_min = 0.40
key_tap_max = 0.60
reaction_delay_min = 0.30
reaction_delay_max = 0.50
bar_miss_limit = 8

[timing.timeouts]
CASTING = 3.5
WAITING_BITE = 60.0
REACTING = 5.0
CATCHING = 20.0
UNKNOWN = 5.0

[minigame]
dead_zone_mult = 0.10
outside_bounds_mult = 0.95

[debug]
result_screen = false
"""

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(DEFAULT_CONFIG_TOML.strip())
        print(f"[INFO] Generated default config at '{CONFIG_PATH}'.")
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)

CFG = load_config()