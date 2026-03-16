#!/usr/bin/env python3
"""
Color-Value Mapper
==================
Since the decoder has no DIP switches and is stuck in program mode,
we need to map EXACTLY which DMX values produce which colors.

This does a full 0-255 sweep on ch5 (Fixture 1 Red channel) and
asks you to identify the color at each step. We'll use this to
build a lookup table so the web UI can translate "I want red at 50%"
into the correct DMX value.

Sweep goes in steps of 5 for speed. You only need to type the color
when it CHANGES. Just press Enter if it's the same as last time.
"""
import sys
import time
import json
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

def set_ch(ch, val):
    """Set one channel, all others zero."""
    s.post(f"{URL}/api/test-channel",
           json={"channel": ch, "value": val}, timeout=3)


TEST_CH = 5  # F1 Red (or whatever the decoder thinks it is)

print("=" * 65)
print("  COLOR-VALUE MAPPER")
print("=" * 65)
print()
print(f"  Sweeping channel {TEST_CH} from 0 to 255 in steps of 5.")
print()
print("  Type the COLOR you see (red, green, blue, white, off, cycle, etc)")
print("  Press ENTER if same color as previous.")
print("  Type 'q' to quit.")
print()

color_map = {}
last_color = "off"

for val in range(0, 256, 5):
    set_ch(TEST_CH, val)
    time.sleep(0.6)

    try:
        ans = input(f"  ch{TEST_CH}={val:>3}  [{last_color:>8}] --> ").strip()
    except (KeyboardInterrupt, EOFError):
        break

    if ans.lower() == 'q':
        break

    if ans:
        last_color = ans.lower()

    color_map[val] = last_color

# Also test 255 explicitly
if 255 not in color_map:
    set_ch(TEST_CH, 255)
    time.sleep(0.6)
    try:
        ans = input(f"  ch{TEST_CH}=255  [{last_color:>8}] --> ").strip()
        if ans:
            last_color = ans.lower()
        color_map[255] = last_color
    except (KeyboardInterrupt, EOFError):
        pass

blackout()

# ── Analysis ─────────────────────────────────────────────────
print(f"\n{'=' * 65}")
print(f"  RESULTS: Channel {TEST_CH} value-to-color map")
print(f"{'=' * 65}")

# Group consecutive values by color
ranges = []
current_color = None
range_start = 0

for val in sorted(color_map.keys()):
    color = color_map[val]
    if color != current_color:
        if current_color is not None:
            ranges.append((range_start, val - 1, current_color))
        current_color = color
        range_start = val

if current_color is not None:
    ranges.append((range_start, 255, current_color))

print()
for start, end, color in ranges:
    marker = " <<<" if color == "red" else ""
    print(f"  {start:>3} - {end:>3}: {color}{marker}")

print()

# Count unique colors
colors = set(color_map.values()) - {'off'}
print(f"  Unique colors found: {len(colors)}")
print(f"  Colors: {', '.join(sorted(colors))}")

# Find red range
red_vals = [v for v, c in color_map.items() if 'red' in c]
if red_vals:
    print(f"\n  RED values: {min(red_vals)} - {max(red_vals)}")
    print(f"  This means: to get red, send value {min(red_vals)}-{max(red_vals)} on ch5")

# Save results
results = {
    "channel": TEST_CH,
    "color_map": {str(k): v for k, v in sorted(color_map.items())},
    "ranges": [{"start": s, "end": e, "color": c} for s, e, c in ranges],
}

try:
    with open("/tmp/color_value_map.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved to /tmp/color_value_map.json")
except Exception as e:
    print(f"\n  Could not save results: {e}")

print()
print("  NEXT STEPS:")
print("  1. Run this again for ch6 (Green), ch7 (Blue), ch8 (White)")
print(f"     python3 {sys.argv[0]}  (edit TEST_CH at top of script)")
print("  2. With the color maps, we can build a translation layer")
print("     in the web UI so sliders work correctly")
print()
