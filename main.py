#!/usr/bin/env python3
"""
NTE Fishing Bot — State-Aware Edition (Windows + Linux)
--------------------------------------
Controls: ` (grave) to toggle ON/OFF, Ctrl+C to quit

Requirements (Windows):
    pip install opencv-python numpy mss pynput

Requirements (Linux):
    pip install opencv-python evdev numpy tomli --break-system-packages
    sudo pacman -S grim
    sudo usermod -aG input $USER  (then re-login)

Place images/ folder with bar.png and fish_hooked.png in the same folder as this script.
"""

import os
import sys
import re
import time
import random
import threading
import subprocess
from enum import Enum, auto
from typing import Optional, Tuple

import numpy as np
import cv2

# ─────────────────────────────────────────────────────────────────────────────
# TOML PARSER 
# ─────────────────────────────────────────────────────────────────────────────

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("[ERROR] Python 3.11+ is required, OR install 'tomli':")
        print("        pip install tomli")
        sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT CONFIGURATION GENERATION
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG_TOML = """
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                    NTE FISHING BOT CONFIGURATION                       ║
# ║  Modify these values to fine-tune the bot for your setup.              ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

[paths]
bar_image = "./images/bar.png"
hooked_image = "./images/fish_hooked.png"

[screen]
# Base resolution used to calculate the percentages
base_width = 1920
base_height = 1080
# Optional: Force a specific resolution (e.g., "2560x1440"). Leave empty "" for auto-detect.
manual_resolution = ""

[regions]
# All regions are defined as percentages (0.0 to 1.0) of your screen width/height
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
result_confidence = 0.75
hooked_confidence = 0.75
# Ring detection geometry (scaled automatically based on resolution)
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
# dead_zone_mult: Fish is perfectly centered, do nothing (percentage of green bar half-width)
dead_zone_mult = 0.10
# outside_bounds_mult: Fish is escaping, hold key to sprint (percentage of green bar half-width)
outside_bounds_mult = 0.95
"""

def load_config(path="config.toml") -> dict:
    """Load config from TOML file, generating it if it doesn't exist."""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_CONFIG_TOML.strip())
        print(f"[INFO] Generated default config at '{path}'. You can customize it and restart.")
    
    with open(path, "rb") as f:
        return tomllib.load(f)

# ─────────────────────────────────────────────────────────────────────────────
# INITIALIZATION
# ─────────────────────────────────────────────────────────────────────────────

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

if not IS_WINDOWS and not IS_LINUX:
    print("[ERROR] This script only supports Windows and Linux")
    sys.exit(1)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_SCRIPT_DIR, "config.toml")
CFG = load_config(CONFIG_PATH)

_TEMPLATE_PATH = os.path.join(_SCRIPT_DIR, CFG["paths"]["bar_image"])
_RESULT_TEMPLATE = cv2.imread(_TEMPLATE_PATH, cv2.IMREAD_GRAYSCALE)
if _RESULT_TEMPLATE is None:
    raise FileNotFoundError(f"{CFG['paths']['bar_image']} not found at {_TEMPLATE_PATH}")

_HOOKED_TEMPLATE_PATH = os.path.join(_SCRIPT_DIR, CFG["paths"]["hooked_image"])
_HOOKED_TEMPLATE = cv2.imread(_HOOKED_TEMPLATE_PATH, cv2.IMREAD_GRAYSCALE)
if _HOOKED_TEMPLATE is None:
    raise FileNotFoundError(f"{CFG['paths']['hooked_image']} not found at {_HOOKED_TEMPLATE_PATH}")

class Key:
    F = "F"; A = "A"; D = "D"; GRAVE = "GRAVE"; ESC = "ESC"; SPACE = "SPACE"

COLORS = {
    "blue": {"low": np.array(CFG["colors"]["blue"]["low"]), "high": np.array(CFG["colors"]["blue"]["high"])},
    "green": {"low": np.array(CFG["colors"]["green"]["low"]), "high": np.array(CFG["colors"]["green"]["high"])},
    "yellow": {"low": np.array(CFG["colors"]["yellow"]["low"]), "high": np.array(CFG["colors"]["yellow"]["high"])},
    "hooked_blue": {"low": np.array(CFG["colors"]["hooked_blue"]["low"]), "high": np.array(CFG["colors"]["hooked_blue"]["high"])}
}

# ─────────────────────────────────────────────────────────────────────────────
# SCREEN RESOLUTION DETECTION & SCALING
# ─────────────────────────────────────────────────────────────────────────────

_screen_width: int = CFG["screen"]["base_width"]
_screen_height: int = CFG["screen"]["base_height"]
_scaled_regions: dict = {}

def get_screen_resolution() -> Tuple[int, int]:
    manual = CFG["screen"].get("manual_resolution", "").strip()
    if manual:
        try:
            w, h = manual.lower().split("x")
            return int(w), int(h)
        except Exception: pass

    if IS_WINDOWS:
        try:
            monitor = _sct.monitors[1] 
            return monitor["width"], monitor["height"]
        except Exception: pass

    if IS_LINUX:
        try:
            result = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if " connected" in line:
                        match = re.search(r'(\d+)x(\d+)', line)
                        if match: return int(match.group(1)), int(match.group(2))
        except Exception: pass
        try:
            result = subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                match = re.search(r'(\d+)x(\d+)', result.stdout)
                if match: return int(match.group(1)), int(match.group(2))
        except Exception: pass

    return CFG["screen"]["base_width"], CFG["screen"]["base_height"]

def scale_region(region_percent: dict, width: int, height: int) -> dict:
    return {
        "left": int(region_percent["left"] * width),
        "top": int(region_percent["top"] * height),
        "width": max(1, int(region_percent["width"] * width)),
        "height": max(1, int(region_percent["height"] * height)),
    }

def get_region(name: str) -> dict:
    return _scaled_regions[name]

def init_screen() -> None:
    global _screen_width, _screen_height, _scaled_regions
    _screen_width, _screen_height = get_screen_resolution()
    _scaled_regions = {name: scale_region(region, _screen_width, _screen_height) for name, region in CFG["regions"].items()}
    print(f"[INFO] Screen: {_screen_width}x{_screen_height}")

# ─────────────────────────────────────────────────────────────────────────────
# PLATFORM-SPECIFIC INPUT SETUP
# ─────────────────────────────────────────────────────────────────────────────

if IS_WINDOWS:
    import mss
    from pynput import keyboard as pynput_keyboard
    from ctypes import windll, Structure, Union, byref, sizeof
    from ctypes.wintypes import DWORD, WORD, ULONG, LONG, UINT

    class MOUSEINPUT(Structure):
        _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD), ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG)]
    class KEYBDINPUT(Structure):
        _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG)]
    class HARDWAREINPUT(Structure):
        _fields_ = [("uMsg", UINT), ("wParamL", WORD), ("wParamH", WORD)]
    class _INPUT_UNION(Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]
    class INPUT(Structure):
        _fields_ = [("type", DWORD), ("union", _INPUT_UNION)]

    INPUT_KEYBOARD = 1; KEYEVENTF_KEYUP = 0x0002; KEYEVENTF_SCANCODE = 0x0008; KEYEVENTF_EXTENDEDKEY = 0x0001
    SCAN_CODES = { Key.F: 0x21, Key.A: 0x1E, Key.D: 0x20, Key.GRAVE: 0x29, Key.ESC: 0x01, Key.SPACE: 0x39 }
    EXTENDED_KEYS = set()
    _sct = mss.mss()

    def _win_send_scan(scan_code: int, key_up: bool, extended: bool = False):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD; inp.union.ki.wVk = 0; inp.union.ki.wScan = scan_code
        inp.union.ki.dwFlags = KEYEVENTF_SCANCODE
        if key_up: inp.union.ki.dwFlags |= KEYEVENTF_KEYUP
        if extended: inp.union.ki.dwFlags |= KEYEVENTF_EXTENDEDKEY
        inp.union.ki.time = 0; inp.union.ki.dwExtraInfo = 0
        windll.user32.SendInput(1, byref(inp), sizeof(INPUT))

elif IS_LINUX:
    import select
    from evdev import UInput, InputDevice, list_devices
    from evdev.ecodes import EV_KEY, KEY_F, KEY_A, KEY_D, KEY_GRAVE, KEY_ESC, KEY_SPACE

    EVDEV_KEY_MAP = { Key.F: KEY_F, Key.A: KEY_A, Key.D: KEY_D, Key.GRAVE: KEY_GRAVE, Key.ESC: KEY_ESC, Key.SPACE: KEY_SPACE }
    
    # Name of the virtual device we create (used to exclude it from hotkey listening)
    VIRTUAL_KB_NAME = "Logitech USB Keyboard"
    
    _ui = UInput(
        {EV_KEY: [KEY_F, KEY_A, KEY_D, KEY_GRAVE, KEY_ESC, KEY_SPACE]},
        name=VIRTUAL_KB_NAME, vendor=0x046D, product=0xC31C,
    )

# ─────────────────────────────────────────────────────────────────────────────
# INPUT FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def press_key(key: str, duration: float = None) -> None:
    if duration is None:
        duration = random.uniform(CFG["timing"]["key_tap_min"], CFG["timing"]["key_tap_max"])

    if IS_WINDOWS:
        scan = SCAN_CODES[key]; ext = key in EXTENDED_KEYS
        _win_send_scan(scan, False, ext); time.sleep(duration); _win_send_scan(scan, True, ext)
    else:
        evdev_key = EVDEV_KEY_MAP[key]
        _ui.write(EV_KEY, evdev_key, 1); _ui.syn(); time.sleep(duration); _ui.write(EV_KEY, evdev_key, 0); _ui.syn()
    time.sleep(random.uniform(0.02, 0.05))

def hold_key(key: str) -> None:
    if IS_WINDOWS: _win_send_scan(SCAN_CODES[key], False, key in EXTENDED_KEYS)
    else: _ui.write(EV_KEY, EVDEV_KEY_MAP[key], 1); _ui.syn()

def release_key(key: str) -> None:
    if IS_WINDOWS: _win_send_scan(SCAN_CODES[key], True, key in EXTENDED_KEYS)
    else: _ui.write(EV_KEY, EVDEV_KEY_MAP[key], 0); _ui.syn()

def cleanup_input() -> None:
    if IS_LINUX: _ui.close()
    elif IS_WINDOWS:
        try: _sct.close()
        except: pass

# ─────────────────────────────────────────────────────────────────────────────
# SCREEN CAPTURE
# ─────────────────────────────────────────────────────────────────────────────

def grab(region: dict, grayscale: bool = False) -> Optional[np.ndarray]:
    x, y, w, h = region["left"], region["top"], region["width"], region["height"]
    if IS_WINDOWS:
        try:
            screenshot = _sct.grab({"left": x, "top": y, "width": w, "height": h})
            img = np.array(screenshot)[:, :, :3]
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if grayscale else img
        except: return None
    else:
        try:
            r = subprocess.run(["grim", "-g", f"{x},{y} {w}x{h}", "-t", "png", "-"], capture_output=True, timeout=0.5)
            if r.returncode != 0 or not r.stdout: return None
            return cv2.imdecode(np.frombuffer(r.stdout, dtype=np.uint8), cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR)
        except: return None

# ─────────────────────────────────────────────────────────────────────────────
# DETECTORS
# ─────────────────────────────────────────────────────────────────────────────

def detect_fish_hooked(debug: bool = False) -> bool:
    img = grab(get_region("hooked_search"))
    if img is None: return False
    h, w = img.shape[:2]; cx, cy = w // 2, h // 2
    scale_factor = min(w, h) / 100.0 
    R_INNER = int(CFG["detection"]["hooked_r_inner"] * scale_factor)
    R_OUTER = int(CFG["detection"]["hooked_r_outer"] * scale_factor)

    Y, X = np.ogrid[:h, :w]
    dist_sq = (X - cx) ** 2 + (Y - cy) ** 2
    annulus = ((dist_sq >= R_INNER ** 2) & (dist_sq <= R_OUTER ** 2)).astype(np.uint8) * 255
    interior = (dist_sq < R_INNER ** 2).astype(np.uint8) * 255

    img_masked = cv2.bitwise_and(img, img, mask=annulus)
    hsv = cv2.cvtColor(img_masked, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, COLORS["hooked_blue"]["low"], COLORS["hooked_blue"]["high"])
    mask_clean = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=1)

    img_interior = cv2.bitwise_and(img, img, mask=interior)
    hsv_interior = cv2.cvtColor(img_interior, cv2.COLOR_BGR2HSV)
    mask_interior = cv2.inRange(hsv_interior, COLORS["hooked_blue"]["low"], COLORS["hooked_blue"]["high"])

    blue_in_ring = int(cv2.countNonZero(mask_clean))
    blue_in_center = int(cv2.countNonZero(mask_interior))
    ratio = blue_in_ring / (blue_in_center + 1)

    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask_clean, connectivity=8)
    largest_arc = int(stats[1:, cv2.CC_STAT_AREA].max()) if num_labels > 1 else 0

    scaled_arc_min = int(CFG["detection"]["hooked_arc_min_size"] * scale_factor * scale_factor)
    scaled_ring_min = int(CFG["detection"]["hooked_ring_min_pixels"] * scale_factor * scale_factor)

    return blue_in_ring >= scaled_ring_min and ratio >= 2.0 and largest_arc >= scaled_arc_min

def detect_result_screen() -> bool:
    img = grab(get_region("result_search"), grayscale=True)
    if img is None: return False
    th, tw = _RESULT_TEMPLATE.shape[:2]; ih, iw = img.shape[:2]
    if ih < th or iw < tw: return False
    result = cv2.matchTemplate(img, _RESULT_TEMPLATE, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return float(max_val) >= CFG["detection"]["result_confidence"]

def find_bar_positions() -> Optional[Tuple[float, float, float]]:
    region = get_region("bar")
    img = grab(region)
    if img is None: return None
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV); w = region["width"]
    green_cols = np.where(cv2.inRange(hsv, COLORS["green"]["low"], COLORS["green"]["high"]).any(axis=0))[0]
    if len(green_cols) == 0: return None
    yellow_cols = np.where(cv2.inRange(hsv, COLORS["yellow"]["low"], COLORS["yellow"]["high"]).any(axis=0))[0]
    if len(yellow_cols) == 0: return None
    green_center = (int(green_cols[0]) + int(green_cols[-1])) / 2.0
    green_half = (int(green_cols[-1]) - int(green_cols[0])) / 2.0
    yellow_x = float(np.mean(yellow_cols))
    return yellow_x / w, green_center / w, green_half / w

# ─────────────────────────────────────────────────────────────────────────────
# STATES & BOT
# ─────────────────────────────────────────────────────────────────────────────

class State(Enum):
    IDLE = auto(); CASTING = auto(); WAITING_BITE = auto()
    REACTING = auto(); MINIGAME = auto(); CATCHING = auto(); UNKNOWN = auto()

class FishingBot:
    def __init__(self):
        self.running = self.active = False
        self._thread = None; self._held_key = None; self._flags = {}; self._bar_misses = 0

    def toggle(self):
        self.active = not self.active
        print(f"[BOT] {'ON ✓' if self.active else 'OFF ✗'}")
        if not self.active: self._release_all()

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True).start()
        print("[BOT] Ready. Press ` to toggle. Ctrl+C to quit.")

    def stop(self):
        self.running = False; self._release_all(); cleanup_input()

    def _release_all(self):
        if self._held_key is not None: release_key(self._held_key); self._held_key = None

    def _hold(self, key):
        if self._held_key != key: self._release_all(); hold_key(key); self._held_key = key

    def _release(self): self._release_all()

    def _observe(self, cur: State) -> State:
        match cur:
            case State.WAITING_BITE: return State.WAITING_BITE if detect_fish_hooked() else State.UNKNOWN
            case State.REACTING | State.MINIGAME:
                if find_bar_positions() is not None: return State.MINIGAME
                if detect_result_screen(): return State.CATCHING
                return State.UNKNOWN
            case State.CATCHING: return State.CATCHING if detect_result_screen() else State.UNKNOWN
            case _: return State.UNKNOWN

    def _next_state(self, cur: State, obs: State, elapsed: float) -> State:
        to = CFG["timing"]["timeouts"]
        match cur:
            case State.IDLE: return State.CASTING
            case State.CASTING:
                if elapsed >= to["CASTING"]: return State.WAITING_BITE
            case State.WAITING_BITE:
                if obs == State.WAITING_BITE: return State.REACTING
                if elapsed >= to["WAITING_BITE"]: print("[BOT] No bite in 60s — recasting..."); return State.IDLE
            case State.REACTING:
                if obs == State.MINIGAME: return State.MINIGAME
                if obs == State.CATCHING: return State.CATCHING
                if elapsed >= to["REACTING"]: print("[BOT] Hook missed — recasting..."); return State.IDLE
            case State.MINIGAME:
                if obs == State.CATCHING: self._bar_misses = 0; return State.CATCHING
                if obs != State.MINIGAME:
                    self._bar_misses += 1
                    if self._bar_misses >= CFG["timing"]["bar_miss_limit"]:
                        self._bar_misses = 0; print("[BOT] Bar gone — checking for result..."); return State.CATCHING
                else: self._bar_misses = 0
            case State.CATCHING:
                if obs != State.CATCHING and self._flags.get("dismissed"): return State.IDLE
                if elapsed >= to["CATCHING"]: print("[BOT] Catch timeout — recasting..."); return State.IDLE
            case State.UNKNOWN:
                if elapsed >= to["UNKNOWN"]: return State.IDLE
        return cur

    def _act(self, state: State):
        match state:
            case State.IDLE: pass
            case State.CASTING:
                if not self._flags.get("cast_done"):
                    time.sleep(random.uniform(0.3, 0.6)); press_key(Key.F, random.uniform(0.03, 0.07))
                    self._flags["cast_done"] = True; print("[BOT] Cast!")
            case State.REACTING:
                if not self._flags.get("reacted"):
                    time.sleep(random.uniform(CFG["timing"]["reaction_delay_min"], CFG["timing"]["reaction_delay_max"]))
                    press_key(Key.F, random.uniform(0.04, 0.1)); self._flags["reacted"] = True; print("[BOT] Hooked!")
            case State.MINIGAME:
                result = find_bar_positions()
                if result is None: return
                yellow_norm, green_center_norm, green_half_norm = result
                error = yellow_norm - green_center_norm
                dead_zone = green_half_norm * CFG["minigame"]["dead_zone_mult"]
                outside_bounds = green_half_norm * CFG["minigame"]["outside_bounds_mult"]
                if error > outside_bounds: self._hold(Key.A)
                elif error < -outside_bounds: self._hold(Key.D)
                elif error > dead_zone: self._release(); press_key(Key.A, random.uniform(0.04, 0.08))
                elif error < -dead_zone: self._release(); press_key(Key.D, random.uniform(0.04, 0.08))
                else: self._release()
            case State.CATCHING:
                self._release()
                if detect_result_screen():
                    now = time.time(); last_attempt = self._flags.get("last_dismiss_attempt", 0)
                    if now - last_attempt > 3.0:
                        if last_attempt == 0: time.sleep(random.uniform(1.2, 1.8))
                        press_key(Key.ESC); self._flags["last_dismiss_attempt"] = time.time()
                        self._flags["dismissed"] = True; print("[BOT] Attempting to dismiss result screen...")
            case State.UNKNOWN: self._release()

    def _on_enter(self, state: State):
        self._flags = {}; self._bar_misses = 0; self._release_all(); print(f"[BOT] ── {state.name}")

    def _loop(self):
        state = State.IDLE; state_entered = time.time(); self._on_enter(state)
        while self.running:
            if not self.active:
                self._release_all()
                while self.running and not self.active: time.sleep(0.1)
                state = State.IDLE; state_entered = time.time(); self._on_enter(state); continue
            obs = self._observe(state); elapsed = time.time() - state_entered
            next_state = self._next_state(state, obs, elapsed)
            if next_state != state: state = next_state; state_entered = time.time(); self._on_enter(state)
            self._act(state); time.sleep(CFG["timing"]["poll_interval"])

# ─────────────────────────────────────────────────────────────────────────────
# HOTKEY LISTENER
# ─────────────────────────────────────────────────────────────────────────────

def hotkey_listener(bot: FishingBot):
    if IS_WINDOWS:
        def on_press(key):
            try:
                if key.char == '`': bot.toggle()
            except AttributeError: pass
        with pynput_keyboard.Listener(on_press=on_press) as listener:
            while bot.running: time.sleep(0.1)
            listener.stop()
    else:
        devices = []
        for path in list_devices():
            try:
                dev = InputDevice(path)
                # Ensure it has EV_KEY capabilities
                if EV_KEY in dev.capabilities():
                    keys = dev.capabilities()[EV_KEY]
                    # A real keyboard will have letter keys (like KEY_A). Mice/power buttons won't.
                    if KEY_A in keys:
                        # CRITICAL: Exclude the virtual keyboard we created to prevent infinite loops
                        if VIRTUAL_KB_NAME not in dev.name:
                            devices.append(dev)
                            print(f"[BOT] Auto-detected keyboard: {dev.name} ({dev.path})")
            except Exception:
                continue

        if not devices:
            print("[WARN] No physical keyboards detected — hotkey disabled.")
            return

        last_toggle = 0.0
        try:
            while bot.running:
                r, _, _ = select.select(devices, [], [], 0.1)
                for dev in r:
                    for event in dev.read():
                        if event.type == EV_KEY and event.code == KEY_GRAVE and event.value == 1:
                            now = time.monotonic()
                            if now - last_toggle > 0.5: last_toggle = now; bot.toggle()
        except Exception as ex: print(f"[WARN] Hotkey error: {ex}")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  NTE Fishing Bot  —  State-Aware Edition")
    print(f"  Platform: {'Windows' if IS_WINDOWS else 'Linux'}")
    print("  `       → Toggle ON / OFF")
    print("  Ctrl+C  → Quit")
    print("=" * 60)

    init_screen()

    if IS_WINDOWS:
        print("[INFO] Using SendInput with hardware scan codes")

    bot = FishingBot()
    threading.Thread(target=hotkey_listener, args=(bot,), daemon=True).start()
    bot.start()

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n[BOT] Shutting down...")
        bot.stop()