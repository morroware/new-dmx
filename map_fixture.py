#!/usr/bin/env python3
"""
DMX Fixture Mapper – simple channel-by-channel labeller
Lights one channel at 255 (all others off), you type what you see, repeat.

Usage:
    python3 map_fixture.py
    python3 map_fixture.py --host 192.168.1.50 --start 5 --count 60

At each prompt:
    Type label and Enter  → save label and go to next channel
    Enter (blank)         → skip this channel
    b                     → go back one channel
    q                     → quit and save
"""

import argparse, json, sys, time
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

def flash(host, port, ch):
    """Zero all channels, set ch to 255. Same call the sweep uses."""
    r = requests.post(f"http://{host}:{port}/api/test-channel",
                      json={"channel": ch, "value": 255}, timeout=5)
    r.raise_for_status()

def blackout(host, port):
    requests.post(f"http://{host}:{port}/api/blackout", timeout=5)

def push_labels(host, port, labels):
    r = requests.post(f"http://{host}:{port}/api/channel-labels",
                      json={"labels": {str(k): v for k, v in labels.items()}},
                      timeout=5)
    r.raise_for_status()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host",  default="localhost")
    p.add_argument("--port",  type=int, default=5000)
    p.add_argument("--start", type=int, default=5,  help="First channel (default 5)")
    p.add_argument("--count", type=int, default=60, help="How many channels (default 60)")
    args = p.parse_args()

    # quick connectivity check
    try:
        r = requests.get(f"http://{args.host}:{args.port}/api/health", timeout=5)
        print(f"Server OK: {r.json()}")
    except Exception as e:
        sys.exit(f"Cannot reach server: {e}")

    channels = list(range(args.start, args.start + args.count))
    labels = {}   # {ch: label_string}
    i = 0

    print()
    print("Light comes on → type what you see → Enter")
    print("Shortcuts: r=Red  g=Green  b=Blue  w=White  a=Amber  uv=UV")
    print("           1r=F1 Red  2g=F2 Green  3b=F3 Blue  4w=F4 White")
    print("blank=skip  b=back  q=quit+save")
    print()

    COLORS = {"r":"Red","g":"Green","b":"Blue","w":"White",
               "a":"Amber","uv":"UV","s":"Strobe","d":"Dimmer"}

    while i < len(channels):
        ch = channels[i]
        existing = labels.get(ch, "")

        # light it up
        try:
            flash(args.host, args.port, ch)
        except Exception as e:
            print(f"  ERROR flashing ch {ch}: {e}")
            i += 1
            continue

        hint = f" [{existing}]" if existing else ""
        try:
            raw = input(f"  ch {ch:>3}{hint} → ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if raw == "q":
            break
        if raw == "b":
            if i > 0:
                i -= 1
            continue
        if raw == "":
            i += 1
            continue

        # parse shorthand like "1r", "2w", "3b", "4g" or "1 red" etc.
        # also plain color shortcuts "r", "g", "b", "w"
        raw_lower = raw.lower()

        # "1r" / "2w" / "3b" shorthand
        label = None
        if len(raw_lower) >= 2 and raw_lower[0].isdigit() and raw_lower[1:] in COLORS:
            label = f"F{raw_lower[0]} {COLORS[raw_lower[1:]]}"
        # "1 red" / "2 w" / "3 blue"
        elif " " in raw_lower:
            parts = raw_lower.split(None, 1)
            if parts[0].isdigit():
                color = COLORS.get(parts[1], parts[1].title())
                label = f"F{parts[0]} {color}"
        # plain color "r" "g" "b" "w"
        if label is None:
            label = COLORS.get(raw_lower, raw.strip())

        labels[ch] = label
        print(f"         ✓ ch {ch} = {label}")
        i += 1

    blackout(args.host, args.port)
    print()

    if not labels:
        print("Nothing mapped.")
        return

    # show summary
    print(f"{'Ch':>4}  Label")
    print("─" * 20)
    for ch in sorted(labels):
        print(f"{ch:>4}  {labels[ch]}")
    print()

    # save JSON
    out = {"mapped_at": datetime.now().isoformat(timespec="seconds"), "channels": labels}
    with open("fixture_map.json", "w") as f:
        json.dump(out, f, indent=2)
    print("Saved → fixture_map.json")

    # push to server
    try:
        push_labels(args.host, args.port, labels)
        print(f"Pushed {len(labels)} labels to DMX server.")
    except Exception as e:
        print(f"Label push failed: {e}")

if __name__ == "__main__":
    main()
