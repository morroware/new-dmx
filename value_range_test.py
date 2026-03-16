#!/usr/bin/env python3
"""
Test what DMX values produce light on a single channel.
Steps through 0-255 in increments of 10 to find the on/off boundaries.
"""
import sys
import time
try:
    import requests
except ImportError:
    sys.exit("pip install requests")

HOST = sys.argv[1] if len(sys.argv) > 1 else "localhost"
PORT = sys.argv[2] if len(sys.argv) > 2 else "5000"
URL = f"http://{HOST}:{PORT}"

s = requests.Session()
s.headers["Content-Type"] = "application/json"

try:
    s.get(f"{URL}/api/health", timeout=3).raise_for_status()
    print("Connected.\n")
except Exception:
    sys.exit(f"Cannot reach {URL}")

def solo(ch, val):
    s.post(f"{URL}/api/test-channel", json={"channel": ch, "value": val}, timeout=3)

def blackout():
    s.post(f"{URL}/api/blackout", timeout=3)

CH = 5  # test on ch5 (Red, fixture 1)
print(f"Testing channel {CH} (Red) at every value from 0 to 255, step 10")
print(f"For each value: type 'y' if light is ON, Enter/n if OFF, 'q' to quit")
print(f"Just need on/off -- not brightness level.\n")

on_ranges = []
was_on = False
range_start = 0

for val in list(range(0, 256, 10)) + [255]:
    solo(CH, val)
    time.sleep(0.3)

    try:
        ans = input(f"  ch{CH} = {val:>3}  light on? [y/n/q]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        break

    if ans == 'q':
        break

    is_on = ans.startswith('y')

    if is_on and not was_on:
        range_start = val
    elif not is_on and was_on:
        on_ranges.append((range_start, val - 1))

    was_on = is_on

if was_on:
    on_ranges.append((range_start, 255))

blackout()

print(f"\n{'=' * 50}")
print(f"  Channel {CH} -- value ranges that produce light:")
print(f"{'=' * 50}")
if on_ranges:
    for start, end in on_ranges:
        print(f"  {start:>3} - {end:>3}  (ON)")
else:
    print("  No values produced light!")
print()
