#!/usr/bin/env python3
"""
Decoder Mode Discovery Test
============================
We know ch5-8 = F1 RGBW at value=50, but other values produce WRONG colors.
This means the decoder is likely in program/macro mode, not direct PWM mode.

Channels 1-4 are probably: mode, dimmer, strobe, speed (or similar).
This script tries every combination to find the magic values that put
the decoder into direct 4-channel RGBW mode.

The goal: find ch1-4 values where ch5=25, ch5=128, ch5=200 ALL produce RED
(just at different brightness), not different colors.
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

def set_all(ch_dict):
    """Blackout everything, then set channels."""
    s.post(f"{URL}/api/blackout", timeout=3)
    time.sleep(0.15)
    s.post(f"{URL}/api/channels",
           json={"channels": {str(k): v for k, v in ch_dict.items()}}, timeout=3)


print("=" * 65)
print("  DECODER MODE DISCOVERY")
print("=" * 65)
print()
print("  Your decoder likely has channels 1-4 as control channels")
print("  (mode, dimmer, strobe, speed) and ch5-8 as RGBW.")
print()
print("  We need to find the right ch1-4 values to put the decoder")
print("  into DIRECT PWM mode so ch5 = red brightness, not program#.")
print()
print("  For each test, tell me:")
print("    'red'     = steady red (GOOD! This is what we want)")
print("    'cycle'   = cycling through colors (still in program mode)")
print("    'off'     = nothing")
print("    'blue'    = wrong color")
print("    'white'   = white light")
print("    Or describe what you see")
print("    'q' = quit")
print()
print("  IMPORTANT: Watch for 3-5 seconds each time!")
print()

results = []

# ── PHASE 1: Does ch1 control the mode? ─────────────────────
print("─" * 65)
print("  PHASE 1: Testing ch1 as MODE channel")
print("  (ch5=128 should be RED if decoder is in direct mode)")
print("─" * 65)
print()

# Try ch1 at key values with ch5=128
# Most decoders: ch1=0 = manual/direct, higher values = programs
phase1_tests = [
    ("ch1=0, ch5=128",           {1: 0, 5: 128}),
    ("ch1=0, ch2=255, ch5=128",  {1: 0, 2: 255, 5: 128}),
    ("ch1=0, ch2=255, ch3=0, ch4=0, ch5=128",
     {1: 0, 2: 255, 3: 0, 4: 0, 5: 128}),
    ("ch1=1, ch2=255, ch5=128",  {1: 1, 2: 255, 5: 128}),
    ("ch1=10, ch2=255, ch5=128", {1: 10, 2: 255, 5: 128}),
    ("ch1=50, ch2=255, ch5=128", {1: 50, 2: 255, 5: 128}),
    ("ch1=127, ch2=255, ch5=128",{1: 127, 2: 255, 5: 128}),
    ("ch1=128, ch2=255, ch5=128",{1: 128, 2: 255, 5: 128}),
    ("ch1=200, ch2=255, ch5=128",{1: 200, 2: 255, 5: 128}),
    ("ch1=255, ch2=255, ch5=128",{1: 255, 2: 255, 5: 128}),
]

quit_flag = False
for desc, ch_dict in phase1_tests:
    set_all(ch_dict)
    time.sleep(1.0)
    try:
        ans = input(f"  {desc:45s} --> ? ").strip()
    except (KeyboardInterrupt, EOFError):
        quit_flag = True
        break
    if ans.lower() == 'q':
        quit_flag = True
        break
    results.append((desc, ans))
    if 'red' in ans.lower() and 'cycle' not in ans.lower():
        print(f"  *** POSSIBLE HIT: {desc} = {ans} ***")

if quit_flag:
    blackout()
    print("\n  Results so far:")
    for desc, ans in results:
        print(f"    {desc}: {ans}")
    sys.exit(0)


# ── PHASE 2: Test if ch2 is dimmer ──────────────────────────
print()
print("─" * 65)
print("  PHASE 2: Testing ch2 as DIMMER (with best ch1 from Phase 1)")
print("  Using ch5=50 (known red)")
print("─" * 65)
print()

# Use ch5=50 which we know works, and try ch2 at different levels
phase2_tests = [
    ("ch2=0, ch5=50",    {2: 0, 5: 50}),
    ("ch2=50, ch5=50",   {2: 50, 5: 50}),
    ("ch2=128, ch5=50",  {2: 128, 5: 50}),
    ("ch2=200, ch5=50",  {2: 200, 5: 50}),
    ("ch2=255, ch5=50",  {2: 255, 5: 50}),
]

for desc, ch_dict in phase2_tests:
    set_all(ch_dict)
    time.sleep(1.0)
    try:
        ans = input(f"  {desc:45s} --> ? ").strip()
    except (KeyboardInterrupt, EOFError):
        quit_flag = True
        break
    if ans.lower() == 'q':
        quit_flag = True
        break
    results.append((desc, ans))

if quit_flag:
    blackout()
    print("\n  Results so far:")
    for desc, ans in results:
        print(f"    {desc}: {ans}")
    sys.exit(0)


# ── PHASE 3: Verify -- can we get RED at multiple values? ───
print()
print("─" * 65)
print("  PHASE 3: VERIFICATION - ch5 at multiple values")
print("  Goal: ALL should be RED at different brightness")
print("─" * 65)
print()
print("  Testing with ch1=0, ch2=255 (best guess for direct mode)")
print()

phase3_tests = [
    ("ch1=0, ch2=255, ch5=25",  {1: 0, 2: 255, 5: 25}),
    ("ch1=0, ch2=255, ch5=50",  {1: 0, 2: 255, 5: 50}),
    ("ch1=0, ch2=255, ch5=75",  {1: 0, 2: 255, 5: 75}),
    ("ch1=0, ch2=255, ch5=100", {1: 0, 2: 255, 5: 100}),
    ("ch1=0, ch2=255, ch5=128", {1: 0, 2: 255, 5: 128}),
    ("ch1=0, ch2=255, ch5=150", {1: 0, 2: 255, 5: 150}),
    ("ch1=0, ch2=255, ch5=200", {1: 0, 2: 255, 5: 200}),
    ("ch1=0, ch2=255, ch5=255", {1: 0, 2: 255, 5: 255}),
]

for desc, ch_dict in phase3_tests:
    set_all(ch_dict)
    time.sleep(1.0)
    try:
        ans = input(f"  {desc:45s} --> ? ").strip()
    except (KeyboardInterrupt, EOFError):
        quit_flag = True
        break
    if ans.lower() == 'q':
        quit_flag = True
        break
    results.append((desc, ans))

if quit_flag:
    blackout()
    print("\n  Results so far:")
    for desc, ans in results:
        print(f"    {desc}: {ans}")
    sys.exit(0)


# ── PHASE 4: Maybe the decoder uses a DIFFERENT layout ──────
print()
print("─" * 65)
print("  PHASE 4: Alternative layouts")
print("  Maybe it's NOT ch1=mode. Let's test other theories.")
print("─" * 65)
print()

# Theory: Maybe ch4=mode, ch3=dimmer, ch2=strobe, ch1=speed
# Theory: Maybe we need ch1-4 ALL at specific values
phase4_tests = [
    ("ALL zeros + ch5=128",
     {1: 0, 2: 0, 3: 0, 4: 0, 5: 128}),
    ("ch1=255, ch2=255, ch3=255, ch4=255, ch5=128",
     {1: 255, 2: 255, 3: 255, 4: 255, 5: 128}),
    ("ch3=255, ch4=0, ch5=128",
     {3: 255, 4: 0, 5: 128}),
    ("ch4=255, ch5=128",
     {4: 255, 5: 128}),
    ("ch3=0, ch4=255, ch5=128",
     {3: 0, 4: 255, 5: 128}),
    # Maybe the RGBW channels are actually ch1-4 and ch5-8 are control?
    ("ch1=128 only (is ch1 actually Red?)",
     {1: 128}),
    ("ch1=128, ch5=0 (ch1=Red, ch5=mode?)",
     {1: 128, 5: 0}),
    # Maybe each decoder is 6-channel: mode, dimmer, R, G, B, W
    # Decoder 1 at addr 1: ch1=mode, ch2=dim, ch3=R, ch4=G, ch5=B, ch6=W
    ("ch1=0, ch2=255, ch3=128 (6ch: mode=0, dim=255, R=128)",
     {1: 0, 2: 255, 3: 128}),
    ("ch1=0, ch2=255, ch4=128 (6ch: mode=0, dim=255, G=128)",
     {1: 0, 2: 255, 4: 128}),
]

for desc, ch_dict in phase4_tests:
    set_all(ch_dict)
    time.sleep(1.5)
    try:
        ans = input(f"  {desc:45s} --> ? ").strip()
    except (KeyboardInterrupt, EOFError):
        quit_flag = True
        break
    if ans.lower() == 'q':
        quit_flag = True
        break
    results.append((desc, ans))


# ── PHASE 5: Rapid sweep of ch5 with ch1=0 ──────────────────
if not quit_flag:
    print()
    print("─" * 65)
    print("  PHASE 5: Quick sweep of ch5 values (ch1=0, others=0)")
    print("  Just tell me the COLOR for each (not brightness)")
    print("─" * 65)
    print()

    for val in range(0, 256, 10):
        set_all({1: 0, 2: 0, 3: 0, 4: 0, 5: val})
        time.sleep(0.8)
        try:
            ans = input(f"  ch5={val:>3} --> color? ").strip()
        except (KeyboardInterrupt, EOFError):
            quit_flag = True
            break
        if ans.lower() == 'q':
            quit_flag = True
            break
        results.append((f"sweep ch5={val}", ans))


blackout()

# ── SUMMARY ──────────────────────────────────────────────────
print(f"\n{'=' * 65}")
print("  ALL RESULTS")
print(f"{'=' * 65}")
for desc, ans in results:
    print(f"  {desc:50s}: {ans}")

print(f"\n{'=' * 65}")
print("  ANALYSIS")
print(f"{'=' * 65}")
# Look for any test where ch5=128 produced red
hits = [(d, a) for d, a in results if '128' in d and 'red' in a.lower()]
if hits:
    print("  GOOD NEWS: These settings produced RED at ch5=128:")
    for d, a in hits:
        print(f"    {d}: {a}")
else:
    print("  No combination produced red at ch5=128.")
    print("  The decoder may need physical DIP switch changes.")
    print()
    print("  CHECK YOUR DECODER:")
    print("    1. Look for DIP switches or buttons on the DMX decoder board")
    print("    2. Look for a small display or LEDs showing mode")
    print("    3. DIP switch 10 is often 'test/function mode' - make sure it's OFF")
    print("    4. Some decoders have a 'MODE' button - press it to cycle modes")
    print("    5. Look for labels like '4CH' or 'RGBW' on the decoder")
print()
