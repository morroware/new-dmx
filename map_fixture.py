#!/usr/bin/env python3
"""
DMX Fixture Mapper
Lights one channel at 255 (all others off), you type what you see, repeat.

Usage:
    python3 map_fixture.py
    python3 map_fixture.py --host 192.168.1.50 --start 5 --count 60

At each prompt:
    Type label and Enter  → save and advance
    Enter (blank)         → skip
    b                     → go back one channel
    q                     → quit and save
"""

import argparse, json, sys, time, requests
from datetime import datetime

def test_channel(host, port, ch, value=255):
    r = requests.post(
        f"http://{host}:{port}/api/test-channel",
        json={"channel": ch, "value": value},
        timeout=5,
    )
    r.raise_for_status()
    return r.json()

def blackout(host, port):
    requests.post(f"http://{host}:{port}/api/blackout", timeout=5)

def push_labels(host, port, labels):
    r = requests.post(
        f"http://{host}:{port}/api/channel-labels",
        json={"labels": {str(k): v for k, v in labels.items()}},
        timeout=5,
    )
    r.raise_for_status()

COLORS = {
    "r": "Red", "g": "Green", "b": "Blue", "w": "White",
    "a": "Amber", "uv": "UV", "s": "Strobe", "d": "Dimmer",
}

def parse_label(raw):
    raw_l = raw.lower()
    # "1r" → F1 Red
    if len(raw_l) >= 2 and raw_l[0].isdigit() and raw_l[1:] in COLORS:
        return f"F{raw_l[0]} {COLORS[raw_l[1:]]}"
    # "1 red" / "2 w"
    parts = raw_l.split(None, 1)
    if len(parts) == 2 and parts[0].isdigit():
        return f"F{parts[0]} {COLORS.get(parts[1], parts[1].title())}"
    # plain color "r" "g" etc
    return COLORS.get(raw_l, raw.strip())

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host",  default="localhost")
    p.add_argument("--port",  type=int, default=5000)
    p.add_argument("--start", type=int, default=5,  help="First channel (default 5)")
    p.add_argument("--count", type=int, default=60, help="How many channels (default 60)")
    args = p.parse_args()

    # ── Server health check ────────────────────────────────────────────────────
    try:
        h = requests.get(f"http://{args.host}:{args.port}/api/health", timeout=5).json()
    except Exception as e:
        sys.exit(f"\nERROR: Cannot reach server at {args.host}:{args.port}\n  {e}\n  Is app.py running?")

    enttec = h.get("enttec_connected", False)
    artnet = h.get("artnet_enabled", False)
    running = h.get("dmx_running", False)

    print(f"\nServer: dmx_running={running}  enttec={enttec}  artnet={artnet}")

    if not running:
        print("\nWARNING: dmx_running=False – DMX thread is not running! No output possible.")
        print("         Restart app.py and try again.")
        sys.exit(1)

    if not enttec and not artnet:
        print("\nWARNING: No output active (enttec=False, artnet=False).")
        print("         Check ENTTEC dongle is plugged in. App may need restart.")
        sys.exit(1)

    # ── Startup flash test: blink ch 5 three times so user confirms signal reaches fixture ──
    print(f"\nFlashing channel {args.start} three times to confirm signal reaches fixture...")
    for _ in range(3):
        resp = test_channel(args.host, args.port, args.start, 255)
        print(f"  ON  → server replied: {resp}")
        time.sleep(0.6)
        resp = test_channel(args.host, args.port, args.start, 0)
        print(f"  OFF → server replied: {resp}")
        time.sleep(0.3)

    answer = input("\nDid the fixture flash? [y/n]: ").strip().lower()
    if answer != "y":
        print("\nFixture did not respond. Possible causes:")
        print("  1. ENTTEC USB dongle not recognised – unplug and replug, restart app.py")
        print("  2. DMX cable not connected / wrong port")
        print("  3. Fixture not set to DMX mode or wrong start address")
        print("  4. app.py is running but outputting to wrong device")
        print("\nRun this to check ENTTEC status:")
        print(f"  curl http://{args.host}:{args.port}/api/health")
        sys.exit(1)

    # ── Main mapping loop ──────────────────────────────────────────────────────
    print("\nLight comes on → type what you see → Enter")
    print("  1r=F1 Red  1g=F1 Green  1b=F1 Blue  1w=F1 White  (2r, 3b, etc.)")
    print("  blank=skip   b=back   q=quit+save\n")

    channels = list(range(args.start, args.start + args.count))
    labels = {}
    i = 0

    while i < len(channels):
        ch = channels[i]
        existing = labels.get(ch, "")

        try:
            test_channel(args.host, args.port, ch, 255)
        except Exception as e:
            print(f"  ERROR on ch {ch}: {e}")
            i += 1
            continue

        hint = f" [{existing}]" if existing else ""
        try:
            raw = input(f"  ch {ch:>3}{hint} → ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
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

        label = parse_label(raw)
        labels[ch] = label
        print(f"         ✓  {label}")
        i += 1

    blackout(args.host, args.port)

    if not labels:
        print("Nothing mapped.")
        return

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'Ch':>4}  Label")
    print("─" * 20)
    for ch in sorted(labels):
        print(f"{ch:>4}  {labels[ch]}")

    with open("fixture_map.json", "w") as f:
        json.dump({"mapped_at": datetime.now().isoformat(timespec="seconds"),
                   "channels": labels}, f, indent=2)
    print("\nSaved → fixture_map.json")

    try:
        push_labels(args.host, args.port, labels)
        print(f"Pushed {len(labels)} labels to DMX server.")
    except Exception as e:
        print(f"Label push failed: {e}")

if __name__ == "__main__":
    main()
