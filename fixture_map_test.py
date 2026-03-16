#!/usr/bin/env python3
"""
Figure out which DMX channels control which fixture.
Sets ONE channel at a time and asks WHICH FIXTURE lights up.
Then tests the value-to-color mapping on each fixture.
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

def blackout():
    s.post(f"{URL}/api/blackout", timeout=3)

def solo(ch, val):
    s.post(f"{URL}/api/test-channel",
           json={"channel": ch, "value": val}, timeout=3)

def set_chs(d):
    s.post(f"{URL}/api/blackout", timeout=3)
    time.sleep(0.1)
    s.post(f"{URL}/api/channels",
           json={"channels": {str(k): v for k, v in d.items()}}, timeout=3)

# ── PART 1: Which channel controls which fixture? ──────────────

print("=" * 60)
print("  PART 1: Channel-to-Fixture Mapping")
print("=" * 60)
print()
print("  I'll light ONE channel at a time (value=50).")
print("  Tell me WHICH FIXTURE lights up and what COLOR.")
print()
print("  Example answers:")
print("    '1 red'    = fixture 1 shows red")
print("    '2 green'  = fixture 2 shows green")
print("    '1 red 2 blue' = fixture 1 red AND fixture 2 blue")
print("    'none'     = no fixture lights up")
print("    'q'        = quit this section")
print()
print("  Fixture numbering: look at your 4 lights and mentally")
print("  number them 1, 2, 3, 4 from left to right (or however")
print("  makes sense to you).")
print()

ch_to_fixture = {}

for ch in range(1, 25):
    solo(ch, 50)
    time.sleep(1.0)  # hold for 1 sec so color stabilizes

    try:
        ans = input(f"  ch {ch:>2} = 50  -->  which fixture, what color? ").strip()
    except (KeyboardInterrupt, EOFError):
        break

    if ans.lower() == 'q':
        break

    ch_to_fixture[ch] = ans
    if ans.lower() not in ('none', 'nothing', 'off', ''):
        print(f"         --> {ans}")

blackout()

print(f"\n{'=' * 60}")
print("  PART 1 RESULTS: Channel → Fixture mapping")
print(f"{'=' * 60}")
for ch, ans in sorted(ch_to_fixture.items()):
    if ans.lower() not in ('none', 'nothing', 'off', ''):
        print(f"  ch {ch:>2}: {ans}")

# ── PART 2: Value-to-color table for one channel ───────────────

print(f"\n{'=' * 60}")
print("  PART 2: Color table for one fixture")
print("=" * 60)
print()
print("  Now I'll test ONE channel at every value from 0-255")
print("  in steps of 25, holding each for a few seconds.")
print("  Tell me the color you see (or 'off').")
print()

# Find a channel that produced a response
test_ch = None
for ch, ans in sorted(ch_to_fixture.items()):
    if ans.lower() not in ('none', 'nothing', 'off', ''):
        test_ch = ch
        break

if test_ch is None:
    try:
        test_ch = int(input("  Which channel to test? "))
    except (ValueError, EOFError):
        test_ch = 5

print(f"  Testing channel {test_ch}")
print(f"  For each value, type the color (red/green/blue/white/off/etc)")
print()

color_table = {}
for val in range(0, 256, 25):
    solo(test_ch, val)
    time.sleep(1.5)

    try:
        ans = input(f"  ch{test_ch} = {val:>3}  -->  color? ").strip()
    except (KeyboardInterrupt, EOFError):
        break

    if ans.lower() == 'q':
        break

    color_table[val] = ans

# Do the boundaries more precisely
if color_table:
    print(f"\n  Now let's find precise boundaries...")
    print(f"  Testing every 5 values in interesting ranges.")
    print()

    prev_color = ""
    for val in range(0, 256, 5):
        # Skip if we already have a nearby reading
        nearest = min(color_table.keys(), key=lambda k: abs(k - val)) if color_table else None
        if nearest is not None and abs(nearest - val) <= 2:
            continue

        solo(test_ch, val)
        time.sleep(1.0)

        try:
            ans = input(f"  ch{test_ch} = {val:>3}  -->  color? ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if ans.lower() == 'q':
            break

        color_table[val] = ans


blackout()

print(f"\n{'=' * 60}")
print(f"  PART 2 RESULTS: Channel {test_ch} color table")
print(f"{'=' * 60}")
prev = ""
for val in sorted(color_table.keys()):
    color = color_table[val]
    marker = " <<<" if color != prev else ""
    print(f"  {val:>3}: {color}{marker}")
    prev = color

# ── Save results ──────────────────────────────────────────────

import json
results = {
    "channel_to_fixture": ch_to_fixture,
    "color_table": {f"ch{test_ch}": {str(k): v for k, v in color_table.items()}},
}
with open("fixture_map_results.json", "w") as f:
    json.dump(results, f, indent=2)
print(f"\nResults saved to fixture_map_results.json")
