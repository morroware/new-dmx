# DMX Controller - General Purpose

A Python-based DMX512 controller with a web interface for testing and controlling any DMX lighting fixture. Supports **ENTTEC Open DMX USB** and **Art-Net** output, unlimited named scenes, configurable channel counts and labels, and optional GPIO trigger/safety inputs on Raspberry Pi.

## Features

- **Web Interface** - Dark-themed responsive UI with per-channel sliders, labels, and real-time control
- **Configurable Channels** - Start with 16, add up to 512 in increments of 8 from the UI
- **Custom Channel Labels** - Name each channel (e.g. "Dimmer", "Red", "Strobe") for any fixture
- **Unlimited Scenes** - Create, name, save, recall, and delete as many scenes as you need
- **Art-Net Output** - Send DMX data over the network (UDP broadcast or unicast) alongside or instead of USB
- **Art-Net Receiver** - Listen for incoming Art-Net and output via ENTTEC USB (Pi-to-Pi bridging)
- **ENTTEC USB** - Direct DMX512 output via ENTTEC Open DMX USB (FTDI-based)
- **Trigger System** - Configurable trigger scene + idle scene with adjustable duration timer
- **GPIO Support** - Optional contact closure trigger (pin 17) and safety switch (pin 27) on Raspberry Pi
- **Emergency Blackout** - One-button kill to zero all channels
- **Auto-start** - Runs as a systemd service on boot
- **Auto-recovery** - Automatic ENTTEC USB reconnection and GPIO re-initialization

## Hardware Requirements

- **Raspberry Pi** (tested on Pi 4 & Pi 5) — or any Linux machine for USB/Art-Net only
- **ENTTEC Open DMX USB** adapter (FTDI-based) — optional if using Art-Net only
- **DMX fixtures** (any DMX512-compatible lights, fog machines, etc.)
- Standard USB and XLR DMX cables

### GPIO Wiring (Optional)

```
GPIO Pin 17 --> Contact closure switch --> GND  (trigger input)
GPIO Pin 27 --> Safety toggle switch   --> GND  (safety lockout)
```

Internal pull-ups are enabled — no external resistors needed.

## Quick Install

```bash
git clone <your-repo-url>
cd new-dmx
sudo ./install.sh
```

Open `http://<your-pi-ip>:5000` in a browser.

### What the installer does

1. Installs system packages (python3, libusb, libgpiod, curl)
2. Blacklists ftdi_sio kernel module for ENTTEC access
3. Creates udev rules for non-root USB access
4. Copies application to `/opt/dmx`
5. Creates config directory at `/var/lib/dmx`
6. Creates environment file at `/etc/dmx/dmx.env`
7. Sets up Python venv and installs dependencies
8. Creates and enables a `dmx` systemd service
9. Runs a health check

### Reinstalling / Upgrading

```bash
git pull
sudo ./install.sh
```

Existing configuration and scenes are preserved.

## Uninstall

```bash
sudo ./uninstall.sh
```

### Wipe Existing Install and Clone Fresh

If you want a completely fresh install (instead of preserving config):

```bash
# 1) Remove system install/service
cd ~/new-dmx
sudo ./uninstall.sh

# 2) Remove old repo checkout
cd ~
rm -rf ~/new-dmx

# 3) Clone fresh and install
git clone <your-repo-url> ~/new-dmx
cd ~/new-dmx
sudo ./install.sh
```

Optional: also remove saved scenes/config before reinstalling:

```bash
sudo rm -rf /var/lib/dmx
```

## Manual Start (Development)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./start.sh
```

## Usage

### Channels Tab

- Each channel has a slider (0-255) and a customizable label
- Click any channel label to rename it (e.g. "Red", "Dimmer", "Gobo")
- Use **+ Add Channels** / **- Remove Channels** to adjust the visible channel count
- **BLACKOUT** zeros all channels instantly
- **TRIGGER** fires the configured trigger sequence

### Scenes Tab

- **Save Current State as Scene** — enter a name and save all current slider values
- Click any scene button to apply it
- Right-click a scene button to delete it
- **Trigger Configuration** — select which scene fires on trigger, which scene to return to, and the duration

### Settings Tab

- **Art-Net Mode** — select Disabled, Sender, or Receiver mode
- **Channel Labels** — managed from the Channels tab (click to rename)
- **GPIO** — shows pin assignments and current contact/safety state

### Stadium Pro III 1200W RGBW Setup (Verified in this project)

For the Stadium Pro III 1200W RGBW tested with this controller, the working profile is:

- `7ch`: `Dimmer, Strobe, Color Macro, Red, Green, Blue, White`

If DMX channels feel "off" (for example, color sliders trigger strobe/macro), the fixture and controller are in different DMX personalities.

1. On the fixture display, set DMX personality to **7ch**.
2. In the web UI, open **Settings → Fixture Profiles** and apply **Stadium Pro III - RGBW (7ch: Dim/Strobe/Macro/R/G/B/W)**.
3. If behavior still mismatches, run **DMX Channel Tester** to verify the fixture's real mapping channel-by-channel.


## Art-Net

Art-Net uses UDP packets on port 6454. The controller supports three modes, selectable from the **Settings** tab:

| Mode | Description |
|------|-------------|
| **Disabled** | No Art-Net activity (default) |
| **Sender** | Sends DMX data as Art-Net packets to a target IP |
| **Receiver** | Listens for incoming Art-Net packets and outputs via ENTTEC USB |

Sender and Receiver are mutually exclusive — enabling one disables the other.

### Art-Net Sender

Sends your DMX channel values over the network to Art-Net nodes or software.

1. Go to **Settings** > **Art-Net Mode** > select **Sender**
2. Set the **Target IP** (use `255.255.255.255` for broadcast, or a specific node IP)
3. Set the **Universe** number
4. Click **Save Art-Net Settings**

Art-Net Sender runs alongside ENTTEC USB — you can use both simultaneously, or either alone.

### Art-Net Receiver

Listens for incoming Art-Net DMX packets and outputs the received data via the ENTTEC USB adapter. This is ideal for **Pi-to-Pi bridging** — one Pi runs the controller UI and sends Art-Net, a second Pi receives it and drives fixtures over USB.

1. Go to **Settings** > **Art-Net Mode** > select **Receiver**
2. Set the **Listen Universe** number (must match the sender's universe)
3. Click **Save Art-Net Settings**

In receiver mode:
- The channel sliders show incoming Art-Net values in real-time
- The status bar shows **RECV** with packet count and last-seen timing
- The ENTTEC USB output continuously sends received data to fixtures at 44Hz

#### Example: Pi-to-Pi Setup

```
Pi #1 (Controller)                    Pi #2 (Output Node)
┌─────────────────┐                  ┌─────────────────┐
│ Web UI + Scenes  │  ── Art-Net ──> │ Art-Net Receiver │
│ Mode: Sender     │    (UDP 6454)   │ Mode: Receiver   │
│ Target: Pi2 IP   │                 │ ENTTEC USB ──> Fixtures
└─────────────────┘                  └─────────────────┘
```

Both Pis run the same `app.py`. Pi #1 has Sender mode targeting Pi #2's IP address. Pi #2 has Receiver mode with ENTTEC USB connected to DMX fixtures.

### Environment Variables

```bash
DMX_ARTNET_ENABLED=true              # Enable sender mode
DMX_ARTNET_TARGET_IP=192.168.1.100   # Sender target IP
DMX_ARTNET_UNIVERSE=0                # Universe (sender and receiver)
DMX_ARTNET_RECEIVER=true             # Enable receiver mode
```

## Configuration

All configuration is persisted to `/var/lib/dmx/config.json` and survives reboots. You can also set environment variables in `/etc/dmx/dmx.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `DMX_CONFIG_DIR` | `/var/lib/dmx` | Config file directory |
| `DMX_FTDI_URL` | `ftdi://0403:6001/1` | FTDI device URL |
| `DMX_ARTNET_ENABLED` | `false` | Enable Art-Net sender |
| `DMX_ARTNET_TARGET_IP` | `255.255.255.255` | Art-Net sender target IP |
| `DMX_ARTNET_UNIVERSE` | `0` | Art-Net universe (sender and receiver) |
| `DMX_ARTNET_RECEIVER` | `false` | Enable Art-Net receiver mode |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web interface |
| GET | `/api/health` | Health check (200 ok, 503 degraded) |
| GET | `/api/status` | System status, channels, labels |
| POST | `/api/trigger` | Fire the trigger sequence |
| POST | `/api/scene/<id>` | Apply a scene |
| GET | `/api/scenes` | List all scenes |
| POST | `/api/scenes` | Create/update a scene `{id, name, channels}` |
| DELETE | `/api/scenes/<id>` | Delete a scene |
| POST | `/api/channel` | Set one channel `{channel, value}` |
| POST | `/api/channels` | Set multiple channels `{channels: {1: 255, 2: 128}}` |
| POST | `/api/blackout` | Zero all channels |
| GET/POST | `/api/config` | Read/update config (visible channels, trigger, Art-Net, labels) |
| POST | `/api/channel-labels` | Update channel labels `{1: "Red", 2: "Green"}` |

## Service Management

```bash
sudo systemctl status dmx
sudo systemctl restart dmx
sudo systemctl stop dmx
sudo journalctl -u dmx -f
```

## File Layout

| Path | Description |
|------|-------------|
| `app.py` | Flask application — DMX control, Art-Net, GPIO, API |
| `index.html` | Web UI |
| `install.sh` | Automated installer |
| `uninstall.sh` | Uninstaller |
| `start.sh` | Manual startup script |
| `requirements.txt` | Python dependencies |
| `/opt/dmx/` | Installed application |
| `/var/lib/dmx/config.json` | Persisted scenes and configuration |
| `/etc/dmx/dmx.env` | Environment variables |

## Troubleshooting

### Git pull fails with "detected dubious ownership"

If `git pull` shows:

```
fatal: detected dubious ownership in repository at '/home/tech/new-dmx'
```

mark the repo path as safe for your user, then pull again:

```bash
git config --global --add safe.directory /home/tech/new-dmx
git pull
```

If your repo is in a different path, replace `/home/tech/new-dmx` with that exact path.

### ENTTEC not detected

```bash
lsusb | grep -i ftdi
lsmod | grep ftdi_sio        # Should show nothing
sudo rmmod ftdi_sio           # If loaded, unload it
sudo systemctl restart dmx
```

### Art-Net not reaching fixtures

- Verify the target IP is correct and reachable
- Check that UDP port 6454 is not blocked by a firewall
- Use Wireshark to verify packets are being sent
- Try broadcast (`255.255.255.255`) if unicast isn't working

### GPIO not working

```bash
gpioinfo gpiochip4 2>/dev/null || gpioinfo gpiochip0
gpioget gpiochip4 17    # or gpiochip0
gpioget gpiochip4 27
```
