#!/usr/bin/env python3
"""
Layout Test - Determine the exact decoder channel layout.

We know: 4 fixtures, 4 decoders, and ch1 controls a fixture.
Question: Are decoders in 4-channel mode (addr 1,5,9,13) or
8-channel mode (addr 1,9,17,25)?

This test sets specific channels and asks which fixture lights up.
Number your fixtures 1-4 as you see them (left to right, or however).
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

def test_channel(ch, val):
    """Zero ALL channels, set ONE channel."""
    s.post(f"{URL}/api/test-channel",
           json={"channel": ch, "value": val}, timeout=3)

def set_channels(ch_dict):
    """Zero all, then set multiple channels."""
    s.post(f"{URL}/api/test-channel", json={"channel": 1, "value": 0}, timeout=3)
    time.sleep(0.05)
    if ch_dict:
        s.post(f"{URL}/api/channels",
               json={"channels": {str(k): v for k, v in ch_dict.items()}}, timeout=3)

def ask(prompt):
    try:
        ans = input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        return None
    return None if ans.lower() == 'q' else ans

print("=" * 65)
print("  LAYOUT TEST")
print("=" * 65)
print()
print("  Number your 4 fixtures 1-4 (left to right or however).")
print("  For each test, tell me: which fixture # and what color.")
print("  Example: '2 red' or 'none' or '1 red 3 red'")
print("  Type 'q' to quit.")
print()

results = []

# ── PART 1: One channel at a time, value=50 ─────────────────
# Test ch1 through ch32 to find ALL responding channels
print("── PART 1: Finding all fixture channels (value=50) ──")
print("   (Channels that show nothing will be skipped quickly)")
print()

for ch in range(1, 33):
    test_channel(ch, 50)
    time.sleep(0.8)
    ans = ask(f"  ch{ch:>2} = 50  --> which fixture, what color? ")
    if ans is None:
        blackout()
        break
    results.append((f"ch{ch}=50", ans))
    if ans.lower() not in ('none', 'nothing', 'off', 'no', 'n', ''):
        print(f"         --> {ans}")

blackout()

# ── PART 2: Value test on confirmed Red channels ────────────
print()
print("── PART 2: Value test on Red channels ──")
print("   Testing different values on channels that showed RED.")
print("   If it's ALWAYS red (different brightness), the decoder")
print("   is in direct RGBW mode. If colors change, it's program mode.")
print()

# Find channels that showed red
red_channels = []
for desc, ans in results:
    if ans and 'red' in ans.lower():
        ch = int(desc.split('=')[0].replace('ch', ''))
        red_channels.append(ch)

if not red_channels:
    print("  No red channels found! Using ch1 and ch5 as defaults.")
    red_channels = [1, 5]

for ch in red_channels[:2]:  # Test first 2 red channels
    print(f"\n  Testing channel {ch}:")
    for val in [10, 25, 50, 75, 100, 128, 200, 255]:
        test_channel(ch, val)
        time.sleep(0.8)
        ans = ask(f"    ch{ch} = {val:>3}  --> color? ")
        if ans is None:
            blackout()
            break
        results.append((f"ch{ch}={val}", ans))
    else:
        continue
    break

blackout()

# ── SUMMARY ──────────────────────────────────────────────────
print(f"\n{'=' * 65}")
print("  RESULTS")
print(f"{'=' * 65}")

# Part 1: Channel map
print("\n  Channel Map (value=50):")
fixture_channels = {}
for desc, ans in results:
    if '=' in desc and ans and ans.lower() not in ('none', 'nothing', 'off', 'no', 'n', ''):
        print(f"    {desc:15s}: {ans}")

# Part 2: Value tests
print("\n  Value Tests:")
for desc, ans in results:
    if any(f"ch{ch}=" in desc and desc != f"ch{ch}=50" for ch in red_channels[:2]):
        print(f"    {desc:15s}: {ans}")

# Analysis
print(f"\n{'=' * 65}")
print("  ANALYSIS")
print(f"{'=' * 65}")

# Check for 4-ch vs 8-ch mode
active_channels = []
for desc, ans in results:
    if '=50' in desc and ans and ans.lower() not in ('none', 'nothing', 'off', 'no', 'n', ''):
        ch = int(desc.split('=')[0].replace('ch', ''))
        active_channels.append(ch)

if active_channels:
    gaps = [active_channels[i+1] - active_channels[i]
            for i in range(len(active_channels)-1)]

    print(f"  Active channels: {active_channels}")
    print(f"  Gaps between groups: {gaps}")

    # Detect grouping
    if len(active_channels) >= 8:
        # Check if groups of 4 with gaps of 4 (8-ch mode: addr 1,9,17,25)
        groups_of_4 = []
        i = 0
        while i < len(active_channels):
            group = [active_channels[i]]
            while i + 1 < len(active_channels) and active_channels[i+1] == active_channels[i] + 1:
                i += 1
                group.append(active_channels[i])
            groups_of_4.append(group)
            i += 1

        print(f"  Channel groups: {groups_of_4}")

        if len(groups_of_4) >= 2:
            group_size = len(groups_of_4[0])
            start_gap = groups_of_4[1][0] - groups_of_4[0][0] if len(groups_of_4) > 1 else 0
            print(f"  Group size: {group_size} channels")
            print(f"  Group spacing: {start_gap} channels")

            if group_size == 4 and start_gap == 4:
                print("  --> 4-channel mode, consecutive addressing")
            elif group_size == 4 and start_gap == 8:
                print("  --> 8-channel mode (4 RGBW + 4 control per decoder)")
            elif group_size == 4:
                print(f"  --> 4-channel mode, {start_gap}-channel spacing")
print()
