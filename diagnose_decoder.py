#!/usr/bin/env python3
"""
Stadium Pro III 1200W RGBW – Decoder Auto-Diagnostic
=====================================================
Automatically tests common RGBW DMX decoder channel layouts to find
which one your decoder is using.  No manual input needed during each
test — just watch the light and answer simple questions.

Common decoder layouts tested:
  A) 4ch direct at addr 1:  ch1=R, ch2=G, ch3=B, ch4=W
  B) 4ch offset at addr 5:  ch5=R, ch6=G, ch7=B, ch8=W  (current default)
  C) 6ch dimmer-first:      ch1=Dim, ch2=R, ch3=G, ch4=B, ch5=W, ch6=Strobe
  D) 8ch full-feature:      ch1=Dim, ch2=R, ch3=G, ch4=B, ch5=W, ch6=Strobe, ch7=Mode, ch8=Speed
  E) 8ch mode-first:        ch1=Mode, ch2=Dim, ch3=R, ch4=G, ch5=B, ch6=W, ch7=Strobe, ch8=Speed

For each layout the script lights up what *should* be red, then green,
then blue, then white — and asks you to confirm.

Usage:
    python3 diagnose_decoder.py
    python3 diagnose_decoder.py --host 192.168.1.50
    python3 diagnose_decoder.py --host 192.168.1.50 --port 5000
"""

import argparse
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("requests is required:  pip install requests")


# ── ANSI helpers ─────────────────────────────────────────────────────────────

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
CYAN    = "\033[36m"
WHITE   = "\033[97m"

def c(text, *codes):
    return "".join(codes) + str(text) + RESET

def header(txt):
    w = max(len(txt) + 4, 64)
    print(c(f"\n{'━' * w}", BOLD, CYAN))
    print(c(f"  {txt}", BOLD, CYAN))
    print(c(f"{'━' * w}", BOLD, CYAN))

def ok(txt):   print(c(f"  ✓ {txt}", GREEN))
def warn(txt): print(c(f"  ⚠ {txt}", YELLOW))
def err(txt):  print(c(f"  ✗ {txt}", RED))
def info(txt): print(c(f"  · {txt}", DIM))


# ── Decoder Layouts ──────────────────────────────────────────────────────────
# Each layout defines:
#   name:        Human-readable description
#   setup:       Dict of {channel: value} to set BEFORE color channels
#                (e.g. dimmer=255, mode=0)
#   red/green/blue/white:  The channel number that controls that color
#   channels_per_fixture:  Total channels this layout consumes per fixture

LAYOUTS = [
    {
        "id": "4ch-addr1",
        "name": "4ch Direct @ Address 1  (ch1=R, ch2=G, ch3=B, ch4=W)",
        "profile_id": "generic-rgbw-4ch",
        "start_address": 1,
        "setup": {},
        "red": 1, "green": 2, "blue": 3, "white": 4,
        "channels_per_fixture": 4,
    },
    {
        "id": "4ch-addr5",
        "name": "4ch Direct @ Address 5  (ch5=R, ch6=G, ch7=B, ch8=W)",
        "profile_id": "stadium-pro-iii-rgbw-4ch",
        "start_address": 5,
        "setup": {},
        "red": 5, "green": 6, "blue": 7, "white": 8,
        "channels_per_fixture": 4,
    },
    {
        "id": "6ch-dimmer-first",
        "name": "6ch Dimmer-first  (ch1=Dim, ch2=R, ch3=G, ch4=B, ch5=W, ch6=Strobe)",
        "profile_id": "stadium-pro-iii-6ch",
        "start_address": 1,
        "setup": {1: 255, 6: 0},  # dimmer full, strobe off
        "red": 2, "green": 3, "blue": 4, "white": 5,
        "channels_per_fixture": 6,
    },
    {
        "id": "5ch-dimmer-first",
        "name": "5ch Dimmer-first  (ch1=Dim, ch2=R, ch3=G, ch4=B, ch5=W)",
        "profile_id": "generic-dimmer-rgbw-5ch",
        "start_address": 1,
        "setup": {1: 255},  # dimmer full
        "red": 2, "green": 3, "blue": 4, "white": 5,
        "channels_per_fixture": 5,
    },
    {
        "id": "8ch-dimmer-first",
        "name": "8ch Full  (ch1=Dim, ch2=R, ch3=G, ch4=B, ch5=W, ch6=Strobe, ch7=Mode, ch8=Speed)",
        "profile_id": "stadium-pro-iii-8ch",
        "start_address": 1,
        "setup": {1: 255, 6: 0, 7: 0, 8: 0},  # dimmer full, effects off
        "red": 2, "green": 3, "blue": 4, "white": 5,
        "channels_per_fixture": 8,
    },
    {
        "id": "8ch-mode-first",
        "name": "8ch Mode-first  (ch1=Mode, ch2=Dim, ch3=R, ch4=G, ch5=B, ch6=W, ch7=Strobe, ch8=Speed)",
        "profile_id": "stadium-pro-iii-8ch-alt",
        "start_address": 1,
        "setup": {1: 0, 2: 255, 7: 0, 8: 0},  # mode=direct, dimmer full
        "red": 3, "green": 4, "blue": 5, "white": 6,
        "channels_per_fixture": 8,
    },
    {
        "id": "6ch-dimmer-strobe-rgbw",
        "name": "6ch  (ch1=Dim, ch2=Strobe, ch3=R, ch4=G, ch5=B, ch6=W)",
        "profile_id": "generic-dimmer-strobe-rgbw-6ch",
        "start_address": 1,
        "setup": {1: 255, 2: 0},  # dimmer full, strobe off
        "red": 3, "green": 4, "blue": 5, "white": 6,
        "channels_per_fixture": 6,
    },
]


# ── HTTP helpers ─────────────────────────────────────────────────────────────

class DMX:
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
        self.s.post(f"{self.url}/api/blackout", timeout=5).raise_for_status()

    def set_channels(self, ch_dict):
        self.s.post(
            f"{self.url}/api/channels",
            json={"channels": {str(k): v for k, v in ch_dict.items()}},
            timeout=5,
        ).raise_for_status()

    def reset_config(self):
        """Reset server config to factory defaults (clears stale persisted config)."""
        try:
            r = self.s.post(f"{self.url}/api/config/reset", timeout=5)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def apply_profile(self, profile_id, start_address=1, fixture_count=1):
        r = self.s.post(
            f"{self.url}/api/fixture-profiles/apply",
            json={
                "profile_id": profile_id,
                "start_address": start_address,
                "fixture_count": fixture_count,
            },
            timeout=5,
        )
        r.raise_for_status()
        return r.json()


def yesno(prompt_text):
    while True:
        ans = input(c(f"  → {prompt_text} [y/n]: ", CYAN)).strip().lower()
        if ans in ('y', 'yes'):
            return True
        if ans in ('n', 'no'):
            return False
        print("    Please answer y or n.")


def ask_color(expected):
    """Ask what color the user sees. Returns True if it matches expected."""
    ans = input(c(f"  → What color do you see? (expecting {expected}, or 'off'/'wrong'): ", CYAN)).strip().lower()
    return expected.lower() in ans


# ── Quick mode ───────────────────────────────────────────────────────────────

def run_quick_mode(dmx, fixture_count):
    """Cycle through each layout showing RED for 3 seconds each.

    The user watches and tells us which one lit up red (or any light at all).
    Much faster than the full interactive test.
    """
    header("QUICK MODE — Watch for RED light")
    print()
    info("I'll cycle through each layout for 3 seconds each.")
    info("Watch the fixture and note which number lights up RED.")
    print()

    for i, layout in enumerate(LAYOUTS, 1):
        dmx.blackout()
        time.sleep(0.3)

        ch_dict = dict(layout["setup"])
        ch_dict[layout["red"]] = 255

        print(c(f"  [{i}/{len(LAYOUTS)}] {layout['name']}", BOLD, YELLOW))
        info(f"Channels: {ch_dict}")
        dmx.set_channels(ch_dict)
        time.sleep(3.0)

    dmx.blackout()

    print()
    header("Which layout produced RED light?")
    for i, layout in enumerate(LAYOUTS, 1):
        print(f"  {i}) {layout['name']}")
    print(f"  0) None of them worked")
    print()

    while True:
        try:
            choice = int(input(c("  → Enter number: ", CYAN)).strip())
        except (ValueError, KeyboardInterrupt, EOFError):
            choice = -1
        if 0 <= choice <= len(LAYOUTS):
            break
        print("    Invalid choice, try again.")

    if choice == 0:
        header("NO MATCHING LAYOUT FOUND")
        print()
        warn("None of the common layouts matched your decoder.")
        info("Try the full interactive mode (without --quick) for more options,")
        info("or check your decoder's DIP switches and wiring.")
        return

    winner = LAYOUTS[choice - 1]
    header(f"SELECTED: {winner['name']}")

    if yesno(f"Apply this profile for {fixture_count} fixture(s)?"):
        try:
            result = dmx.apply_profile(
                winner["profile_id"],
                start_address=winner["start_address"],
                fixture_count=fixture_count,
            )
            ok("Profile applied!")
            ok(f"Visible channels: {result.get('visible_channels', '?')}")
        except Exception as e:
            err(f"Failed to apply profile: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Diagnose RGBW decoder channel layout")
    parser.add_argument("--host", default="localhost", help="DMX server host")
    parser.add_argument("--port", default="5000", help="DMX server port")
    parser.add_argument("--fixtures", type=int, default=4,
                        help="Number of fixtures to configure after detection (default: 4)")
    parser.add_argument("--quick", action="store_true",
                        help="Quick mode: cycle through layouts showing RED only, 3s each")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    dmx = DMX(base_url)

    # ── Connect ──────────────────────────────────────────────────
    header("Stadium Pro III – Decoder Diagnostic")
    info(f"Connecting to {base_url} ...")

    health = dmx.health()
    if not health:
        err(f"Cannot connect to DMX server at {base_url}")
        err("Make sure app.py is running.")
        sys.exit(1)

    driver = health.get("dmx_driver", "unknown")
    ok(f"Connected — DMX {'online' if health.get('dmx_connected') else 'OFFLINE'} (driver: {driver})")

    if not health.get("dmx_connected"):
        warn("DMX hardware not connected! The test will still run but")
        warn("no signal will reach the fixture. Connect your ENTTEC adapter first.")
        if not yesno("Continue anyway?"):
            sys.exit(0)

    # ── Reset persisted config to avoid stale channel mappings ──
    print()
    info("Resetting server config to factory defaults...")
    reset_result = dmx.reset_config()
    if reset_result and reset_result.get("success"):
        ok("Config reset — stale channel mappings cleared")
    else:
        warn("Could not reset config (may be running older server version)")

    print()
    info("This will test common RGBW decoder channel layouts.")
    info("For each layout, the script will try to light RED, GREEN, BLUE, WHITE.")
    info("Tell me if the colors match. We'll find your decoder's layout.")
    print()
    info("Make sure:")
    info("  1. The light is powered on")
    info("  2. DMX cable is connected (ENTTEC → decoder → fixture)")
    info("  3. Decoder DIP switches set to address 001")
    info("  4. You can see the light from where you are")
    print()

    if not yesno("Ready to begin?"):
        sys.exit(0)

    # ── Quick mode: just blast RED on each layout, user picks ──
    if args.quick:
        return run_quick_mode(dmx, args.fixtures)

    # ── Test each layout ─────────────────────────────────────────
    winner = None

    for layout in LAYOUTS:
        header(f"Testing: {layout['name']}")

        colors = [
            ("RED",   layout["red"]),
            ("GREEN", layout["green"]),
            ("BLUE",  layout["blue"]),
            ("WHITE", layout["white"]),
        ]

        score = 0

        for color_name, color_ch in colors:
            # Blackout first
            dmx.blackout()
            time.sleep(0.3)

            # Set control channels (dimmer, mode, etc.)
            ch_dict = dict(layout["setup"])
            # Set the color channel to full
            ch_dict[color_ch] = 255

            info(f"Setting channels: {ch_dict}")
            dmx.set_channels(ch_dict)
            time.sleep(1.5)  # Give decoder time to respond

            if ask_color(color_name):
                ok(f"{color_name} confirmed!")
                score += 1
            else:
                err(f"{color_name} did not match.")
                # If first color fails, skip rest of this layout
                if score == 0 and color_name == "RED":
                    info("Skipping remaining colors for this layout.")
                    break

        dmx.blackout()

        if score == 4:
            ok(f"ALL 4 COLORS MATCHED — Layout: {layout['name']}")
            winner = layout
            break
        elif score > 0:
            warn(f"{score}/4 colors matched. Partial match.")
            if yesno("Try next layout?"):
                continue
            else:
                warn("Using this partial match as the best option.")
                winner = layout
                break
        else:
            info("No match. Trying next layout...")

    print()

    # ── Results ──────────────────────────────────────────────────
    if winner:
        header(f"DETECTED LAYOUT: {winner['name']}")
        print()
        info(f"Profile ID:           {winner['profile_id']}")
        info(f"Start address:        {winner['start_address']}")
        info(f"Channels per fixture: {winner['channels_per_fixture']}")

        if winner["setup"]:
            info(f"Control channels:     {winner['setup']}")
            print()
            warn("IMPORTANT: Your decoder has control channels that need specific values!")
            warn("The control channels must be set correctly or colors won't work:")
            for ch, val in sorted(winner["setup"].items()):
                ch_names = {
                    1: "Dimmer/Mode", 2: "Dimmer/Strobe",
                    6: "Strobe", 7: "Mode", 8: "Speed"
                }
                name = ch_names.get(ch, f"Control")
                info(f"  Channel {ch} ({name}) = {val}")

        print()
        if yesno(f"Apply this profile for {args.fixtures} fixture(s)?"):
            try:
                result = dmx.apply_profile(
                    winner["profile_id"],
                    start_address=winner["start_address"],
                    fixture_count=args.fixtures,
                )
                ok("Profile applied!")
                ok(f"Visible channels: {result.get('visible_channels', '?')}")
                labels = result.get("labels", {})
                if labels:
                    info("Channel labels:")
                    for ch_str in sorted(labels, key=lambda x: int(x)):
                        info(f"  Ch {ch_str:>3}: {labels[ch_str]}")
            except Exception as e:
                err(f"Failed to apply profile: {e}")
                err("You may need to add this profile to app.py first.")
                err(f"Profile ID needed: {winner['profile_id']}")
        else:
            info("Profile not applied. You can apply it manually via the web UI.")

    else:
        header("NO MATCHING LAYOUT FOUND")
        print()
        warn("None of the common layouts matched your decoder.")
        print()
        info("Possible causes:")
        info("  1. Decoder DIP switches are set to a non-standard address")
        info("  2. Decoder is in a program/macro mode (not direct PWM)")
        info("  3. DMX signal isn't reaching the decoder")
        info("  4. Decoder uses a proprietary channel layout")
        print()
        info("Next steps:")
        info("  1. Check the DIP switches on your decoder:")
        info("     - Address should typically be 001 (all DIP switches down/off)")
        info("     - Mode switch should be set to 4CH or RGBW")
        info("  2. Look for a MODE button on the decoder and try pressing it")
        info("  3. Try the interactive tester: python3 stadium_channel_tester.py")
        info("  4. Check decoder wiring: R→Ch1, G→Ch2, B→Ch3, W→Ch4")
        print()
        info("If your decoder has a digital display, note the address shown.")
        info("Then re-run this script — we can add a custom start address test.")


if __name__ == "__main__":
    main()
