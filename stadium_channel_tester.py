#!/usr/bin/env python3
"""
Stadium Pro II 1200x RGBW – Fast Channel Mapping Wizard
========================================================
Flashes one channel at a time.  At each step you type what you see
(e.g. "f1 red", "f2 white", "strobe", "nothing") and press Enter.
It records the mapping, moves to the next channel automatically, and
pushes all labels to the DMX server when you finish.

Usage:
    python3 stadium_channel_tester.py [--host HOST] [--port PORT]
                                      [--start-ch N] [--channels N]

At each prompt type one of:
    f<N> <color>   – fixture N, colour name  (e.g.  f1 red,  f3 white)
    <anything>     – freeform label           (e.g.  strobe,  dimmer, nothing)
    ?              – re-flash this channel
    b              – blackout then re-flash
    skip / s       – skip (no label)
    back / p       – go back one channel
    done / q       – finish early, save & push
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

def api_test_channel(sess, base_url, ch, val):
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
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

# ── Label parsing ──────────────────────────────────────────────────────────────

# Colour aliases so "red", "r", "R" all work
COLOR_ALIASES = {
    "r": "Red", "red": "Red",
    "g": "Green", "green": "Green",
    "b": "Blue", "blue": "Blue",
    "w": "White", "white": "White",
    "a": "Amber", "amber": "Amber",
    "uv": "UV", "violet": "UV",
}

def parse_label(raw: str):
    """
    Convert user input to a clean label string.

    "f1 red"   → "F1 Red"
    "f2 w"     → "F2 White"
    "strobe"   → "Strobe"
    "f3"       → "F3"          (fixture without colour – unusual but valid)
    """
    raw = raw.strip()
    if not raw:
        return None

    parts = raw.lower().split()

    # fixture shorthand: f<N> [color]
    if parts[0].startswith("f") and parts[0][1:].isdigit():
        fixture_num = parts[0][1:]
        color_raw   = " ".join(parts[1:]) if len(parts) > 1 else ""
        color       = COLOR_ALIASES.get(color_raw, color_raw.title())
        label       = f"F{fixture_num} {color}".strip() if color else f"F{fixture_num}"
        return label

    # freeform – just title-case it
    return " ".join(p.capitalize() for p in parts)

# ── Core wizard ────────────────────────────────────────────────────────────────

FLASH_VALUE = 220   # bright but not blinding
FLASH_DELAY = 0.15  # short pause after setting channel so DMX frame arrives

SESSION_FILE = "stadium_mapping.json"

def save_mapping(mapping: dict, path: str):
    out = {
        "fixture": "Stadium Pro II 1200x RGBW",
        "mapped_at": datetime.now().isoformat(timespec="seconds"),
        "channels": mapping,
    }
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    ok(f"Mapping saved → {path}")


def push_labels(http_sess, base_url, mapping: dict):
    labels = {ch: info["label"] for ch, info in mapping.items()
              if info.get("label")}
    if not labels:
        warn("No labels to push.")
        return
    if api_apply_labels(http_sess, base_url, labels):
        ok(f"Pushed {len(labels)} label(s) to the DMX server.")
    else:
        err("Label push failed.")


def print_summary(mapping: dict):
    print(c(f"\n  {'Ch':>4}  Label", BOLD))
    print("  " + "─" * 30)
    for ch_str in sorted(mapping, key=lambda x: int(x)):
        label = mapping[ch_str].get("label", "(skipped)")
        colour = GREEN if label and label != "(skipped)" else DIM
        print(c(f"  {int(ch_str):>4}  {label}", colour))


def run_wizard(args, base_url, http_sess):
    total    = args.channels
    start_ch = args.start_ch
    mapping  = {}   # {str(ch): {"label": str}}

    # Load existing session so you can resume
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE) as f:
                loaded = json.load(f)
            mapping = loaded.get("channels", {})
            ok(f"Resumed from {SESSION_FILE}  ({len(mapping)} channels already mapped)")
        except Exception:
            pass

    print(c(f"\n  Channels {start_ch} → {start_ch + total - 1}  |  "
            f"Type what you see, Enter to advance.\n", DIM))
    print(c("  Format:  f<N> <color>   e.g.  f1 red   f2 white   f3 blue", DIM))
    print(c("  Other:   strobe / dimmer / nothing / skip / back / done\n", DIM))

    ch_list = list(range(start_ch, start_ch + total))
    i = 0

    while i < len(ch_list):
        ch = ch_list[i]
        ch_str = str(ch)
        existing = mapping.get(ch_str, {}).get("label", "")

        # Flash this channel
        api_test_channel(http_sess, base_url, ch, FLASH_VALUE)
        time.sleep(FLASH_DELAY)

        # Prompt
        existing_hint = c(f" [{existing}]", YELLOW) if existing else ""
        prompt_txt = (c(f"  ch {ch:>3}", BOLD + CYAN)
                      + existing_hint
                      + c(" → ", CYAN))
        try:
            raw = input(prompt_txt).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        # Commands
        if raw in ("done", "q", "quit"):
            break

        if raw in ("back", "p"):
            if i > 0:
                i -= 1
            else:
                warn("Already at first channel.")
            continue

        if raw in ("skip", "s", ""):
            # Leave any existing label intact, just move on
            i += 1
            continue

        if raw == "?":
            # Re-flash without advancing
            api_blackout(http_sess, base_url)
            time.sleep(0.1)
            api_test_channel(http_sess, base_url, ch, FLASH_VALUE)
            continue

        if raw == "b":
            api_blackout(http_sess, base_url)
            time.sleep(0.3)
            api_test_channel(http_sess, base_url, ch, FLASH_VALUE)
            continue

        # Record label
        label = parse_label(raw)
        if label:
            mapping[ch_str] = {"label": label}
            ok(f"ch {ch} → {label}")
        else:
            warn("Nothing recorded – try again or type 'skip'.")
            continue

        i += 1

    # Done
    api_blackout(http_sess, base_url)
    print_summary(mapping)
    save_mapping(mapping, SESSION_FILE)
    push_labels(http_sess, base_url, mapping)
    print(c("\n  All channels blacked out.  Mapping complete.\n", BOLD))


# ── Entry point ────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Fast step-by-step DMX channel mapper for Stadium Pro II 1200x RGBW")
    p.add_argument("--host",     default="localhost")
    p.add_argument("--port",     type=int, default=5000)
    p.add_argument("--start-ch", type=int, default=1, metavar="N",
                   help="First channel to test (default: 1)")
    p.add_argument("--channels", type=int, default=32, metavar="N",
                   help="How many channels to step through (default: 32)")
    return p.parse_args()


def main():
    args = parse_args()
    base_url = f"http://{args.host}:{args.port}"

    http_sess = requests.Session()
    http_sess.headers["Content-Type"] = "application/json"

    print(c(f"\nConnecting to {base_url} …", DIM))
    health = check_server(http_sess, base_url)
    if health is None:
        err(f"Cannot reach {base_url} – is app.py running?")
        sys.exit(1)
    ok(f"Server OK  (ENTTEC={health.get('enttec_connected')}, "
       f"Art-Net={health.get('artnet_enabled')})")

    run_wizard(args, base_url, http_sess)
    http_sess.close()


if __name__ == "__main__":
    main()
