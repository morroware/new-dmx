#!/usr/bin/env python3
"""
Dead-simple channel-by-channel test.
Blackouts the ENTIRE DMX universe, then sets ONE channel to ONE value.
Nothing else running, no pins, no tricks. Just raw DMX.

For each channel + value combo, you tell me exactly what you see.
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

# Verify server
try:
    s.get(f"{URL}/api/health", timeout=3).raise_for_status()
    print("Connected to DMX server.\n")
except Exception:
    sys.exit(f"Cannot reach {URL} -- is app.py running?")


def blackout():
    s.post(f"{URL}/api/blackout", timeout=3)

def solo(channel, value):
    """Blackout everything, then set exactly ONE channel."""
    s.post(f"{URL}/api/test-channel",
           json={"channel": channel, "value": value}, timeout=3)


print("=" * 60)
print("  CHANNEL TEST -- one channel at a time, clean DMX frame")
print("=" * 60)
print()
print("  For each test I will:")
print("    1. Blackout all 512 channels")
print("    2. Set ONE channel to the shown value")
print("    3. Wait for you to describe what you see")
print()
print("  Type what you see:")
print("    red, green, blue, white, off, strobe, colors, dim, etc.")
print("    Or just press Enter if nothing / no change")
print("    Type 'q' to quit")
print()

# Test channels 1-24 at values 0, 50, 128, 200, 255
test_values = [128, 200, 50, 255, 0]
results = {}

for ch in range(1, 25):
    print(f"\n{'─' * 50}")
    print(f"  CHANNEL {ch}")
    print(f"{'─' * 50}")

    ch_results = {}
    for val in test_values:
        blackout()
        time.sleep(0.15)
        solo(ch, val)
        time.sleep(0.5)

        try:
            ans = input(f"  ch {ch:>2} = {val:>3}  -->  what do you see? ").strip()
        except (KeyboardInterrupt, EOFError):
            blackout()
            print("\nDone.")
            sys.exit(0)

        if ans.lower() == 'q':
            blackout()
            # Print summary
            print("\n\n" + "=" * 60)
            print("  RESULTS SUMMARY")
            print("=" * 60)
            for rch, rvals in sorted(results.items()):
                responses = [f"{v}={r}" for v, r in sorted(rvals.items()) if r]
                if responses:
                    print(f"  ch {rch:>2}: {', '.join(responses)}")
            print()
            sys.exit(0)

        ch_results[val] = ans
        if ans:
            print(f"         recorded: {ans}")

    results[ch] = ch_results

    # Quick analysis
    non_empty = [v for v in ch_results.values() if v]
    unique = set(v.lower() for v in non_empty if v.lower() not in ('off', 'nothing', 'no', ''))
    if len(unique) == 1:
        print(f"  >>> Likely a {unique.pop().upper()} channel (same response at all levels)")
    elif len(unique) > 1:
        print(f"  >>> Changes behavior at different values -- probably MODE/MACRO channel")
    else:
        print(f"  >>> No visible response")


blackout()
print("\n\n" + "=" * 60)
print("  RESULTS SUMMARY")
print("=" * 60)
for ch, vals in sorted(results.items()):
    responses = [f"{v}={r}" for v, r in sorted(vals.items()) if r]
    if responses:
        print(f"  ch {ch:>2}: {', '.join(responses)}")
print()
