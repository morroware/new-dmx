#!/usr/bin/env python3
"""
Quick single-channel sweep — lights up ONE channel at a time.
Run this, watch the light, and note what each channel does.

Usage:
    python3 quick_channel_test.py
    python3 quick_channel_test.py --host 192.168.1.50
"""

import argparse
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("requests required: pip install requests")

BOLD  = "\033[1m"
CYAN  = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED   = "\033[31m"
DIM   = "\033[2m"
RESET = "\033[0m"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default="5000")
    parser.add_argument("--channels", type=int, default=8,
                        help="How many channels to test (default: 8)")
    args = parser.parse_args()

    base = f"http://{args.host}:{args.port}"
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"

    # Verify connection
    try:
        r = s.get(f"{base}/api/health", timeout=5)
        r.raise_for_status()
        h = r.json()
        print(f"{GREEN}Connected — DMX {'online' if h.get('dmx_connected') else 'OFFLINE'}{RESET}")
    except Exception as e:
        print(f"{RED}Cannot connect to {base}: {e}{RESET}")
        sys.exit(1)

    def blackout():
        s.post(f"{base}/api/blackout", timeout=5)

    def set_ch(ch_dict):
        s.post(f"{base}/api/channels",
               json={"channels": {str(k): v for k, v in ch_dict.items()}},
               timeout=5)

    print()
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  SINGLE CHANNEL TEST{RESET}")
    print(f"{BOLD}{CYAN}  Testing channels 1–{args.channels}, one at a time at 255{RESET}")
    print(f"{BOLD}{CYAN}  All other channels will be 0{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")
    print()
    print(f"{DIM}  For each channel, note what you see:{RESET}")
    print(f"{DIM}    r = red, g = green, b = blue, w = white{RESET}")
    print(f"{DIM}    d = dimmer (brightness change), s = strobe/flash{RESET}")
    print(f"{DIM}    m = mode/program change, off = nothing{RESET}")
    print(f"{DIM}    ? = something else (describe it){RESET}")
    print()

    results = {}

    for ch in range(1, args.channels + 1):
        blackout()
        time.sleep(0.5)

        set_ch({ch: 255})
        time.sleep(1.0)

        print(f"{BOLD}{YELLOW}  Channel {ch}{RESET} is set to {BOLD}255{RESET} (all others = 0)")
        ans = input(f"{CYAN}  → What do you see? {RESET}").strip().lower()

        if not ans:
            ans = "off"

        results[ch] = ans
        print()

    # Now test all channels at different values
    blackout()
    time.sleep(0.5)

    print(f"{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  COMBINATION TEST{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")
    print()

    # If any channel was identified as dimmer, test with it on
    dimmer_chs = [ch for ch, r in results.items() if r in ('d', 'dim', 'dimmer')]
    color_chs = {r: ch for ch, r in results.items() if r in ('r', 'red', 'g', 'green', 'b', 'blue', 'w', 'white')}

    if dimmer_chs:
        print(f"{GREEN}  Found dimmer on channel(s): {dimmer_chs}{RESET}")
        print(f"{DIM}  Testing colors WITH dimmer at 255...{RESET}")
        print()

        for ch in range(1, args.channels + 1):
            if ch in dimmer_chs:
                continue
            blackout()
            time.sleep(0.3)
            combo = {d: 255 for d in dimmer_chs}
            combo[ch] = 255
            set_ch(combo)
            time.sleep(1.0)
            print(f"{BOLD}{YELLOW}  Channel {ch}{RESET} = 255 + dimmer(s) {dimmer_chs} = 255")
            ans = input(f"{CYAN}  → What color? {RESET}").strip().lower()
            if ans:
                results[ch] = ans
            print()

    blackout()

    # Print summary
    print()
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  RESULTS SUMMARY{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")
    print()

    role_map = {
        'r': 'Red', 'red': 'Red',
        'g': 'Green', 'green': 'Green',
        'b': 'Blue', 'blue': 'Blue',
        'w': 'White', 'white': 'White',
        'd': 'Dimmer', 'dim': 'Dimmer', 'dimmer': 'Dimmer',
        's': 'Strobe', 'strobe': 'Strobe',
        'm': 'Mode', 'mode': 'Mode',
        'off': '(no response)',
    }

    channel_map = {}
    for ch, ans in sorted(results.items()):
        role = role_map.get(ans, ans)
        print(f"  Channel {ch}: {BOLD}{role}{RESET}")
        if role in ('Red', 'Green', 'Blue', 'White', 'Dimmer', 'Strobe', 'Mode'):
            channel_map[ch] = role

    print()
    print(f"{BOLD}Channel map for app.py:{RESET}")
    print(f"  {channel_map}")
    print()

    # Suggest what profile to use or create
    has_dimmer = 'Dimmer' in channel_map.values()
    has_strobe = 'Strobe' in channel_map.values()
    has_mode = 'Mode' in channel_map.values()
    n_channels = max(results.keys()) if results else 4

    if not has_dimmer and not has_strobe and not has_mode:
        # Pure RGBW — but possibly in a different order
        color_order = []
        for ch in sorted(channel_map.keys()):
            color_order.append(channel_map[ch])
        print(f"{GREEN}  Looks like a {len(channel_map)}ch direct color mode{RESET}")
        print(f"  Channel order: {color_order}")
    else:
        print(f"{GREEN}  Detected: {n_channels}ch mode with", end="")
        if has_dimmer: print(" Dimmer", end="")
        if has_strobe: print(" + Strobe", end="")
        if has_mode: print(" + Mode", end="")
        print(f"{RESET}")

    print()
    print(f"{DIM}  Copy the channel map above and share it so the config{RESET}")
    print(f"{DIM}  can be updated to match your light.{RESET}")


if __name__ == "__main__":
    main()
