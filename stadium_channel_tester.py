#!/usr/bin/env python3
"""
Stadium Pro II 1200x RGBW – Fast Channel Mapping Wizard
========================================================
Flashes one channel at a time (all others zeroed).  At each step you
type what you see and press Enter.  It records the label and moves on.

Known so far:
  Ch 1–4   : control / unknown (nothing visible when lit)
  Ch 5     : Red   \
  Ch 6     : Green  | Zone 1  (pattern repeats every 4 channels)
  Ch 7     : Blue   |
  Ch 8     : White /
  Ch 9–12  : Zone 2, 13–16: Zone 3, … etc.

Usage:
    python3 stadium_channel_tester.py
    python3 stadium_channel_tester.py --start-ch 5 --channels 60
    python3 stadium_channel_tester.py --host 192.168.1.50

At each prompt:
    f<N> <color>  – e.g.  f1 red   f2 white   f3 blue   f4 green
    <anything>    – freeform label  (strobe, dimmer, nothing, …)
    skip / s      – skip this channel, no label
    back / p      – go back one channel
    ?             – re-flash current channel
    done / q      – stop early, save & push labels
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("requests is required: pip install requests")

# ── ANSI helpers ───────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"
RED_C  = "\033[31m"

def c(text, *codes): return "".join(codes) + str(text) + RESET
def ok(txt):   print(c(f"  ✓ {txt}", GREEN))
def warn(txt): print(c(f"  ! {txt}", YELLOW))
def err(txt):  print(c(f"  ✗ {txt}", RED_C))

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def api_test_channel(sess, base_url, ch, val=220):
    """Zero all channels, then set ch=val.  Proven to work with this fixture."""
    try:
        r = sess.post(f"{base_url}/api/test-channel",
                      json={"channel": ch, "value": val}, timeout=5)
        r.raise_for_status()
        return True
    except Exception as exc:
        err(f"test-channel failed: {exc}")
        return False

def api_blackout(sess, base_url):
    try:
        sess.post(f"{base_url}/api/blackout", timeout=5).raise_for_status()
    except Exception as exc:
        err(f"blackout failed: {exc}")

def api_apply_labels(sess, base_url, labels: dict):
    try:
        r = sess.post(f"{base_url}/api/channel-labels",
                      json={"labels": {str(k): v for k, v in labels.items()}},
                      timeout=5)
        r.raise_for_status()
        return True
    except Exception as exc:
        err(f"apply-labels failed: {exc}")
        return False

def check_server(sess, base_url):
    try:
        r = sess.get(f"{base_url}/api/health", timeout=5)
        if r.status_code not in (200, 503):
            r.raise_for_status()
        return r.json()
    except Exception:
        return None

# ── Label parsing ──────────────────────────────────────────────────────────────

COLOR_ALIASES = {
    "r": "Red",   "red":   "Red",
    "g": "Green", "green": "Green",
    "b": "Blue",  "blue":  "Blue",
    "w": "White", "white": "White",
    "a": "Amber", "amber": "Amber",
    "uv": "UV",   "violet": "UV",
}

def parse_label(raw: str):
    raw = raw.strip()
    if not raw:
        return None
    parts = raw.lower().split()
    if parts[0].startswith("f") and parts[0][1:].isdigit():
        num      = parts[0][1:]
        color_in = " ".join(parts[1:]) if len(parts) > 1 else ""
        color    = COLOR_ALIASES.get(color_in, color_in.title())
        return f"F{num} {color}".strip() if color else f"F{num}"
    return " ".join(p.capitalize() for p in parts)

# ── Session helpers ────────────────────────────────────────────────────────────

SESSION_FILE = "stadium_mapping.json"

def load_mapping():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE) as f:
                return json.load(f).get("channels", {})
        except Exception:
            pass
    return {}

def save_mapping(mapping: dict):
    out = {
        "fixture":    "Stadium Pro II 1200x RGBW",
        "mapped_at":  datetime.now().isoformat(timespec="seconds"),
        "channels":   mapping,
    }
    with open(SESSION_FILE, "w") as f:
        json.dump(out, f, indent=2)
    ok(f"Saved → {SESSION_FILE}")

def print_summary(mapping: dict):
    print(c(f"\n  {'Ch':>4}  Label", BOLD))
    print("  " + "─" * 30)
    for ch_str in sorted(mapping, key=lambda x: int(x)):
        label  = mapping[ch_str].get("label", "(skipped)")
        colour = GREEN if label and label != "(skipped)" else DIM
        print(c(f"  {int(ch_str):>4}  {label}", colour))

def push_labels(http_sess, base_url, mapping: dict):
    labels = {ch: info["label"] for ch, info in mapping.items() if info.get("label")}
    if not labels:
        warn("No labels to push.")
        return
    if api_apply_labels(http_sess, base_url, labels):
        ok(f"Pushed {len(labels)} label(s) to DMX server.")
    else:
        err("Label push failed.")

# ── Wizard ─────────────────────────────────────────────────────────────────────

def run_wizard(args, base_url, http_sess):
    mapping  = load_mapping()
    if mapping:
        ok(f"Resumed from {SESSION_FILE}  ({len(mapping)} channels already mapped)")

    ch_list = list(range(args.start_ch, args.start_ch + args.channels))

    print(c(f"\n  Channels {ch_list[0]} → {ch_list[-1]}  |  "
            "flash value = 220 (all others zeroed)\n", DIM))
    print(c("  f<N> <color>  e.g.  f1 red  f2 white  f3 blue  f4 green", DIM))
    print(c("  skip/s=no label   back/p=go back   ?=re-flash   done/q=finish\n", DIM))

    i = 0
    while i < len(ch_list):
        ch     = ch_list[i]
        ch_str = str(ch)
        existing = mapping.get(ch_str, {}).get("label", "")

        # Flash: zero everything, set this channel to 220
        api_test_channel(http_sess, base_url, ch, 220)

        hint = c(f" [{existing}]", YELLOW) if existing else ""
        try:
            raw = input(c(f"  ch {ch:>3}", BOLD + CYAN) + hint + c(" → ", CYAN)).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if raw in ("done", "q", "quit"):
            break

        if raw in ("back", "p"):
            if i > 0:
                i -= 1
            else:
                warn("Already at first channel.")
            continue

        if raw in ("skip", "s", ""):
            i += 1
            continue

        if raw == "?":
            # blink off then back on
            api_blackout(http_sess, base_url)
            time.sleep(0.2)
            api_test_channel(http_sess, base_url, ch, 220)
            continue

        if raw == "b":
            api_blackout(http_sess, base_url)
            time.sleep(0.4)
            api_test_channel(http_sess, base_url, ch, 220)
            continue

        label = parse_label(raw)
        if label:
            mapping[ch_str] = {"label": label}
            ok(f"ch {ch} → {label}")
        else:
            warn("Not recorded. Try again or type 'skip'.")
            continue

        i += 1

    api_blackout(http_sess, base_url)
    print_summary(mapping)
    save_mapping(mapping)
    push_labels(http_sess, base_url, mapping)
    print(c("\n  Done – all channels blacked out.\n", BOLD))

# ── Entry point ────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Fast DMX channel mapper for Stadium Pro II 1200x RGBW")
    p.add_argument("--host",     default="localhost")
    p.add_argument("--port",     type=int, default=5000)
    p.add_argument("--start-ch", type=int, default=5, metavar="N",
                   help="First channel to test (default: 5 – skips control channels 1-4)")
    p.add_argument("--channels", type=int, default=60, metavar="N",
                   help="How many channels to step through (default: 60)")
    return p.parse_args()

def main():
    args     = parse_args()
    base_url = f"http://{args.host}:{args.port}"

    http_sess = requests.Session()
    http_sess.headers["Content-Type"] = "application/json"

    print(c(f"\nConnecting to {base_url} …", DIM))
    health = check_server(http_sess, base_url)
    if health is None:
        err(f"Cannot reach {base_url} – is app.py running?")
        sys.exit(1)

    enttec  = health.get("enttec_connected", False)
    artnet  = health.get("artnet_enabled",   False)
    running = health.get("dmx_running",      False)

    if enttec or artnet:
        ok(f"Server OK  |  ENTTEC={enttec}  Art-Net={artnet}  DMX running={running}")
    else:
        warn(f"NO output active (ENTTEC={enttec}, Art-Net={artnet}, dmx_running={running})")
        warn("Fixture will not respond until output is active.")

    run_wizard(args, base_url, http_sess)
    http_sess.close()

if __name__ == "__main__":
    main()
