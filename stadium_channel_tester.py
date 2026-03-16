#!/usr/bin/env python3
"""
Stadium Pro III 1200W RGBW – Channel Discovery Tool
====================================================
Walks you through every DMX channel at multiple intensity levels so you can
figure out what each channel does on a fixture with no documentation.

Key features:
  - Guided walk-through: steps each channel through 5 levels (0→64→128→192→255)
  - Hold / pin channels: keep some channels lit while testing others
    (critical for seeing dimmers, strobes, and mode channels work)
  - Live status bar: always shows what every channel is set to
  - Smart combos: tests dimmer-over-colour, strobe-with-colour, etc.
  - Session save/load: pick up where you left off

Usage:
    python3 stadium_channel_tester.py
    python3 stadium_channel_tester.py --host 192.168.1.50
    python3 stadium_channel_tester.py --channels 16

Quick-start:
    1. Start app.py on the Pi / server
    2. Run this script
    3. Choose (w) walk-through to step through each channel
    4. Pin channels you identify as colours, then re-test unknowns
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("requests is required:  pip install requests")


# ── ANSI helpers ──────────────────────────────────────────────────────────────

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
WHITE   = "\033[97m"
BG_RED  = "\033[41m"
BG_GRN  = "\033[42m"
BG_BLU  = "\033[44m"
BG_WHT  = "\033[47m"
BG_DARK = "\033[40m"

def c(text, *codes):
    return "".join(codes) + str(text) + RESET

def header(txt):
    w = max(len(txt) + 4, 60)
    print(c(f"\n{'━'*w}", CYAN))
    print(c(f"  {txt}", BOLD, CYAN))
    print(c(f"{'━'*w}", CYAN))

def ok(txt):   print(c(f"  ✓ {txt}", GREEN))
def warn(txt): print(c(f"  ⚠ {txt}", YELLOW))
def err(txt):  print(c(f"  ✗ {txt}", RED))
def info(txt): print(c(f"  · {txt}", DIM))
def hint(txt): print(c(f"    {txt}", DIM))


# ── HTTP helpers ──────────────────────────────────────────────────────────────

class DMXConnection:
    """Wraps all communication with the Flask DMX server."""

    def __init__(self, base_url):
        self.base_url = base_url
        self.http = requests.Session()
        self.http.headers.update({"Content-Type": "application/json"})

    def health(self):
        try:
            r = self.http.get(f"{self.base_url}/api/health", timeout=5)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def set_channel(self, channel, value):
        """Set ONE channel without touching others."""
        try:
            self.http.post(
                f"{self.base_url}/api/channel",
                json={"channel": channel, "value": value},
                timeout=5,
            ).raise_for_status()
            return True
        except Exception as exc:
            err(f"set_channel failed: {exc}")
            return False

    def set_channels(self, channel_dict):
        """Set multiple channels without touching others."""
        if not channel_dict:
            return True
        try:
            self.http.post(
                f"{self.base_url}/api/channels",
                json={"channels": {str(k): v for k, v in channel_dict.items()}},
                timeout=5,
            ).raise_for_status()
            return True
        except Exception as exc:
            err(f"set_channels failed: {exc}")
            return False

    def isolate_channel(self, channel, value):
        """Set ONE channel to value, zero ALL others."""
        try:
            self.http.post(
                f"{self.base_url}/api/test-channel",
                json={"channel": channel, "value": value},
                timeout=5,
            ).raise_for_status()
            return True
        except Exception as exc:
            err(f"isolate_channel failed: {exc}")
            return False

    def blackout(self):
        try:
            self.http.post(f"{self.base_url}/api/blackout", timeout=5).raise_for_status()
            return True
        except Exception as exc:
            err(f"blackout failed: {exc}")
            return False

    def apply_labels(self, labels):
        try:
            self.http.post(
                f"{self.base_url}/api/channel-labels",
                json={"labels": {str(k): v for k, v in labels.items()}},
                timeout=5,
            ).raise_for_status()
            return True
        except Exception as exc:
            err(f"apply_labels failed: {exc}")
            return False

    def close(self):
        self.http.close()


# ── Channel state tracker ────────────────────────────────────────────────────

class ChannelState:
    """
    Tracks local knowledge of channel values and pinned channels.
    Pinned channels stay at their value when you blackout or isolate.
    """

    def __init__(self, start_ch, num_channels, dmx):
        self.start = start_ch
        self.count = num_channels
        self.end = start_ch + num_channels - 1
        self.dmx = dmx
        self.values = {}      # {ch: current_value}
        self.pinned = {}      # {ch: pinned_value}

    @property
    def channels(self):
        return range(self.start, self.end + 1)

    def set(self, channel, value):
        """Set a channel and send to server."""
        value = max(0, min(255, value))
        self.values[channel] = value
        self.dmx.set_channel(channel, value)

    def set_multi(self, ch_dict):
        """Set multiple channels and send to server."""
        clamped = {ch: max(0, min(255, v)) for ch, v in ch_dict.items()}
        self.values.update(clamped)
        self.dmx.set_channels(clamped)

    def pin(self, channel, value=None):
        """Pin a channel at its current (or given) value."""
        if value is not None:
            self.pinned[channel] = max(0, min(255, value))
        elif channel in self.values:
            self.pinned[channel] = self.values[channel]
        else:
            self.pinned[channel] = 255

    def unpin(self, channel):
        self.pinned.pop(channel, None)

    def unpin_all(self):
        self.pinned.clear()

    def blackout(self):
        """Zero everything, then restore pinned channels."""
        self.dmx.blackout()
        self.values = {ch: 0 for ch in self.channels}
        if self.pinned:
            self.values.update(self.pinned)
            self.dmx.set_channels(self.pinned)

    def restore_pins(self):
        """Re-send just the pinned values (after a blackout/isolate)."""
        if self.pinned:
            self.dmx.set_channels(self.pinned)
            self.values.update(self.pinned)

    def get(self, channel):
        return self.values.get(channel, 0)

    def isolate_with_pins(self, channel, value):
        """
        Set one channel to value, zero all non-pinned channels.
        This is the key improvement: you can see dimmers/strobes work
        because the pinned colour channels stay lit.
        """
        ch_dict = {}
        for ch in self.channels:
            if ch == channel:
                ch_dict[ch] = value
            elif ch in self.pinned:
                ch_dict[ch] = self.pinned[ch]
            else:
                ch_dict[ch] = 0
        self.values.update(ch_dict)
        self.dmx.set_channels(ch_dict)


# ── Display helpers ───────────────────────────────────────────────────────────

LABEL_COLORS = {
    "red": RED, "green": GREEN, "blue": BLUE, "white": WHITE,
    "dimmer": YELLOW, "strobe": MAGENTA, "mode": MAGENTA,
    "speed": MAGENTA, "amber": YELLOW, "uv": MAGENTA,
}

def bar_char(value):
    """Return a block character representing brightness level."""
    if value == 0:   return "·"
    if value < 64:   return "░"
    if value < 128:  return "▒"
    if value < 192:  return "▓"
    return "█"

def print_status(state, session, current_ch=None):
    """Print a compact live view of all channels."""
    print()
    chs = session.get("channels", {})
    line1 = "  "   # channel numbers
    line2 = "  "   # value bars
    line3 = "  "   # labels

    for ch in state.channels:
        is_current = (ch == current_ch)
        is_pinned = (ch in state.pinned)
        val = state.get(ch)
        ch_info = chs.get(str(ch), {})
        label = ch_info.get("label", "")
        short_label = label[:5] if label else ""

        # Channel number
        if is_current:
            line1 += c(f"{ch:>5}", BOLD, YELLOW)
        elif is_pinned:
            line1 += c(f"{ch:>5}", CYAN)
        else:
            line1 += c(f"{ch:>5}", DIM)

        # Value bar
        vstr = f"{val:>3}" if val > 0 else "  ·"
        if is_current:
            line2 += c(f" {vstr} ", BOLD, WHITE)
        elif is_pinned:
            line2 += c(f" {vstr} ", CYAN)
        elif val > 0:
            line2 += c(f" {vstr} ", GREEN)
        else:
            line2 += c(f" {vstr} ", DIM)

        # Label
        lbl_color = DIM
        for keyword, col in LABEL_COLORS.items():
            if keyword in label.lower():
                lbl_color = col
                break
        if is_pinned:
            short_label = (short_label or "PIN")
            line3 += c(f"{short_label:>5}", CYAN)
        elif short_label:
            line3 += c(f"{short_label:>5}", lbl_color)
        else:
            line3 += "     "

    print(line1)
    print(line2)
    print(line3)

    # Legend
    parts = []
    if current_ch is not None:
        parts.append(c(f"◆ ch{current_ch}", YELLOW))
    if state.pinned:
        pin_str = ",".join(str(ch) for ch in sorted(state.pinned))
        parts.append(c(f"📌 pinned: {pin_str}", CYAN))
    if parts:
        print("  " + "  ".join(parts))


def print_bar(value, width=30):
    """Print an ASCII brightness bar."""
    filled = round(value / 255 * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = round(value / 255 * 100)
    return f"[{bar}] {value:>3} ({pct:>3}%)"


# ── Label shortcuts ───────────────────────────────────────────────────────────

LABEL_SHORTCUTS = {
    "r": "Red", "g": "Green", "b": "Blue", "w": "White",
    "a": "Amber", "uv": "UV", "s": "Strobe", "d": "Dimmer",
    "m": "Mode", "p": "Program", "sp": "Speed", "ma": "Master",
    "ct": "Color Temp", "cm": "Color Macro",
    "n": "Nothing", "x": "Nothing", "?": "Unknown",
}

def resolve_label(raw):
    """Turn user input into a clean label."""
    raw = raw.strip()
    if not raw:
        return ""
    low = raw.lower()
    if low in LABEL_SHORTCUTS:
        return LABEL_SHORTCUTS[low]
    return raw.title()


# ── Session management ────────────────────────────────────────────────────────

def new_session(start_ch, num_channels):
    return {
        "fixture": "Stadium Pro III 1200W RGBW",
        "created": datetime.now().isoformat(timespec="seconds"),
        "start_channel": start_ch,
        "num_channels": num_channels,
        "channels": {},
    }

def save_session(sess, path):
    with open(path, "w") as f:
        json.dump(sess, f, indent=2)
    ok(f"Saved to {path}")

def load_session(path):
    with open(path) as f:
        return json.load(f)


# ── Walk-through mode ─────────────────────────────────────────────────────────

WALK_LEVELS = [0, 64, 128, 192, 255]

def walk_through(state, session, start_from=None):
    """
    THE key feature: step through each channel, test at multiple levels,
    and record what you see.  Pinned channels stay active so you can
    see dimmers/strobes/modes work.
    """
    header("Guided Walk-Through")
    print()
    if not state.pinned:
        print(c("  TIP: If no channels produce visible light on their own, you may", YELLOW))
        print(c("  need a dimmer/master channel active. Try the walk-through first.", YELLOW))
        print(c("  If nothing lights up, quit (q), pin channel 1 at 255, and retry.", YELLOW))
    else:
        print(c(f"  Pinned channels will stay active: {dict(state.pinned)}", CYAN))
    print()
    print(c("  For each channel you'll see it at 5 levels: 0, 64, 128, 192, 255", DIM))
    print(c("  Then type what you observed.", DIM))
    print()
    print(c("  Label shortcuts:", DIM))
    print(c("    r=Red  g=Green  b=Blue  w=White  d=Dimmer  s=Strobe", DIM))
    print(c("    m=Mode  sp=Speed  a=Amber  uv=UV  n/x=Nothing  ?=Unknown", DIM))
    print()
    print(c("  Navigation:", DIM))
    print(c("    Enter     = skip / no label        p = pin this channel", DIM))
    print(c("    back      = go to previous channel", DIM))
    print(c("    hold NNN  = hold this ch at NNN while continuing", DIM))
    print(c("    q         = stop walk-through", DIM))
    print()

    ch_list = list(state.channels)
    if start_from is not None and start_from in ch_list:
        idx = ch_list.index(start_from)
    else:
        idx = 0

    while idx < len(ch_list):
        ch = ch_list[idx]
        existing = session["channels"].get(str(ch), {}).get("label", "")

        # Show status bar
        print_status(state, session, current_ch=ch)
        print()

        # Step through the levels
        print(c(f"  ── Channel {ch} ──", BOLD, WHITE))
        if existing:
            print(c(f"     Previous label: {existing}", YELLOW))
        print()

        for level in WALK_LEVELS:
            state.isolate_with_pins(ch, level)
            bar = print_bar(level)
            pct_label = f"{round(level/255*100)}%"
            print(c(f"    ch{ch} = {level:>3}  {bar}", WHITE if level > 0 else DIM))
            time.sleep(0.6)

        # Hold at 255 for observation
        state.isolate_with_pins(ch, 255)
        print()

        # Ask for label
        prompt_str = c(f"  ch {ch}", BOLD, YELLOW)
        if existing:
            prompt_str += c(f" [{existing}]", DIM)
        prompt_str += c(" label: ", CYAN)

        try:
            raw = input(prompt_str).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        # Handle special commands
        low = raw.lower()
        if low == "q" or low == "quit":
            break
        elif low == "back" or low == "b":
            if idx > 0:
                idx -= 1
            else:
                warn("Already at first channel.")
            continue
        elif low.startswith("pin") or low == "p":
            # Pin at current value (255 since we're holding there)
            parts = low.split()
            pin_val = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 255
            state.pin(ch, pin_val)
            ok(f"Pinned ch{ch} at {pin_val}")
            # Still ask for a label
            try:
                raw2 = input(c(f"  ch {ch} label: ", CYAN)).strip()
            except (KeyboardInterrupt, EOFError):
                raw2 = ""
            label = resolve_label(raw2)
            if label:
                session["channels"].setdefault(str(ch), {})["label"] = label
                ok(f"ch {ch} = {label}")
            idx += 1
            continue
        elif low.startswith("hold"):
            parts = low.split()
            hold_val = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 255
            state.pin(ch, hold_val)
            ok(f"Pinned ch{ch} at {hold_val} (will stay on)")
            idx += 1
            continue
        elif low.startswith("unpin"):
            parts = low.split()
            if len(parts) > 1 and parts[1].isdigit():
                state.unpin(int(parts[1]))
                ok(f"Unpinned ch{parts[1]}")
            else:
                state.unpin(ch)
                ok(f"Unpinned ch{ch}")
            continue

        # Normal label entry
        label = resolve_label(raw)
        if label and label.lower() != "nothing":
            session["channels"].setdefault(str(ch), {})["label"] = label
            ok(f"ch {ch} = {label}")
        elif raw:
            session["channels"].setdefault(str(ch), {})["label"] = label
            info(f"ch {ch} = {label}")

        idx += 1

    # Clean up
    state.blackout()
    ok("Walk-through done")
    print()


# ── Sweep with pins ───────────────────────────────────────────────────────────

def sweep_channel(state, channel, step=5, delay=0.03, hold=1.5):
    """Ramp 0 -> 255 -> 0 while keeping pinned channels active."""
    print(c(f"  Sweeping ch {channel}  ▲ 0 → 255 ...", YELLOW))
    for v in range(0, 256, step):
        state.isolate_with_pins(channel, v)
        time.sleep(delay)
    print(c(f"  Peak (255) – holding {hold}s ...", YELLOW))
    time.sleep(hold)
    print(c(f"  Sweeping ch {channel}  ▼ 255 → 0 ...", YELLOW))
    for v in range(255, -1, -step):
        state.isolate_with_pins(channel, v)
        time.sleep(delay)
    state.isolate_with_pins(channel, 0)
    ok("Sweep done")


# ── Multi-level hold test ────────────────────────────────────────────────────

def level_test(state, channel):
    """
    Step through a channel at specific values, pausing for observation.
    Pinned channels stay active.
    """
    levels = [0, 1, 16, 32, 64, 96, 128, 160, 192, 224, 255]
    print()
    print(c(f"  Level test on ch {channel}  (Enter = next, q = stop)", BOLD))
    if state.pinned:
        print(c(f"  Pinned channels active: {dict(state.pinned)}", CYAN))
    print()

    for val in levels:
        state.isolate_with_pins(channel, val)
        bar = print_bar(val)
        try:
            note = input(c(f"    ch{channel} = {val:>3}  {bar}  note: ", CYAN)).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if note.lower() == "q":
            break
        if note:
            ch_str = str(channel)
            ch_data = state.dmx  # not used for notes
            # Could store notes but keep it simple

    state.isolate_with_pins(channel, 0)
    ok("Level test done")


# ── Dimmer finder ─────────────────────────────────────────────────────────────

def find_dimmer(state, session):
    """
    Systematically test if any channel acts as a master dimmer.
    Sets ALL channels in range to 255, then dims one channel at a time
    to see if it controls overall brightness.
    """
    header("Dimmer Finder")
    print(c("  Sets all channels to 255, then dims each one individually.", DIM))
    print(c("  Watch for the channel that fades the ENTIRE light.", DIM))
    print(c("  Press Enter after each test.  Type 'y' if it's the dimmer.", DIM))
    print()

    # First, all channels on
    all_on = {ch: 255 for ch in state.channels}
    state.set_multi(all_on)
    try:
        input(c("  All channels at 255.  Is the light fully on? [Enter to continue] ", YELLOW))
    except (KeyboardInterrupt, EOFError):
        state.blackout()
        return

    for ch in state.channels:
        # Dim just this one channel to 0, rest stay at 255
        state.set_multi(all_on)
        time.sleep(0.3)
        state.set(ch, 0)
        try:
            resp = input(c(f"  ch{ch} → 0 (rest at 255). Did entire light dim/go off? [y/N/q]: ", CYAN)).strip().lower()
        except (KeyboardInterrupt, EOFError):
            break
        if resp == "q":
            break
        if resp == "y":
            session["channels"].setdefault(str(ch), {})["label"] = "Dimmer"
            state.pin(ch, 255)
            ok(f"ch{ch} = Dimmer!  Pinned at 255.")
            break

    state.blackout()
    ok("Dimmer finder done")


# ── Colour identifier ────────────────────────────────────────────────────────

def identify_colours(state, session):
    """
    If a dimmer is pinned, test each unpinned channel one at a time.
    Much easier to see R/G/B/W when the dimmer is already active.
    """
    header("Colour Identifier")
    if not state.pinned:
        print(c("  TIP: Pin the dimmer channel first (if there is one).", YELLOW))
        print(c("  Use 'pin <ch> <value>' from the main menu.", YELLOW))
        print()

    print(c("  Tests each non-pinned channel one at a time at full brightness.", DIM))
    print(c("  Pinned channels stay active so dimmer/master keeps working.", DIM))
    print(c("  Type what colour you see:  r g b w a uv  or any text.", DIM))
    print()

    for ch in state.channels:
        if ch in state.pinned:
            continue

        state.isolate_with_pins(ch, 255)
        existing = session["channels"].get(str(ch), {}).get("label", "")
        prompt_str = c(f"  ch{ch}", BOLD, YELLOW)
        if existing:
            prompt_str += c(f" [{existing}]", DIM)
        prompt_str += c(" = what colour? ", CYAN)

        try:
            raw = input(prompt_str).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if raw.lower() in ("q", "quit"):
            break

        label = resolve_label(raw)
        if label:
            session["channels"].setdefault(str(ch), {})["label"] = label
            ok(f"ch{ch} = {label}")

    state.blackout()
    ok("Colour identification done")


# ── Combo test ────────────────────────────────────────────────────────────────

def combo_test(state, session):
    """
    Based on discovered labels, run meaningful combination tests
    to verify the mapping makes sense.
    """
    header("Combo Verification Test")

    # Build lookups from session labels
    label_to_ch = {}
    for ch_str, info in session.get("channels", {}).items():
        label = info.get("label", "").lower()
        if label:
            label_to_ch[label] = int(ch_str)

    found = {k: v for k, v in label_to_ch.items()
             if k in ("red", "green", "blue", "white", "dimmer", "strobe", "amber", "uv")}

    if not found:
        warn("No labelled channels found yet. Run walk-through or colour identifier first.")
        return

    print(c(f"  Known channels: {found}", DIM))
    print(c("  Press Enter after each combo to advance. Type 'q' to stop.", DIM))
    print()

    dimmer_ch = found.get("dimmer")

    combos = []
    # Build combos based on what we know
    if "red" in found:
        combos.append(("Red only", {found["red"]: 255}))
    if "green" in found:
        combos.append(("Green only", {found["green"]: 255}))
    if "blue" in found:
        combos.append(("Blue only", {found["blue"]: 255}))
    if "white" in found:
        combos.append(("White only", {found["white"]: 255}))
    if "red" in found and "green" in found:
        combos.append(("Red + Green (= Yellow?)", {found["red"]: 255, found["green"]: 255}))
    if "red" in found and "blue" in found:
        combos.append(("Red + Blue (= Magenta?)", {found["red"]: 255, found["blue"]: 255}))
    if "green" in found and "blue" in found:
        combos.append(("Green + Blue (= Cyan?)", {found["green"]: 255, found["blue"]: 255}))
    if "red" in found and "green" in found and "blue" in found:
        combos.append(("RGB full (= White?)", {found["red"]: 255, found["green"]: 255, found["blue"]: 255}))
    if all(k in found for k in ("red", "green", "blue", "white")):
        combos.append(("RGBW all full", {found["red"]: 255, found["green"]: 255, found["blue"]: 255, found["white"]: 255}))
    if "strobe" in found and "red" in found:
        combos.append(("Red + Strobe test", {found["red"]: 255, found["strobe"]: 128}))

    if not combos:
        warn("Not enough labelled channels for meaningful combos.")
        return

    for name, ch_dict in combos:
        state.blackout()
        time.sleep(0.2)
        # Add dimmer if known
        if dimmer_ch:
            ch_dict[dimmer_ch] = 255
        state.set_multi(ch_dict)

        vals_str = "  ".join(f"ch{ch}={v}" for ch, v in sorted(ch_dict.items()))
        try:
            resp = input(c(f"  {name:<30}  ({vals_str}) → ", CYAN)).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if resp.lower() == "q":
            break

    state.blackout()
    ok("Combo test done")


# ── Print session summary ────────────────────────────────────────────────────

def print_session(session, state):
    header("Discovery Session")
    print(f"  Fixture  : {session['fixture']}")
    print(f"  Created  : {session['created']}")
    print(f"  Channels : {session['start_channel']} – {session['start_channel'] + session['num_channels'] - 1}")
    print()

    chs = session.get("channels", {})
    if not chs:
        warn("No channels discovered yet.")
        return

    print(c(f"  {'Ch':>4}  {'Label':<20}  {'Pinned':<8}  Notes", BOLD))
    print("  " + "─" * 55)
    for ch in range(session["start_channel"], session["start_channel"] + session["num_channels"]):
        ch_str = str(ch)
        if ch_str not in chs:
            continue
        ch_info = chs[ch_str]
        label = ch_info.get("label", "")
        notes = ch_info.get("notes", "")
        pinned = "📌" if ch in state.pinned else ""

        # Colour the label
        lbl_color = ""
        for keyword, col in LABEL_COLORS.items():
            if keyword in label.lower():
                lbl_color = col
                break
        label_str = c(f"{label:<20}", lbl_color) if lbl_color else f"{label:<20}"
        print(f"  {ch:>4}  {label_str}  {pinned:<8}  {notes}")

    print()


# ── Main menu ─────────────────────────────────────────────────────────────────

MENU_TEXT = """
{bold}Main Commands:{reset}
  {cy}w{r}   Guided walk-through     Steps each channel through 5 brightness levels
  {cy}f{r}   Find dimmer              Tests which channel is the master dimmer
  {cy}i{r}   Identify colours         One-by-one colour test (pin dimmer first!)
  {cy}t{r}   Combo test               Verify discovered mapping with colour combos

{bold}Channel Control:{reset}
  {cy}s{r}   Sweep current channel    Ramp 0→255→0 with pins active
  {cy}v{r}   Set value                e.g. 'v 128' or 'v' for prompt
  {cy}l{r}   Level test               Step through 11 levels with notes
  {cy}0{r}   Blackout                 Zero all (restores pinned channels)

{bold}Navigation:{reset}
  {cy}n{r}   Next channel             {cy}p{r}   Previous channel
  {cy}g{r}   Go to channel #          e.g. 'g 5'

{bold}Pin/Hold:{reset}
  {cy}pin{r}    Pin current channel    e.g. 'pin' or 'pin 128' or 'pin 3 255'
  {cy}unpin{r}  Unpin channel          e.g. 'unpin' or 'unpin 3'  or 'unpin all'
  {cy}pins{r}   Show pinned channels

{bold}Session:{reset}
  {cy}d{r}   Show discovered map      {cy}S{r}   Save session to file
  {cy}L{r}   Load session from file   {cy}A{r}   Apply labels to DMX server
  {cy}?{r}   Show this menu           {cy}q{r}   Quit
""".format(bold=BOLD, reset=RESET, cy=CYAN, r=RESET)


def main_loop(args, dmx, state, session):
    current_ch = args.start_ch
    session_file = args.session_file

    header("Stadium Pro III 1200W RGBW – Channel Discovery")
    print(c(f"  Server   : {dmx.base_url}", DIM))
    print(c(f"  Channels : {args.start_ch} – {args.start_ch + args.channels - 1}  ({args.channels} total)", DIM))
    print()
    print(c("  RECOMMENDED: Start with 'w' (walk-through) to discover all channels.", GREEN))
    print(c("  If nothing lights up, try 'f' (find dimmer) first.", GREEN))
    print(MENU_TEXT)

    while True:
        # Show compact status
        print_status(state, session, current_ch)

        ch_info = session["channels"].get(str(current_ch), {})
        current_label = ch_info.get("label", "")
        tag = c(f" [{current_label}]", YELLOW) if current_label else ""

        try:
            cmd = input(c(f"\n  ch{current_ch}{tag} > ", BOLD, CYAN)).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not cmd:
            # Toggle current channel on at 255 with pins
            state.isolate_with_pins(current_ch, 255)
            info(f"ch{current_ch} = 255 (+ pins)")
            continue

        low = cmd.lower()
        parts = low.split()
        cmd0 = parts[0]

        # ── Walk-through ──────────────────────────────────────────
        if cmd0 == "w":
            start_from = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else current_ch
            walk_through(state, session, start_from=start_from)

        # ── Find dimmer ───────────────────────────────────────────
        elif cmd0 == "f":
            find_dimmer(state, session)

        # ── Identify colours ──────────────────────────────────────
        elif cmd0 == "i":
            identify_colours(state, session)

        # ── Combo test ────────────────────────────────────────────
        elif cmd0 == "t":
            combo_test(state, session)

        # ── Navigation ────────────────────────────────────────────
        elif cmd0 == "n":
            if current_ch < state.end:
                current_ch += 1
                state.isolate_with_pins(current_ch, 255)
            else:
                warn("At last channel.")

        elif cmd0 == "p" and len(parts) == 1:
            if current_ch > state.start:
                current_ch -= 1
                state.isolate_with_pins(current_ch, 255)
            else:
                warn("At first channel.")

        elif cmd0 == "g":
            try:
                ch = int(parts[1]) if len(parts) > 1 else int(input(c("    Channel #: ", CYAN)))
                if state.start <= ch <= state.end:
                    current_ch = ch
                    state.isolate_with_pins(current_ch, 255)
                    info(f"Jumped to ch{ch}")
                else:
                    warn(f"ch{ch} outside range {state.start}–{state.end}")
            except (ValueError, EOFError):
                warn("Invalid channel number.")

        # ── Sweep ─────────────────────────────────────────────────
        elif cmd0 == "s":
            sweep_channel(state, current_ch)

        # ── Set value ─────────────────────────────────────────────
        elif cmd0 == "v":
            try:
                val = int(parts[1]) if len(parts) > 1 else int(input(c("    Value (0-255): ", CYAN)))
                val = max(0, min(255, val))
                state.isolate_with_pins(current_ch, val)
                info(f"ch{current_ch} = {val}")
            except (ValueError, EOFError):
                warn("Invalid value.")

        # ── Level test ────────────────────────────────────────────
        elif cmd0 == "l":
            level_test(state, current_ch)

        # ── Blackout ──────────────────────────────────────────────
        elif cmd0 in ("0", "b", "blackout"):
            state.blackout()
            ok("Blackout (pins restored)")

        # ── Pin ───────────────────────────────────────────────────
        elif cmd0 == "pin":
            if len(parts) >= 3 and parts[1].isdigit():
                # pin <ch> <val>
                pin_ch = int(parts[1])
                pin_val = int(parts[2]) if parts[2].isdigit() else 255
                state.pin(pin_ch, pin_val)
                state.restore_pins()
                ok(f"Pinned ch{pin_ch} at {pin_val}")
            elif len(parts) == 2 and parts[1].isdigit():
                # pin <val>  (pin current channel at val)
                state.pin(current_ch, int(parts[1]))
                state.restore_pins()
                ok(f"Pinned ch{current_ch} at {parts[1]}")
            else:
                # pin  (pin current channel at 255)
                state.pin(current_ch, 255)
                state.restore_pins()
                ok(f"Pinned ch{current_ch} at 255")

        elif cmd0 == "unpin":
            if len(parts) >= 2:
                if parts[1] == "all":
                    state.unpin_all()
                    ok("All pins cleared")
                elif parts[1].isdigit():
                    state.unpin(int(parts[1]))
                    ok(f"Unpinned ch{parts[1]}")
            else:
                state.unpin(current_ch)
                ok(f"Unpinned ch{current_ch}")

        elif cmd0 == "pins":
            if state.pinned:
                print(c(f"  Pinned: {dict(state.pinned)}", CYAN))
            else:
                info("No channels pinned.")

        # ── Session ───────────────────────────────────────────────
        elif cmd0 == "d":
            print_session(session, state)

        elif cmd == "S":
            path = input(c(f"    Save to [{session_file}]: ", CYAN)).strip() or session_file
            save_session(session, path)
            session_file = path

        elif cmd == "L":
            path = input(c(f"    Load from [{session_file}]: ", CYAN)).strip() or session_file
            if os.path.exists(path):
                session.update(load_session(path))
                ok(f"Loaded from {path}")
            else:
                err(f"File not found: {path}")

        elif cmd == "A":
            labels = {}
            for ch_str, ch_info in session.get("channels", {}).items():
                label = ch_info.get("label", "").strip()
                if label and label.lower() not in ("nothing", "unknown"):
                    labels[int(ch_str)] = label
            if not labels:
                warn("No meaningful labels to apply.")
            else:
                print(c(f"  Applying {len(labels)} label(s): {labels}", YELLOW))
                if dmx.apply_labels(labels):
                    ok("Labels applied to server!")
                else:
                    err("Failed – check server connection.")

        # ── Help ──────────────────────────────────────────────────
        elif cmd0 == "?":
            print(MENU_TEXT)

        # ── Quit ──────────────────────────────────────────────────
        elif cmd0 == "q":
            try:
                save = input(c("  Save session before quitting? [Y/n]: ", YELLOW)).strip().lower()
            except EOFError:
                save = "n"
            if save != "n":
                save_session(session, session_file)
            state.blackout()
            print(c("\n  Goodbye – all channels blacked out.\n", BOLD))
            break

        else:
            warn(f"Unknown command '{cmd}'.  Type '?' for help.")


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Stadium Pro III 1200W RGBW – Channel Discovery Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--host", default="localhost",
                   help="DMX server host (default: localhost)")
    p.add_argument("--port", type=int, default=5000,
                   help="DMX server port (default: 5000)")
    p.add_argument("--start-ch", type=int, default=1, metavar="N",
                   help="First DMX channel to test (default: 1)")
    p.add_argument("--channels", type=int, default=16, metavar="N",
                   help="Number of channels to probe (default: 16)")
    p.add_argument("--session-file", default="stadium_discovery.json", metavar="FILE",
                   help="Session file path (default: stadium_discovery.json)")
    return p.parse_args()


def main():
    args = parse_args()
    base_url = f"http://{args.host}:{args.port}"

    dmx = DMXConnection(base_url)

    print(c(f"\n  Connecting to {base_url} ...", DIM))
    health = dmx.health()
    if health is None:
        err(f"Cannot reach {base_url} – is app.py running?")
        err("Start with:  python3 app.py  or  sudo systemctl start dmx")
        sys.exit(1)

    enttec = health.get("enttec_connected", False)
    artnet = health.get("artnet_enabled", False)
    ok(f"Connected  (ENTTEC={enttec}, Art-Net={artnet})")

    if not enttec and not artnet:
        warn("No DMX output active – commands will be stored but won't reach the fixture.")

    # Create channel state tracker
    ch_state = ChannelState(args.start_ch, args.channels, dmx)

    # Load or create session
    session = new_session(args.start_ch, args.channels)
    if os.path.exists(args.session_file):
        try:
            loaded = load_session(args.session_file)
            session.update(loaded)
            ok(f"Resumed session from {args.session_file}")
        except Exception as exc:
            warn(f"Could not load {args.session_file}: {exc}")

    main_loop(args, dmx, ch_state, session)
    dmx.close()


if __name__ == "__main__":
    main()
