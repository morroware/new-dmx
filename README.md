# DMX Controller - General Purpose

A Python-based DMX512 controller with a web interface for testing and controlling any DMX lighting fixture. Supports **ENTTEC Open DMX USB** and **Art-Net** output, unlimited named scenes, configurable channel counts and labels, and optional GPIO trigger/safety inputs on Raspberry Pi.

## Features

- **Web Interface** - Dark-themed responsive UI with per-channel sliders, labels, and real-time control
- **Configurable Channels** - Start with 16, add up to 512 in increments of 8 from the UI
- **Custom Channel Labels** - Name each channel (e.g. "Dimmer", "Red", "Strobe") for any fixture
- **Unlimited Scenes** - Create, name, save, recall, and delete as many scenes as you need
- **Art-Net Output** - Send DMX data over the network (UDP broadcast or unicast) alongside or instead of USB
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

- **Art-Net** — enable/disable, set target IP (broadcast or unicast), and universe number
- **Channel Labels** — managed from the Channels tab (click to rename)
- **GPIO** — shows pin assignments and current contact/safety state

## Art-Net

Art-Net sends DMX data as UDP packets (port 6454). To enable:

1. Go to the **Settings** tab in the web UI
2. Check **Enable Art-Net Output**
3. Set the **Target IP** (use `255.255.255.255` for broadcast, or a specific node IP)
4. Set the **Universe** number
5. Click **Save Art-Net Settings**

Art-Net runs alongside ENTTEC USB — you can use both simultaneously, or either alone.

Environment variable overrides:

```bash
DMX_ARTNET_ENABLED=true
DMX_ARTNET_TARGET_IP=192.168.1.100
DMX_ARTNET_UNIVERSE=0
```

## Configuration

All configuration is persisted to `/var/lib/dmx/config.json` and survives reboots. You can also set environment variables in `/etc/dmx/dmx.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `DMX_CONFIG_DIR` | `/var/lib/dmx` | Config file directory |
| `DMX_FTDI_URL` | `ftdi://0403:6001/1` | FTDI device URL |
| `DMX_ARTNET_ENABLED` | `false` | Enable Art-Net output |
| `DMX_ARTNET_TARGET_IP` | `255.255.255.255` | Art-Net target IP |
| `DMX_ARTNET_UNIVERSE` | `0` | Art-Net universe |

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
