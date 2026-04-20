# Stadium PRO III 1200x RGBW — Linking Lights with RDM & Individual Fixture Addressing

## Overview

Each Stadium PRO III 1200x housing contains **4 individual RGBW fixtures**. In
the current setup, all 4 fixtures in a single housing respond to the same 4 DMX
channels (R, G, B, W) because they share one external DMX decoder set to a
single start address.

This guide explains how to:
- Use the **PI (Power Interconnect) wire** to daisy-chain multiple lights
- Upgrade from **3-pin to 5-pin DMX** to enable RDM
- Make **each of the 4 fixtures per housing individually addressable**
- Scale to multiple linked Stadium PRO III lights

---

## Understanding the Wiring

### Current Setup (3-Pin DMX)

```
3-Pin XLR Pinout:
  Pin 1 — Signal Ground (shield)
  Pin 2 — Data– (DMX inverted)
  Pin 3 — Data+ (DMX non-inverted)
```

With 3-pin DMX you get standard DMX512 only — no return path for RDM.

### The PI Wire (5-Pin DMX)

The **PI wire** refers to **pins 4 and 5** on 5-pin XLR DMX connectors. These
pins are reserved by the DMX512-A / ANSI E1.20 standard for a **secondary data
pair** which RDM uses as a **return communication path**.

```
5-Pin XLR Pinout:
  Pin 1 — Signal Ground (shield)
  Pin 2 — Data– (DMX primary, inverted)
  Pin 3 — Data+ (DMX primary, non-inverted)
  Pin 4 — Data– (Secondary / RDM return, inverted)    ← PI wire
  Pin 5 — Data+ (Secondary / RDM return, non-inverted) ← PI wire
```

**Why it matters:** Standard DMX512 is one-way (controller → fixtures). RDM
(Remote Device Management, ANSI E1.20) is **bidirectional** — it uses the
same data pair (pins 2 & 3) in a half-duplex manner for both sending and
receiving. Pins 4 & 5 can carry a secondary DMX universe or serve as dedicated
return lines depending on the implementation.

> **Note:** Many modern RDM implementations actually use half-duplex
> communication on pins 2 & 3 only and do not require pins 4 & 5. Check your
> decoder documentation to confirm whether your specific decoders use the PI
> pair for RDM or for a second DMX universe.

---

## What You Need

### Hardware

| Item | Qty | Purpose |
|------|-----|---------|
| **5-pin XLR DMX cables** | 1 per link | Replace 3-pin cables to carry RDM data |
| **5-pin to 3-pin adapters** | As needed | Only if mixing connector types in the chain |
| **RDM-capable DMX controller/interface** | 1 | Your ENTTEC DMX USB Pro already supports RDM |
| **RDM-capable DMX decoders** | 1 per fixture | Must support RDM for remote addressing |
| **DMX terminator (120Ω)** | 1 | Must be placed at the **end** of the daisy chain |
| **3-pin to 5-pin pigtail adapters** | As needed | If your Stadium PRO III has 3-pin sockets only |

### Software

- **ENTTEC RDM Controller software** or any RDM discovery tool
- This project's web UI (for DMX control after addressing is set)

---

## Step-by-Step: Individual Fixture Addressing

### Step 1 — Understand the Addressing Math

Each Stadium PRO III housing has 4 fixtures. In **4-channel RGBW mode**, each
fixture needs 4 DMX channels:

```
SINGLE HOUSING (currently — all 4 fixtures on same address):
  Decoder Address: 001
  All 4 fixtures → Ch 1 (R), Ch 2 (G), Ch 3 (B), Ch 4 (W)
  Total channels used: 4

SINGLE HOUSING (goal — each fixture individually addressed):
  Decoder 1 → Fixture 1: Ch  1 (R), Ch  2 (G), Ch  3 (B), Ch  4 (W)
  Decoder 2 → Fixture 2: Ch  5 (R), Ch  6 (G), Ch  7 (B), Ch  8 (W)
  Decoder 3 → Fixture 3: Ch  9 (R), Ch 10 (G), Ch 11 (B), Ch 12 (W)
  Decoder 4 → Fixture 4: Ch 13 (R), Ch 14 (G), Ch 15 (B), Ch 16 (W)
  Total channels used: 16
```

### Step 2 — Wire Each Fixture to Its Own Decoder

Currently, a single decoder drives all 4 fixtures in one housing. To gain
individual control:

**Option A — 4 Separate Decoders (Recommended)**

Wire each of the 4 RGBW LED arrays in the housing to its own DMX decoder.
Each decoder gets a unique DMX start address.

```
Stadium PRO III Housing
├── Fixture 1 RGBW → Decoder A (address 001)
├── Fixture 2 RGBW → Decoder B (address 005)
├── Fixture 3 RGBW → Decoder C (address 009)
└── Fixture 4 RGBW → Decoder D (address 013)
```

**Option B — Multi-Channel Decoder**

Use a single decoder that supports 16+ channels and wire all 4 fixtures to
different output groups on the same decoder. Set it to 16-channel mode if
available.

### Step 3 — Daisy-Chain Multiple Lights Using the PI Wire / 5-Pin DMX

Connect lights in a **daisy chain** (series, not star/parallel):

```
                    5-pin DMX Cable     5-pin DMX Cable     5-pin DMX Cable
  ┌──────────┐     ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
  │ DMX       │────→│ Light 1      │───→│ Light 2      │───→│ Light 3      │──→ [120Ω TERM]
  │ Controller│     │ (Ch 1–16)    │    │ (Ch 17–32)   │    │ (Ch 33–48)   │
  └──────────┘     └──────────────┘    └──────────────┘    └──────────────┘
  (ENTTEC USB)      4 fixtures          4 fixtures          4 fixtures
                    4 decoders          4 decoders          4 decoders
```

**Wiring rules:**
1. **DMX OUT** of one light connects to **DMX IN** of the next
2. Use **5-pin XLR cables** throughout to preserve the PI/RDM data path
3. Place a **120Ω termination resistor** (or terminator plug) at the very last
   fixture in the chain
4. Maximum recommended cable run: **300 meters (1,000 ft)** total for the
   entire chain
5. Maximum recommended devices: **32 per universe** without a DMX splitter

### Step 4 — Set DMX Addresses

#### Manual Method (DIP Switches)

Each decoder has DIP switches for setting its DMX start address. Common
address settings for 4-channel mode:

```
Light 1 (4 fixtures, addresses 1–16):
  Decoder A: Address 001 → DIP: all OFF           (binary: 000000001)
  Decoder B: Address 005 → DIP: 1+3 ON            (binary: 000000101)
  Decoder C: Address 009 → DIP: 1+4 ON            (binary: 000001001)
  Decoder D: Address 013 → DIP: 1+3+4 ON          (binary: 000001101)

Light 2 (4 fixtures, addresses 17–32):
  Decoder E: Address 017 → DIP: 1+5 ON            (binary: 000010001)
  Decoder F: Address 021 → DIP: 1+3+5 ON          (binary: 000010101)
  Decoder G: Address 025 → DIP: 1+4+5 ON          (binary: 000011001)
  Decoder H: Address 029 → DIP: 1+3+4+5 ON        (binary: 000011101)

Light 3 (4 fixtures, addresses 33–48):
  Decoder I: Address 033 → DIP: 1+6 ON            (binary: 000100001)
  Decoder J: Address 037 → DIP: 1+3+6 ON          (binary: 000100101)
  Decoder K: Address 041 → DIP: 1+4+6 ON          (binary: 000101001)
  Decoder L: Address 045 → DIP: 1+3+4+6 ON        (binary: 000101101)
```

> **DIP Switch Reference:** Switch 1 = 1, Switch 2 = 2, Switch 3 = 4,
> Switch 4 = 8, Switch 5 = 16, Switch 6 = 32, Switch 7 = 64, Switch 8 = 128,
> Switch 9 = 256. Add the values of all ON switches to get the address.

#### RDM Method (Remote — No Physical Access Needed)

If your decoders support RDM, you can set addresses remotely:

1. **Connect** all lights in the daisy chain with 5-pin cables
2. **Run RDM Discovery** from your controller:
   ```bash
   # Using ENTTEC's RDM Controller software, or:
   # Many open-source tools support RDM discovery
   ```
3. The controller will discover all RDM-capable devices on the bus
4. **Assign unique addresses** to each decoder through the RDM software
5. **Verify** by sending test patterns to individual addresses

**RDM advantages:**
- No need to physically access DIP switches on each decoder
- Can re-address fixtures from the ground (useful for high-mounted stadium lights)
- Discover and identify all devices on the DMX bus
- Monitor decoder status, temperature, and errors remotely

### Step 5 — Configure This Software

After addressing, update the controller software to match your fixture layout.

**For 1 light (4 individually addressed fixtures):**
Set visible channels to **16** in the web UI Settings panel.

**For 3 lights (12 individually addressed fixtures):**
Set visible channels to **48** in the web UI Settings panel.

**For N lights:**
Set visible channels to **N × 4 fixtures × 4 channels = N × 16**.

**Channel labels** will auto-generate based on the fixture profile, or you can
customize them in the Settings panel. Example for 3 linked lights:

```
Light 1:  F1 R/G/B/W (1–4),   F2 R/G/B/W (5–8),   F3 R/G/B/W (9–12),  F4 R/G/B/W (13–16)
Light 2:  F5 R/G/B/W (17–20), F6 R/G/B/W (21–24),  F7 R/G/B/W (25–28), F8 R/G/B/W (29–32)
Light 3:  F9 R/G/B/W (33–36), F10 R/G/B/W (37–40), F11 R/G/B/W (41–44), F12 R/G/B/W (45–48)
```

---

## Scaling Limits

| Factor | Limit | Notes |
|--------|-------|-------|
| DMX channels per universe | 512 | Hard limit of DMX512 protocol |
| Max fixtures per universe (4ch mode) | 128 | 512 ÷ 4 = 128 fixtures |
| Max Stadium PRO III lights per universe | 32 | 128 fixtures ÷ 4 per housing = 32 housings |
| Max devices on a single DMX bus | 32 | Add DMX splitter/booster for more |
| Max cable length | 300m / 1000ft | Total chain length, not per segment |

**To exceed 32 lights:** Use a **DMX splitter** to create multiple isolated bus
segments sharing the same universe, or use **Art-Net** (already supported by
this project) to run multiple DMX universes over Ethernet.

---

## Troubleshooting

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| RDM discovery finds no devices | Decoders don't support RDM | Check decoder specs; use DIP switches instead |
| Some fixtures don't respond | Address conflict or wrong wiring | Verify each decoder has a unique address |
| Signal drops on long chains | Missing termination or cable too long | Add 120Ω terminator; add DMX splitter/booster |
| Flickering on distant fixtures | Signal degradation | Shorten chain or add DMX booster |
| All fixtures respond the same | All decoders set to same address | Re-address each decoder to unique start address |
| Colors are wrong | Decoder in wrong channel mode | Set all decoders to 4CH/RGBW mode via DIP switches |
| PI wire connected but no RDM | 3-pin adapters in chain | 3→5 pin adapters break the RDM path; use 5-pin throughout |

---

## Quick Reference: Wiring Diagram

```
CONTROLLER (Raspberry Pi + ENTTEC DMX USB Pro)
    │
    │  5-pin XLR cable
    ▼
┌─────────────── STADIUM PRO III  LIGHT 1 ───────────────┐
│                                                         │
│  DMX IN ──┬── Decoder A (addr 001) ── Fixture 1 RGBW   │
│           ├── Decoder B (addr 005) ── Fixture 2 RGBW   │
│           ├── Decoder C (addr 009) ── Fixture 3 RGBW   │
│           └── Decoder D (addr 013) ── Fixture 4 RGBW   │
│                                                         │
│  DMX OUT (THRU) ────────────────────────────────────────┘
    │
    │  5-pin XLR cable
    ▼
┌─────────────── STADIUM PRO III  LIGHT 2 ───────────────┐
│                                                         │
│  DMX IN ──┬── Decoder E (addr 017) ── Fixture 5 RGBW   │
│           ├── Decoder F (addr 021) ── Fixture 6 RGBW   │
│           ├── Decoder G (addr 025) ── Fixture 7 RGBW   │
│           └── Decoder H (addr 029) ── Fixture 8 RGBW   │
│                                                         │
│  DMX OUT (THRU) ────────────────────────────────────────┘
    │
    │  5-pin XLR cable
    ▼
┌─────────────── STADIUM PRO III  LIGHT 3 ───────────────┐
│                                                         │
│  DMX IN ──┬── Decoder I (addr 033) ── Fixture 9 RGBW   │
│           ├── Decoder J (addr 037) ── Fixture 10 RGBW  │
│           ├── Decoder K (addr 041) ── Fixture 11 RGBW  │
│           └── Decoder L (addr 045) ── Fixture 12 RGBW  │
│                                                         │
│  DMX OUT → [120Ω TERMINATOR]                            │
└─────────────────────────────────────────────────────────┘
```

---

## Summary

1. **Switch to 5-pin DMX cables** to enable the PI wire / RDM return path
2. **Wire each fixture to its own decoder** (4 decoders per Stadium PRO III housing)
3. **Set unique DMX addresses** on each decoder (manually via DIP switches or remotely via RDM)
4. **Daisy-chain lights** using DMX OUT → DMX IN with 5-pin cables
5. **Terminate** the last light in the chain with a 120Ω resistor
6. **Update this software** to match the total number of individually controlled channels
