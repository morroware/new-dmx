#!/usr/bin/env python3
"""
RuggedGrade 1200W RGB Stadium Light – Channel Guide Reference
=============================================================
Derived from the official RuggedGrade channel guide documentation.

Each fixture uses 4 DMX channels in RGBW order:
  Channel 1: Red
  Channel 2: Green
  Channel 3: Blue
  Channel 4: White

Fixtures are addressed sequentially starting at DMX address 1, with each
fixture occupying 4 channels.  Up to 100 fixtures fit in one DMX universe
(addresses 1–400 of 512).

Usage:
    from ruggedgrade_1200w_channel_guide import CHANNEL_GUIDE, get_fixture

    fixture = get_fixture(1)
    # {'fixture_no': 1, 'address': 1, 'red': 1, 'green': 2, 'blue': 3, 'white': 4}
"""

CHANNELS_PER_FIXTURE = 4
MAX_FIXTURES = 100


def _build_channel_guide():
    """Build the full 100-fixture channel guide matching the documentation."""
    guide = {}
    for i in range(1, MAX_FIXTURES + 1):
        address = (i - 1) * CHANNELS_PER_FIXTURE + 1
        guide[i] = {
            'fixture_no': i,
            'address': address,
            'red': address,
            'green': address + 1,
            'blue': address + 2,
            'white': address + 3,
        }
    return guide


CHANNEL_GUIDE = _build_channel_guide()


def get_fixture(fixture_no):
    """Return channel info for a fixture number (1–100)."""
    if fixture_no < 1 or fixture_no > MAX_FIXTURES:
        raise ValueError(f"Fixture number must be 1–{MAX_FIXTURES}, got {fixture_no}")
    return CHANNEL_GUIDE[fixture_no]


def get_fixture_by_address(address):
    """Return channel info for the fixture at a given DMX start address."""
    if address < 1 or address > MAX_FIXTURES * CHANNELS_PER_FIXTURE:
        raise ValueError(f"Address out of range: {address}")
    if (address - 1) % CHANNELS_PER_FIXTURE != 0:
        raise ValueError(f"Address {address} is not a fixture start address "
                         f"(must be 1, 5, 9, ... {MAX_FIXTURES * CHANNELS_PER_FIXTURE - 3})")
    fixture_no = (address - 1) // CHANNELS_PER_FIXTURE + 1
    return CHANNEL_GUIDE[fixture_no]


def generate_labels(fixture_count, start_fixture=1):
    """Generate channel label dict for N fixtures, suitable for app.py config.

    Args:
        fixture_count: Number of fixtures to label (1–100).
        start_fixture: First fixture number (default 1).

    Returns:
        dict mapping DMX channel number → label string, e.g.
        {1: 'F1 Red', 2: 'F1 Green', 3: 'F1 Blue', 4: 'F1 White', ...}
    """
    labels = {}
    for i in range(fixture_count):
        f = start_fixture + i
        info = CHANNEL_GUIDE[f]
        labels[info['red']] = f'F{f} Red'
        labels[info['green']] = f'F{f} Green'
        labels[info['blue']] = f'F{f} Blue'
        labels[info['white']] = f'F{f} White'
    return labels


if __name__ == '__main__':
    # Print the full channel guide (matches the documentation tables)
    print("RuggedGrade 1200W RGB Stadium Light – Channel Guide")
    print("=" * 60)
    print(f"{'Fixture No.':<12} {'Address':<9} {'Red':<6} {'Green':<7} {'Blue':<6} {'White':<6}")
    print("-" * 60)
    for i in range(1, MAX_FIXTURES + 1):
        f = CHANNEL_GUIDE[i]
        print(f"{i:#<4}{'':8} {f['address']:<9} {f['red']:<6} {f['green']:<7} {f['blue']:<6} {f['white']:<6}")
