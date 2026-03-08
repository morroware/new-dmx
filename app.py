#!/usr/bin/env python3
"""
General-Purpose DMX512 Controller
Supports ENTTEC Open DMX USB and Art-Net output.
Configurable channels, unlimited named scenes, and web UI.
"""

from flask import Flask, jsonify, request, send_file
import time
import json
import logging
import os
import sys
import glob
import atexit
import ipaddress
import signal
import socket
import struct
import tempfile
from threading import Lock, Timer, Thread

# ============================================
# Logging Setup
# ============================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dmx")

try:
    from pyftdi.ftdi import Ftdi
    from pyftdi.usbtools import UsbTools
    FTDI_AVAILABLE = True
except Exception as ftdi_import_error:
    Ftdi = None
    UsbTools = None
    FTDI_AVAILABLE = False
import importlib
import importlib.util

# Detect GPIO libraries (gpiod preferred, lgpio as fallback; works on Pi 4 & Pi 5)
GPIO_AVAILABLE = False
GPIO_LIB = None
gpiod = None
lgpio = None

if importlib.util.find_spec("gpiod"):
    try:
        gpiod = importlib.import_module("gpiod")
    except Exception:
        gpiod = None

if importlib.util.find_spec("lgpio"):
    try:
        lgpio = importlib.import_module("lgpio")
    except Exception:
        lgpio = None

if gpiod is not None:
    GPIO_AVAILABLE = True
    GPIO_LIB = 'gpiod'
elif lgpio is not None:
    GPIO_AVAILABLE = True
    GPIO_LIB = 'lgpio'
else:
    logger.warning("No GPIO library available")

app = Flask(__name__)

# Path for persisting config across restarts
CONFIG_DIR = os.environ.get("DMX_CONFIG_DIR", "/var/lib/dmx")
CONFIG_FILE = os.environ.get(
    "DMX_CONFIG_FILE",
    os.path.join(CONFIG_DIR, "config.json"),
)

# ============================================
# CONFIGURATION
# ============================================

class Config:
    """Application configuration"""

    # GPIO Settings
    CONTACT_PIN = 17
    SAFETY_SWITCH_PIN = 27
    GPIO_CHIP = None

    # DMX Settings
    DMX_CHANNELS = 512
    DMX_REFRESH_RATE = 44
    FTDI_URL = os.environ.get("DMX_FTDI_URL", "ftdi://0403:6001/1")

    # How many channels to show in the UI by default
    VISIBLE_CHANNELS = 16

    # Art-Net settings
    ARTNET_ENABLED = os.environ.get("DMX_ARTNET_ENABLED", "false").lower() in ("1", "true", "yes")
    ARTNET_TARGET_IP = os.environ.get("DMX_ARTNET_TARGET_IP", "255.255.255.255")
    ARTNET_PORT = 6454
    ARTNET_UNIVERSE = int(os.environ.get("DMX_ARTNET_UNIVERSE", "0"))
    ARTNET_SUBNET = 0
    ARTNET_NET = 0

    # Art-Net Receiver mode — listen for incoming ArtNet and output via ENTTEC
    ARTNET_RECEIVER_ENABLED = os.environ.get("DMX_ARTNET_RECEIVER", "false").lower() in ("1", "true", "yes")

    # Trigger timing
    TRIGGER_DURATION = 10.0  # seconds
    TRIGGER_SCENE = None  # scene id to apply on trigger (None = disabled)
    IDLE_SCENE = None  # scene id to return to after trigger (None = blackout)

    # GPIO debounce
    DEBOUNCE_TIME = 0.3  # seconds

    # Channel labels — user-customizable names for each channel number.
    # Any channel not listed here is shown as "Channel N".
    CHANNEL_LABELS = {}

    # Scenes — unlimited named scenes stored as {id: {name, channels}}
    SCENES = {}


config = Config()

# ============================================
# Config Persistence
# ============================================

def save_config():
    """Save current config to disk (atomic write)"""
    try:
        config_dir = os.path.dirname(CONFIG_FILE)
        os.makedirs(config_dir, exist_ok=True)
        data = {
            'visible_channels': config.VISIBLE_CHANNELS,
            'trigger_duration': config.TRIGGER_DURATION,
            'trigger_scene': config.TRIGGER_SCENE,
            'idle_scene': config.IDLE_SCENE,
            'channel_labels': {str(k): v for k, v in config.CHANNEL_LABELS.items()},
            'artnet_enabled': config.ARTNET_ENABLED,
            'artnet_target_ip': config.ARTNET_TARGET_IP,
            'artnet_universe': config.ARTNET_UNIVERSE,
            'artnet_receiver_enabled': config.ARTNET_RECEIVER_ENABLED,
            'scenes': {}
        }
        for sid, scene in config.SCENES.items():
            data['scenes'][sid] = {
                'name': scene['name'],
                'channels': {str(k): v for k, v in scene['channels'].items()}
            }
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, CONFIG_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.warning("Could not save config: %s", e)


def load_config():
    """Load config from disk if it exists"""
    if not os.path.exists(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)

        if 'visible_channels' in data:
            config.VISIBLE_CHANNELS = max(1, min(512, int(data['visible_channels'])))
        if 'trigger_duration' in data:
            config.TRIGGER_DURATION = max(0.5, min(300.0, float(data['trigger_duration'])))
        if 'trigger_scene' in data:
            config.TRIGGER_SCENE = data['trigger_scene']
        if 'idle_scene' in data:
            config.IDLE_SCENE = data['idle_scene']
        if 'artnet_enabled' in data:
            config.ARTNET_ENABLED = bool(data['artnet_enabled'])
        if 'artnet_target_ip' in data:
            config.ARTNET_TARGET_IP = str(data['artnet_target_ip'])
        if 'artnet_universe' in data:
            config.ARTNET_UNIVERSE = int(data['artnet_universe'])
        if 'artnet_receiver_enabled' in data:
            config.ARTNET_RECEIVER_ENABLED = bool(data['artnet_receiver_enabled'])

        if 'channel_labels' in data and isinstance(data['channel_labels'], dict):
            config.CHANNEL_LABELS = {}
            for k, v in data['channel_labels'].items():
                try:
                    config.CHANNEL_LABELS[int(k)] = str(v)
                except (TypeError, ValueError):
                    pass

        if 'scenes' in data and isinstance(data['scenes'], dict):
            for sid, scene in data['scenes'].items():
                try:
                    channels = {}
                    for ch, val in scene.get('channels', {}).items():
                        channels[int(ch)] = max(0, min(255, int(val)))
                    config.SCENES[str(sid)] = {
                        'name': scene.get('name', sid),
                        'channels': channels
                    }
                except (TypeError, ValueError) as e:
                    logger.warning("Invalid scene data for %s: %s", sid, e)

        logger.info("Loaded saved configuration from disk")
    except Exception as e:
        logger.warning("Could not load config (using defaults): %s", e)

# ============================================
# Global State
# ============================================

class SystemState:
    """Global system state manager"""

    def __init__(self):
        self.ftdi_device = None
        self.ftdi_lock = Lock()  # Protects ftdi_device open/close/use
        self.dmx_data = bytearray([0] * (config.DMX_CHANNELS + 1))
        self.dmx_lock = Lock()
        self.current_scene = None
        self.trigger_timer = None
        self.timer_lock = Lock()
        self.gpio_line = None
        self.gpio_safety_line = None
        self.gpio_chip = None
        self.gpio_chip_id = None
        self.gpio_ready = False
        self.dmx_thread = None
        self.dmx_running = False
        self.enttec_url = None
        self.enttec_last_error = None
        # Art-Net
        self.artnet_socket = None
        self.artnet_sequence = 0
        # Art-Net Receiver
        self.artnet_receiver_socket = None
        self.artnet_receiver_thread = None
        self.artnet_receiver_running = False
        self.artnet_receiver_packets = 0
        self.artnet_receiver_last_seen = 0  # monotonic timestamp of last packet

state = SystemState()

# ============================================
# Validation Helpers
# ============================================

def validate_ip_address(ip_str):
    """Validate an IP address string. Returns True if valid."""
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        # Also allow broadcast "255.255.255.255"
        return ip_str == "255.255.255.255"

# ============================================
# Art-Net Functions
# ============================================

ARTNET_HEADER = b'Art-Net\x00'
ARTNET_OPCODE_DMX = 0x5000

def init_artnet():
    """Initialize Art-Net UDP socket"""
    if not config.ARTNET_ENABLED:
        return False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        state.artnet_socket = sock
        logger.info("Art-Net initialized: target=%s:%d universe=%d",
                     config.ARTNET_TARGET_IP, config.ARTNET_PORT, config.ARTNET_UNIVERSE)
        return True
    except Exception as e:
        logger.warning("Could not initialize Art-Net: %s", e)
        state.artnet_socket = None
        return False


def send_artnet_frame():
    """Send current DMX data as an Art-Net DMX packet"""
    if state.artnet_socket is None:
        return
    try:
        state.artnet_sequence = (state.artnet_sequence + 1) % 256
        if state.artnet_sequence == 0:
            state.artnet_sequence = 1

        # Art-Net universe addressing: 15-bit field split into
        # Net (bits 14-8), Sub-Uni (bits 7-4), Universe (bits 3-0)
        # For the wire format: low byte = (subnet << 4) | universe, high byte = net
        full_universe = config.ARTNET_UNIVERSE
        universe_lo = full_universe & 0xFF
        universe_hi = (full_universe >> 8) & 0x7F

        with state.dmx_lock:
            dmx_payload = bytes(state.dmx_data[1:513])  # channels 1-512

        length = len(dmx_payload)

        packet = bytearray()
        packet.extend(ARTNET_HEADER)                          # 8 bytes: "Art-Net\0"
        packet.extend(struct.pack('<H', ARTNET_OPCODE_DMX))   # 2 bytes: opcode (little-endian)
        packet.extend(struct.pack('>H', 14))                  # 2 bytes: protocol version (big-endian)
        packet.append(state.artnet_sequence)                  # 1 byte: sequence
        packet.append(0)                                      # 1 byte: physical port
        packet.append(universe_lo)                            # 1 byte: universe low
        packet.append(universe_hi)                            # 1 byte: universe high
        packet.extend(struct.pack('>H', length))              # 2 bytes: data length (big-endian)
        packet.extend(dmx_payload)                            # N bytes: DMX data

        state.artnet_socket.sendto(
            bytes(packet),
            (config.ARTNET_TARGET_IP, config.ARTNET_PORT)
        )
    except Exception as e:
        logger.warning("Art-Net send error: %s", e)

# ============================================
# Art-Net Receiver Functions
# ============================================

def parse_artnet_dmx(packet):
    """Parse an Art-Net ArtDmx packet. Returns (universe, dmx_data) or None."""
    if len(packet) < 18:
        return None
    # Check header
    if packet[:8] != ARTNET_HEADER:
        return None
    # Check opcode (little-endian)
    opcode = struct.unpack('<H', packet[8:10])[0]
    if opcode != ARTNET_OPCODE_DMX:
        return None
    # Universe: low byte at offset 14, high byte at offset 15
    universe_lo = packet[14]
    universe_hi = packet[15]
    universe = universe_lo | (universe_hi << 8)
    # Data length (big-endian) at offset 16
    data_length = struct.unpack('>H', packet[16:18])[0]
    if len(packet) < 18 + data_length:
        return None
    dmx_data = packet[18:18 + data_length]
    return (universe, dmx_data)


def init_artnet_receiver():
    """Initialize Art-Net receiver socket (bind to port 6454)."""
    if not config.ARTNET_RECEIVER_ENABLED:
        return False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', config.ARTNET_PORT))
        sock.settimeout(1.0)  # Allow periodic checks for shutdown
        state.artnet_receiver_socket = sock
        logger.info("Art-Net receiver listening on 0.0.0.0:%d (universe %d)",
                     config.ARTNET_PORT, config.ARTNET_UNIVERSE)
        return True
    except Exception as e:
        logger.error("Could not start Art-Net receiver: %s", e)
        state.artnet_receiver_socket = None
        return False


def artnet_receiver_thread():
    """Background thread: listens for ArtNet packets and updates DMX data."""
    logger.info("Art-Net receiver thread started (universe %d)", config.ARTNET_UNIVERSE)
    while state.artnet_receiver_running:
        try:
            sock = state.artnet_receiver_socket
            if sock is None:
                time.sleep(1.0)
                continue
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue

            result = parse_artnet_dmx(data)
            if result is None:
                continue

            universe, dmx_payload = result

            # Only accept packets for our configured universe
            if universe != config.ARTNET_UNIVERSE:
                continue

            # Write received DMX data into our buffer
            with state.dmx_lock:
                for i, val in enumerate(dmx_payload):
                    ch = i + 1
                    if ch > config.DMX_CHANNELS:
                        break
                    state.dmx_data[ch] = val

            state.artnet_receiver_packets += 1
            state.artnet_receiver_last_seen = time.monotonic()

        except Exception as e:
            if state.artnet_receiver_running:
                logger.warning("Art-Net receiver error: %s", e)
            time.sleep(0.1)

    logger.info("Art-Net receiver thread stopped")


def start_artnet_receiver():
    """Start the Art-Net receiver thread."""
    if state.artnet_receiver_thread is not None and state.artnet_receiver_thread.is_alive():
        return
    if not init_artnet_receiver():
        return
    state.artnet_receiver_running = True
    state.artnet_receiver_packets = 0
    state.artnet_receiver_last_seen = 0
    state.artnet_receiver_thread = Thread(target=artnet_receiver_thread, daemon=True)
    state.artnet_receiver_thread.start()


def stop_artnet_receiver():
    """Stop the Art-Net receiver thread."""
    state.artnet_receiver_running = False
    if state.artnet_receiver_thread is not None:
        state.artnet_receiver_thread.join(timeout=3)
        state.artnet_receiver_thread = None
    if state.artnet_receiver_socket is not None:
        try:
            state.artnet_receiver_socket.close()
        except Exception:
            pass
        state.artnet_receiver_socket = None


# ============================================
# ENTTEC DMX Functions
# ============================================

def _flush_usb_cache():
    """Flush pyftdi's internal USB device cache to force fresh enumeration.

    After a USB disconnect, pyftdi's UsbTools keeps stale device handles
    which cause 'No such device' errors even after the device is plugged
    back in.  Flushing the cache forces a clean re-scan.
    """
    try:
        if UsbTools is not None:
            UsbTools.flush_cache()
    except Exception:
        pass
    # Also release any lingering libusb references
    try:
        if UsbTools is not None:
            UsbTools.release_all_devices()
    except Exception:
        pass


def _disable_usb_autosuspend():
    """Disable USB autosuspend for FTDI devices to prevent kernel-level disconnects.

    The Linux kernel can put USB devices into suspend mode to save power,
    which causes 'No such device' errors for devices that need continuous
    communication like DMX controllers.
    """
    try:
        for power_dir in glob.glob("/sys/bus/usb/devices/*/power"):
            try:
                idVendor_path = os.path.join(os.path.dirname(power_dir), "idVendor")
                if not os.path.exists(idVendor_path):
                    continue
                with open(idVendor_path) as f:
                    vid = f.read().strip()
                if vid != "0403":  # FTDI vendor ID
                    continue
                control_path = os.path.join(power_dir, "control")
                if os.path.exists(control_path):
                    with open(control_path, 'w') as f:
                        f.write("on")
                autosuspend_path = os.path.join(power_dir, "autosuspend_delay_ms")
                if os.path.exists(autosuspend_path):
                    with open(autosuspend_path, 'w') as f:
                        f.write("-1")
            except (PermissionError, OSError):
                pass  # May not have write access; not fatal
    except Exception:
        pass


def init_enttec():
    """Initialize ENTTEC Open DMX USB.

    Caller must hold state.ftdi_lock.
    """
    if not FTDI_AVAILABLE:
        state.enttec_last_error = f"pyftdi unavailable: {ftdi_import_error}"
        logger.error("%s", state.enttec_last_error)
        return False

    def _candidate_urls(devices):
        urls = []
        urls.append(config.FTDI_URL)
        urls.extend([
            "ftdi://::/1",
            "ftdi://::/2",
            "ftdi://0403:6001/1",
            "ftdi://0403:6001/2",
        ])
        for desc, _iface in devices:
            serial = getattr(desc, 'sn', None)
            if serial:
                urls.append(f"ftdi://::{serial}/1")
                urls.append(f"ftdi://::{serial}/2")
        return list(dict.fromkeys(urls))

    try:
        # Flush stale USB handles before scanning
        _flush_usb_cache()

        logger.info("Initializing ENTTEC Open DMX USB...")
        devices = Ftdi.list_devices()
        if not devices:
            state.enttec_last_error = "No FTDI devices found"
            logger.debug("No FTDI devices found (ENTTEC not connected)")
            return False

        logger.info("Found %d FTDI device(s)", len(devices))
        for idx, (desc, _iface) in enumerate(devices, start=1):
            logger.info(
                "  Device %d: vid=0x%04x pid=0x%04x serial=%s",
                idx, getattr(desc, 'vid', 0), getattr(desc, 'pid', 0),
                getattr(desc, 'sn', 'n/a')
            )

        last_error = None
        for url in _candidate_urls(devices):
            try:
                ftdi = Ftdi()
                ftdi.open_from_url(url)
                state.ftdi_device = ftdi
                state.enttec_url = url
                state.enttec_last_error = None
                logger.info("Opened FTDI device with URL: %s", url)
                break
            except Exception as e:
                last_error = e
                logger.debug("  FTDI open failed for %s: %s", url, e)

        if state.ftdi_device is None:
            hint = (
                "Unable to open any detected FTDI device. "
                "Make sure ftdi_sio is unloaded/blacklisted, udev permissions are set, "
                "and DMX_FTDI_URL points at the correct adapter/interface."
            )
            state.enttec_last_error = f"{hint} Last error: {last_error}"
            logger.error("%s", state.enttec_last_error)
            return False

        # Configure for DMX512
        state.ftdi_device.set_baudrate(250000)
        state.ftdi_device.set_line_property(8, 2, 'N')
        state.ftdi_device.set_latency_timer(2)  # 2ms latency (1ms can cause USB timeouts)

        # Set USB write timeout to prevent hangs on stale connections
        try:
            usb_dev = state.ftdi_device.usb_dev
            if usb_dev is not None:
                usb_dev.default_timeout = 1000  # 1 second USB timeout
        except Exception:
            pass  # Not all pyftdi versions expose usb_dev

        # Disable USB autosuspend for FTDI devices
        _disable_usb_autosuspend()

        logger.info("ENTTEC initialized successfully")
        return True

    except Exception as e:
        state.enttec_last_error = str(e)
        logger.error("Error initializing ENTTEC: %s", e)
        return False


def reinit_enttec():
    """Safely close and re-initialize the ENTTEC.

    Uses ftdi_lock to prevent the refresh thread from using a
    half-closed device.
    """
    with state.ftdi_lock:
        try:
            if state.ftdi_device:
                try:
                    state.ftdi_device.close()
                except Exception:
                    pass
                state.ftdi_device = None
                state.enttec_url = None
            return init_enttec()
        except Exception as e:
            logger.error("Error re-initializing ENTTEC: %s", e)
            return False


def dmx_refresh_thread():
    """Background thread to continuously send DMX frames via ENTTEC and/or Art-Net."""
    refresh_interval = 1.0 / config.DMX_REFRESH_RATE
    consecutive_errors = 0
    MAX_ERRORS_BEFORE_REINIT = 3
    REINIT_BACKOFF_BASE = 2.0
    offline_backoff = 1.0
    offline_backoff_max = 10.0
    _last_reinit_log = 0  # Throttle repetitive log messages

    logger.info("DMX refresh thread started (%d Hz)", config.DMX_REFRESH_RATE)

    while state.dmx_running:
        try:
            # Hold the ftdi_lock during the entire send so reinit_enttec()
            # cannot close the device mid-write.
            with state.ftdi_lock:
                device = state.ftdi_device
                if device is not None:
                    # Snapshot DMX data under lock (fast)
                    with state.dmx_lock:
                        frame = bytes(state.dmx_data)

                    # DMX512 break + MAB + data
                    device.set_break(True)
                    time.sleep(0.000088)  # break: 88µs minimum
                    device.set_break(False)
                    time.sleep(0.000008)  # MAB: 8µs minimum
                    device.write_data(frame)

                    consecutive_errors = 0
                    offline_backoff = 1.0
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors <= MAX_ERRORS_BEFORE_REINIT:
                logger.warning("DMX write error (%d/%d): %s",
                               consecutive_errors, MAX_ERRORS_BEFORE_REINIT, e)
                time.sleep(0.1)
            else:
                # Exponential backoff on re-init attempts, cap at 10s
                backoff = min(REINIT_BACKOFF_BASE * (2 ** (consecutive_errors - MAX_ERRORS_BEFORE_REINIT - 1)), 10.0)
                now = time.monotonic()
                # Throttle log spam: only log every 30s after initial burst
                if consecutive_errors <= MAX_ERRORS_BEFORE_REINIT + 3 or now - _last_reinit_log > 30:
                    logger.warning("ENTTEC disconnected (%d failures). Retrying in %.1fs...",
                                   consecutive_errors, backoff)
                    _last_reinit_log = now
                time.sleep(backoff)
                if reinit_enttec():
                    logger.info("ENTTEC re-initialized successfully, resuming DMX output")
                    consecutive_errors = 0

        # Always send Art-Net if enabled, regardless of ENTTEC status
        if config.ARTNET_ENABLED:
            send_artnet_frame()

        # If no ENTTEC device and it's the only output, back off
        if state.ftdi_device is None and not config.ARTNET_ENABLED:
            time.sleep(offline_backoff)
            offline_backoff = min(offline_backoff * 2, offline_backoff_max)
            reinit_enttec()
            continue

        time.sleep(refresh_interval)

    logger.info("DMX refresh thread stopped")


def start_dmx_refresh():
    """Start background DMX refresh thread"""
    if state.dmx_thread is None or not state.dmx_thread.is_alive():
        state.dmx_running = True
        state.dmx_thread = Thread(target=dmx_refresh_thread, daemon=True)
        state.dmx_thread.start()


def stop_dmx_refresh():
    """Stop background DMX refresh thread"""
    if state.dmx_thread is not None:
        state.dmx_running = False
        state.dmx_thread.join(timeout=2)
        state.dmx_thread = None


def set_channel(channel, value):
    """Set a single DMX channel value"""
    if 1 <= channel <= config.DMX_CHANNELS:
        with state.dmx_lock:
            state.dmx_data[int(channel)] = max(0, min(255, int(value)))


def apply_scene(scene_id, zero_unset=True):
    """Apply a scene to DMX channels.

    Args:
        scene_id: The scene identifier to apply.
        zero_unset: If True, channels not defined in the scene are set to 0.
                    This ensures clean, predictable state for device testing.
    """
    if scene_id not in config.SCENES:
        logger.error("Scene '%s' not found", scene_id)
        return False

    scene = config.SCENES[scene_id]
    with state.dmx_lock:
        if zero_unset:
            for i in range(1, config.DMX_CHANNELS + 1):
                state.dmx_data[i] = 0
        for channel, value in scene['channels'].items():
            if 1 <= int(channel) <= config.DMX_CHANNELS:
                state.dmx_data[int(channel)] = max(0, min(255, int(value)))

    state.current_scene = scene_id
    logger.info("Applied scene: %s", scene['name'])
    return True


def get_current_channels():
    """Get current DMX channel values as a dict of channel_number: value"""
    with state.dmx_lock:
        result = {}
        for i in range(1, config.VISIBLE_CHANNELS + 1):
            result[i] = state.dmx_data[i]
        return result

# ============================================
# GPIO Functions
# ============================================

def _normalize_gpiochip_id(chip_id):
    if chip_id is None:
        return None
    if isinstance(chip_id, int):
        return chip_id
    chip_id = str(chip_id).strip()
    if chip_id.isdigit():
        return int(chip_id)
    if chip_id.startswith("/dev/") or chip_id.startswith("gpiochip"):
        return chip_id
    return chip_id


def _gpiochip_candidates():
    if config.GPIO_CHIP is not None:
        return [_normalize_gpiochip_id(config.GPIO_CHIP)]
    candidates = []
    for path in sorted(glob.glob("/dev/gpiochip*")):
        candidates.append(path)
    return candidates


def _chip_id_to_path(chip_id):
    if chip_id is None:
        return "/dev/gpiochip0"
    if isinstance(chip_id, int):
        return f"/dev/gpiochip{chip_id}"
    chip_id = str(chip_id)
    if chip_id.isdigit():
        return f"/dev/gpiochip{chip_id}"
    if chip_id.startswith("gpiochip"):
        return f"/dev/{chip_id}"
    return chip_id


def _open_gpiod_line(chip_id):
    chip_id = _normalize_gpiochip_id(chip_id)
    if hasattr(gpiod, "request_lines") and hasattr(gpiod, "LineSettings"):
        chip_path = _chip_id_to_path(chip_id)
        direction_enum = getattr(gpiod, "LineDirection", None)
        bias_enum = getattr(gpiod, "LineBias", None)
        if direction_enum is None and hasattr(gpiod, "line"):
            direction_enum = gpiod.line.Direction
            bias_enum = gpiod.line.Bias
        line_settings = gpiod.LineSettings(
            direction=direction_enum.INPUT,
            bias=bias_enum.PULL_UP,
        )
        line_request = gpiod.request_lines(
            chip_path,
            consumer="dmx_controller",
            config={
                config.CONTACT_PIN: line_settings,
                config.SAFETY_SWITCH_PIN: line_settings,
            },
        )
        return None, line_request

    chip = gpiod.Chip(chip_id) if chip_id is not None else None
    try:
        contact_line = chip.get_line(config.CONTACT_PIN)
        contact_line.request(
            consumer="dmx_controller",
            type=gpiod.LINE_REQ_DIR_IN,
            flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_UP,
        )
        safety_line = chip.get_line(config.SAFETY_SWITCH_PIN)
        safety_line.request(
            consumer="dmx_controller",
            type=gpiod.LINE_REQ_DIR_IN,
            flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_UP,
        )
        return chip, (contact_line, safety_line)
    except Exception:
        if chip is not None:
            try:
                chip.close()
            except Exception:
                pass
        raise


def _open_lgpio_line(chip_id):
    chip_id = _normalize_gpiochip_id(chip_id)
    if isinstance(chip_id, str):
        digits = "".join(ch for ch in chip_id if ch.isdigit())
        chip_id = int(digits) if digits else None
    chip_id = 0 if chip_id is None else chip_id
    chip = lgpio.gpiochip_open(chip_id)
    try:
        lgpio.gpio_claim_input(chip, config.CONTACT_PIN, lgpio.SET_PULL_UP)
        lgpio.gpio_claim_input(chip, config.SAFETY_SWITCH_PIN, lgpio.SET_PULL_UP)
        return chip
    except Exception:
        try:
            lgpio.gpiochip_close(chip)
        except Exception:
            pass
        raise


def init_gpio():
    """Initialize GPIO for contact closure detection."""
    global GPIO_LIB

    if not GPIO_AVAILABLE:
        logger.info("GPIO not available (not running on Raspberry Pi)")
        return False

    if state.gpio_line is not None or state.gpio_chip is not None:
        try:
            if GPIO_LIB == 'gpiod' and state.gpio_line is not None:
                state.gpio_line.release()
            if GPIO_LIB == 'gpiod' and state.gpio_safety_line is not None:
                state.gpio_safety_line.release()
            if GPIO_LIB == 'gpiod' and state.gpio_chip is not None:
                state.gpio_chip.close()
            if GPIO_LIB == 'lgpio' and state.gpio_chip is not None:
                lgpio.gpiochip_close(state.gpio_chip)
        except Exception as e:
            logger.warning("GPIO cleanup before init failed: %s", e)
        state.gpio_line = None
        state.gpio_safety_line = None
        state.gpio_chip = None
        state.gpio_chip_id = None

    libs_to_try = []
    if GPIO_LIB == 'gpiod':
        libs_to_try.append('gpiod')
        if lgpio is not None:
            libs_to_try.append('lgpio')
    elif GPIO_LIB == 'lgpio':
        libs_to_try.append('lgpio')
        if gpiod is not None:
            libs_to_try.append('gpiod')
    else:
        if gpiod is not None:
            libs_to_try.append('gpiod')
        if lgpio is not None:
            libs_to_try.append('lgpio')

    for lib in libs_to_try:
        try:
            if lib == 'gpiod':
                for chip_id in _gpiochip_candidates():
                    try:
                        state.gpio_chip, opened_line = _open_gpiod_line(chip_id)
                        if isinstance(opened_line, tuple):
                            state.gpio_line, state.gpio_safety_line = opened_line
                        else:
                            state.gpio_line = opened_line
                            state.gpio_safety_line = None
                        state.gpio_ready = True
                        state.gpio_chip_id = chip_id
                        GPIO_LIB = 'gpiod'
                        logger.info("GPIO initialized (gpiod) - %s pin %d with pull-up",
                                    chip_id, config.CONTACT_PIN)
                        return True
                    except Exception as e:
                        logger.debug("GPIO init failed on %s (gpiod): %s", chip_id, e)

            elif lib == 'lgpio':
                for chip_id in _gpiochip_candidates():
                    try:
                        state.gpio_chip = _open_lgpio_line(chip_id)
                        state.gpio_ready = True
                        state.gpio_chip_id = chip_id
                        GPIO_LIB = 'lgpio'
                        logger.info("GPIO initialized (lgpio) - %s pin %d with pull-up",
                                    chip_id, config.CONTACT_PIN)
                        return True
                    except Exception as e:
                        logger.debug("GPIO init failed on %s (lgpio): %s", chip_id, e)

        except Exception as e:
            logger.warning("GPIO initialization failed (%s): %s", lib, e)

    state.gpio_ready = False
    logger.warning("GPIO: all libraries and chips exhausted - trigger unavailable")
    return False


def _gpio_value_to_int(val):
    if hasattr(val, 'value'):
        return int(val.value)
    return int(val)


def _read_gpio_pin(pin):
    if GPIO_LIB == 'gpiod':
        try:
            return _gpio_value_to_int(state.gpio_line.get_value(pin))
        except TypeError:
            line = state.gpio_line if pin == config.CONTACT_PIN else state.gpio_safety_line
            if line is None:
                return None
            return _gpio_value_to_int(line.get_value())
    if GPIO_LIB == 'lgpio':
        return lgpio.gpio_read(state.gpio_chip, pin)
    return None


def check_contact_state():
    if not GPIO_AVAILABLE or not state.gpio_ready:
        return None
    try:
        return _read_gpio_pin(config.CONTACT_PIN)
    except Exception as e:
        logger.warning("GPIO read error: %s", e)
        return None


def check_safety_switch_state():
    if not GPIO_AVAILABLE or not state.gpio_ready:
        return None
    try:
        return _read_gpio_pin(config.SAFETY_SWITCH_PIN)
    except Exception as e:
        logger.warning("Safety GPIO read error: %s", e)
        return None


def is_safe_to_operate():
    safety_state = check_safety_switch_state()
    if safety_state is None:
        return True  # No safety switch = always safe
    return safety_state == 0


def trigger_sequence():
    """Execute the trigger sequence (apply trigger scene, then revert after duration)"""
    if not is_safe_to_operate():
        logger.info("Trigger ignored: safety switch is OFF/unsafe")
        return False

    trigger_scene = config.TRIGGER_SCENE
    if trigger_scene is None or trigger_scene not in config.SCENES:
        logger.info("Trigger ignored: no trigger scene configured")
        return False

    logger.info("TRIGGER DETECTED!")

    with state.timer_lock:
        if state.trigger_timer is not None:
            state.trigger_timer.cancel()

        apply_scene(trigger_scene)

        idle_scene = config.IDLE_SCENE

        def _return_to_idle():
            with state.timer_lock:
                if idle_scene and idle_scene in config.SCENES:
                    apply_scene(idle_scene)
                else:
                    # Blackout
                    with state.dmx_lock:
                        for i in range(1, config.DMX_CHANNELS + 1):
                            state.dmx_data[i] = 0
                    state.current_scene = None
                state.trigger_timer = None

        state.trigger_timer = Timer(config.TRIGGER_DURATION, _return_to_idle)
        state.trigger_timer.daemon = True
        state.trigger_timer.start()

    logger.info("Timer set: revert in %.1f seconds", config.TRIGGER_DURATION)
    return True

# ============================================
# Flask Routes
# ============================================

@app.route('/')
def index():
    return send_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html'))


@app.route('/api/status')
def api_status():
    contact_state = check_contact_state()
    safety_switch_state = check_safety_switch_state()

    return jsonify({
        'enttec_connected': state.ftdi_device is not None,
        'enttec_url': state.enttec_url,
        'enttec_last_error': state.enttec_last_error,
        'dmx_running': state.dmx_running and (state.dmx_thread is not None and state.dmx_thread.is_alive()),
        'current_scene': state.current_scene,
        'contact_state': 'closed' if contact_state == 0 else 'open' if contact_state == 1 else 'unknown',
        'safety_switch_state': 'on' if safety_switch_state == 0 else 'off' if safety_switch_state == 1 else 'unknown',
        'safe_to_operate': is_safe_to_operate(),
        'gpio_available': GPIO_AVAILABLE,
        'gpio_ready': state.gpio_ready,
        'visible_channels': config.VISIBLE_CHANNELS,
        'trigger_duration': config.TRIGGER_DURATION,
        'trigger_scene': config.TRIGGER_SCENE,
        'idle_scene': config.IDLE_SCENE,
        'artnet_enabled': config.ARTNET_ENABLED,
        'artnet_target_ip': config.ARTNET_TARGET_IP,
        'artnet_universe': config.ARTNET_UNIVERSE,
        'artnet_receiver_enabled': config.ARTNET_RECEIVER_ENABLED,
        'artnet_receiver_active': state.artnet_receiver_running and state.artnet_receiver_thread is not None and state.artnet_receiver_thread.is_alive(),
        'artnet_receiver_packets': state.artnet_receiver_packets,
        'artnet_receiver_last_seen': round(time.monotonic() - state.artnet_receiver_last_seen, 1) if state.artnet_receiver_last_seen > 0 else None,
        'channels': get_current_channels(),
        'channel_labels': {str(k): v for k, v in config.CHANNEL_LABELS.items()},
    })


@app.route('/api/trigger', methods=['POST'])
def api_trigger():
    if trigger_sequence():
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Trigger failed (safety switch OFF or no trigger scene configured)'}), 409


@app.route('/api/scene/<scene_id>', methods=['POST'])
def api_apply_scene(scene_id):
    if not is_safe_to_operate():
        return jsonify({'error': 'Safety switch is OFF'}), 409
    with state.timer_lock:
        if state.trigger_timer is not None:
            state.trigger_timer.cancel()
            state.trigger_timer = None

    if apply_scene(scene_id):
        return jsonify({'success': True, 'scene': scene_id})
    else:
        return jsonify({'error': 'Scene not found'}), 404


@app.route('/api/scenes', methods=['GET'])
def api_list_scenes():
    scenes = {}
    for sid, scene in config.SCENES.items():
        scenes[sid] = {
            'name': scene['name'],
            'channels': scene['channels']
        }
    return jsonify(scenes)


@app.route('/api/scenes', methods=['POST'])
def api_create_scene():
    """Create or update a scene"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400

    scene_id = data.get('id')
    name = data.get('name', '')
    raw_channels = data.get('channels', {})

    if not scene_id or not isinstance(scene_id, str):
        return jsonify({'error': 'Scene id is required'}), 400

    # Sanitize scene id
    scene_id = scene_id.strip().replace(' ', '_')[:64]
    if not scene_id:
        return jsonify({'error': 'Invalid scene id'}), 400

    channels = {}
    try:
        for ch, val in raw_channels.items():
            ch_int = int(ch)
            if 1 <= ch_int <= config.DMX_CHANNELS:
                channels[ch_int] = max(0, min(255, int(val)))
    except (TypeError, ValueError) as e:
        return jsonify({'error': f'Invalid channel data: {e}'}), 400

    config.SCENES[scene_id] = {
        'name': name or scene_id,
        'channels': channels
    }
    save_config()

    if state.current_scene == scene_id:
        apply_scene(scene_id)

    return jsonify({'success': True, 'id': scene_id})


@app.route('/api/scenes/<scene_id>', methods=['DELETE'])
def api_delete_scene(scene_id):
    """Delete a scene"""
    if scene_id not in config.SCENES:
        return jsonify({'error': 'Scene not found'}), 404

    del config.SCENES[scene_id]

    # Clean up references
    if config.TRIGGER_SCENE == scene_id:
        config.TRIGGER_SCENE = None
    if config.IDLE_SCENE == scene_id:
        config.IDLE_SCENE = None
    if state.current_scene == scene_id:
        state.current_scene = None

    save_config()
    return jsonify({'success': True})


@app.route('/api/channel', methods=['POST'])
def api_set_channel():
    data = request.get_json()
    if not data or 'channel' not in data or 'value' not in data:
        return jsonify({'error': 'Missing channel or value'}), 400

    try:
        channel = int(data['channel'])
        value = int(data['value'])
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid channel or value'}), 400

    if not (1 <= channel <= config.DMX_CHANNELS):
        return jsonify({'error': 'Channel out of range'}), 400

    safe_value = max(0, min(255, value))
    set_channel(channel, safe_value)
    return jsonify({'success': True, 'channel': channel, 'value': safe_value})


@app.route('/api/channels', methods=['POST'])
def api_set_channels():
    """Set multiple channels at once"""
    data = request.get_json()
    if not isinstance(data, dict) or 'channels' not in data:
        return jsonify({'error': 'Missing channels object'}), 400

    try:
        with state.dmx_lock:
            for ch, val in data['channels'].items():
                ch_int = int(ch)
                if 1 <= ch_int <= config.DMX_CHANNELS:
                    state.dmx_data[ch_int] = max(0, min(255, int(val)))
    except (TypeError, ValueError) as e:
        return jsonify({'error': f'Invalid channel data: {e}'}), 400

    return jsonify({'success': True})


@app.route('/api/blackout', methods=['POST'])
def api_blackout():
    with state.timer_lock:
        if state.trigger_timer is not None:
            state.trigger_timer.cancel()
            state.trigger_timer = None
    with state.dmx_lock:
        for i in range(1, config.DMX_CHANNELS + 1):
            state.dmx_data[i] = 0
    state.current_scene = None
    logger.info("BLACKOUT - All channels zeroed")
    return jsonify({'success': True})


@app.route('/api/channels/all', methods=['POST'])
def api_set_all_channels():
    """Set all visible channels to a single value"""
    data = request.get_json()
    if not isinstance(data, dict) or 'value' not in data:
        return jsonify({'error': 'Missing value'}), 400

    try:
        value = max(0, min(255, int(data['value'])))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid value'}), 400

    with state.dmx_lock:
        for i in range(1, config.VISIBLE_CHANNELS + 1):
            state.dmx_data[i] = value
    state.current_scene = None
    logger.info("Set all %d channels to %d", config.VISIBLE_CHANNELS, value)
    return jsonify({'success': True, 'value': value})


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'POST':
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({'error': 'Invalid JSON body'}), 400

        if 'visible_channels' in data:
            config.VISIBLE_CHANNELS = max(1, min(512, int(data['visible_channels'])))

        if 'trigger_duration' in data:
            try:
                dur = float(data['trigger_duration'])
                if dur != dur:
                    return jsonify({'error': 'Invalid duration value'}), 400
                config.TRIGGER_DURATION = max(0.5, min(300.0, dur))
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid duration value'}), 400

        if 'trigger_scene' in data:
            val = data['trigger_scene']
            config.TRIGGER_SCENE = str(val) if val else None

        if 'idle_scene' in data:
            val = data['idle_scene']
            config.IDLE_SCENE = str(val) if val else None

        if 'channel_labels' in data and isinstance(data['channel_labels'], dict):
            for k, v in data['channel_labels'].items():
                try:
                    ch = int(k)
                    label = str(v).strip()
                    if label:
                        config.CHANNEL_LABELS[ch] = label
                    elif ch in config.CHANNEL_LABELS:
                        del config.CHANNEL_LABELS[ch]
                except (TypeError, ValueError):
                    pass

        if 'artnet_receiver_enabled' in data:
            was_receiver = config.ARTNET_RECEIVER_ENABLED
            config.ARTNET_RECEIVER_ENABLED = bool(data['artnet_receiver_enabled'])
            if config.ARTNET_RECEIVER_ENABLED and not was_receiver:
                # Disable sender when enabling receiver
                config.ARTNET_ENABLED = False
                if state.artnet_socket:
                    state.artnet_socket.close()
                    state.artnet_socket = None
                start_artnet_receiver()
            elif not config.ARTNET_RECEIVER_ENABLED and was_receiver:
                stop_artnet_receiver()

        if 'artnet_enabled' in data:
            was_enabled = config.ARTNET_ENABLED
            config.ARTNET_ENABLED = bool(data['artnet_enabled'])
            if config.ARTNET_ENABLED:
                # Disable receiver when enabling sender
                if config.ARTNET_RECEIVER_ENABLED:
                    config.ARTNET_RECEIVER_ENABLED = False
                    stop_artnet_receiver()
                if not was_enabled:
                    init_artnet()
            elif not config.ARTNET_ENABLED and was_enabled:
                if state.artnet_socket:
                    state.artnet_socket.close()
                    state.artnet_socket = None

        if 'artnet_target_ip' in data:
            ip_str = str(data['artnet_target_ip']).strip()
            if not validate_ip_address(ip_str):
                return jsonify({'error': f'Invalid IP address: {ip_str}'}), 400
            config.ARTNET_TARGET_IP = ip_str

        if 'artnet_universe' in data:
            config.ARTNET_UNIVERSE = max(0, min(32767, int(data['artnet_universe'])))

        save_config()
        return jsonify({'success': True})
    else:
        return jsonify({
            'visible_channels': config.VISIBLE_CHANNELS,
            'trigger_duration': config.TRIGGER_DURATION,
            'trigger_scene': config.TRIGGER_SCENE,
            'idle_scene': config.IDLE_SCENE,
            'channel_labels': {str(k): v for k, v in config.CHANNEL_LABELS.items()},
            'artnet_enabled': config.ARTNET_ENABLED,
            'artnet_target_ip': config.ARTNET_TARGET_IP,
            'artnet_universe': config.ARTNET_UNIVERSE,
            'artnet_receiver_enabled': config.ARTNET_RECEIVER_ENABLED,
            'contact_pin': config.CONTACT_PIN,
            'safety_switch_pin': config.SAFETY_SWITCH_PIN,
            'scenes': {sid: {'name': s['name'], 'channels': s['channels']} for sid, s in config.SCENES.items()},
        })


@app.route('/api/channel-labels', methods=['POST'])
def api_set_channel_labels():
    """Update channel labels"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400

    for k, v in data.items():
        try:
            ch = int(k)
            label = str(v).strip()
            if label:
                config.CHANNEL_LABELS[ch] = label
            elif ch in config.CHANNEL_LABELS:
                del config.CHANNEL_LABELS[ch]
        except (TypeError, ValueError):
            pass

    save_config()
    return jsonify({'success': True, 'labels': {str(k): v for k, v in config.CHANNEL_LABELS.items()}})

# ============================================
# Fixture Profiles
# ============================================

FIXTURE_PROFILES = {
    'generic-rgb-3ch': {
        'name': 'Generic RGB (3ch)',
        'manufacturer': 'Generic',
        'channels_per_fixture': 3,
        'channel_map': {
            1: 'Red',
            2: 'Green',
            3: 'Blue',
        },
    },
    'generic-rgbw-4ch': {
        'name': 'Generic RGBW (4ch: R/G/B/W)',
        'manufacturer': 'Generic',
        'channels_per_fixture': 4,
        'channel_map': {
            1: 'Red',
            2: 'Green',
            3: 'Blue',
            4: 'White',
        },
    },
    'generic-dimmer-rgbw-5ch': {
        'name': 'Generic Dimmer + RGBW (5ch)',
        'manufacturer': 'Generic',
        'channels_per_fixture': 5,
        'channel_map': {
            1: 'Dimmer',
            2: 'Red',
            3: 'Green',
            4: 'Blue',
            5: 'White',
        },
    },
    'generic-dimmer-strobe-rgbw-6ch': {
        'name': 'Generic Dimmer + Strobe + RGBW (6ch)',
        'manufacturer': 'Generic',
        'channels_per_fixture': 6,
        'channel_map': {
            1: 'Dimmer',
            2: 'Strobe',
            3: 'Red',
            4: 'Green',
            5: 'Blue',
            6: 'White',
        },
    },
    'generic-dimmer-strobe-macro-rgbw-7ch': {
        'name': 'Generic Dimmer + Strobe + Macro + RGBW (7ch)',
        'manufacturer': 'Generic',
        'channels_per_fixture': 7,
        'channel_map': {
            1: 'Dimmer',
            2: 'Strobe',
            3: 'Color Macro',
            4: 'Red',
            5: 'Green',
            6: 'Blue',
            7: 'White',
        },
    },
    'generic-rgbw-strobe-mode-speed-8ch': {
        'name': 'Generic RGBW + Strobe + Mode + Speed (8ch)',
        'manufacturer': 'Generic',
        'channels_per_fixture': 8,
        'channel_map': {
            1: 'Dimmer',
            2: 'Red',
            3: 'Green',
            4: 'Blue',
            5: 'White',
            6: 'Strobe',
            7: 'Mode',
            8: 'Speed',
        },
    },
    'generic-mode-dimmer-rgbw-strobe-speed-8ch': {
        'name': 'Generic Mode + Dimmer + RGBW + Strobe + Speed (8ch alt)',
        'manufacturer': 'Generic',
        'channels_per_fixture': 8,
        'channel_map': {
            1: 'Mode',
            2: 'Dimmer',
            3: 'Red',
            4: 'Green',
            5: 'Blue',
            6: 'White',
            7: 'Strobe',
            8: 'Speed',
        },
    },
    'generic-rgbw-strobe-macro-speed-mode-9ch': {
        'name': 'Generic RGBW + Strobe + Macro + Speed + Mode (9ch)',
        'manufacturer': 'Generic',
        'channels_per_fixture': 9,
        'channel_map': {
            1: 'Dimmer',
            2: 'Red',
            3: 'Green',
            4: 'Blue',
            5: 'White',
            6: 'Strobe',
            7: 'Color Macro',
            8: 'Speed',
            9: 'Mode',
        },
    },
    'generic-par-basic-8ch': {
        'name': 'Generic LED PAR Basic (8ch)',
        'manufacturer': 'Generic',
        'channels_per_fixture': 8,
        'channel_map': {
            1: 'Dimmer',
            2: 'Red',
            3: 'Green',
            4: 'Blue',
            5: 'White',
            6: 'Strobe',
            7: 'Program',
            8: 'Speed',
        },
    },
    'generic-moving-head-12ch': {
        'name': 'Generic Moving Head Spot/Wash (12ch)',
        'manufacturer': 'Generic',
        'channels_per_fixture': 12,
        'channel_map': {
            1: 'Pan',
            2: 'Pan Fine',
            3: 'Tilt',
            4: 'Tilt Fine',
            5: 'Pan/Tilt Speed',
            6: 'Dimmer',
            7: 'Shutter/Strobe',
            8: 'Color',
            9: 'Gobo',
            10: 'Gobo Rotate',
            11: 'Prism/Focus',
            12: 'Control/Reset',
        },
    },
}


@app.route('/api/fixture-profiles', methods=['GET'])
def api_list_fixture_profiles():
    """List available fixture profiles"""
    profiles = {}
    for pid, profile in FIXTURE_PROFILES.items():
        profiles[pid] = {
            'name': profile['name'],
            'manufacturer': profile['manufacturer'],
            'channels_per_fixture': profile['channels_per_fixture'],
            'channel_map': {str(k): v for k, v in profile['channel_map'].items()},
        }
    return jsonify(profiles)


@app.route('/api/fixture-profiles/apply', methods=['POST'])
def api_apply_fixture_profile():
    """Apply a fixture profile: sets channel labels and visible channel count"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or 'profile_id' not in data:
        return jsonify({'error': 'Missing profile_id'}), 400

    profile_id = data['profile_id']
    if profile_id not in FIXTURE_PROFILES:
        return jsonify({'error': f'Unknown profile: {profile_id}'}), 404

    profile = FIXTURE_PROFILES[profile_id]
    start_address = max(1, min(512, int(data.get('start_address', 1))))
    fixture_count = max(1, int(data.get('fixture_count', 1)))
    channels_per_fixture = profile['channels_per_fixture']

    # Clear existing labels
    config.CHANNEL_LABELS = {}

    # Apply labels for each fixture
    for fixture_idx in range(fixture_count):
        base = start_address + (fixture_idx * channels_per_fixture)
        for offset, label in profile['channel_map'].items():
            ch = base + (offset - 1)
            if ch > 512:
                break
            if fixture_count > 1:
                config.CHANNEL_LABELS[ch] = f'F{fixture_idx + 1} {label}'
            else:
                config.CHANNEL_LABELS[ch] = label

    # Set visible channels to cover all fixtures
    total_channels = start_address - 1 + (fixture_count * channels_per_fixture)
    config.VISIBLE_CHANNELS = max(config.VISIBLE_CHANNELS, min(512, total_channels))

    save_config()
    logger.info("Applied fixture profile '%s' (%d fixture(s) starting at ch %d)",
                profile['name'], fixture_count, start_address)
    return jsonify({
        'success': True,
        'profile': profile['name'],
        'visible_channels': config.VISIBLE_CHANNELS,
        'channel_labels': {str(k): v for k, v in config.CHANNEL_LABELS.items()},
    })

# ============================================
# Channel Tester
# ============================================

@app.route('/api/test-channel', methods=['POST'])
def api_test_channel():
    """Set a single channel to a value, all others to 0. For DMX mapping discovery."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or 'channel' not in data:
        return jsonify({'error': 'Missing channel'}), 400

    try:
        channel = max(1, min(512, int(data['channel'])))
        value = max(0, min(255, int(data.get('value', 255))))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid channel or value'}), 400

    # Zero all channels first, then set requested channel (1-indexed)
    with state.dmx_lock:
        for i in range(1, config.DMX_CHANNELS + 1):
            state.dmx_data[i] = 0
        state.dmx_data[channel] = value

    logger.info("Channel test: ch %d = %d (all others = 0)", channel, value)
    return jsonify({'success': True, 'channel': channel, 'value': value})


# ============================================
# Health Check
# ============================================

@app.route('/api/health')
def api_health():
    healthy = state.dmx_running and state.dmx_thread is not None and state.dmx_thread.is_alive()
    status_code = 200 if healthy else 503
    return jsonify({
        'status': 'ok' if healthy else 'degraded',
        'enttec_connected': state.ftdi_device is not None,
        'enttec_url': state.enttec_url,
        'enttec_last_error': state.enttec_last_error,
        'dmx_running': healthy,
        'artnet_enabled': config.ARTNET_ENABLED,
        'artnet_receiver_enabled': config.ARTNET_RECEIVER_ENABLED,
        'artnet_receiver_active': state.artnet_receiver_running,
        'gpio_available': GPIO_AVAILABLE,
        'gpio_ready': state.gpio_ready,
        'safe_to_operate': is_safe_to_operate(),
    }), status_code

# ============================================
# Initialization & Shutdown
# ============================================

_initialized = False


def _gpio_monitor():
    """Background thread: polls GPIO for contact closure events."""
    last_state = None
    last_safety_state = None
    last_trigger_time = 0.0
    consecutive_errors = 0
    max_errors_before_reinit = 3

    while state.dmx_running:
        try:
            if not state.gpio_ready:
                if init_gpio():
                    logger.info("GPIO initialized from monitor thread")
                    last_state = None
                else:
                    time.sleep(5.0)
                    continue

            current_state = check_contact_state()
            safety_state = check_safety_switch_state()
            if safety_state is not None:
                if last_safety_state == 0 and safety_state == 1:
                    logger.warning("Safety switch turned OFF - forcing blackout")
                    with state.timer_lock:
                        if state.trigger_timer is not None:
                            state.trigger_timer.cancel()
                            state.trigger_timer = None
                    # Apply idle scene or blackout
                    if config.IDLE_SCENE and config.IDLE_SCENE in config.SCENES:
                        apply_scene(config.IDLE_SCENE)
                    else:
                        with state.dmx_lock:
                            for i in range(1, config.DMX_CHANNELS + 1):
                                state.dmx_data[i] = 0
                        state.current_scene = None
                last_safety_state = safety_state

            if current_state is not None:
                now = time.monotonic()
                if (last_state == 1 and current_state == 0
                        and (now - last_trigger_time) >= config.DEBOUNCE_TIME):
                    last_trigger_time = now
                    trigger_sequence()
                last_state = current_state
                consecutive_errors = 0
            time.sleep(0.05)
        except Exception as e:
            consecutive_errors += 1
            logger.warning("GPIO monitor error (%d/%d): %s",
                           consecutive_errors, max_errors_before_reinit, e)
            if consecutive_errors >= max_errors_before_reinit:
                logger.info("Attempting GPIO re-initialization...")
                state.gpio_ready = False
                last_state = None
                consecutive_errors = 0
            time.sleep(1.0)


def _cleanup():
    global _initialized
    if not _initialized:
        return
    _initialized = False

    logger.info("Shutting down DMX controller...")
    stop_dmx_refresh()

    with state.timer_lock:
        if state.trigger_timer:
            state.trigger_timer.cancel()

    with state.ftdi_lock:
        if state.ftdi_device:
            try:
                state.ftdi_device.close()
            except Exception:
                pass
        state.ftdi_device = None
        state.enttec_url = None

    if state.artnet_socket:
        try:
            state.artnet_socket.close()
        except Exception:
            pass
        state.artnet_socket = None

    stop_artnet_receiver()

    if GPIO_AVAILABLE:
        try:
            if GPIO_LIB == 'gpiod' and state.gpio_line is not None:
                state.gpio_line.release()
            if GPIO_LIB == 'gpiod' and state.gpio_safety_line is not None:
                state.gpio_safety_line.release()
            if GPIO_LIB == 'gpiod' and state.gpio_chip is not None:
                state.gpio_chip.close()
            if GPIO_LIB == 'lgpio' and state.gpio_chip is not None:
                lgpio.gpiochip_close(state.gpio_chip)
        except Exception as e:
            logger.warning("GPIO cleanup failed: %s", e)

    logger.info("Shutdown complete")


def _initialize():
    global _initialized
    if _initialized:
        return
    _initialized = True

    logger.info("=" * 50)
    logger.info("DMX CONTROLLER - General Purpose")
    logger.info("=" * 50)

    load_config()

    with state.ftdi_lock:
        if not init_enttec():
            logger.warning("ENTTEC not available at startup. Will keep retrying in the background.")

    # Art-Net sender and receiver are mutually exclusive
    if config.ARTNET_RECEIVER_ENABLED:
        config.ARTNET_ENABLED = False  # Disable sender when in receiver mode
        start_artnet_receiver()
    elif config.ARTNET_ENABLED:
        init_artnet()

    start_dmx_refresh()
    time.sleep(0.5)

    init_gpio()

    if GPIO_AVAILABLE:
        Thread(target=_gpio_monitor, daemon=True).start()

    atexit.register(_cleanup)

    outputs = []
    if state.ftdi_device is not None:
        outputs.append("ENTTEC USB")
    elif FTDI_AVAILABLE:
        outputs.append("ENTTEC USB (retrying)")
    if config.ARTNET_RECEIVER_ENABLED:
        outputs.append(f"Art-Net Receiver (universe {config.ARTNET_UNIVERSE})")
    elif config.ARTNET_ENABLED:
        outputs.append(f"Art-Net ({config.ARTNET_TARGET_IP} universe {config.ARTNET_UNIVERSE})")

    logger.info("=" * 50)
    logger.info("System ready!")
    logger.info("  Visible channels: %d", config.VISIBLE_CHANNELS)
    logger.info("  Output: %s", ', '.join(outputs) if outputs else 'none configured')
    logger.info("  Scenes loaded: %d", len(config.SCENES))
    logger.info("  Web interface: http://0.0.0.0:5000")
    if GPIO_AVAILABLE and state.gpio_ready:
        logger.info("  GPIO trigger pin %d monitoring active", config.CONTACT_PIN)
        logger.info("  GPIO safety switch pin %d monitoring active", config.SAFETY_SWITCH_PIN)
    elif GPIO_AVAILABLE:
        logger.info("  GPIO available but init failed - monitor will retry automatically")
    logger.info("=" * 50)


def _on_sigterm(_signum, _frame):
    sys.exit(0)


signal.signal(signal.SIGTERM, _on_sigterm)
_initialize()


def main():
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")


if __name__ == "__main__":
    main()
