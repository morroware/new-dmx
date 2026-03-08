#!/usr/bin/env python3
"""
Stadium Pro II 1200x RGBW – Channel Discovery & Mapping Tester
===============================================================
Connects to the local DMX Flask server (app.py) and systematically
tests every channel so you can observe what each one does and build
an accurate fixture profile from scratch.

Usage:
    python3 stadium_channel_tester.py [--host HOST] [--port PORT] [--start-ch N] [--channels N]

Quick-start:
    python3 stadium_channel_tester.py          # assumes server at localhost:5000
    python3 stadium_channel_tester.py --host 192.168.1.50 --port 5000

Controls (interactive menu shown at runtime):
    s  – sweep current channel 0 → 255 → 0
    v  – set channel to a specific value
    n  – move to next channel
    p  – move to previous channel
    g  – jump to a specific channel number
    b  – blackout (all channels 0)
    r  – run automatic channel scan (all channels, brief flash each)
    c  – run colour-combo quick-test (helps identify R/G/B/W channels)
    e  – test effect channels in common value bands
    l  – label / annotate the current channel
    d  – dump current discovery session
    S  – save session to JSON file
    L  – load session from JSON file
    A  – apply discovered mappings to the DMX server as channel labels
    q  – quit
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

# ── Colour helpers (ANSI) ──────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
MAGENTA= "\033[35m"
WHITE  = "\033[97m"
DIM    = "\033[2m"

def c(text, *codes): return "".join(codes) + str(text) + RESET
def header(txt): print(c(f"\n{'─'*60}\n  {txt}\n{'─'*60}", BOLD, CYAN))
def ok(txt): print(c(f"  ✓ {txt}", GREEN))
def warn(txt): print(c(f"  ! {txt}", YELLOW))
def err(txt): print(c(f"  ✗ {txt}", RED))
def info(txt): print(c(f"  · {txt}", DIM))

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def api_test_channel(session, base_url, channel, value):
    """POST /api/test-channel  – isolates one channel, zeros the rest."""
    try:
        r = session.post(
            f"{base_url}/api/test-channel",
            json={"channel": channel, "value": value},
            timeout=5,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        err(f"api_test_channel failed: {exc}")
        return False


def api_set_channels(session, base_url, channel_dict):
    """POST /api/channels  – sets multiple channels simultaneously."""
    try:
        r = session.post(
            f"{base_url}/api/channels",
            json={"channels": {str(k): v for k, v in channel_dict.items()}},
            timeout=5,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        err(f"api_set_channels failed: {exc}")
        return False


def api_blackout(session, base_url):
    try:
        r = session.post(f"{base_url}/api/blackout", timeout=5)
        r.raise_for_status()
        return True
    except Exception as exc:
        err(f"blackout failed: {exc}")
        return False


def api_apply_labels(session, base_url, labels: dict):
    """POST /api/channel-labels  – saves label strings for channels."""
    try:
        r = session.post(
            f"{base_url}/api/channel-labels",
            json={"labels": {str(k): v for k, v in labels.items()}},
            timeout=5,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        err(f"apply_labels failed: {exc}")
        return False


def check_server(session, base_url):
    try:
        r = session.get(f"{base_url}/api/health", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

# ── Sweep helpers ──────────────────────────────────────────────────────────────

def sweep_channel(session, base_url, channel, step=5, delay=0.04, hold=1.0):
    """Ramp channel 0→255→0 so you can watch the effect."""
    print(c(f"  Sweeping ch {channel} ▲ 0→255 ...", YELLOW))
    for v in range(0, 256, step):
        api_test_channel(session, base_url, channel, v)
        time.sleep(delay)
    print(c(f"  Peak (255) – holding {hold}s ...", YELLOW))
    time.sleep(hold)
    print(c(f"  Sweeping ch {channel} ▼ 255→0 ...", YELLOW))
    for v in range(255, -1, -step):
        api_test_channel(session, base_url, channel, v)
        time.sleep(delay)
    ok("Sweep complete – channel left at 0")


def flash_channel(session, base_url, channel, value=255, on_time=0.6, off_time=0.3):
    """Flash once at `value` then back to 0."""
    api_test_channel(session, base_url, channel, value)
    time.sleep(on_time)
    api_test_channel(session, base_url, channel, 0)
    time.sleep(off_time)


def test_value_bands(session, base_url, channel):
    """
    Pause at common effect/mode band boundaries so you can observe
    what changes at each threshold.  Useful for strobe, program, speed…
    """
    bands = [
        (0,   "Off / 0"),
        (1,   "Low (1)"),
        (10,  "Band 1–10 start"),
        (26,  "Band ~10%"),
        (51,  "Band ~20%"),
        (77,  "Band ~30%"),
        (102, "Band ~40%"),
        (128, "Band ~50% / mid"),
        (153, "Band ~60%"),
        (179, "Band ~70%"),
        (204, "Band ~80%"),
        (230, "Band ~90%"),
        (240, "High-end band"),
        (255, "Max (255)"),
    ]
    print()
    print(c(f"  Effect-band scan on channel {channel}", BOLD))
    print(c("  Press Enter at each step to advance (Ctrl-C to abort).", DIM))
    for val, label in bands:
        api_test_channel(session, base_url, channel, val)
        try:
            input(c(f"    ch{channel} = {val:>3}  ({label}) → ", CYAN))
        except (KeyboardInterrupt, EOFError):
            print()
            break
    api_test_channel(session, base_url, channel, 0)
    ok("Band scan complete – channel left at 0")


# ── Colour combo tests ─────────────────────────────────────────────────────────

COLOUR_COMBOS = [
    # label, {ch_offset: value} – offsets relative to user-chosen start address
    ("Blackout",         {}),
    ("Ch1 = 255 only",   {1: 255}),
    ("Ch2 = 255 only",   {2: 255}),
    ("Ch3 = 255 only",   {3: 255}),
    ("Ch4 = 255 only",   {4: 255}),
    ("Ch5 = 255 only",   {5: 255}),
    ("Ch6 = 255 only",   {6: 255}),
    ("Ch7 = 255 only",   {7: 255}),
    ("Ch8 = 255 only",   {8: 255}),
    ("Ch1+Ch2+Ch3 = 255 (RGB white?)",      {1: 255, 2: 255, 3: 255}),
    ("Ch1+Ch2 = 255 (yellow?)",             {1: 255, 2: 255}),
    ("Ch1+Ch3 = 255 (magenta?)",            {1: 255, 3: 255}),
    ("Ch2+Ch3 = 255 (cyan?)",               {2: 255, 3: 255}),
    ("Ch1=255 Ch2=128 Ch3=0 (orange?)",     {1: 255, 2: 128, 3: 0}),
    ("All 4 colour chs at 255 (RGBW full)", {1: 255, 2: 255, 3: 255, 4: 255}),
    ("Blackout (end)",   {}),
]

def colour_combo_test(session, base_url, start_ch):
    """
    Fires common colour combinations relative to `start_ch`.
    Helps you identify which offsets are R, G, B, W.
    """
    header(f"Colour-Combo Quick-Test  (start channel = {start_ch})")
    print(c("  Watch the light carefully.", DIM))
    print(c("  Press Enter at each step (Ctrl-C to skip).", DIM))
    for label, offsets in COLOUR_COMBOS:
        # build absolute channel dict, zero everything in range first
        ch_vals = {}
        for off in range(1, 9):
            ch_vals[start_ch + off - 1] = offsets.get(off, 0)
        api_set_channels(session, base_url, ch_vals)
        try:
            input(c(f"    {label} → ", CYAN))
        except (KeyboardInterrupt, EOFError):
            print()
            break
    api_blackout(session, base_url)
    ok("Colour-combo test done – blacked out")


# ── Auto channel scan ─────────────────────────────────────────────────────────

COLOR_SHORTHANDS = {
    "r": "Red", "g": "Green", "b": "Blue", "w": "White",
    "a": "Amber", "uv": "UV", "s": "Strobe", "d": "Dimmer",
    "m": "Master", "p": "Program", "sp": "Speed",
}

def auto_scan(session, base_url, start_ch, num_channels, sess_channels):
    """
    Light each channel one at a time and ask: fixture number + color.
    Builds a mapping you can push to the server with 'A'.
    """
    header(f"Mapping scan: channels {start_ch} → {start_ch + num_channels - 1}")
    print(c("  Channel lights up at 255. Type what you see, then Enter.", DIM))
    print(c("  Format:  <fixture#> <color>   e.g.  1 red   2 w   3 blue", DIM))
    print(c("  Shortcuts: r=Red  g=Green  b=Blue  w=White  a=Amber  uv=UV", DIM))
    print(c("             s=Strobe  d=Dimmer  m=Master  p=Program  sp=Speed", DIM))
    print(c("  skip/s = no label   back/b = go back   done/q = stop early\n", DIM))

    ch_list = list(range(start_ch, start_ch + num_channels))
    i = 0
    while i < len(ch_list):
        ch = ch_list[i]
        existing = sess_channels.get(str(ch), {}).get("label", "")

        api_test_channel(session, base_url, ch, 255)

        hint = c(f" [{existing}]", YELLOW) if existing else ""
        try:
            raw = input(c(f"  ch {ch:>3}", BOLD + CYAN) + hint + c(" → ", CYAN)).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if raw in ("done", "q"):
            break

        if raw in ("back", "b"):
            if i > 0:
                i -= 1
            else:
                warn("Already at first channel.")
            continue

        if raw in ("skip", "s", ""):
            i += 1
            continue

        # parse "<fixture_num> <color>" or freeform
        parts = raw.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            fixture = parts[0]
            color_in = parts[1].lower()
            color = COLOR_SHORTHANDS.get(color_in, color_in.title())
            label = f"F{fixture} {color}"
        elif len(parts) == 1 and parts[0].isdigit():
            label = f"F{parts[0]}"
        else:
            # freeform
            words = raw.lower().split()
            label = " ".join(COLOR_SHORTHANDS.get(w, w.title()) for w in words)

        sess_channels[str(ch)] = {"label": label}
        ok(f"ch {ch} → {label}")
        i += 1

    api_blackout(session, base_url)
    ok("Mapping scan complete – blacked out")


# ── Session data management ───────────────────────────────────────────────────

def default_session(start_ch, num_channels):
    return {
        "fixture": "Stadium Pro II 1200x RGBW",
        "created": datetime.now().isoformat(timespec="seconds"),
        "start_channel": start_ch,
        "num_channels": num_channels,
        "channels": {},   # keyed by str(channel_number)
    }


def print_session(sess):
    header("Current Discovery Session")
    print(f"  Fixture  : {sess['fixture']}")
    print(f"  Created  : {sess['created']}")
    print(f"  Start ch : {sess['start_channel']}")
    print(f"  # chs    : {sess['num_channels']}")
    print()
    if not sess["channels"]:
        warn("No channels annotated yet.")
        return
    print(c(f"  {'Ch':>4}  {'Label':<22}  {'Value hint':<14}  Notes", BOLD))
    print("  " + "─"*62)
    for ch_str in sorted(sess["channels"], key=lambda x: int(x)):
        ch_info = sess["channels"][ch_str]
        label  = ch_info.get("label", "")
        notes  = ch_info.get("notes", "")
        vhint  = ch_info.get("value_hint", "")
        print(f"  {int(ch_str):>4}  {label:<22}  {vhint:<14}  {notes}")


def save_session(sess, path):
    with open(path, "w") as f:
        json.dump(sess, f, indent=2)
    ok(f"Session saved → {path}")


def load_session(path):
    with open(path) as f:
        return json.load(f)


def annotate_channel(sess, channel):
    ch_str = str(channel)
    existing = sess["channels"].get(ch_str, {})
    print()
    print(c(f"  Annotating channel {channel}", BOLD))
    print(c("  (Press Enter to keep existing value)", DIM))

    label = input(c(f"    Label [{existing.get('label','')}]: ", CYAN)).strip()
    if label:
        existing["label"] = label

    notes = input(c(f"    Notes [{existing.get('notes','')}]: ", CYAN)).strip()
    if notes:
        existing["notes"] = notes

    vhint = input(c(f"    Value hint, e.g. '0-127=slow, 128-255=fast' [{existing.get('value_hint','')}]: ", CYAN)).strip()
    if vhint:
        existing["value_hint"] = vhint

    sess["channels"][ch_str] = existing
    ok(f"Channel {channel} annotated.")


# ── Known channel type suggestions ────────────────────────────────────────────

COMMON_CHANNEL_TYPES = [
    "Dimmer/Master",
    "Red",
    "Green",
    "Blue",
    "White",
    "Amber",
    "UV/Violet",
    "Strobe",
    "Flash Rate",
    "Color Macro",
    "Program/Mode",
    "Program Speed",
    "Pan",
    "Tilt",
    "Zoom",
    "Focus",
    "Reset/Control",
    "Unknown",
]

def suggest_label():
    print(c("\n  Common channel types:", DIM))
    for i, t in enumerate(COMMON_CHANNEL_TYPES, 1):
        print(c(f"    {i:>2}. {t}", DIM))
    choice = input(c("    Pick number or type custom label: ", CYAN)).strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(COMMON_CHANNEL_TYPES):
            return COMMON_CHANNEL_TYPES[idx]
    except ValueError:
        pass
    return choice


# ── Apply mappings back to DMX server ─────────────────────────────────────────

def apply_mappings_to_server(session, http_session, base_url):
    """Push discovered channel labels to the DMX server."""
    labels = {}
    for ch_str, info in session["channels"].items():
        label = info.get("label", "").strip()
        if label:
            labels[int(ch_str)] = label
    if not labels:
        warn("No labelled channels to apply.")
        return
    print(c(f"\n  Applying {len(labels)} channel label(s) to {base_url} …", YELLOW))
    if api_apply_labels(http_session, base_url, labels):
        ok(f"Labels applied: {labels}")
    else:
        err("Failed to apply labels – check server connection.")


# ── Main interactive loop ──────────────────────────────────────────────────────

MENU = f"""
{c('Commands', BOLD)}
  {c('s', CYAN)}  sweep channel 0→255→0          {c('v', CYAN)}  set channel to specific value
  {c('n', CYAN)}  next channel                    {c('p', CYAN)}  previous channel
  {c('g', CYAN)}  jump to channel #               {c('b', CYAN)}  blackout all channels
  {c('r', CYAN)}  mapping scan (label each ch)    {c('c', CYAN)}  colour-combo quick test
  {c('e', CYAN)}  effect band step-through        {c('l', CYAN)}  label / annotate channel
  {c('k', CYAN)}  pick label from common list     {c('d', CYAN)}  dump session to terminal
  {c('S', CYAN)}  save session to JSON file       {c('L', CYAN)}  load session from JSON
  {c('A', CYAN)}  apply labels to DMX server      {c('q', CYAN)}  quit
"""


def prompt(current_ch, label):
    tag = c(f" [{label}]", YELLOW) if label else ""
    return input(c(f"\n  ch {current_ch}{tag} > ", BOLD + CYAN)).strip()


def run_interactive(args, base_url, http_session, sess):
    current_ch = args.start_ch
    session_file = args.session_file

    header("Stadium Pro II 1200x RGBW – Channel Tester")
    print(c(f"  Server  : {base_url}", DIM))
    print(c(f"  Start ch: {args.start_ch}   |   Testing {args.channels} channels   |   Fixture start = ch {args.start_ch}", DIM))
    print(MENU)

    while True:
        ch_info = sess["channels"].get(str(current_ch), {})
        current_label = ch_info.get("label", "")

        try:
            cmd = prompt(current_ch, current_label)
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not cmd:
            # Poke the channel at 255 so something is visible
            api_test_channel(http_session, base_url, current_ch, 255)
            info(f"Channel {current_ch} set to 255 (all others 0).  Use 'b' to blackout.")
            continue

        cmd0 = cmd[0].lower() if cmd else ""

        # ── navigation ────────────────────────────────────────────────
        if cmd == "n" or cmd == "next":
            next_ch = current_ch + 1
            if next_ch >= args.start_ch + args.channels:
                warn("Already at last channel.")
            else:
                current_ch = next_ch
                api_test_channel(http_session, base_url, current_ch, 255)
                info(f"→ Channel {current_ch}")

        elif cmd == "p" or cmd == "prev":
            if current_ch <= args.start_ch:
                warn("Already at first channel.")
            else:
                current_ch -= 1
                api_test_channel(http_session, base_url, current_ch, 255)
                info(f"← Channel {current_ch}")

        elif cmd0 == "g":
            try:
                ch = int(cmd.split()[1]) if len(cmd.split()) > 1 else int(input(c("    Jump to channel #: ", CYAN)))
                if args.start_ch <= ch < args.start_ch + args.channels:
                    current_ch = ch
                    api_test_channel(http_session, base_url, current_ch, 255)
                    info(f"Jumped to channel {current_ch}")
                else:
                    warn(f"Channel {ch} outside test range ({args.start_ch}–{args.start_ch+args.channels-1})")
            except (ValueError, EOFError):
                warn("Invalid channel number.")

        # ── blackout ──────────────────────────────────────────────────
        elif cmd0 == "b":
            api_blackout(http_session, base_url)
            ok("Blackout")

        # ── sweep ─────────────────────────────────────────────────────
        elif cmd0 == "s":
            sweep_channel(http_session, base_url, current_ch)

        # ── set value ─────────────────────────────────────────────────
        elif cmd0 == "v":
            try:
                parts = cmd.split()
                val = int(parts[1]) if len(parts) > 1 else int(input(c("    Value (0-255): ", CYAN)))
                val = max(0, min(255, val))
                api_test_channel(http_session, base_url, current_ch, val)
                info(f"Channel {current_ch} = {val}")
            except (ValueError, EOFError):
                warn("Invalid value.")

        # ── auto scan ─────────────────────────────────────────────────
        elif cmd0 == "r":
            try:
                confirm = input(c(f"    Map channels {args.start_ch}–{args.start_ch+args.channels-1}? [y/N]: ", YELLOW)).strip().lower()
            except EOFError:
                confirm = "n"
            if confirm == "y":
                auto_scan(http_session, base_url, args.start_ch, args.channels, sess["channels"])

        # ── colour combo ─────────────────────────────────────────────
        elif cmd0 == "c":
            colour_combo_test(http_session, base_url, args.start_ch)

        # ── effect bands ──────────────────────────────────────────────
        elif cmd0 == "e":
            test_value_bands(http_session, base_url, current_ch)

        # ── annotate ──────────────────────────────────────────────────
        elif cmd0 == "l":
            annotate_channel(sess, current_ch)

        elif cmd0 == "k":
            label = suggest_label()
            if label:
                ch_str = str(current_ch)
                sess["channels"].setdefault(ch_str, {})["label"] = label
                ok(f"Channel {current_ch} labelled as '{label}'")

        # ── dump ──────────────────────────────────────────────────────
        elif cmd0 == "d":
            print_session(sess)

        # ── save / load ───────────────────────────────────────────────
        elif cmd == "S":
            path = input(c(f"    Save to [{session_file}]: ", CYAN)).strip() or session_file
            save_session(sess, path)
            session_file = path

        elif cmd == "L":
            path = input(c(f"    Load from [{session_file}]: ", CYAN)).strip() or session_file
            if os.path.exists(path):
                sess.update(load_session(path))
                ok(f"Session loaded from {path}")
            else:
                err(f"File not found: {path}")

        # ── apply to server ───────────────────────────────────────────
        elif cmd == "A":
            apply_mappings_to_server(sess, http_session, base_url)

        # ── quit ──────────────────────────────────────────────────────
        elif cmd0 == "q":
            try:
                save = input(c("  Save session before quitting? [Y/n]: ", YELLOW)).strip().lower()
            except EOFError:
                save = "n"
            if save != "n":
                save_session(sess, session_file)
            api_blackout(http_session, base_url)
            print(c("\n  Goodbye – all channels blacked out.\n", BOLD))
            break

        elif cmd0 == "?":
            print(MENU)

        else:
            warn(f"Unknown command '{cmd}'.  Type '?' for help.")

# ── Entry point ────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Interactive DMX channel tester for Stadium Pro II 1200x RGBW",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--host", default="localhost", help="Flask server host (default: localhost)")
    p.add_argument("--port", type=int, default=5000, help="Flask server port (default: 5000)")
    p.add_argument("--start-ch", type=int, default=5, metavar="N",
                   help="First DMX channel to test (default: 5, first visible RGBW channel)")
    p.add_argument("--channels", type=int, default=60, metavar="N",
                   help="How many channels to probe (default: 60)")
    p.add_argument("--session-file", default="stadium_discovery.json", metavar="FILE",
                   help="JSON file to save/load discovery session (default: stadium_discovery.json)")
    p.add_argument("--auto-scan", action="store_true",
                   help="Run auto-scan immediately on startup then enter interactive mode")
    return p.parse_args()


def main():
    args = parse_args()
    base_url = f"http://{args.host}:{args.port}"

    http_session = requests.Session()
    http_session.headers.update({"Content-Type": "application/json"})

    print(c(f"\nConnecting to DMX server at {base_url} …", DIM))
    health = check_server(http_session, base_url)
    if health is None:
        err(f"Cannot reach {base_url}  – is app.py running?")
        err("Start it with:  python3 app.py   or   sudo systemctl start dmx")
        sys.exit(1)

    status_str = health.get("status", "unknown")
    enttec_ok   = health.get("enttec_connected", False)
    artnet_ok   = health.get("artnet_enabled", False)
    ok(f"Server reachable  (status={status_str}, ENTTEC={enttec_ok}, Art-Net={artnet_ok})")

    if not enttec_ok and not artnet_ok:
        warn("Neither ENTTEC nor Art-Net appears active – DMX may not reach the fixture.")
        warn("You can still run the tester; commands will be stored by the server.")

    # Load or create session
    sess = default_session(args.start_ch, args.channels)
    if os.path.exists(args.session_file):
        try:
            loaded = load_session(args.session_file)
            sess.update(loaded)
            ok(f"Auto-loaded previous session from {args.session_file}")
        except Exception as exc:
            warn(f"Could not load {args.session_file}: {exc}  – starting fresh.")

    if args.auto_scan:
        auto_scan(http_session, base_url, args.start_ch, args.channels, sess["channels"])

    run_interactive(args, base_url, http_session, sess)

    http_session.close()


if __name__ == "__main__":
    main()
