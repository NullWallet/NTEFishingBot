# NTE Fishing Bot — State-Aware Edition

A cross-platform, highly configurable, and stealthy fishing automation script for NTE. 
Built to be resolution-independent using percentage-based screen regions and designed to bypass basic input-detection methods by simulating hardware-level keystrokes.

## ✨ Features

- **🛡️ Anti-Detection Input:** 
  - *Windows:* Uses `SendInput` via raw **hardware scan codes** (appears as a physical keyboard, not virtual).
  - *Linux:* Uses `evdev` `UInput` with spoofed Vendor/Product IDs (appears as a real Logitech USB keyboard).
- **📐 Resolution Independence:** All screen coordinates are defined as percentages (0.0 to 1.0) in the config file, automatically scaling to any monitor size.
- **⚙️ TOML Configuration:** Generates a clean `config.toml` on first run. Tweak colors, timings, regions, and minigame sensitivity without touching the code.
- **🧠 State Machine:** Uses a context-aware state loop (`IDLE` → `CASTING` → `WAITING` → `REACTING` → `MINIGAME` → `CATCHING`) to minimize unnecessary screen reads and maximize reaction speed.
- **🖥️ Cross-Platform:** Seamless support for both Windows and Linux (X11 & Wayland).

---

## 📋 Prerequisites

1. **Python 3.11+** (Required for built-in TOML support. If using 3.10 or lower, the script will automatically use the `tomli` package).
2. **Template Images:** You must provide your own `bar.png` and `fish_hooked.png`. Place them in an `images/` folder next to the script.

---

## 🚀 Installation

### Windows
```powershell
pip install opencv-python numpy mss pynput
```

### Linux (Arch/Manjaro example)
```bash
# Python packages
pip install opencv-python evdev numpy --break-system-packages

# System packages for screen capture and input reading
sudo pacman -S grim

# Grant your user permission to read raw input devices (REQUIRED)
sudo usermod -aG input $USER
# You MUST log out and log back in for this to take effect.
```
---

## ⚙️ Configuration

On the **first run**, the bot will automatically generate a `config.toml` file in the same directory. 

### Screen Regions (Percentages)
All regions are calculated based on a `0.0` to `1.0` scale of your total screen width and height. For example, if the fishing bar is exactly in the middle of a 1920x1080 screen (`X=960`), the percentage is `960 / 1920 = 0.5`.

```toml
[regions]
bar = { left = 0.3167, top = 0.0620, width = 0.3708, height = 0.0157 }
```

### Forcing Screen Resolution (Wayland/Linux)
Because Wayland restricts global screen size queries, the bot tries to auto-detect via `xrandr` or `wlr-randr`. If it fails, it defaults to 1920x1080. You can force it in the config:
```toml
[screen]
manual_resolution = "2560x1440" # Leave empty "" for auto-detect
```

### Minigame Tuning
Adjust how aggressively the bot tracks the fish inside the green bar:
```toml
[minigame]
dead_zone_mult = 0.10      # 10% of bar half-width where it does nothing
outside_bounds_mult = 0.95 # 95% of bar half-width where it holds the key to sprint
```

---

## 🎮 Usage

1. Ensure your game is running and visible on screen.
2. **DO NOT run the script as `sudo` on Linux** (it will break `grim` screen capture).
3. Run the bot:
   ```bash
   python bot.py
   ```
4. **Controls:**
   - Press `` ` `` (grave/tilde key) to **Toggle ON/OFF**.
   - Press `Ctrl+C` in the terminal to **Quit**.

---

## 🔧 How It Works (Linux Input)
To prevent the game from seeing a "Virtual Keyboard" flag, the bot creates a phantom hardware device at the kernel level using `evdev`. 
* It registers a device named `"Logitech USB Keyboard"` with legitimate Logitech Vendor (`0x046D`) and Product (`0xC31C`) IDs.
* To listen for your toggle hotkey (`` ` ``), the bot scans `/dev/input/` for physical keyboards that have letter keys (`KEY_A`) and **explicitly excludes** its own virtual device to prevent an infinite feedback loop.

---

## 🐛 Troubleshooting

* **`[WARN] No keyboard found — hotkey disabled.` (Linux)**
  * You forgot to add your user to the `input` group, or haven't logged out/in yet. Run `id` in your terminal and check if `input` is listed.
* **`FileNotFoundError: bar.png not found`**
  * Make sure you have an `images/` folder next to `bot.py` containing your cropped template images.
* **Bot doesn't capture the screen properly on Linux**
  * If you are on Wayland (GNOME/Sway/Hyprland), ensure `grim` is installed. If the regions are completely off, set `manual_resolution` in `config.toml`.
* **Bot presses keys but the game doesn't react (Windows)**
  * Ensure the game window is in the foreground. Some games require running the terminal as Administrator to accept `SendInput` commands.
```