import time
import random
import sys
from typing import TYPE_CHECKING

import config

if TYPE_CHECKING:
    from bot import FishingBot

# ── Key Definitions ────────────────────────────────────────────────────────

class Key:
    F = "F"; A = "A"; D = "D"; GRAVE = "GRAVE"; ESC = "ESC"; SPACE = "SPACE"

# ── Platform Input Setup ──────────────────────────────────────────────────

if config.IS_WINDOWS:
    from pynput import keyboard as pynput_keyboard
    from pynput.keyboard import Controller as PynputController

    _kb_ctrl = PynputController()

    # Map our internal keys to pynput strings for sending
    _PYNPUT_SEND_MAP = {
        Key.F: 'f', 
        Key.A: 'a', 
        Key.D: 'd', 
        Key.ESC: '\x1b', # Escape character
        Key.SPACE: ' '
    }

elif config.IS_LINUX:
    import select
    from evdev import UInput, InputDevice, list_devices
    from evdev.ecodes import EV_KEY, KEY_F, KEY_A, KEY_D, KEY_GRAVE, KEY_ESC, KEY_SPACE

    EVDEV_KEY_MAP = { 
        Key.F: KEY_F, Key.A: KEY_A, Key.D: KEY_D, 
        Key.GRAVE: KEY_GRAVE, Key.ESC: KEY_ESC, Key.SPACE: KEY_SPACE 
    }
    VIRTUAL_KB_NAME = "Logitech USB Keyboard"
    
    _ui = UInput(
        {EV_KEY: [KEY_F, KEY_A, KEY_D, KEY_GRAVE, KEY_ESC, KEY_SPACE]},
        name=VIRTUAL_KB_NAME, vendor=0x046D, product=0xC31C,
    )

# ── Hotkey Mapping Setup ──────────────────────────────────────────────────

_TOGGLE_CONFIG_STR = config.CFG.get("hotkeys", {}).get("toggle", "`").lower()

if config.IS_WINDOWS:
    import pynput.keyboard as pk
    _PYNPUT_SPECIALS = {
        "tab": pk.Key.tab, "caps_lock": pk.Key.caps_lock,
        "shift": pk.Key.shift, "ctrl": pk.Key.ctrl, "alt": pk.Key.alt, "alt_gr": pk.Key.alt_gr,
        "backspace": pk.Key.backspace, "delete": pk.Key.delete, "insert": pk.Key.insert,
        "home": pk.Key.home, "end": pk.Key.end, "page_up": pk.Key.page_up, "page_down": pk.Key.page_down,
        "enter": pk.Key.enter, "esc": pk.Key.esc, "space": pk.Key.space,
        "up": pk.Key.up, "down": pk.Key.down, "left": pk.Key.left, "right": pk.Key.right,
        "f1": pk.Key.f1, "f2": pk.Key.f2, "f3": pk.Key.f3, "f4": pk.Key.f4,
        "f5": pk.Key.f5, "f6": pk.Key.f6, "f7": pk.Key.f7, "f8": pk.Key.f8,
        "f9": pk.Key.f9, "f10": pk.Key.f10, "f11": pk.Key.f11, "f12": pk.Key.f12,
    }
    # Backtick/Grave is passed as a standard string character in pynput
    _PYNPUT_TOGGLE = _PYNPUT_SPECIALS.get(_TOGGLE_CONFIG_STR, _TOGGLE_CONFIG_STR)

elif config.IS_LINUX:
    from evdev import ecodes as evdev_ecodes
    _EVDEV_SPECIALS = {
        "`": "KEY_GRAVE", "-": "KEY_MINUS", "=": "KEY_EQUAL", "[": "KEY_LEFTBRACE", "]": "KEY_RIGHTBRACE",
        "\\": "KEY_BACKSLASH", ";": "KEY_SEMICOLON", "'": "KEY_APOSTROPHE", ",": "KEY_COMMA", 
        ".": "KEY_DOT", "/": "KEY_SLASH", "space": "KEY_SPACE", "enter": "KEY_ENTER", "tab": "KEY_TAB",
        "esc": "KEY_ESC", "backspace": "KEY_BACKSPACE", "insert": "KEY_INSERT", "delete": "KEY_DELETE",
        "home": "KEY_HOME", "end": "KEY_END", "page_up": "KEY_PAGEUP", "page_down": "KEY_PAGEDOWN",
        "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
        "shift": "KEY_LEFTSHIFT", "ctrl": "KEY_LEFTCTRL", "alt": "KEY_LEFTALT", "caps_lock": "KEY_CAPSLOCK",
    }
    evdev_str = _EVDEV_SPECIALS.get(_TOGGLE_CONFIG_STR, f"KEY_{_TOGGLE_CONFIG_STR.upper()}")
    _EVDEV_TOGGLE_CODE = getattr(evdev_ecodes, evdev_str, None)
    if _EVDEV_TOGGLE_CODE is None:
        print(f"[ERROR] Invalid toggle key '{_TOGGLE_CONFIG_STR}' for Linux.")
        sys.exit(1)

# ── Input Actions ─────────────────────────────────────────────────────────

def press_key(key: str, duration: float = None) -> None:
    if duration is None:
        duration = random.uniform(config.CFG["timing"]["key_tap_min"], config.CFG["timing"]["key_tap_max"])

    if config.IS_WINDOWS:
        _kb_ctrl.press(_PYNPUT_SEND_MAP[key])
        time.sleep(duration)
        _kb_ctrl.release(_PYNPUT_SEND_MAP[key])
    else:
        evdev_key = EVDEV_KEY_MAP[key]
        _ui.write(EV_KEY, evdev_key, 1); _ui.syn(); time.sleep(duration); _ui.write(EV_KEY, evdev_key, 0); _ui.syn()
    
    time.sleep(random.uniform(0.02, 0.05))

def hold_key(key: str) -> None:
    if config.IS_WINDOWS:
        _kb_ctrl.press(_PYNPUT_SEND_MAP[key])
    else:
        _ui.write(EV_KEY, EVDEV_KEY_MAP[key], 1); _ui.syn()

def release_key(key: str) -> None:
    if config.IS_WINDOWS:
        _kb_ctrl.release(_PYNPUT_SEND_MAP[key])
    else:
        _ui.write(EV_KEY, EVDEV_KEY_MAP[key], 0); _ui.syn()

# ── Hotkey Listener ───────────────────────────────────────────────────────

def hotkey_listener(bot: 'FishingBot'):
    if config.IS_WINDOWS:
        def on_press(key):
            try:
                if not isinstance(_PYNPUT_TOGGLE, str):
                    if key == _PYNPUT_TOGGLE: bot.toggle()
                else:
                    if key.char == _PYNPUT_TOGGLE: bot.toggle()
            except AttributeError:
                pass

        with pynput_keyboard.Listener(on_press=on_press) as listener:
            while bot.running: time.sleep(0.1)
            listener.stop()
            
    else:
        devices = []
        for path in list_devices():
            try:
                dev = InputDevice(path)
                if EV_KEY in dev.capabilities():
                    keys = dev.capabilities()[EV_KEY]
                    if KEY_A in keys and VIRTUAL_KB_NAME not in dev.name:
                        devices.append(dev)
                        print(f"[BOT] Auto-detected keyboard: {dev.name} ({dev.path})")
            except Exception: continue

        if not devices:
            print("[WARN] No physical keyboards detected — hotkey disabled.")
            return

        last_toggle = 0.0
        try:
            while bot.running:
                r, _, _ = select.select(devices, [], [], 0.1)
                for dev in r:
                    for event in dev.read():
                        if event.type == EV_KEY and event.code == _EVDEV_TOGGLE_CODE and event.value == 1:
                            now = time.monotonic()
                            if now - last_toggle > 0.5: last_toggle = now; bot.toggle()
        except Exception as ex: print(f"[WARN] Hotkey error: {ex}")

# ── Failsafe & Cleanup ───────────────────────────────────────────────────

def _emergency_release():
    """Failsafe to ensure keys aren't held if the script crashes."""
    if config.IS_WINDOWS:
        for k in _PYNPUT_SEND_MAP.values():
            try: _kb_ctrl.release(k)
            except: pass
    elif config.IS_LINUX:
        try:
            for key in EVDEV_KEY_MAP.values():
                _ui.write(EV_KEY, key, 0)
            _ui.syn()
        except: pass

import atexit
atexit.register(_emergency_release)

def cleanup_input() -> None:
    if config.IS_LINUX: 
        _ui.close()
    import screen
    screen.cleanup_screen()