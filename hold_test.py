#!/usr/bin/env python3
"""
Hold test -- sets channels and HOLDS them steady so you can observe
whether the light is stable or cycling through colors on its own.

Also tests whether channels 1-4 need specific values to put
the decoder into manual DMX mode.
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
    """Blackout first, then set channels. Clean frame."""
    s.post(f"{URL}/api/blackout", timeout=3)
    time.sleep(0.1)
    s.post(f"{URL}/api/channels",
           json={"channels": {str(k): v for k, v in ch_dict.items()}}, timeout=3)


print("=" * 60)
print("  HOLD TEST -- watch each test for 5-10 seconds")
print("=" * 60)
print()
print("  I'll set channels and HOLD them steady.")
print("  Watch carefully: does the color STAY FIXED or CYCLE/CHANGE?")
print()
print("  Answer:")
print("    'red'     = steady red light")
print("    'cycle'   = light is cycling/changing colors on its own")
print("    'off'     = no light")
print("    'green'   = steady green")
print("    Or describe what you see")
print("    'q' = quit")
print()

tests = [
    # Description, channel dict
    ("TEST 1: ch5=50 only (hold 10s -- watch if color changes)",
     {5: 50}),

    ("TEST 2: ch5=50, ch1=0 (does ch1 at 0 change anything?)",
     {1: 0, 5: 50}),

    ("TEST 3: ch1=0, ch2=0, ch3=0, ch4=0, ch5=50",
     {1: 0, 2: 0, 3: 0, 4: 0, 5: 50}),

    ("TEST 4: ch1=0, ch2=0, ch3=0, ch4=0, ch5=100",
     {1: 0, 2: 0, 3: 0, 4: 0, 5: 100}),

    ("TEST 5: ch1=0, ch2=0, ch3=0, ch4=0, ch5=200",
     {1: 0, 2: 0, 3: 0, 4: 0, 5: 200}),

    ("TEST 6: ch5=50, ch6=50 (should be red+green=yellow?)",
     {1: 0, 2: 0, 3: 0, 4: 0, 5: 50, 6: 50}),

    ("TEST 7: ch5=50, ch6=50, ch7=50 (R+G+B=white?)",
     {1: 0, 2: 0, 3: 0, 4: 0, 5: 50, 6: 50, 7: 50}),

    ("TEST 8: ch5=50, ch6=50, ch7=50, ch8=50 (RGBW all on?)",
     {1: 0, 2: 0, 3: 0, 4: 0, 5: 50, 6: 50, 7: 50, 8: 50}),

    # Maybe the decoder reads from ch1 not ch5?
    ("TEST 9: ch1=50 only (is ch1 actually Red?)",
     {1: 50}),

    ("TEST 10: ch1=50, ch2=50, ch3=50, ch4=50",
     {1: 50, 2: 50, 3: 50, 4: 50}),

    # Try with different values in case 50 hits a program boundary
    ("TEST 11: ch5=25 only",
     {5: 25}),

    ("TEST 12: ch5=75 only",
     {5: 75}),

    ("TEST 13: ch5=150 only",
     {5: 150}),

    # Maybe it's 8-channel mode: mode, dim, R, G, B, W, strobe, speed
    # With decoder at address 1: ch1=mode, ch2=dim, ch3=R, ch4=G, ch5=B, ch6=W
    ("TEST 14: ch1=0 (mode=manual), ch2=255 (dimmer), ch3=50 (Red?)",
     {1: 0, 2: 255, 3: 50}),

    ("TEST 15: ch1=0, ch2=255, ch4=50 (Green?)",
     {1: 0, 2: 255, 4: 50}),

    ("TEST 16: ch1=0, ch2=255, ch5=50 (Blue?)",
     {1: 0, 2: 255, 5: 50}),

    ("TEST 17: ch1=0, ch2=255, ch3=50, ch4=50, ch5=50, ch6=50 (all color?)",
     {1: 0, 2: 255, 3: 50, 4: 50, 5: 50, 6: 50}),
]

for desc, ch_dict in tests:
    print(f"\n{'─' * 60}")
    print(f"  {desc}")
    ch_str = ", ".join(f"ch{k}={v}" for k, v in sorted(ch_dict.items()))
    print(f"  Setting: {ch_str}")
    print(f"{'─' * 60}")

    set_channels(ch_dict)

    print("  >>> Watch the light for 5-10 seconds <<<")
    try:
        ans = input("  What do you see? ").strip()
    except (KeyboardInterrupt, EOFError):
        break

    if ans.lower() == 'q':
        break

    print(f"  Recorded: {ans}")

blackout()
print("\nDone -- all channels blacked out.")
