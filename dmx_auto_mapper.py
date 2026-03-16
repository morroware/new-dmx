#!/usr/bin/env python3
"""
DMX Auto-Mapper – Guided fixture channel discovery
===================================================
Walks you through a structured series of tests to automatically build
a complete DMX channel map for unknown fixtures.  Designed for fixtures
with no manufacturer documentation (e.g. Stadium Pro III 1200W RGBW).

Approach:
  Phase 1 – Find fixture boundaries (which channels belong to which fixture)
  Phase 2 – Find the dimmer / master channel
  Phase 3 – Identify colour channels (R, G, B, W, Amber, UV …)
  Phase 4 – Identify effect channels (strobe, mode, speed …)
  Phase 5 – Repeat for additional fixtures
  Phase 6 – Generate fixture profile & apply to server

You only answer simple questions: y/n, colour names, or short descriptions.
The script handles all the DMX commands.

Usage:
    python3 dmx_auto_mapper.py
    python3 dmx_auto_mapper.py --host 192.168.1.50 --port 5000
    python3 dmx_auto_mapper.py --start-ch 1 --max-ch 32
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


# ── ANSI ──────────────────────────────────────────────────────────────────────

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

def c(text, *codes):
    return "".join(codes) + str(text) + RESET

def header(txt):
    w = max(len(txt) + 4, 64)
    print(c(f"\n{'━' * w}", BOLD, CYAN))
    print(c(f"  {txt}", BOLD, CYAN))
    print(c(f"{'━' * w}", BOLD, CYAN))

def subheader(txt):
    print(c(f"\n  ── {txt} ──", BOLD, WHITE))

def ok(txt):      print(c(f"  ✓ {txt}", GREEN))
def warn(txt):    print(c(f"  ⚠ {txt}", YELLOW))
def err(txt):     print(c(f"  ✗ {txt}", RED))
def info(txt):    print(c(f"  · {txt}", DIM))
def prompt(txt):  return input(c(f"  → {txt}", CYAN)).strip()
def yesno(txt):   return prompt(f"{txt} [y/n]: ").lower().startswith("y")
def pause(txt="Press Enter to continue..."):
    try:
        input(c(f"  · {txt}", DIM))
    except (KeyboardInterrupt, EOFError):
        pass


# ── DMX Server Communication ─────────────────────────────────────────────────

class DMX:
    """Talk to the Flask DMX server."""

    def __init__(self, base_url):
        self.url = base_url
        self.s = requests.Session()
        self.s.headers["Content-Type"] = "application/json"

    def health(self):
        try:
            r = self.s.get(f"{self.url}/api/health", timeout=5)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def blackout(self):
        """Zero ALL 512 channels."""
        self.s.post(f"{self.url}/api/blackout", timeout=5).raise_for_status()

    def isolate(self, channel, value=255):
        """Zero all 512 channels, then set ONE channel."""
        self.s.post(
            f"{self.url}/api/test-channel",
            json={"channel": channel, "value": value},
            timeout=5,
        ).raise_for_status()

    def set_channels(self, ch_dict):
        """Partial update – set specific channels, don't touch others."""
        self.s.post(
            f"{self.url}/api/channels",
            json={"channels": {str(k): v for k, v in ch_dict.items()}},
            timeout=5,
        ).raise_for_status()

    def set_scene(self, ch_dict):
        """Blackout first, then set channels. Clean DMX frame."""
        self.blackout()
        if ch_dict:
            self.set_channels(ch_dict)

    def apply_labels(self, labels):
        self.s.post(
            f"{self.url}/api/channel-labels",
            json={"labels": {str(k): v for k, v in labels.items()}},
            timeout=5,
        ).raise_for_status()

    def apply_profile(self, profile_id, start_address, fixture_count):
        self.s.post(
            f"{self.url}/api/fixture-profiles/apply",
            json={
                "profile_id": profile_id,
                "start_address": start_address,
                "fixture_count": fixture_count,
            },
            timeout=5,
        ).raise_for_status()

    def close(self):
        self.s.close()


# ── Result structures ─────────────────────────────────────────────────────────

class ChannelInfo:
    def __init__(self, channel):
        self.channel = channel
        self.label = ""
        self.role = ""       # dimmer, red, green, blue, white, strobe, mode, speed, unknown, nothing
        self.notes = ""
        self.responds = None  # True/False/None

    def to_dict(self):
        return {
            "channel": self.channel,
            "label": self.label,
            "role": self.role,
            "notes": self.notes,
            "responds": self.responds,
        }


class FixtureMap:
    def __init__(self):
        self.fixtures = []    # list of dicts, each with start_ch, end_ch, channels[]

    def add_fixture(self, start_ch, channels):
        self.fixtures.append({
            "fixture_num": len(self.fixtures) + 1,
            "start_ch": start_ch,
            "end_ch": start_ch + len(channels) - 1,
            "channel_count": len(channels),
            "channels": channels,
        })

    def to_dict(self):
        result = []
        for f in self.fixtures:
            result.append({
                "fixture_num": f["fixture_num"],
                "start_ch": f["start_ch"],
                "end_ch": f["end_ch"],
                "channel_count": f["channel_count"],
                "channels": [ch.to_dict() for ch in f["channels"]],
            })
        return result

    def print_summary(self):
        header("Discovered Fixture Map")
        for f in self.fixtures:
            print()
            print(c(f"  Fixture {f['fixture_num']}:  channels {f['start_ch']} – {f['end_ch']}  ({f['channel_count']} ch)", BOLD, WHITE))
            print(c(f"  {'Ch':>5}  {'Role':<12}  {'Label':<16}  Notes", BOLD))
            print(f"  {'─' * 55}")
            for ch_info in f["channels"]:
                role_colors = {
                    "dimmer": YELLOW, "red": RED, "green": GREEN,
                    "blue": BLUE, "white": WHITE, "strobe": MAGENTA,
                    "mode": MAGENTA, "speed": MAGENTA, "amber": YELLOW,
                    "uv": MAGENTA, "nothing": DIM, "unknown": DIM,
                }
                role_c = role_colors.get(ch_info.role, "")
                role_str = c(f"{ch_info.role:<12}", role_c) if role_c else f"{ch_info.role:<12}"
                print(f"  {ch_info.channel:>5}  {role_str}  {ch_info.label:<16}  {ch_info.notes}")


# ── Phase 0: Sanity check – find what value range produces light ──────────────

def phase0_sanity_check(dmx, start_ch, end_ch):
    """
    Some fixtures/decoders have quirky behaviour:
      - 255 on a mode channel = blackout
      - Inverted dimmer (255=off, 0=full)
      - Need specific channel combinations to produce light

    This phase does quick tests to understand the fixture's basic behaviour.
    """
    header("Phase 0: Quick Sanity Check")
    print()
    print(c("  First, let me figure out how your fixture responds to DMX values.", WHITE))
    print(c("  I'll try a few different combinations.", WHITE))
    print()

    tests = [
        ("All channels 0 (blackout)",
         {ch: 0 for ch in range(start_ch, end_ch + 1)}),
        ("All channels 128 (50%)",
         {ch: 128 for ch in range(start_ch, end_ch + 1)}),
        ("All channels 255 (max)",
         {ch: 255 for ch in range(start_ch, end_ch + 1)}),
        ("Ch1=0, rest=255",
         {**{ch: 255 for ch in range(start_ch, end_ch + 1)}, start_ch: 0}),
        ("Ch1=128, rest=255",
         {**{ch: 255 for ch in range(start_ch, end_ch + 1)}, start_ch: 128}),
        ("Ch1=255, rest=0",
         {ch: 0 for ch in range(start_ch, end_ch + 1)} | {start_ch: 255}),
        ("Ch1=128, rest=0",
         {ch: 0 for ch in range(start_ch, end_ch + 1)} | {start_ch: 128}),
        ("Ch1=0, Ch2-5=255",
         {start_ch: 0, **{ch: 255 for ch in range(start_ch + 1, min(start_ch + 5, end_ch + 1))}}),
        ("Ch1=255, Ch2=255 only",
         {start_ch: 255, start_ch + 1: 255}),
    ]

    print(c("  For each test, tell me:", DIM))
    print(c("    l = light is ON (any colour/brightness)", DIM))
    print(c("    n = nothing / dark / blacked out", DIM))
    print(c("    s = strobe / flashing", DIM))
    print(c("    q = stop testing", DIM))
    print()

    results = []
    for desc, ch_dict in tests:
        dmx.set_scene(ch_dict)
        time.sleep(0.8)

        try:
            ans = prompt(f"{desc:<35} → light? [l/n/s/q]: ").lower().strip()
        except (KeyboardInterrupt, EOFError):
            break

        if ans == "q":
            break

        status = "ON" if ans.startswith("l") else "STROBE" if ans.startswith("s") else "OFF"
        results.append((desc, status))

        if status == "ON":
            ok(f"  {desc} → LIGHT ON")
        elif status == "STROBE":
            warn(f"  {desc} → STROBING")
        else:
            info(f"  {desc} → dark")

    dmx.blackout()
    print()

    # Analyze results
    on_tests = [desc for desc, status in results if status == "ON"]
    off_tests = [desc for desc, status in results if status == "OFF"]

    if on_tests:
        ok("Light came on during these tests:")
        for t in on_tests:
            print(c(f"    • {t}", GREEN))
    if off_tests:
        info("Light stayed off during:")
        for t in off_tests:
            print(c(f"    • {t}", DIM))

    # Give guidance
    print()
    all_255_status = next((s for d, s in results if "All channels 255" in d), None)
    all_128_status = next((s for d, s in results if "All channels 128" in d), None)

    if all_255_status == "OFF" and all_128_status == "ON":
        print(c("  *** IMPORTANT: Your fixture blacks out at 255 but works at 128!", BOLD, YELLOW))
        print(c("      This likely means channel 1 is a MODE channel where 255 = blackout.", YELLOW))
        print(c("      The auto-mapper will handle this – keep going.", YELLOW))
    elif all_255_status == "OFF" and all_128_status == "OFF":
        print(c("  *** Your fixture may need specific channel combinations.", YELLOW))
        print(c("      The auto-mapper will try different approaches.", YELLOW))
    elif all_255_status == "ON":
        print(c("  Good – fixture responds normally at max values.", GREEN))

    print()
    pause()


# ── Phase 1: Find fixture boundaries ─────────────────────────────────────────

def phase1_find_boundaries(dmx, start_ch, max_ch):
    """
    Light channels one at a time at MULTIPLE values, ask if anything visible happens.
    Tests at 128, 255, and 64 since some fixtures black out at 255.
    """
    header("Phase 1: Find Fixture Boundaries")
    print()
    print(c("  I'll light each channel one at a time at several values.", WHITE))
    print(c("  Tell me if you see ANY response: light, colour, flicker – anything.", WHITE))
    print()
    print(c("  Answer:  y = yes, something happened", DIM))
    print(c("           n = no, nothing at any value", DIM))
    print(c("           q = stop scanning", DIM))
    print()
    pause()

    responsive = []
    unresponsive_streak = 0
    max_streak = 6  # stop after 6 unresponsive in a row
    test_values = [128, 255, 64]  # try 128 first since 255 may blackout

    for ch in range(start_ch, max_ch + 1):
        saw_response = False

        for val in test_values:
            dmx.isolate(ch, val)
            time.sleep(0.4)

        # After showing all values, ask once
        try:
            ans = prompt(f"ch {ch:>3} (tested at {'/'.join(str(v) for v in test_values)}) – anything? [y/n/q]: ").lower()
        except (KeyboardInterrupt, EOFError):
            break

        if ans == "q":
            break

        if ans.startswith("y"):
            responsive.append(ch)
            unresponsive_streak = 0
        else:
            unresponsive_streak += 1
            if unresponsive_streak >= max_streak and responsive:
                info(f"{max_streak} unresponsive in a row – looks like end of fixture.")
                if yesno("Stop scanning?"):
                    break

    dmx.blackout()

    if not responsive:
        print()
        warn("No channels responded individually!")
        print(c("  This usually means the fixture needs multiple channels active", YELLOW))
        print(c("  at once (e.g. a dimmer + colour).  Let's try that next.", YELLOW))
        return None, start_ch, max_ch

    print()
    ok(f"Responsive channels: {responsive}")
    first = min(responsive)
    last = max(responsive)
    info(f"Fixture appears to use channels {first} – {last} ({last - first + 1} channels)")
    return responsive, first, last


# ── Phase 1b: Brute-force dimmer search ──────────────────────────────────────

def phase1b_brute_dimmer(dmx, start_ch, max_ch):
    """
    If nothing lit up in phase 1, there's probably a dimmer.
    Set ALL channels to 255, check if light comes on.
    Then find the dimmer by dropping channels one at a time.
    """
    header("Phase 1b: Brute-Force Dimmer Search")
    print()
    print(c("  Since no individual channel produced light, the fixture likely", WHITE))
    print(c("  needs multiple channels active at once (e.g. dimmer + colour).", WHITE))
    print()

    # Try setting all channels to 128 first (some fixtures blackout at 255)
    all_on = {ch: 128 for ch in range(start_ch, max_ch + 1)}
    dmx.set_scene(all_on)
    time.sleep(1.0)

    light_on = yesno(f"All channels {start_ch}-{max_ch} at 128.  Is the light ON?")
    if not light_on:
        # Try 255
        all_on = {ch: 255 for ch in range(start_ch, max_ch + 1)}
        dmx.set_scene(all_on)
        time.sleep(1.0)
        light_on = yesno(f"How about all at 255?  Light ON?")

    if not light_on:
        # Try mixed: ch1=0, rest=200 (maybe ch1 is a mode channel where 0=normal)
        mixed = {ch: 200 for ch in range(start_ch, max_ch + 1)}
        mixed[start_ch] = 0
        dmx.set_scene(mixed)
        time.sleep(1.0)
        light_on = yesno(f"Ch{start_ch}=0, rest=200.  Light ON?")
        if light_on:
            print(c(f"  *** Ch{start_ch} at 0 = light works.  It's probably a MODE channel!", BOLD, YELLOW))
            print(c(f"      Value 0 likely means 'normal/manual' mode.", YELLOW))

    if not light_on:
        dmx.blackout()
        err("Light still not on with all channels at max.")
        print(c("  Check: DMX wiring, fixture power, DIP switch address settings.", YELLOW))
        print(c("  The fixture's DMX start address must match where we're testing.", YELLOW))
        print()
        print(c("  Common DIP switch address settings:", WHITE))
        print(c("    Address 1:   all DIP switches OFF (or switch 1 ON only)", DIM))
        print(c("    Address 5:   switches 1+3 ON", DIM))
        print(c("    Address 9:   switches 1+4 ON", DIM))
        print(c("    Address 17:  switches 1+5 ON", DIM))
        print()
        return None, None

    ok("Light is ON with all channels at max!")
    print()
    print(c("  Now I'll drop each channel to 0 one at a time.", WHITE))
    print(c("  Tell me when the ENTIRE light goes off or dims significantly.", WHITE))
    print()

    # all_on contains whichever value combo worked
    dimmer_ch = None
    for ch in range(start_ch, max_ch + 1):
        # Reset to working values
        dmx.set_scene(all_on)
        time.sleep(0.3)
        # Drop this one channel
        dmx.set_channels({ch: 0})
        time.sleep(0.5)

        try:
            ans = prompt(f"ch {ch:>3} → 0 (rest stay).  Light off/dimmed? [y/n/q]: ").lower()
        except (KeyboardInterrupt, EOFError):
            break

        if ans == "q":
            break
        if ans.startswith("y"):
            dimmer_ch = ch
            ok(f"ch {ch} appears to be the DIMMER / MASTER!")
            break

    dmx.blackout()

    if dimmer_ch is None:
        warn("Couldn't identify a dimmer channel.")
        return None, None

    # Now re-run phase 1 with dimmer held
    print()
    print(c(f"  Great! Now I'll hold ch {dimmer_ch} at 255 and test each other channel.", WHITE))
    pause()

    responsive = [dimmer_ch]  # dimmer itself is responsive
    unresponsive_streak = 0
    # Use 200 for test value (safe middle ground – avoids 255 blackout issues)
    test_val = 200

    for ch in range(start_ch, max_ch + 1):
        if ch == dimmer_ch:
            continue

        # Blackout, set dimmer, set test channel
        dmx.blackout()
        time.sleep(0.1)
        dmx.set_channels({dimmer_ch: test_val, ch: test_val})
        time.sleep(0.5)

        try:
            ans = prompt(f"ch {ch:>3} at {test_val} (dimmer ON) – see light/colour? [y/n/q]: ").lower()
        except (KeyboardInterrupt, EOFError):
            break

        if ans == "q":
            break

        if ans.startswith("y"):
            responsive.append(ch)
            unresponsive_streak = 0
        else:
            unresponsive_streak += 1
            if unresponsive_streak >= 6 and len(responsive) > 1:
                info("6 unresponsive in a row – past the fixture boundary.")
                if yesno("Stop scanning?"):
                    break

    dmx.blackout()
    responsive.sort()

    if len(responsive) <= 1:
        warn("Only the dimmer responded. Check fixture wiring.")
        return responsive, dimmer_ch

    first = min(responsive)
    last = max(responsive)
    ok(f"Responsive channels: {responsive}")
    info(f"Fixture uses channels {first} – {last}  ({last - first + 1} channels)")
    return responsive, dimmer_ch


# ── Phase 2: Identify the dimmer (if not already found) ──────────────────────

def phase2_find_dimmer(dmx, responsive_channels, known_dimmer=None):
    """
    If we already found the dimmer in phase 1b, confirm it.
    Otherwise, try to identify it.
    """
    if known_dimmer is not None:
        header("Phase 2: Dimmer Confirmation")
        print()
        print(c(f"  We already identified ch {known_dimmer} as the dimmer.", GREEN))

        # Verify: set dimmer to 0, all others to 255 – light should be off
        ch_dict = {ch: 255 for ch in responsive_channels}
        ch_dict[known_dimmer] = 0
        dmx.set_scene(ch_dict)
        time.sleep(0.5)

        if yesno(f"Dimmer (ch {known_dimmer}) at 0, others at 255. Is light OFF?"):
            ok("Confirmed – dimmer controls the light!")
            # Now verify it fades
            print(c("  Quick fade test...", DIM))
            for val in [0, 64, 128, 192, 255]:
                ch_dict[known_dimmer] = val
                dmx.set_scene(ch_dict)
                time.sleep(0.6)
                print(c(f"    ch {known_dimmer} = {val:>3}  {'░' * (val // 17)}{'·' * (15 - val // 17)}", WHITE if val > 0 else DIM))

            ok("Dimmer fades smoothly – confirmed!")
            dmx.blackout()
            return known_dimmer
        else:
            warn("Hmm, light is still on. Maybe it's not the dimmer.")
            known_dimmer = None

    if known_dimmer is None:
        header("Phase 2: Find the Dimmer")
        print()
        print(c("  I'll set all responsive channels to 255, then drop each one.", WHITE))
        print(c("  Tell me which one makes the whole light go OFF.", WHITE))
        print()

        all_on = {ch: 255 for ch in responsive_channels}

        for ch in responsive_channels:
            dmx.set_scene(all_on)
            time.sleep(0.3)
            dmx.set_channels({ch: 0})
            time.sleep(0.5)

            try:
                ans = prompt(f"ch {ch:>3} → 0.  Light OFF? [y/n/q]: ").lower()
            except (KeyboardInterrupt, EOFError):
                break

            if ans == "q":
                break
            if ans.startswith("y"):
                known_dimmer = ch
                ok(f"ch {ch} = DIMMER!")
                break

        dmx.blackout()

    if known_dimmer is None:
        info("No dimmer found – fixture may be direct-drive (colour channels only).")

    return known_dimmer


# ── Phase 3: Identify colour channels ────────────────────────────────────────

COLOUR_SHORTCUTS = {
    "r": "red", "g": "green", "b": "blue", "w": "white",
    "a": "amber", "uv": "uv", "cw": "cool white", "ww": "warm white",
}

def phase3_identify_colours(dmx, responsive_channels, dimmer_ch):
    """
    With dimmer held at 255, test each channel solo and ask what colour.
    """
    header("Phase 3: Identify Colour Channels")
    print()
    if dimmer_ch:
        print(c(f"  Dimmer (ch {dimmer_ch}) will be held at 255.", CYAN))
    print(c("  I'll light each channel one at a time at full brightness.", WHITE))
    print(c("  Tell me what COLOUR you see.", WHITE))
    print()
    print(c("  Shortcuts:  r=Red  g=Green  b=Blue  w=White  a=Amber  uv=UV", DIM))
    print(c("              cw=Cool White  ww=Warm White", DIM))
    print(c("  Or type:    n=Nothing  ?=Not sure  or any description", DIM))
    print()
    pause()

    results = {}  # {ch: ChannelInfo}

    # Use 200 to avoid 255-blackout issues on some decoders
    test_val = 200

    for ch in responsive_channels:
        if ch == dimmer_ch:
            ci = ChannelInfo(ch)
            ci.role = "dimmer"
            ci.label = "Dimmer"
            ci.responds = True
            results[ch] = ci
            continue

        # Blackout, then set dimmer + test channel
        base = {}
        if dimmer_ch:
            base[dimmer_ch] = test_val
        base[ch] = test_val
        dmx.set_scene(base)
        time.sleep(0.5)

        try:
            ans = prompt(f"ch {ch:>3} at {test_val} – what colour? ").lower().strip()
        except (KeyboardInterrupt, EOFError):
            break

        ci = ChannelInfo(ch)

        if ans in ("q", "quit"):
            break
        elif ans in ("n", "no", "none", "nothing", ""):
            ci.role = "unknown"
            ci.label = ""
            ci.responds = False
            info(f"ch {ch} = no visible colour (might be strobe/mode/speed)")
        elif ans == "?":
            ci.role = "unknown"
            ci.label = "Unknown"
            ci.responds = True
            ci.notes = "responded but colour unclear"
        else:
            # Resolve shortcut
            resolved = COLOUR_SHORTCUTS.get(ans, ans)
            ci.role = resolved
            ci.label = resolved.title()
            ci.responds = True
            ok(f"ch {ch} = {ci.label}")

        results[ch] = ci

    dmx.blackout()
    return results


# ── Phase 4: Identify effect channels ────────────────────────────────────────

def phase4_identify_effects(dmx, channel_map, responsive_channels, dimmer_ch):
    """
    For channels that didn't produce a colour, test them as effect channels.
    Hold dimmer + all colours active, then test unknown channels at various levels.
    """
    unknowns = [ch for ch, ci in channel_map.items()
                 if ci.role in ("unknown",) and not ci.responds]

    if not unknowns:
        info("No unknown channels to test for effects.")
        return channel_map

    header("Phase 4: Identify Effect Channels (Strobe / Mode / Speed)")
    print()
    print(c("  I'll hold all colour channels ON and test each unknown channel", WHITE))
    print(c("  at different levels.  Describe what you see change.", WHITE))
    print()

    # Build the base scene: dimmer + all identified colours at 255
    base_scene = {}
    if dimmer_ch:
        base_scene[dimmer_ch] = 255
    for ch, ci in channel_map.items():
        if ci.role in ("red", "green", "blue", "white", "amber", "uv", "cool white", "warm white"):
            base_scene[ch] = 255

    if not base_scene:
        warn("No colour channels identified yet – can't test effects without visible light.")
        return channel_map

    print(c("  Possible effects:", DIM))
    print(c("    s  = Strobe / flashing           m  = Mode / program select", DIM))
    print(c("    sp = Speed (affects mode speed)   ct = Color Temperature", DIM))
    print(c("    n  = Nothing / no change          ?  = Not sure", DIM))
    print(c("    Or type any description", DIM))
    print()

    EFFECT_SHORTCUTS = {
        "s": "strobe", "st": "strobe", "strobe": "strobe",
        "m": "mode", "mode": "mode", "p": "mode", "prog": "mode",
        "sp": "speed", "speed": "speed",
        "ct": "color temp", "cct": "color temp",
        "n": "nothing", "no": "nothing", "none": "nothing",
    }

    test_values = [0, 32, 64, 128, 192, 255]

    for ch in unknowns:
        subheader(f"Testing ch {ch}")

        for val in test_values:
            scene = dict(base_scene)
            scene[ch] = val
            dmx.set_scene(scene)
            time.sleep(0.8)

            pct = round(val / 255 * 100)
            bar_len = val // 17
            bar = "█" * bar_len + "░" * (15 - bar_len)
            print(c(f"    ch{ch} = {val:>3} ({pct:>3}%)  [{bar}]", WHITE if val > 0 else DIM))

        # Ask what they observed
        try:
            ans = prompt(f"ch {ch:>3} – what did this channel do? ").lower().strip()
        except (KeyboardInterrupt, EOFError):
            break

        if ans in ("q", "quit"):
            break

        resolved = EFFECT_SHORTCUTS.get(ans, ans)
        ci = channel_map[ch]

        if resolved == "nothing":
            ci.role = "nothing"
            ci.label = "Nothing"
            ci.notes = "no visible effect at any level"
        elif resolved in ("strobe", "mode", "speed", "color temp"):
            ci.role = resolved
            ci.label = resolved.title()
            ci.responds = True
            ok(f"ch {ch} = {ci.label}")
        elif ans == "?":
            ci.role = "unknown"
            ci.label = "Unknown"
            ci.notes = "effect unclear"
        else:
            ci.role = resolved
            ci.label = resolved.title()
            ci.responds = True
            ok(f"ch {ch} = {ci.label}")

    dmx.blackout()
    return channel_map


# ── Phase 5: Verify with colour combos ──────────────────────────────────────

def phase5_verify(dmx, channel_map, dimmer_ch):
    """Quick combo tests to verify the mapping looks right."""
    header("Phase 5: Verify Mapping")

    colour_chs = {ci.role: ch for ch, ci in channel_map.items()
                  if ci.role in ("red", "green", "blue", "white")}

    if len(colour_chs) < 2:
        info("Not enough colour channels to verify with combos.")
        return True

    base = {}
    if dimmer_ch:
        base[dimmer_ch] = 255

    combos = []
    if "red" in colour_chs:
        combos.append(("Red only", {colour_chs["red"]: 255}))
    if "green" in colour_chs:
        combos.append(("Green only", {colour_chs["green"]: 255}))
    if "blue" in colour_chs:
        combos.append(("Blue only", {colour_chs["blue"]: 255}))
    if "white" in colour_chs:
        combos.append(("White only", {colour_chs["white"]: 255}))
    if "red" in colour_chs and "green" in colour_chs:
        combos.append(("Red + Green = YELLOW?", {colour_chs["red"]: 255, colour_chs["green"]: 255}))
    if "red" in colour_chs and "blue" in colour_chs:
        combos.append(("Red + Blue = MAGENTA?", {colour_chs["red"]: 255, colour_chs["blue"]: 255}))
    if "green" in colour_chs and "blue" in colour_chs:
        combos.append(("Green + Blue = CYAN?", {colour_chs["green"]: 255, colour_chs["blue"]: 255}))
    if all(k in colour_chs for k in ("red", "green", "blue")):
        combos.append(("R+G+B = WHITE?", {colour_chs["red"]: 255, colour_chs["green"]: 255, colour_chs["blue"]: 255}))

    print()
    print(c("  Quick combo check – does each mix look correct?", WHITE))
    print(c("  Press Enter if correct, type 'n' if wrong.", DIM))
    print()

    all_correct = True
    for name, ch_dict in combos:
        scene = dict(base)
        scene.update(ch_dict)
        dmx.set_scene(scene)
        time.sleep(0.8)

        try:
            ans = prompt(f"{name:<28} correct? [Enter=yes / n=no]: ").lower()
        except (KeyboardInterrupt, EOFError):
            break

        if ans.startswith("n"):
            warn(f"  {name} – WRONG.  Mapping may need adjustment.")
            all_correct = False

    dmx.blackout()

    if all_correct:
        ok("All combos verified!")
    else:
        warn("Some combos were wrong – you may need to re-map some channels.")

    return all_correct


# ── Phase 6: Check for more fixtures ─────────────────────────────────────────

def phase6_check_more_fixtures(dmx, fixture_map, last_end_ch, max_ch):
    """See if there are more fixtures after the one we just mapped."""
    header("Phase 6: Check for Additional Fixtures")
    print()

    next_start = last_end_ch + 1
    if next_start > max_ch:
        info("Reached end of scan range – no more channels to check.")
        return False, next_start

    print(c(f"  Checking channels {next_start}+ for another fixture...", WHITE))
    print()

    # Quick scan: try a few channels
    found_any = False
    for ch in range(next_start, min(next_start + 4, max_ch + 1)):
        dmx.isolate(ch, 255)
        time.sleep(0.5)

    if yesno(f"I lit channels {next_start}-{min(next_start + 3, max_ch)} at 255.  Any light from a DIFFERENT fixture?"):
        found_any = True

    dmx.blackout()

    if found_any:
        ok(f"Another fixture found starting around ch {next_start}!")
        return True, next_start
    else:
        # Maybe the next fixture also has a dimmer – try all at 255
        block_end = min(next_start + 15, max_ch)
        all_on = {ch: 255 for ch in range(next_start, block_end + 1)}
        dmx.set_scene(all_on)
        time.sleep(0.5)

        if yesno(f"Tried all channels {next_start}-{block_end} at 255.  Another fixture on?"):
            found_any = True
            ok("Another fixture detected!")

        dmx.blackout()
        return found_any, next_start

    return False, next_start


# ── Generate output ──────────────────────────────────────────────────────────

def generate_profile(fixture_map):
    """Generate a fixture profile dict that can be added to app.py."""
    if not fixture_map.fixtures:
        return None

    # Use the first fixture as the template
    f = fixture_map.fixtures[0]
    channel_map = {}
    offset = 1
    for ci in f["channels"]:
        if ci.role != "nothing":
            channel_map[offset] = ci.label or ci.role.title()
        offset += 1

    profile = {
        "name": f"Stadium Pro III 1200W ({f['channel_count']}ch discovered)",
        "manufacturer": "Stadium Pro",
        "channels_per_fixture": f["channel_count"],
        "channel_map": channel_map,
    }
    return profile


def save_results(fixture_map, filepath):
    """Save the complete discovery results to JSON."""
    output = {
        "fixture": "Stadium Pro III 1200W RGBW",
        "discovered": datetime.now().isoformat(timespec="seconds"),
        "fixtures": fixture_map.to_dict(),
    }
    with open(filepath, "w") as fp:
        json.dump(output, fp, indent=2)
    ok(f"Results saved to {filepath}")


# ── Main flow ─────────────────────────────────────────────────────────────────

def run_mapper(dmx, start_ch, max_ch):
    fixture_map = FixtureMap()

    header("DMX Auto-Mapper")
    print()
    print(c("  This tool will guide you through discovering what each DMX", WHITE))
    print(c("  channel does on your fixture, step by step.", WHITE))
    print()
    print(c(f"  Scan range: channels {start_ch} – {max_ch}", CYAN))
    print()
    print(c("  Make sure:", YELLOW))
    print(c("    1. The fixture is powered on", YELLOW))
    print(c("    2. DMX cable is connected (ENTTEC or Art-Net)", YELLOW))
    print(c("    3. Fixture's DIP switch address matches start channel", YELLOW))
    print(c("    4. You can see the fixture clearly", YELLOW))
    print()

    if not yesno("Ready to start?"):
        return fixture_map

    # Phase 0: Quick sanity check – some fixtures black out at 255
    phase0_sanity_check(dmx, start_ch, min(start_ch + 15, max_ch))

    current_start = start_ch

    while current_start <= max_ch:
        subheader(f"Mapping fixture starting at ch {current_start}")

        # Phase 1: Find boundaries
        responsive, first_ch, last_ch = phase1_find_boundaries(dmx, current_start, max_ch)

        dimmer_ch = None

        if responsive is None:
            # Phase 1b: Brute force dimmer search
            responsive, dimmer_ch = phase1b_brute_dimmer(dmx, current_start, min(current_start + 15, max_ch))
            if responsive is None:
                err("Could not find any responsive channels.")
                if not yesno("Try scanning from a different start channel?"):
                    break
                try:
                    new_start = int(prompt("New start channel: "))
                    current_start = new_start
                    continue
                except (ValueError, EOFError):
                    break

            first_ch = min(responsive)
            last_ch = max(responsive)

        # Build channel list (contiguous range from first to last)
        fixture_channels = list(range(first_ch, last_ch + 1))

        # Phase 2: Find/confirm dimmer
        dimmer_ch = phase2_find_dimmer(dmx, fixture_channels, dimmer_ch)

        # Phase 3: Identify colours
        channel_map = phase3_identify_colours(dmx, fixture_channels, dimmer_ch)

        # Phase 4: Identify effects
        channel_map = phase4_identify_effects(dmx, channel_map, fixture_channels, dimmer_ch)

        # Phase 5: Verify
        phase5_verify(dmx, channel_map, dimmer_ch)

        # Build the fixture entry
        channel_infos = [channel_map.get(ch, ChannelInfo(ch)) for ch in fixture_channels]
        fixture_map.add_fixture(first_ch, channel_infos)

        # Print what we found so far
        fixture_map.print_summary()

        # Phase 6: Check for more fixtures
        has_more, next_start = phase6_check_more_fixtures(dmx, fixture_map, last_ch, max_ch)

        if has_more:
            current_start = next_start
            print()
            ok("Starting discovery on next fixture...")
        else:
            break

    return fixture_map


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="DMX Auto-Mapper – guided fixture channel discovery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--host", default="localhost",
                   help="DMX server host (default: localhost)")
    p.add_argument("--port", type=int, default=5000,
                   help="DMX server port (default: 5000)")
    p.add_argument("--start-ch", type=int, default=1, metavar="N",
                   help="First channel to scan (default: 1)")
    p.add_argument("--max-ch", type=int, default=32, metavar="N",
                   help="Last channel to scan (default: 32)")
    p.add_argument("--output", default="fixture_discovery.json", metavar="FILE",
                   help="Save results to this file (default: fixture_discovery.json)")
    return p.parse_args()


def main():
    args = parse_args()
    base_url = f"http://{args.host}:{args.port}"

    dmx = DMX(base_url)

    print(c(f"\n  Connecting to {base_url} ...", DIM))
    health = dmx.health()
    if health is None:
        err(f"Cannot reach {base_url}")
        err("Start the DMX server:  python3 app.py  or  sudo systemctl start dmx")
        sys.exit(1)

    enttec = health.get("enttec_connected", False)
    artnet = health.get("artnet_enabled", False)
    ok(f"Connected  (ENTTEC={enttec}, Art-Net={artnet})")

    if not enttec and not artnet:
        warn("No DMX output active – fixture won't receive data!")
        if not yesno("Continue anyway?"):
            sys.exit(0)

    # Run the mapper
    fixture_map = run_mapper(dmx, args.start_ch, args.max_ch)

    if not fixture_map.fixtures:
        err("No fixtures discovered.")
        dmx.close()
        return

    # Final summary
    fixture_map.print_summary()

    # Save results
    save_results(fixture_map, args.output)

    # Generate profile
    profile = generate_profile(fixture_map)
    if profile:
        print()
        header("Generated Fixture Profile")
        print(c(f"  Name: {profile['name']}", WHITE))
        print(c(f"  Channels per fixture: {profile['channels_per_fixture']}", WHITE))
        print(c(f"  Channel map:", WHITE))
        for offset, label in profile["channel_map"].items():
            print(c(f"    {offset:>2}: {label}", CYAN))

    # Apply to server?
    print()
    if yesno("Apply discovered labels to the DMX server?"):
        labels = {}
        for fixture in fixture_map.fixtures:
            prefix = f"F{fixture['fixture_num']} " if len(fixture_map.fixtures) > 1 else ""
            for ci in fixture["channels"]:
                if ci.label and ci.role != "nothing":
                    labels[ci.channel] = f"{prefix}{ci.label}"

        if labels:
            try:
                dmx.apply_labels(labels)
                ok(f"Applied {len(labels)} labels to server!")
                print(c("  Refresh the web UI to see them.", DIM))
            except Exception as exc:
                err(f"Failed to apply labels: {exc}")

    dmx.blackout()
    dmx.close()
    print(c("\n  Done!  All channels blacked out.\n", BOLD))


if __name__ == "__main__":
    main()
