#!/usr/bin/env python3
"""
Mode Finder - Quick test to find the decoder's manual RGBW mode.

Theory: The decoder at address 1 uses 8 channels per fixture:
  ch1-4 = control channels (mode, dimmer, strobe, speed)
  ch5-8 = RGBW

When we test with ch5=50 and all others=0, we see RED.
When we test with ch5=75, we see a WRONG color.

This means ch1-4 might need specific values to enable manual mode,
OR the decoder has a limited value range for direct RGBW control.

This script tests BOTH theories quickly.
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

def set_channels(ch_dict):
    """Set ALL 512 channels to 0, then apply ch_dict on top."""
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
    if ans.lower() == 'q':
        return None
    return ans

print("=" * 65)
print("  MODE FINDER")
print("=" * 65)
print()
print("  For each test, tell me the COLOR you see on FIXTURE 1.")
print("  Just type: red, blue, green, white, off, cycle, etc.")
print("  Press Enter if same as previous. Type 'q' to quit.")
print()

results = []

# ── TEST A: Baseline - does ch5=75 produce red or wrong color? ──
print("── TEST A: Baseline ──")
set_channels({5: 50})
time.sleep(1)
ans = ask("  ch5=50 (all others 0) --> color? ")
if ans is None:
    blackout(); sys.exit(0)
results.append(("A1: ch5=50, others=0", ans or "same"))

set_channels({5: 75})
time.sleep(1)
ans = ask("  ch5=75 (all others 0) --> color? ")
if ans is None:
    blackout(); sys.exit(0)
results.append(("A2: ch5=75, others=0", ans or "same"))

set_channels({5: 128})
time.sleep(1)
ans = ask("  ch5=128 (all others 0) --> color? ")
if ans is None:
    blackout(); sys.exit(0)
results.append(("A3: ch5=128, others=0", ans or "same"))

# ── TEST B: Try ch1=0, ch2=255 (mode=manual, dimmer=full?) ──
print("\n── TEST B: ch1=0, ch2=255 (dimmer theory) ──")
for val in [50, 75, 128]:
    set_channels({1: 0, 2: 255, 5: val})
    time.sleep(1)
    ans = ask(f"  ch1=0, ch2=255, ch5={val} --> color? ")
    if ans is None:
        blackout(); sys.exit(0)
    results.append((f"B: ch1=0,ch2=255,ch5={val}", ans or "same"))

# ── TEST C: Try ch1=255, ch2=255 ──
print("\n── TEST C: ch1=255, ch2=255 ──")
for val in [50, 75, 128]:
    set_channels({1: 255, 2: 255, 5: val})
    time.sleep(1)
    ans = ask(f"  ch1=255, ch2=255, ch5={val} --> color? ")
    if ans is None:
        blackout(); sys.exit(0)
    results.append((f"C: ch1=255,ch2=255,ch5={val}", ans or "same"))

# ── TEST D: Try ch1 at different mode values ──
print("\n── TEST D: Sweep ch1 with ch5=75 fixed ──")
print("  (ch5=75 showed wrong color in baseline - looking for a ch1 value that fixes it)")
for mode in [0, 1, 10, 50, 100, 127, 128, 150, 200, 255]:
    set_channels({1: mode, 5: 75})
    time.sleep(1)
    ans = ask(f"  ch1={mode:>3}, ch5=75 --> color? ")
    if ans is None:
        blackout(); sys.exit(0)
    results.append((f"D: ch1={mode},ch5=75", ans or "same"))
    # If we found red, highlight it
    if ans and 'red' in ans.lower():
        print(f"  *** ch1={mode} makes ch5=75 produce red! ***")

# ── TEST E: Maybe ch4 is mode, not ch1 ──
print("\n── TEST E: Sweep ch4 with ch5=75 fixed ──")
for mode in [0, 50, 100, 128, 200, 255]:
    set_channels({4: mode, 5: 75})
    time.sleep(1)
    ans = ask(f"  ch4={mode:>3}, ch5=75 --> color? ")
    if ans is None:
        blackout(); sys.exit(0)
    results.append((f"E: ch4={mode},ch5=75", ans or "same"))
    if ans and 'red' in ans.lower():
        print(f"  *** ch4={mode} makes ch5=75 produce red! ***")

# ── TEST F: Sweep ch5 value to find the actual usable range ──
print("\n── TEST F: Quick sweep of ch5 to find where red stops ──")
print("  (Just need: 'red' or the other color)")
for val in [10, 20, 30, 40, 50, 55, 60, 63, 64, 65, 70, 75, 80, 90, 100]:
    set_channels({5: val})
    time.sleep(0.8)
    ans = ask(f"  ch5={val:>3} --> color? ")
    if ans is None:
        blackout(); sys.exit(0)
    results.append((f"F: ch5={val}", ans or "same"))

blackout()

print(f"\n{'=' * 65}")
print("  RESULTS")
print(f"{'=' * 65}")
for desc, ans in results:
    marker = " <<<" if ans and 'red' in ans.lower() and '75' in desc else ""
    print(f"  {desc:40s}: {ans}{marker}")

# Check if any mode value fixed ch5=75
d_hits = [(d, a) for d, a in results if d.startswith("D:") and a and 'red' in a.lower()]
e_hits = [(d, a) for d, a in results if d.startswith("E:") and a and 'red' in a.lower()]

print(f"\n{'=' * 65}")
if d_hits or e_hits:
    print("  SOLUTION FOUND!")
    for d, a in d_hits + e_hits:
        print(f"    {d} = {a}")
    print("  These mode values make ch5=75 produce red (correct behavior).")
    print("  The web UI needs to keep these mode channels set permanently.")
else:
    print("  No mode channel value fixed the issue.")
    # Check the sweep results
    f_results = [(d, a) for d, a in results if d.startswith("F:")]
    red_vals = [d.split("=")[1] for d, a in f_results if a and 'red' in a.lower()]
    if red_vals:
        print(f"  Red values on ch5: {', '.join(red_vals)}")
        print(f"  The decoder has a limited range for direct RGBW control.")
        print(f"  We need to scale the web UI sliders to this range.")
    else:
        print("  Need to look at the physical decoder inside the fixture.")
        print("  There may be buttons, jumpers, or a small LCD for mode selection.")
print()
