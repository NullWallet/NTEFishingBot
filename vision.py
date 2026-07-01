import math
from typing import Optional, Tuple

import numpy as np
import cv2

import config
import screen

DEBUG_RESULT = config.CFG.get("debug", {}).get("result_screen", False)

# Load templates
_TEMPLATE_PATH = f"{config._SCRIPT_DIR}/{config.CFG['paths']['bar_image']}"
_RESULT_TEMPLATE = cv2.imread(_TEMPLATE_PATH, cv2.IMREAD_GRAYSCALE)
if _RESULT_TEMPLATE is None:
    raise FileNotFoundError(f"{config.CFG['paths']['bar_image']} not found at {_TEMPLATE_PATH}")

# _HOOKED_TEMPLATE is kept for potential future use, though currently unused by logic
# _HOOKED_TEMPLATE_PATH = f"{config._SCRIPT_DIR}/{config.CFG['paths']['hooked_image']}"

# Pre-convert color arrays to numpy
COLORS = {
    "blue": {"low": np.array(config.CFG["colors"]["blue"]["low"]), "high": np.array(config.CFG["colors"]["blue"]["high"])},
    "green": {"low": np.array(config.CFG["colors"]["green"]["low"]), "high": np.array(config.CFG["colors"]["green"]["high"])},
    "yellow": {"low": np.array(config.CFG["colors"]["yellow"]["low"]), "high": np.array(config.CFG["colors"]["yellow"]["high"])},
    "hooked_blue": {"low": np.array(config.CFG["colors"]["hooked_blue"]["low"]), "high": np.array(config.CFG["colors"]["hooked_blue"]["high"])}
}

def detect_fish_hooked() -> bool:
    img = screen.grab(screen.get_region("hooked_search"))
    if img is None: return False
    h, w = img.shape[:2]; cx, cy = w // 2, h // 2
    scale_factor = min(w, h) / 100.0 
    R_INNER = math.ceil(config.CFG["detection"]["hooked_r_inner"] * scale_factor)
    R_OUTER = math.ceil(config.CFG["detection"]["hooked_r_outer"] * scale_factor)

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

    scaled_arc_min = int(config.CFG["detection"]["hooked_arc_min_size"] * scale_factor * scale_factor)
    scaled_ring_min = int(config.CFG["detection"]["hooked_ring_min_pixels"] * scale_factor * scale_factor)

    return blue_in_ring >= scaled_ring_min and ratio >= 2.0 and largest_arc >= scaled_arc_min

def detect_result_screen() -> bool:
    region = screen.get_region("result_search")
    img = screen.grab(region, grayscale=True)
    
    if img is None:
        if DEBUG_RESULT: print("[DEBUG] Result Screen: Failed to grab region.")
        return False
        
    th, tw = _RESULT_TEMPLATE.shape[:2]
    ih, iw = img.shape[:2]
    
    if ih < th or iw < tw:
        if DEBUG_RESULT: 
            print(f"[DEBUG] Result Screen: Region too small! Grabbed: {iw}x{ih}, Template: {tw}x{th}")
        return False
        
    result = cv2.matchTemplate(img, _RESULT_TEMPLATE, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    
    threshold = config.CFG["detection"]["result_confidence"]
    detected = float(max_val) >= threshold
    
    if DEBUG_RESULT:
        print(f"[DEBUG] Result Screen: Match={max_val:.4f} at {max_loc} | Threshold={threshold} | Detected={detected}")
        
    return detected

def find_bar_positions() -> Optional[Tuple[float, float, float]]:
    region = screen.get_region("bar")
    img = screen.grab(region)
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