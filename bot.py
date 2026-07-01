import time
import random
import threading
from enum import Enum, auto

import config
import input_handler as keys
import vision

class State(Enum):
    IDLE = auto()
    CASTING = auto()
    WAITING_BITE = auto()
    REACTING = auto()
    MINIGAME = auto()
    CATCHING = auto()
    UNKNOWN = auto()

class FishingBot:
    def __init__(self):
        self.running = False
        self.active = False
        self._thread = None
        self._held_key = None
        self._flags = {}
        self._bar_misses = 0

    def toggle(self):
        self.active = not self.active
        print(f"[BOT] {'ON ✓' if self.active else 'OFF ✗'}")
        if not self.active:
            self._release_all()

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True).start()
        print(f"[BOT] Ready. Press '{config.CFG["hotkeys"]["toggle"]}' to toggle. Ctrl+C to quit.")

    def stop(self):
        self.running = False
        self._release_all()
        keys.cleanup_input()

    # ── Key Management ────────────────────────────────────────────────────

    def _release_all(self):
        if self._held_key is not None:
            keys.release_key(self._held_key)
            self._held_key = None

    def _hold(self, key):
        if self._held_key != key:
            self._release_all()
            keys.hold_key(key)
            self._held_key = key

    def _release(self):
        self._release_all()

    # ── State Machine ─────────────────────────────────────────────────────

    def _observe(self, cur: State) -> State:
        """Only check what's relevant for the current state."""
        match cur:
            case State.WAITING_BITE:
                return State.WAITING_BITE if vision.detect_fish_hooked() else State.UNKNOWN
            case State.REACTING | State.MINIGAME:
                if vision.find_bar_positions() is not None:
                    return State.MINIGAME
                if vision.detect_result_screen():
                    return State.CATCHING
                return State.UNKNOWN
            case State.CATCHING:
                return State.CATCHING if vision.detect_result_screen() else State.UNKNOWN
            case _:
                return State.UNKNOWN

    def _next_state(self, cur: State, obs: State, elapsed: float) -> State:
        """Determine if we should transition to a new state."""
        to = config.CFG["timing"]["timeouts"]
        
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
                    if self._bar_misses >= config.CFG["timing"]["bar_miss_limit"]:
                        self._bar_misses = 0
                        print("[BOT] Bar gone — checking for result...")
                        return State.CATCHING
                else:
                    self._bar_misses = 0
                    
            case State.CATCHING:
                # Result screen dismissed and gone -> recast
                if obs != State.CATCHING and self._flags.get("dismissed"):
                    return State.IDLE
                # Waited too long with no result screen (fish escaped)
                if elapsed >= to["CATCHING"]:
                    print("[BOT] Catch timeout — recasting...")
                    return State.IDLE
                    
            case State.UNKNOWN:
                if elapsed >= to["UNKNOWN"]:
                    return State.IDLE
                    
        return cur

    def _act(self, state: State):
        """Execute actions associated with the current state."""
        match state:
            case State.IDLE:
                pass
                
            case State.CASTING:
                if not self._flags.get("cast_done"):
                    time.sleep(random.uniform(0.3, 0.6))
                    keys.press_key(keys.Key.F, random.uniform(0.03, 0.07))
                    self._flags["cast_done"] = True
                    print("[BOT] Cast!")
                    
            case State.REACTING:
                if not self._flags.get("reacted"):
                    time.sleep(random.uniform(
                        config.CFG["timing"]["reaction_delay_min"], 
                        config.CFG["timing"]["reaction_delay_max"]
                    ))
                    keys.press_key(keys.Key.F, random.uniform(0.04, 0.1))
                    self._flags["reacted"] = True
                    print("[BOT] Hooked!")
                    
            case State.MINIGAME:
                result = vision.find_bar_positions()
                if result is None:
                    return
                    
                yellow_norm, green_center_norm, green_half_norm = result
                error = yellow_norm - green_center_norm
                
                dead_zone = green_half_norm * config.CFG["minigame"]["dead_zone_mult"]
                outside_bounds = green_half_norm * config.CFG["minigame"]["outside_bounds_mult"]

                if error > outside_bounds:
                    self._hold(keys.Key.A)
                elif error < -outside_bounds:
                    self._hold(keys.Key.D)
                elif error > dead_zone:
                    self._release()
                    keys.press_key(keys.Key.A, random.uniform(0.04, 0.08))
                elif error < -dead_zone:
                    self._release()
                    keys.press_key(keys.Key.D, random.uniform(0.04, 0.08))
                else:
                    self._release()
                    
            case State.CATCHING:
                self._release()
                if vision.detect_result_screen():
                    now = time.time()
                    last_attempt = self._flags.get("last_dismiss_attempt", 0)
                    
                    # Try pressing ESC every 3 seconds while the screen is visible
                    if now - last_attempt > 3.0:
                        if last_attempt == 0:
                            # First time seeing it -> let the pop-up animation finish
                            time.sleep(random.uniform(1.2, 1.8))
                            
                        keys.press_key(keys.Key.ESC)
                        self._flags["last_dismiss_attempt"] = time.time()
                        self._flags["dismissed"] = True
                        print("[BOT] Attempting to dismiss result screen...")
                        
            case State.UNKNOWN:
                self._release()

    def _on_enter(self, state: State):
        """Reset flags and UI when entering a new state."""
        self._flags = {}
        self._bar_misses = 0
        self._release_all()
        print(f"[BOT] ── {state.name}")

    # ── Main Loop ─────────────────────────────────────────────────────────

    def _loop(self):
        state = State.IDLE
        state_entered = time.time()
        self._on_enter(state)

        while self.running:
            # Pause logic
            if not self.active:
                self._release_all()
                while self.running and not self.active:
                    time.sleep(0.1)
                # Reset cleanly when toggled back on
                state = State.IDLE
                state_entered = time.time()
                self._on_enter(state)
                continue

            # State machine step
            obs = self._observe(state)
            elapsed = time.time() - state_entered
            next_state = self._next_state(state, obs, elapsed)

            if next_state != state:
                state = next_state
                state_entered = time.time()
                self._on_enter(state)

            self._act(state)
            time.sleep(config.CFG["timing"]["poll_interval"])