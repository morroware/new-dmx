#!/usr/bin/env python3
"""
Stadium Pro II 1200x RGBW – Channel Discovery & Mapping Tester
===============================================================
Connects to the local DMX Flask server (app.py) and systematically
tests every channel so you can observe what each one does and build
an accurate fixture profile from scratch.

CONFIRMED mapping (as of initial testing):
  Ch 1–4  : Unknown control channels (still being discovered)
  Ch 5    : Red
  Ch 6    : Green
  Ch 7    : Blue
  Ch 8    : White
  Ch 9–12 : Zone 2 RGBW  (same pattern repeats every 4 channels)
  Ch 13–16: Zone 3 RGBW
  … and so on until the fixture runs out of zones.

Usage:
    python3 stadium_channel_tester.py [options]

    --host HOST         Flask server host (default: localhost)
    --port PORT         Flask server port (default: 5000)
    --start-ch N        First channel to include in tests (default: 1)
    --channels N        Total channels to probe (default: 32)
    --groups N          How many RGBW zones the fixture has (default: 8;
                        use 'z' command to find the real count)
    --session-file FILE JSON file for save/load (default: stadium_discovery.json)
    --auto-scan         Flash all channels on startup, then enter interactive mode

Interactive commands (shown again with '?'):
    s  – sweep current channel 0→255→0
    v  – set channel to a specific value
    n  – next channel              p  – previous channel
    g  – jump to channel #         b  – blackout
    r  – auto-scan all channels    c  – colour-combo test (RGBW absolute)
    z  – zone-step test            e  – effect band step-through
    l  – annotate channel          k  – pick label from list
    W  – write all known RGBW labels to session + server
    d  – dump session              S  – save session to JSON
    L  – load session from JSON    A  – apply labels to DMX server
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

# ── Confirmed fixture constants ────────────────────────────────────────────────

# These are confirmed correct from physical testing.
RGBW_START      = 5   # first Red channel
RGBW_GROUP_SIZE = 4   # R, G, B, W  (4 channels per zone)
# Offset within a group: 0=Red 1=Green 2=Blue 3=White
GROUP_COLORS    = ["Red", "Green", "Blue", "White"]

# Channels before the RGBW block – still under discovery.
PRE_CHANNELS = list(range(1, RGBW_START))  # [1, 2, 3, 4]

# ── ANSI colour helpers ────────────────────────────────────────────────────────

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
def ok(txt):   print(c(f"  ✓ {txt}", GREEN))
def warn(txt): print(c(f"  ! {txt}", YELLOW))
def err(txt):  print(c(f"  ✗ {txt}", RED))
def info(txt): print(c(f"  · {txt}", DIM))

# ── RGBW mapping helpers ───────────────────────────────────────────────────────

def zone_of(ch):
    """Return (zone_index_0, color_name) if ch is in the RGBW block, else None."""
    if ch < RGBW_START:
        return None
    offset = (ch - RGBW_START) % RGBW_GROUP_SIZE
    zone   = (ch - RGBW_START) // RGBW_GROUP_SIZE
    return zone, GROUP_COLORS[offset]


def zone_channels(zone_index):
    """Return the 4 absolute channel numbers for zone_index (0-based)."""
    base = RGBW_START + zone_index * RGBW_GROUP_SIZE
    return list(range(base, base + RGBW_GROUP_SIZE))


def build_rgbw_labels(num_groups):
    """
    Generate {channel: label} for all RGBW zone channels given the
    total number of zones.  Zone 1 channels get simple labels;
    subsequent zones are prefixed "Z2 ", "Z3 ", etc.
    """
    labels = {}
    for z in range(num_groups):
        for color_offset, color_name in enumerate(GROUP_COLORS):
            ch = RGBW_START + z * RGBW_GROUP_SIZE + color_offset
            prefix = f"Z{z+1} " if num_groups > 1 else ""
            labels[ch] = f"{prefix}{color_name}"
    return labels


def channel_display_name(ch, num_groups):
    """Human-readable name for any channel."""
    if ch in PRE_CHANNELS:
        return f"Ch {ch} (control – TBD)"
    result = zone_of(ch)
    if result is None:
        return f"Ch {ch}"
    zone, color = result
    if zone >= num_groups:
        return f"Ch {ch} (beyond configured zones)"
    zone_label = f"Zone {zone+1}" if num_groups > 1 else "Zone 1"
    return f"Ch {ch} – {zone_label} {color}"

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def api_test_channel(session, base_url, channel, value):
    """POST /api/test-channel – isolates one channel, zeros the rest."""
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
    """POST /api/channels – set multiple channels at once."""
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
    """POST /api/channel-labels – persist label strings in the server."""
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

# ── Sweep / flash helpers ──────────────────────────────────────────────────────

def sweep_channel(session, base_url, channel, step=5, delay=0.04, hold=1.0):
    """Ramp channel 0→255→0."""
    print(c(f"  Sweeping ch {channel} ▲ 0→255 …", YELLOW))
    for v in range(0, 256, step):
        api_test_channel(session, base_url, channel, v)
        time.sleep(delay)
    print(c(f"  Peak (255) – holding {hold}s …", YELLOW))
    time.sleep(hold)
    print(c(f"  Sweeping ch {channel} ▼ 255→0 …", YELLOW))
    for v in range(255, -1, -step):
        api_test_channel(session, base_url, channel, v)
        time.sleep(delay)
    ok("Sweep complete – channel left at 0")


def flash_channel(session, base_url, channel, value=255, on_time=0.6, off_time=0.3):
    api_test_channel(session, base_url, channel, value)
    time.sleep(on_time)
    api_test_channel(session, base_url, channel, 0)
    time.sleep(off_time)


def test_value_bands(session, base_url, channel):
    """Pause at common threshold values – useful for strobe, mode, speed channels."""
    bands = [
        (0,   "Off / 0"),
        (1,   "Low (1)"),
        (10,  "~4%"),
        (26,  "~10%"),
        (51,  "~20%"),
        (77,  "~30%"),
        (102, "~40%"),
        (128, "~50% / mid"),
        (153, "~60%"),
        (179, "~70%"),
        (204, "~80%"),
        (230, "~90%"),
        (240, "High-end"),
        (255, "Max (255)"),
    ]
    print()
    print(c(f"  Effect-band scan on channel {channel}", BOLD))
    print(c("  Press Enter at each step (Ctrl-C to abort).", DIM))
    for val, label in bands:
        api_test_channel(session, base_url, channel, val)
        try:
            input(c(f"    ch{channel} = {val:>3}  ({label}) → ", CYAN))
        except (KeyboardInterrupt, EOFError):
            print()
            break
    api_test_channel(session, base_url, channel, 0)
    ok("Band scan complete – channel left at 0")

# ── Colour combo test (uses confirmed absolute channels) ───────────────────────

def colour_combo_test(session, base_url, num_groups):
    """
    Fire colour combinations using the confirmed absolute channel numbers
    so you can verify the RGBW mapping and spot any anomalies.
    """
    r_ch, g_ch, b_ch, w_ch = RGBW_START, RGBW_START+1, RGBW_START+2, RGBW_START+3

    combos = [
        ("Blackout",                         {}),
        (f"Ch {r_ch} = 255  → should be RED only",     {r_ch: 255}),
        (f"Ch {g_ch} = 255  → should be GREEN only",   {g_ch: 255}),
        (f"Ch {b_ch} = 255  → should be BLUE only",    {b_ch: 255}),
        (f"Ch {w_ch} = 255  → should be WHITE only",   {w_ch: 255}),
        (f"R+G = 255        → should be YELLOW",        {r_ch: 255, g_ch: 255}),
        (f"R+B = 255        → should be MAGENTA",       {r_ch: 255, b_ch: 255}),
        (f"G+B = 255        → should be CYAN",          {g_ch: 255, b_ch: 255}),
        (f"R+G+B = 255      → should be WHITE (RGB)",   {r_ch: 255, g_ch: 255, b_ch: 255}),
        (f"R+G+B+W = 255    → all on, full white",      {r_ch: 255, g_ch: 255, b_ch: 255, w_ch: 255}),
        (f"R=255 G=128      → orange",                  {r_ch: 255, g_ch: 128}),
        (f"R=128 B=255      → violet",                  {r_ch: 128, b_ch: 255}),
        # If there are multiple zones, light zone 1 vs zone 2 to confirm repeat
        *([
            (f"Zone 1 only (chs {RGBW_START}–{RGBW_START+3}) white",
             {RGBW_START+i: 255 for i in range(4)}),
            (f"Zone 2 only (chs {RGBW_START+4}–{RGBW_START+7}) white",
             {RGBW_START+4+i: 255 for i in range(4)}),
        ] if num_groups >= 2 else []),
        ("Blackout (end)", {}),
    ]

    header("Colour-Combo Verification Test")
    print(c("  Channels used: "
            f"R={r_ch}  G={g_ch}  B={b_ch}  W={w_ch}", DIM))
    print(c("  Press Enter at each step (Ctrl-C to skip).", DIM))

    for label, ch_vals in combos:
        # Zero Zone 1 block, then apply the combo
        zero = {RGBW_START + i: 0 for i in range(RGBW_GROUP_SIZE * max(num_groups, 2))}
        zero.update(ch_vals)
        api_set_channels(session, base_url, zero)
        try:
            input(c(f"    {label} → ", CYAN))
        except (KeyboardInterrupt, EOFError):
            print()
            break

    api_blackout(session, base_url)
    ok("Colour-combo test done – blacked out")

# ── Zone step test ─────────────────────────────────────────────────────────────

def zone_step_test(session, base_url, num_groups):
    """
    Light one zone at full white, all others off, stepping through each zone.
    Use this to:
      • Count how many physical sections the fixture has
      • Confirm the 4-channel RGBW repeat is correct
      • Spot any zones that don't respond (might need more channels)
    """
    header("Zone-Step Test")
    print(c(f"  Testing {num_groups} zone(s).  Each zone will go full white.", DIM))
    print(c(f"  RGBW start ch: {RGBW_START},  group size: {RGBW_GROUP_SIZE}", DIM))
    print(c("  Press Enter to advance, Ctrl-C to stop early.", DIM))
    print()

    for z in range(num_groups):
        chs = zone_channels(z)
        ch_vals = {}
        # Zero all zones first
        for zz in range(num_groups):
            for c_ in zone_channels(zz):
                ch_vals[c_] = 0
        # Light this zone white
        for c_ in chs:
            ch_vals[c_] = 255

        api_set_channels(session, base_url, ch_vals)
        try:
            input(c(f"    Zone {z+1}  (chs {chs[0]}–{chs[-1]}) → ", CYAN))
        except (KeyboardInterrupt, EOFError):
            print()
            break

    api_blackout(session, base_url)
    ok("Zone-step test done – blacked out")

# ── Auto channel scan ─────────────────────────────────────────────────────────

def auto_scan(session, base_url, start_ch, num_channels, num_groups,
              flash_val=200, on_time=0.8, off_time=0.4):
    """Flash each channel in sequence with zone annotations."""
    header(f"Auto-scan: channels {start_ch} → {start_ch + num_channels - 1}")
    print(c("  Each channel will flash at 200 briefly.", DIM))
    print(c("  Channels in the known RGBW block are annotated.", DIM))
    print()

    for ch in range(start_ch, start_ch + num_channels):
        name = channel_display_name(ch, num_groups)
        print(c(f"  {name}", BOLD), end="  ", flush=True)
        flash_channel(session, base_url, ch, flash_val, on_time, off_time)
        print(c("done", DIM))

    api_blackout(session, base_url)
    ok("Auto-scan complete")

# ── Session data management ───────────────────────────────────────────────────

def default_session(start_ch, num_channels, num_groups):
    sess = {
        "fixture": "Stadium Pro II 1200x RGBW",
        "created": datetime.now().isoformat(timespec="seconds"),
        "start_channel": start_ch,
        "num_channels": num_channels,
        "rgbw_start": RGBW_START,
        "rgbw_group_size": RGBW_GROUP_SIZE,
        "num_groups": num_groups,
        "channels": {},
    }
    # Pre-populate confirmed RGBW channels
    labels = build_rgbw_labels(num_groups)
    for ch, label in labels.items():
        sess["channels"][str(ch)] = {
            "label": label,
            "notes": "confirmed RGBW pattern",
            "value_hint": "0=off 255=full",
        }
    # Mark the pre-RGBW channels as needing discovery
    for ch in PRE_CHANNELS:
        sess["channels"][str(ch)] = {
            "label": "",
            "notes": "control channel – use 'e' band test to identify",
            "value_hint": "",
        }
    return sess


def print_session(sess):
    header("Current Discovery Session")
    print(f"  Fixture   : {sess['fixture']}")
    print(f"  Created   : {sess['created']}")
    print(f"  RGBW start: ch {sess.get('rgbw_start', RGBW_START)},  "
          f"group size: {sess.get('rgbw_group_size', RGBW_GROUP_SIZE)},  "
          f"zones: {sess.get('num_groups', '?')}")
    print()
    if not sess["channels"]:
        warn("No channels annotated yet.")
        return
    print(c(f"  {'Ch':>4}  {'Label':<24}  {'Value hint':<18}  Notes", BOLD))
    print("  " + "─"*70)
    for ch_str in sorted(sess["channels"], key=lambda x: int(x)):
        ch_info = sess["channels"][ch_str]
        label  = ch_info.get("label", "")
        notes  = ch_info.get("notes", "")
        vhint  = ch_info.get("value_hint", "")
        row_color = DIM if not label else RESET
        print(c(f"  {int(ch_str):>4}  {label:<24}  {vhint:<18}  {notes}", row_color))


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

    vhint = input(c(f"    Value hint [{existing.get('value_hint','')}]: ", CYAN)).strip()
    if vhint:
        existing["value_hint"] = vhint

    sess["channels"][ch_str] = existing
    ok(f"Channel {channel} annotated.")

# ── Known channel type quick-pick ─────────────────────────────────────────────

COMMON_CHANNEL_TYPES = [
    "Dimmer/Master",
    "Red", "Green", "Blue", "White", "Amber", "UV/Violet",
    "Strobe", "Flash Rate",
    "Color Macro", "Program/Mode", "Program Speed",
    "Pan", "Tilt", "Zoom", "Focus",
    "Reset/Control", "Unknown",
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

# ── Apply mappings to server ───────────────────────────────────────────────────

def apply_mappings_to_server(sess, http_session, base_url):
    """Push all labelled channels from the session to the DMX server."""
    labels = {}
    for ch_str, ch_info in sess["channels"].items():
        label = ch_info.get("label", "").strip()
        if label:
            labels[int(ch_str)] = label
    if not labels:
        warn("No labelled channels to apply.")
        return
    print(c(f"\n  Applying {len(labels)} channel label(s) to {base_url} …", YELLOW))
    if api_apply_labels(http_session, base_url, labels):
        ok(f"Applied {len(labels)} labels successfully.")
        for ch, lbl in sorted(labels.items()):
            print(c(f"    ch {ch:>3} → {lbl}", DIM))
    else:
        err("Failed to apply labels – check server connection.")


def write_known_rgbw_labels(sess, http_session, base_url, num_groups):
    """Populate session + server with all confirmed RGBW zone labels."""
    labels = build_rgbw_labels(num_groups)
    for ch, label in labels.items():
        sess["channels"].setdefault(str(ch), {})["label"] = label
        sess["channels"][str(ch)].setdefault("notes", "confirmed RGBW pattern")
        sess["channels"][str(ch)].setdefault("value_hint", "0=off 255=full")
    print(c(f"\n  Writing {len(labels)} confirmed RGBW labels …", YELLOW))
    if api_apply_labels(http_session, base_url, labels):
        ok(f"RGBW labels written for {num_groups} zone(s).")
        for ch, lbl in sorted(labels.items()):
            print(c(f"    ch {ch:>3} → {lbl}", DIM))
    else:
        err("Label write failed – check server connection.")

# ── Interactive loop ───────────────────────────────────────────────────────────

MENU = f"""
{c('Commands', BOLD)}
  {c('s', CYAN)}  sweep channel 0→255→0          {c('v', CYAN)}  set channel to specific value
  {c('n', CYAN)}  next channel                    {c('p', CYAN)}  previous channel
  {c('g', CYAN)}  jump to channel #               {c('b', CYAN)}  blackout
  {c('r', CYAN)}  auto-scan all channels          {c('c', CYAN)}  colour-combo test (RGBW verified)
  {c('z', CYAN)}  zone-step test                  {c('e', CYAN)}  effect band step-through
  {c('l', CYAN)}  annotate channel                {c('k', CYAN)}  pick label from list
  {c('W', CYAN)}  write all known RGBW labels     {c('d', CYAN)}  dump session to terminal
  {c('S', CYAN)}  save session to JSON            {c('L', CYAN)}  load session from JSON
  {c('A', CYAN)}  apply labels to DMX server      {c('?', CYAN)}  show this menu
  {c('q', CYAN)}  quit
"""


def prompt_line(current_ch, label, num_groups):
    zone_info = zone_of(current_ch)
    if zone_info is not None:
        z, color = zone_info
        zone_tag = c(f" Z{z+1}/{color}", MAGENTA)
    else:
        zone_tag = c(" (ctrl)", YELLOW)
    lbl_tag = c(f" [{label}]", YELLOW) if label else ""
    return input(c(f"\n  ch {current_ch}", BOLD + CYAN) + zone_tag + lbl_tag
                 + c(" > ", BOLD + CYAN)).strip()


def run_interactive(args, base_url, http_session, sess):
    current_ch = args.start_ch
    session_file = args.session_file
    num_groups = args.groups

    header("Stadium Pro II 1200x RGBW – Channel Tester")
    print(c(f"  Server   : {base_url}", DIM))
    print(c(f"  RGBW     : ch {RGBW_START}=R  {RGBW_START+1}=G  "
            f"{RGBW_START+2}=B  {RGBW_START+3}=W  (repeats every {RGBW_GROUP_SIZE})", DIM))
    print(c(f"  Zones    : {num_groups} configured  "
            f"(ch {RGBW_START}–{RGBW_START + num_groups*RGBW_GROUP_SIZE - 1})", DIM))
    print(c(f"  Control  : ch 1–{RGBW_START-1} still being identified", YELLOW))
    print(MENU)

    while True:
        ch_info = sess["channels"].get(str(current_ch), {})
        current_label = ch_info.get("label", "")

        try:
            cmd = prompt_line(current_ch, current_label, num_groups)
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not cmd:
            api_test_channel(http_session, base_url, current_ch, 255)
            info(f"Channel {current_ch} = 255 (all others 0).  Use 'b' to blackout.")
            continue

        cmd0 = cmd[0]

        # ── navigation ────────────────────────────────────────────────
        if cmd in ("n", "next"):
            if current_ch >= args.start_ch + args.channels - 1:
                warn("Already at last channel.")
            else:
                current_ch += 1
                api_test_channel(http_session, base_url, current_ch, 255)
                info(f"→ {channel_display_name(current_ch, num_groups)}")

        elif cmd in ("p", "prev"):
            if current_ch <= args.start_ch:
                warn("Already at first channel.")
            else:
                current_ch -= 1
                api_test_channel(http_session, base_url, current_ch, 255)
                info(f"← {channel_display_name(current_ch, num_groups)}")

        elif cmd0 == "g":
            try:
                ch = int(cmd.split()[1]) if len(cmd.split()) > 1 else \
                     int(input(c("    Jump to channel #: ", CYAN)))
                if args.start_ch <= ch < args.start_ch + args.channels:
                    current_ch = ch
                    api_test_channel(http_session, base_url, current_ch, 255)
                    info(f"Jumped to {channel_display_name(current_ch, num_groups)}")
                else:
                    warn(f"Channel {ch} outside range "
                         f"({args.start_ch}–{args.start_ch+args.channels-1})")
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
                val = int(parts[1]) if len(parts) > 1 else \
                      int(input(c("    Value (0-255): ", CYAN)))
                val = max(0, min(255, val))
                api_test_channel(http_session, base_url, current_ch, val)
                info(f"Channel {current_ch} = {val}")
            except (ValueError, EOFError):
                warn("Invalid value.")

        # ── auto scan ─────────────────────────────────────────────────
        elif cmd0 == "r":
            try:
                confirm = input(c(
                    f"    Scan channels {args.start_ch}–"
                    f"{args.start_ch+args.channels-1}? [y/N]: ", YELLOW
                )).strip().lower()
            except EOFError:
                confirm = "n"
            if confirm == "y":
                auto_scan(http_session, base_url,
                          args.start_ch, args.channels, num_groups)

        # ── colour combo ──────────────────────────────────────────────
        elif cmd0 == "c":
            colour_combo_test(http_session, base_url, num_groups)

        # ── zone step ─────────────────────────────────────────────────
        elif cmd0 == "z":
            zone_step_test(http_session, base_url, num_groups)

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

        # ── write known RGBW labels ───────────────────────────────────
        elif cmd == "W":
            try:
                new_groups = input(c(
                    f"    Number of RGBW zones [{num_groups}]: ", CYAN
                )).strip()
                if new_groups:
                    num_groups = int(new_groups)
                    sess["num_groups"] = num_groups
            except (ValueError, EOFError):
                pass
            write_known_rgbw_labels(sess, http_session, base_url, num_groups)

        # ── dump ──────────────────────────────────────────────────────
        elif cmd0 == "d":
            print_session(sess)

        # ── save / load ───────────────────────────────────────────────
        elif cmd == "S":
            path = input(c(f"    Save to [{session_file}]: ", CYAN)).strip() \
                   or session_file
            save_session(sess, path)
            session_file = path

        elif cmd == "L":
            path = input(c(f"    Load from [{session_file}]: ", CYAN)).strip() \
                   or session_file
            if os.path.exists(path):
                sess.update(load_session(path))
                num_groups = sess.get("num_groups", num_groups)
                ok(f"Session loaded from {path}")
            else:
                err(f"File not found: {path}")

        # ── apply to server ───────────────────────────────────────────
        elif cmd == "A":
            apply_mappings_to_server(sess, http_session, base_url)

        # ── quit ──────────────────────────────────────────────────────
        elif cmd0 == "q":
            try:
                save = input(c("  Save session before quitting? [Y/n]: ",
                               YELLOW)).strip().lower()
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
        description="Stadium Pro II 1200x RGBW channel tester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--host", default="localhost",
                   help="Flask server host (default: localhost)")
    p.add_argument("--port", type=int, default=5000,
                   help="Flask server port (default: 5000)")
    p.add_argument("--start-ch", type=int, default=1, metavar="N",
                   help="First channel to probe (default: 1)")
    p.add_argument("--channels", type=int, default=32, metavar="N",
                   help="Total channels to probe (default: 32)")
    p.add_argument("--groups", type=int, default=8, metavar="N",
                   help="Number of RGBW zones to label (default: 8; "
                        "use 'z' zone-step test to find the real count)")
    p.add_argument("--session-file", default="stadium_discovery.json",
                   metavar="FILE",
                   help="JSON file for save/load (default: stadium_discovery.json)")
    p.add_argument("--auto-scan", action="store_true",
                   help="Flash all channels on startup then enter interactive mode")
    return p.parse_args()


def main():
    args = parse_args()
    base_url = f"http://{args.host}:{args.port}"

    http_session = requests.Session()
    http_session.headers.update({"Content-Type": "application/json"})

    print(c(f"\nConnecting to DMX server at {base_url} …", DIM))
    health = check_server(http_session, base_url)
    if health is None:
        err(f"Cannot reach {base_url} – is app.py running?")
        err("Start it with:  python3 app.py   or   sudo systemctl start dmx")
        sys.exit(1)

    enttec_ok = health.get("enttec_connected", False)
    artnet_ok = health.get("artnet_enabled", False)
    ok(f"Server reachable  (status={health.get('status','?')}, "
       f"ENTTEC={enttec_ok}, Art-Net={artnet_ok})")

    if not enttec_ok and not artnet_ok:
        warn("Neither ENTTEC nor Art-Net is active – DMX may not reach the fixture.")

    # Load session or create a pre-populated one from confirmed RGBW mapping
    if os.path.exists(args.session_file):
        try:
            sess = load_session(args.session_file)
            # update num_groups from CLI if explicitly passed
            if "--groups" in sys.argv:
                sess["num_groups"] = args.groups
            args.groups = sess.get("num_groups", args.groups)
            ok(f"Loaded previous session from {args.session_file}")
        except Exception as exc:
            warn(f"Could not load {args.session_file}: {exc}  – starting fresh.")
            sess = default_session(args.start_ch, args.channels, args.groups)
    else:
        sess = default_session(args.start_ch, args.channels, args.groups)
        ok(f"New session created with {args.groups} RGBW zones pre-labelled.")

    if args.auto_scan:
        auto_scan(http_session, base_url,
                  args.start_ch, args.channels, args.groups)

    run_interactive(args, base_url, http_session, sess)

    http_session.close()


if __name__ == "__main__":
    main()
