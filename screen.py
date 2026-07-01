import re
import math
import subprocess
from typing import Optional, Tuple

import numpy as np

import config

_screen_width: int = config.CFG["screen"]["base_width"]
_screen_height: int = config.CFG["screen"]["base_height"]
_scaled_regions: dict = {}

# Windows mss instance
_sct = None
if config.IS_WINDOWS:
    import mss
    _sct = mss.mss()

def get_screen_resolution() -> Tuple[int, int]:
    manual = config.CFG["screen"].get("manual_resolution", "").strip()
    if manual:
        try:
            w, h = manual.lower().split("x")
            return int(w), int(h)
        except Exception: pass

    if config.IS_WINDOWS and _sct:
        try:
            monitor = _sct.monitors[1] 
            return monitor["width"], monitor["height"]
        except Exception: pass

    if config.IS_LINUX:
        try:
            r = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                for line in r.stdout.split('\n'):
                    if " connected" in line:
                        m = re.search(r'(\d+)x(\d+)', line)
                        if m: return int(m.group(1)), int(m.group(2))
        except Exception: pass
        try:
            r = subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                m = re.search(r'(\d+)x(\d+)', r.stdout)
                if m: return int(m.group(1)), int(m.group(2))
        except Exception: pass

    return config.CFG["screen"]["base_width"], config.CFG["screen"]["base_height"]

def scale_region(region_percent: dict, width: int, height: int) -> dict:
    return {
        "left": math.ceil(region_percent["left"] * width),
        "top": math.ceil(region_percent["top"] * height),
        "width": max(1, math.ceil(region_percent["width"] * width)),
        "height": max(1, math.ceil(region_percent["height"] * height)),
    }

def get_region(name: str) -> dict:
    return _scaled_regions[name]

def init_screen() -> None:
    global _screen_width, _screen_height, _scaled_regions
    _screen_width, _screen_height = get_screen_resolution()
    _scaled_regions = {
        name: scale_region(region, _screen_width, _screen_height) 
        for name, region in config.CFG["regions"].items()
    }
    print(f"[INFO] Screen: {_screen_width}x{_screen_height}")

def grab(region: dict, grayscale: bool = False) -> Optional[np.ndarray]:
    x, y, w, h = region["left"], region["top"], region["width"], region["height"]
    
    if config.IS_WINDOWS and _sct:
        try:
            import cv2
            screenshot = _sct.grab({"left": x, "top": y, "width": w, "height": h})
            img = np.array(screenshot)[:, :, :3]
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if grayscale else img
        except: return None
    else:
        try:
            import cv2
            r = subprocess.run(
                ["grim", "-g", f"{x},{y} {w}x{h}", "-t", "png", "-"], 
                capture_output=True, timeout=0.5
            )
            if r.returncode != 0 or not r.stdout: return None
            flag = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
            return cv2.imdecode(np.frombuffer(r.stdout, dtype=np.uint8), flag)
        except: return None

def cleanup_screen() -> None:
    if _sct:
        try: _sct.close()
        except: pass