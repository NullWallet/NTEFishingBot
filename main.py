#!/usr/bin/env python3
"""
NTE Fishing Bot — State-Aware Edition (Windows + Linux)
--------------------------------------
Controls: ` (grave) to toggle ON/OFF, Ctrl+C to quit

Requirements (Windows):
    pip install opencv-python numpy mss pynput

Requirements (Linux):
    pip install opencv-python evdev numpy --break-system-packages
    sudo pacman -S grim
    sudo usermod -aG input $USER  (then re-login)

Place images/ folder with bar.png and fish_hooked.png in the same folder as this script.

Anti-detection approach:
    - Windows: SendInput with hardware scan codes (appears as real keyboard input)
    - Linux:   evdev UInput (creates virtual /dev/input device, mimics real hardware)

Screen resolution:
    - Auto-detected on Windows
    - Auto-detected on Linux (X11), or set FISHBOT_RESOLUTION=WIDTHxHEIGHT for Wayland
    - All coordinates are percentage-based, scaled at runtime
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
# PLATFORM DETECTION
# ─────────────────────────────────────────────────────────────────────────────

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

if not IS_WINDOWS and not IS_LINUX:
    print("[ERROR] This script only supports Windows and Linux")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Key identifiers (platform-agnostic)
class Key:
    F = "F"
    A = "A"
    D = "D"
    GRAVE = "GRAVE"
    ESC = "ESC"
    SPACE = "SPACE"

# ── BASE RESOLUTION (all percentages are relative to this) ───────────────────

BASE_WIDTH = 1920
BASE_HEIGHT = 1080

# ── REGIONS AS PERCENTAGES ──────────────────────────────────────────────────
# Original 1920x1080 coordinates converted to 0.0-1.0 range

REGIONS_PERCENT = {
    "result_search": {
        "left": 775 / BASE_WIDTH,      # ~0.404
        "top": 960 / BASE_HEIGHT,      # ~0.889
        "width": 370 / BASE_WIDTH,     # ~0.193
        "height": 45 / BASE_HEIGHT,    # ~0.042
    },
    "hooked_search": {
        "left": 1727 / BASE_WIDTH,     # ~0.899
        "top": 921 / BASE_HEIGHT,      # ~0.853
        "width": 100 / BASE_WIDTH,     # ~0.052
        "height": 100 / BASE_HEIGHT,   # ~0.093
    },
    "f_btn": {
        "left": 1727 / BASE_WIDTH,     # ~0.899
        "top": 921 / BASE_HEIGHT,      # ~0.853
        "width": 100 / BASE_WIDTH,     # ~0.052
        "height": 100 / BASE_HEIGHT,   # ~0.093
    },
    "bar": {
        "left": 608 / BASE_WIDTH,      # ~0.317
        "top": 67 / BASE_HEIGHT,       # ~0.062
        "width": 712 / BASE_WIDTH,     # ~0.371
        "height": 17 / BASE_HEIGHT,    # ~0.016
    },
}

# ── TEMPLATE PATHS ───────────────────────────────────────────────────────────

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_PATH = os.path.join(_SCRIPT_DIR, "./images/bar.png")
_RESULT_TEMPLATE = cv2.imread(_TEMPLATE_PATH, cv2.IMREAD_GRAYSCALE)
if _RESULT_TEMPLATE is None:
    raise FileNotFoundError(f"bar.png not found at {_TEMPLATE_PATH}")

_HOOKED_TEMPLATE_PATH = os.path.join(_SCRIPT_DIR, "images/fish_hooked.png")
_HOOKED_TEMPLATE = cv2.imread(_HOOKED_TEMPLATE_PATH, cv2.IMREAD_GRAYSCALE)
if _HOOKED_TEMPLATE is None:
    raise FileNotFoundError(f"fish_hooked.png not found at {_HOOKED_TEMPLATE_PATH}")

RESULT_CONFIDENCE = 0.75
HOOKED_CONFIDENCE = 0.75

# ── COLOUR THRESHOLDS (HSV) ─────────────────────────────────────────────────

BLUE_LOW             = np.array([ 95, 150, 150])
BLUE_HIGH            = np.array([125, 255, 255])
BLUE_PIXEL_THRESHOLD = 50

GREEN_LOW  = np.array([ 75, 180, 180])
GREEN_HIGH = np.array([ 92, 255, 255])

YELLOW_LOW  = np.array([18,  50, 220])
YELLOW_HIGH = np.array([38, 180, 255])

HOOKED_BLUE_LOW  = np.array([103, 190, 200])
HOOKED_BLUE_HIGH = np.array([113, 255, 255])
HOOKED_PIXEL_THRESHOLD = 30

# ── TIMING ───────────────────────────────────────────────────────────────────

POLL_INTERVAL      = 0.05
KEY_TAP_MIN        = 0.40
KEY_TAP_MAX        = 0.60
REACTION_DELAY_MIN = 0.30
REACTION_DELAY_MAX = 0.50

STATE_TIMEOUTS = {
    "CASTING":       3.5,
    "WAITING_BITE": 60.0,
    "REACTING":      5.0,
    "CATCHING":     20.0,
    "UNKNOWN":       5.0,
}

BAR_MISS_LIMIT = 8

# ─────────────────────────────────────────────────────────────────────────────
# SCREEN RESOLUTION DETECTION & SCALING
# ─────────────────────────────────────────────────────────────────────────────

# Cached resolution (set during init)
_screen_width: int = BASE_WIDTH
_screen_height: int = BASE_HEIGHT
# Cached scaled regions
_scaled_regions: dict = {}


def get_screen_resolution() -> Tuple[int, int]:
    """Detect current screen resolution."""
    
    if IS_WINDOWS:
        # mss provides monitor info
        try:
            monitor = _sct.monitors[1]  # Index 0 is virtual, 1 is primary
            return monitor["width"], monitor["height"]
        except Exception:
            pass

    # Linux
    # Method 1: Environment variable (for Wayland or manual override)
    env_res = os.environ.get("FISHBOT_RESOLUTION")
    if env_res:
        try:
            w, h = env_res.lower().split("x")
            return int(w), int(h)
        except Exception:
            pass

    # Method 2: xrandr (X11)
    try:
        result = subprocess.run(
            ["xrandr", "--current"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if " connected" in line:
                    match = re.search(r'(\d+)x(\d+)', line)
                    if match:
                        return int(match.group(1)), int(match.group(2))
    except Exception:
        pass

    # Method 3: wlr-randr (wlroots Wayland)
    try:
        result = subprocess.run(
            ["wlr-randr"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            match = re.search(r'(\d+)x(\d+)', result.stdout)
            if match:
                return int(match.group(1)), int(match.group(2))
    except Exception:
        pass

    # Method 4: gnome-randr (GNOME Wayland)
    try:
        result = subprocess.run(
            ["gnome-randr"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            match = re.search(r'(\d+)x(\d+)', result.stdout)
            if match:
                return int(match.group(1)), int(match.group(2))
    except Exception:
        pass

    # Method 5: kscreen-doctor (KDE Wayland)
    try:
        result = subprocess.run(
            ["kscreen-doctor", "--outputs"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            match = re.search(r'(\d+)x(\d+)', result.stdout)
            if match:
                return int(match.group(1)), int(match.group(2))
    except Exception:
        pass

    # Fallback
    print("[WARN] Could not detect screen resolution, using 1920x1080")
    print("       Set FISHBOT_RESOLUTION=WIDTHxHEIGHT to override (e.g., 2560x1440)")
    return BASE_WIDTH, BASE_HEIGHT


def scale_region(region_percent: dict, width: int, height: int) -> dict:
    """Convert percentage-based region to pixel coordinates."""
    return {
        "left":   int(region_percent["left"] * width),
        "top":    int(region_percent["top"] * height),
        "width":  max(1, int(region_percent["width"] * width)),
        "height": max(1, int(region_percent["height"] * height)),
    }


def get_region(name: str) -> dict:
    """Get a region scaled to current screen resolution (cached)."""
    return _scaled_regions[name]


def init_screen() -> None:
    """Initialize screen resolution and cache all scaled regions."""
    global _screen_width, _screen_height, _scaled_regions
    
    _screen_width, _screen_height = get_screen_resolution()
    
    # Scale all regions
    _scaled_regions = {
        name: scale_region(region, _screen_width, _screen_height)
        for name, region in REGIONS_PERCENT.items()
    }
    
    print(f"[INFO] Screen: {_screen_width}x{_screen_height} (base: {BASE_WIDTH}x{BASE_HEIGHT})")
    print(f"[INFO] Scaled regions:")
    for name, region in _scaled_regions.items():
        print(f"       {name}: left={region['left']}, top={region['top']}, "
              f"{region['width']}x{region['height']}")

# ─────────────────────────────────────────────────────────────────────────────
# PLATFORM-SPECIFIC INPUT SETUP
# ─────────────────────────────────────────────────────────────────────────────

if IS_WINDOWS:
    import mss
    from pynput import keyboard as pynput_keyboard
    from ctypes import windll, Structure, Union, byref, sizeof
    from ctypes.wintypes import DWORD, WORD, ULONG, LONG, UINT

    # ── Windows SendInput Structures ──────────────────────────────────────

    class MOUSEINPUT(Structure):
        _fields_ = [
            ("dx", LONG), ("dy", LONG), ("mouseData", DWORD),
            ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG),
        ]

    class KEYBDINPUT(Structure):
        _fields_ = [
            ("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD),
            ("time", DWORD), ("dwExtraInfo", ULONG),
        ]

    class HARDWAREINPUT(Structure):
        _fields_ = [("uMsg", UINT), ("wParamL", WORD), ("wParamH", WORD)]

    class _INPUT_UNION(Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(Structure):
        _fields_ = [("type", DWORD), ("union", _INPUT_UNION)]

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008
    KEYEVENTF_EXTENDEDKEY = 0x0001

    # Hardware scan codes (what real keyboards send over USB/PS2)
    SCAN_CODES = {
        Key.F: 0x21,
        Key.A: 0x1E,
        Key.D: 0x20,
        Key.GRAVE: 0x29,
        Key.ESC: 0x01,
        Key.SPACE: 0x39,
    }

    EXTENDED_KEYS = set()

    # Global mss instance (must be created before init_screen)
    _sct = mss.mss()

elif IS_LINUX:
    import select
    from evdev import UInput, InputDevice, list_devices
    from evdev.ecodes import EV_KEY, KEY_F, KEY_A, KEY_D, KEY_GRAVE, KEY_ESC, KEY_SPACE

    EVDEV_KEY_MAP = {
        Key.F: KEY_F,
        Key.A: KEY_A,
        Key.D: KEY_D,
        Key.GRAVE: KEY_GRAVE,
        Key.ESC: KEY_ESC,
        Key.SPACE: KEY_SPACE,
    }

    # Virtual keyboard with real vendor/product IDs
    _ui = UInput(
        {EV_KEY: [KEY_F, KEY_A, KEY_D, KEY_GRAVE, KEY_ESC, KEY_SPACE]},
        name="Logitech USB Keyboard",
        vendor=0x046D,
        product=0xC31C,
    )

# ─────────────────────────────────────────────────────────────────────────────
# INPUT FUNCTIONS (Platform-Agnostic)
# ─────────────────────────────────────────────────────────────────────────────

def press_key(key: str, duration: float = None) -> None:
    """Press and release a key with human-like timing."""
    if duration is None:
        duration = random.uniform(KEY_TAP_MIN, KEY_TAP_MAX)

    if IS_WINDOWS:
        scan = SCAN_CODES[key]
        ext = key in EXTENDED_KEYS
        _win_send_scan(scan, key_up=False, extended=ext)
        time.sleep(duration)
        _win_send_scan(scan, key_up=True, extended=ext)
    else:
        evdev_key = EVDEV_KEY_MAP[key]
        _ui.write(EV_KEY, evdev_key, 1)
        _ui.syn()
        time.sleep(duration)
        _ui.write(EV_KEY, evdev_key, 0)
        _ui.syn()

    time.sleep(random.uniform(0.02, 0.05))


def hold_key(key: str) -> None:
    """Hold a key down (no release)."""
    if IS_WINDOWS:
        scan = SCAN_CODES[key]
        ext = key in EXTENDED_KEYS
        _win_send_scan(scan, key_up=False, extended=ext)
    else:
        evdev_key = EVDEV_KEY_MAP[key]
        _ui.write(EV_KEY, evdev_key, 1)
        _ui.syn()


def release_key(key: str) -> None:
    """Release a held key."""
    if IS_WINDOWS:
        scan = SCAN_CODES[key]
        ext = key in EXTENDED_KEYS
        _win_send_scan(scan, key_up=True, extended=ext)
    else:
        evdev_key = EVDEV_KEY_MAP[key]
        _ui.write(EV_KEY, evdev_key, 0)
        _ui.syn()


def cleanup_input() -> None:
    """Clean up platform-specific resources."""
    if IS_LINUX:
        _ui.close()
    elif IS_WINDOWS:
        try:
            _sct.close()
        except Exception:
            pass


# Windows-only helper (defined after INPUT structures)
if IS_WINDOWS:
    def _win_send_scan(scan_code: int, key_up: bool, extended: bool = False):
        """Send keyboard input using hardware scan code."""
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = 0
        inp.union.ki.wScan = scan_code
        inp.union.ki.dwFlags = KEYEVENTF_SCANCODE
        if key_up:
            inp.union.ki.dwFlags |= KEYEVENTF_KEYUP
        if extended:
            inp.union.ki.dwFlags |= KEYEVENTF_EXTENDEDKEY
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = 0
        windll.user32.SendInput(1, byref(inp), sizeof(INPUT))

# ─────────────────────────────────────────────────────────────────────────────
# SCREEN CAPTURE (Platform-Agnostic)
# ─────────────────────────────────────────────────────────────────────────────

def grab(region: dict, grayscale: bool = False) -> Optional[np.ndarray]:
    """
    Capture a screen region.
    Returns BGR numpy array (or grayscale if requested).
    """
    x, y, w, h = region["left"], region["top"], region["width"], region["height"]

    if IS_WINDOWS:
        try:
            monitor = {"left": x, "top": y, "width": w, "height": h}
            screenshot = _sct.grab(monitor)
            # mss returns BGRA, convert to BGR by dropping alpha
            img = np.array(screenshot)[:, :, :3]
            if grayscale:
                return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            return img
        except Exception:
            return None
    else:
        # Linux: use grim for Wayland
        try:
            r = subprocess.run(
                ["grim", "-g", f"{x},{y} {w}x{h}", "-t", "png", "-"],
                capture_output=True,
                timeout=0.5,
            )
            if r.returncode != 0 or not r.stdout:
                return None
            arr = np.frombuffer(r.stdout, dtype=np.uint8)
            flag = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
            return cv2.imdecode(arr, flag)
        except Exception:
            return None

# ─────────────────────────────────────────────────────────────────────────────
# DETECTORS
# ─────────────────────────────────────────────────────────────────────────────

def detect_fish_hooked(debug: bool = False) -> bool:
    """Detect the blue arc around the F button when fish is hooked."""
    img = grab(get_region("hooked_search"))
    if img is None:
        return False

    h, w = img.shape[:2]
    cx, cy = w // 2, h // 2

    # Scale the ring radii based on region size relative to base
    scale_factor = min(w, h) / 100.0  # Base region was 100x100
    R_INNER = int(35 * scale_factor)
    R_OUTER = int(40 * scale_factor)

    Y, X = np.ogrid[:h, :w]
    dist_sq = (X - cx) ** 2 + (Y - cy) ** 2
    annulus = ((dist_sq >= R_INNER ** 2) & (dist_sq <= R_OUTER ** 2)).astype(np.uint8) * 255
    interior = (dist_sq < R_INNER ** 2).astype(np.uint8) * 255

    # Colour filter on annulus
    img_masked = cv2.bitwise_and(img, img, mask=annulus)
    hsv = cv2.cvtColor(img_masked, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, HOOKED_BLUE_LOW, HOOKED_BLUE_HIGH)

    # Erode to kill noise
    kernel = np.ones((3, 3), np.uint8)
    mask_clean = cv2.erode(mask, kernel, iterations=1)

    # Interior colour check (for ratio)
    img_interior = cv2.bitwise_and(img, img, mask=interior)
    hsv_interior = cv2.cvtColor(img_interior, cv2.COLOR_BGR2HSV)
    mask_interior = cv2.inRange(hsv_interior, HOOKED_BLUE_LOW, HOOKED_BLUE_HIGH)

    blue_in_ring = int(cv2.countNonZero(mask_clean))
    blue_in_center = int(cv2.countNonZero(mask_interior))
    ratio = blue_in_ring / (blue_in_center + 1)

    # Largest connected arc
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask_clean, connectivity=8)
    largest_arc = int(stats[1:, cv2.CC_STAT_AREA].max()) if num_labels > 1 else 0

    # Scale thresholds based on region size
    scaled_arc_min = int(25 * scale_factor * scale_factor)
    scaled_ring_min = int(15 * scale_factor * scale_factor)

    detected = (
        blue_in_ring >= scaled_ring_min
        and ratio >= 2.0
        and largest_arc >= scaled_arc_min
    )

    if debug:
        ts = int(time.time() * 1000)
        debug_dir = os.path.join(_SCRIPT_DIR, "debug")
        os.makedirs(debug_dir, exist_ok=True)

        cv2.imwrite(os.path.join(debug_dir, f"{ts}_hooked_raw.png"), img)
        cv2.imwrite(os.path.join(debug_dir, f"{ts}_hooked_masked_region.png"), img_masked)
        cv2.imwrite(os.path.join(debug_dir, f"{ts}_hooked_mask.png"), mask)
        cv2.imwrite(os.path.join(debug_dir, f"{ts}_hooked_mask_clean.png"), mask_clean)

        overlay = img.copy()
        overlay[mask_clean > 0] = (0, 255, 255)
        overlay[mask_interior > 0] = (0, 0, 255)
        contours, _ = cv2.findContours(annulus.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay, contours, -1, (0, 255, 0), 1)
        cv2.imwrite(os.path.join(debug_dir, f"{ts}_hooked_overlay.png"), overlay)

        print(
            f"[DEBUG] hooked — in_ring={blue_in_ring} in_center={blue_in_center} "
            f"ratio={ratio:.2f} largest_arc={largest_arc} detected={detected} "
            f"(scaled: ring_min={scaled_ring_min}, arc_min={scaled_arc_min})"
            f"  → debug/{ts}_hooked_*.png"
        )

    return detected


def detect_result_screen() -> bool:
    """Template match for result screen text."""
    img = grab(get_region("result_search"), grayscale=True)
    if img is None:
        return False

    th, tw = _RESULT_TEMPLATE.shape[:2]
    ih, iw = img.shape[:2]

    if ih < th or iw < tw:
        return False

    result = cv2.matchTemplate(img, _RESULT_TEMPLATE, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)

    return float(max_val) >= RESULT_CONFIDENCE


def find_bar_positions() -> Optional[Tuple[float, float, float]]:
    """Find yellow marker and green bar positions. Returns (yellow_x, green_center, green_half) normalized."""
    region = get_region("bar")
    img = grab(region)
    if img is None:
        return None

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    w = region["width"]

    green_cols = np.where(cv2.inRange(hsv, GREEN_LOW, GREEN_HIGH).any(axis=0))[0]
    if len(green_cols) == 0:
        return None

    yellow_cols = np.where(cv2.inRange(hsv, YELLOW_LOW, YELLOW_HIGH).any(axis=0))[0]
    if len(yellow_cols) == 0:
        return None

    green_center = (int(green_cols[0]) + int(green_cols[-1])) / 2.0
    green_half = (int(green_cols[-1]) - int(green_cols[0])) / 2.0
    yellow_x = float(np.mean(yellow_cols))

    return yellow_x / w, green_center / w, green_half / w

# ─────────────────────────────────────────────────────────────────────────────
# STATES
# ─────────────────────────────────────────────────────────────────────────────

class State(Enum):
    IDLE = auto()
    CASTING = auto()
    WAITING_BITE = auto()
    REACTING = auto()
    MINIGAME = auto()
    CATCHING = auto()
    UNKNOWN = auto()

# ─────────────────────────────────────────────────────────────────────────────
# BOT
# ─────────────────────────────────────────────────────────────────────────────

class FishingBot:
    def __init__(self):
        self.running = False
        self.active = False
        self._thread = None
        self._held_key = None
        self._flags = {}
        self._bar_misses = 0

    # ── public ───────────────────────────────────────────────────────────

    def toggle(self):
        self.active = not self.active
        print(f"[BOT] {'ON ✓' if self.active else 'OFF ✗'}")
        if not self.active:
            self._release_all()

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[BOT] Ready. Press ` to toggle. Ctrl+C to quit.")

    def stop(self):
        self.running = False
        self._release_all()
        cleanup_input()

    # ── key helpers ──────────────────────────────────────────────────────

    def _release_all(self):
        if self._held_key is not None:
            release_key(self._held_key)
            self._held_key = None

    def _hold(self, key):
        if self._held_key != key:
            self._release_all()
            hold_key(key)
            self._held_key = key

    def _release(self):
        self._release_all()

    # ── context-aware observe ────────────────────────────────────────────

    def _observe(self, cur: State) -> State:
        """Only check what's relevant for the current state."""
        match cur:
            case State.WAITING_BITE:
                if detect_fish_hooked(debug=False):
                    return State.WAITING_BITE
                return State.UNKNOWN

            case State.REACTING | State.MINIGAME:
                if find_bar_positions() is not None:
                    return State.MINIGAME
                if detect_result_screen():
                    return State.CATCHING
                return State.UNKNOWN

            case State.CATCHING:
                if detect_result_screen():
                    return State.CATCHING
                return State.UNKNOWN

            case _:
                return State.UNKNOWN

    # ── transitions ──────────────────────────────────────────────────────

    def _next_state(self, cur: State, obs: State, elapsed: float) -> State:
        to = STATE_TIMEOUTS

        match cur:
            case State.IDLE:
                return State.CASTING

            case State.CASTING:
                if elapsed >= to["CASTING"]:
                    return State.WAITING_BITE

            case State.WAITING_BITE:
                if obs == State.WAITING_BITE:
                    return State.REACTING
                if elapsed >= to["WAITING_BITE"]:
                    print("[BOT] No bite in 60s — recasting...")
                    return State.IDLE

            case State.REACTING:
                if obs == State.MINIGAME:
                    return State.MINIGAME
                if obs == State.CATCHING:
                    return State.CATCHING
                if elapsed >= to["REACTING"]:
                    print("[BOT] Hook missed — recasting...")
                    return State.IDLE

            case State.MINIGAME:
                if obs == State.CATCHING:
                    self._bar_misses = 0
                    return State.CATCHING
                if obs != State.MINIGAME:
                    self._bar_misses += 1
                    if self._bar_misses >= BAR_MISS_LIMIT:
                        self._bar_misses = 0
                        print("[BOT] Bar gone — checking for result...")
                        return State.CATCHING
                else:
                    self._bar_misses = 0

            case State.CATCHING:
                if obs != State.CATCHING and self._flags.get("dismissed"):
                    return State.IDLE
                if elapsed >= to["CATCHING"]:
                    print("[BOT] Catch timeout — recasting...")
                    return State.IDLE

            case State.UNKNOWN:
                if elapsed >= to["UNKNOWN"]:
                    return State.IDLE

        return cur

    # ── actions ──────────────────────────────────────────────────────────

    def _act(self, state: State):
        match state:
            case State.IDLE:
                pass

            case State.CASTING:
                if not self._flags.get("cast_done"):
                    time.sleep(random.uniform(0.3, 0.6))
                    press_key(Key.F, random.uniform(0.03, 0.07))
                    self._flags["cast_done"] = True
                    print("[BOT] Cast!")

            case State.REACTING:
                if not self._flags.get("reacted"):
                    time.sleep(random.uniform(REACTION_DELAY_MIN, REACTION_DELAY_MAX))
                    press_key(Key.F, random.uniform(0.04, 0.1))
                    self._flags["reacted"] = True
                    print("[BOT] Hooked!")

            case State.MINIGAME:
                result = find_bar_positions()
                if result is None:
                    return

                yellow_norm, green_center_norm, green_half_norm = result
                error = yellow_norm - green_center_norm

                dead_zone = green_half_norm * 0.10
                outside_bounds = green_half_norm * 0.95

                if error > outside_bounds:
                    self._hold(Key.A)
                elif error < -outside_bounds:
                    self._hold(Key.D)
                elif error > dead_zone:
                    self._release()
                    press_key(Key.A, random.uniform(0.04, 0.08))
                elif error < -dead_zone:
                    self._release()
                    press_key(Key.D, random.uniform(0.04, 0.08))
                else:
                    self._release()

            case State.CATCHING:
                self._release()
                if detect_result_screen():
                    now = time.time()
                    last_attempt = self._flags.get("last_dismiss_attempt", 0)

                    if now - last_attempt > 3.0:
                        if last_attempt == 0:
                            time.sleep(random.uniform(1.2, 1.8))

                        press_key(Key.ESC)
                        self._flags["last_dismiss_attempt"] = time.time()
                        self._flags["dismissed"] = True
                        print("[BOT] Attempting to dismiss result screen...")

            case State.UNKNOWN:
                self._release()

    # ── state entry ──────────────────────────────────────────────────────

    def _on_enter(self, state: State):
        self._flags = {}
        self._bar_misses = 0
        self._release_all()
        print(f"[BOT] ── {state.name}")

    # ── main loop ────────────────────────────────────────────────────────

    def _loop(self):
        state = State.IDLE
        state_entered = time.time()
        self._on_enter(state)

        while self.running:
            if not self.active:
                self._release_all()
                while self.running and not self.active:
                    time.sleep(0.1)
                state = State.IDLE
                state_entered = time.time()
                self._on_enter(state)
                continue

            obs = self._observe(state)
            elapsed = time.time() - state_entered
            next_state = self._next_state(state, obs, elapsed)

            if next_state != state:
                state = next_state
                state_entered = time.time()
                self._on_enter(state)

            self._act(state)
            time.sleep(POLL_INTERVAL)

# ─────────────────────────────────────────────────────────────────────────────
# HOTKEY LISTENER (Platform-Specific)
# ─────────────────────────────────────────────────────────────────────────────

def hotkey_listener(bot: FishingBot):
    """Listen for ` key to toggle bot on/off."""

    if IS_WINDOWS:
        def on_press(key):
            try:
                if key.char == '`':
                    bot.toggle()
            except AttributeError:
                pass

        with pynput_keyboard.Listener(on_press=on_press) as listener:
            while bot.running:
                time.sleep(0.1)
            listener.stop()

    else:
        # Linux: use evdev to listen to real keyboard
        KEYBOARD_NAME = "ROYUAN Gaming Keyboard"
        devices = []
        for path in list_devices():
            try:
                dev = InputDevice(path)
                if KEYBOARD_NAME in dev.name:
                    devices.append(dev)
                    print(f"[BOT] Listening: {dev.name} ({dev.path})")
            except Exception:
                continue

        if not devices:
            print("[WARN] No keyboard found — hotkey disabled.")
            return

        last_toggle = 0.0
        try:
            while bot.running:
                r, _, _ = select.select(devices, [], [], 0.1)
                for dev in r:
                    for event in dev.read():
                        if event.type == EV_KEY and event.code == KEY_GRAVE and event.value == 1:
                            now = time.monotonic()
                            if now - last_toggle > 0.5:
                                last_toggle = now
                                bot.toggle()
        except Exception as ex:
            print(f"[WARN] Hotkey error: {ex}")

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

    # Initialize screen resolution and scale regions
    init_screen()

    if IS_WINDOWS:
        print("[INFO] Using SendInput with hardware scan codes")

    bot = FishingBot()
    threading.Thread(target=hotkey_listener, args=(bot,), daemon=True).start()
    bot.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[BOT] Shutting down...")
        bot.stop()