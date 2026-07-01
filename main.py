#!/usr/bin/env python3
import time
import threading

import config
import screen
import input_handler
from bot import FishingBot

if __name__ == "__main__":
    print("=" * 60)
    print("  NTE Fishing Bot  —  State-Aware Edition")
    print(f"  Platform: {'Windows' if config.IS_WINDOWS else 'Linux'}")
    print("=" * 60)

    # Initialize screen resolution and cache scaled regions
    screen.init_screen()

    if config.IS_WINDOWS:
        print("[INFO] Using SendInput with hardware scan codes")

    bot = FishingBot()
    
    # Start hotkey listener in a background thread
    threading.Thread(target=input_handler.hotkey_listener, args=(bot,), daemon=True).start()
    
    # Start the bot state machine
    bot.start()

    try:
        # Keep main thread alive to listen for Ctrl+C
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[BOT] Shutting down...")
        bot.stop()