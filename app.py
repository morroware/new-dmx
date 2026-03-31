#!/usr/bin/env python3
"""
General-Purpose DMX512 Controller
Supports ENTTEC DMX USB Pro (primary), ENTTEC Open DMX USB (fallback),
and Art-Net output.  Configurable channels, unlimited named scenes, and web UI.
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
import rdm as rdm_module

# ============================================
# Logging Setup
# ============================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dmx")

# --- Serial (ENTTEC DMX USB Pro) ---
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except Exception as serial_import_error:
    serial = None
    SERIAL_AVAILABLE = False

# --- PyFTDI (ENTTEC Open DMX USB fallback) ---
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
    DMX_REFRESH_RATE = 40
    # Driver selection: "auto" tries Pro first, then Open DMX USB.
    # Force with "enttec_pro" or "enttec_open".
    DMX_DRIVER = os.environ.get("DMX_DRIVER", "auto")
    # Serial port for ENTTEC DMX USB Pro (auto-detected if empty)
    DMX_SERIAL_PORT = os.environ.get("DMX_SERIAL_PORT", "")
    FTDI_URL = os.environ.get("DMX_FTDI_URL", "ftdi://0403:6001/1")

    # How many channels to show in the UI by default.
    # 16 channels covers 4 RuggedGrade 1200W RGB Stadium Lights in 4ch
    # RGBW mode (4 fixtures × 4 channels = 16).  Increase to 400 for
    # the full 100-fixture capacity shown in the channel guide.
    # Run  python3 diagnose_decoder.py  to auto-detect channel layout.
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
    #
    # Default: 4x RuggedGrade 1200W RGB Stadium Lights, 4ch RGBW mode,
    # starting at address 1.  Per the channel guide each fixture uses
    # 4 channels (Red, Green, Blue, White) with addresses incrementing
    # by 4.  Apply the 'ruggedgrade-1200w-rgb-stadium-4ch' fixture
    # profile via the UI to reconfigure for a different fixture count.
    CHANNEL_LABELS = {
        1: 'F1 Red', 2: 'F1 Green', 3: 'F1 Blue', 4: 'F1 White',
        5: 'F2 Red', 6: 'F2 Green', 7: 'F2 Blue', 8: 'F2 White',
        9: 'F3 Red', 10: 'F3 Green', 11: 'F3 Blue', 12: 'F3 White',
        13: 'F4 Red', 14: 'F4 Green', 15: 'F4 Blue', 16: 'F4 White',
    }

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
        # DMX output device — exactly one of serial_device (Pro) or ftdi_device (Open) is active
        self.serial_device = None       # pyserial Serial object (ENTTEC DMX USB Pro)
        self.ftdi_device = None         # pyftdi Ftdi object (ENTTEC Open DMX USB)
        self.dmx_driver = None          # "enttec_pro" | "enttec_open" | None
        self.ftdi_lock = Lock()         # Protects both serial_device and ftdi_device
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
        self.enttec_url = None          # FTDI URL or serial port path
        self.enttec_last_error = None
        # GPIO monitoring
        self.gpio_running = False
        # Art-Net
        self.artnet_socket = None
        self.artnet_sequence = 0
        # Art-Net Receiver
        self.artnet_receiver_socket = None
        self.artnet_receiver_thread = None
        self.artnet_receiver_running = False
        self.artnet_receiver_packets = 0
        self.artnet_receiver_last_seen = 0  # monotonic timestamp of last packet
        # RDM (Remote Device Management)
        self.rdm_supported = False          # True if ENTTEC Pro supports RDM
        self.rdm_devices = {}               # {uid_string: RDMDevice}
        self.rdm_discovery_running = False
        self.rdm_lock = Lock()              # Protects rdm_devices dict
        self.rdm_last_discovery = 0         # monotonic timestamp

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
        return False


def normalize_scene_id(scene_id):
    """Normalize and validate a scene id."""
    if not isinstance(scene_id, str):
        return None
    normalized = scene_id.strip().replace(' ', '_')[:64]
    return normalized or None


def parse_scene_channels(raw_channels):
    """Validate and normalize incoming scene channel payload."""
    if raw_channels is None:
        raw_channels = {}
    if not isinstance(raw_channels, dict):
        raise ValueError("channels must be an object of channel/value pairs")

    channels = {}
    for ch, val in raw_channels.items():
        ch_int = int(ch)
        if 1 <= ch_int <= config.DMX_CHANNELS:
            channels[ch_int] = max(0, min(255, int(val)))
    return channels

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

# ENTTEC DMX USB Pro protocol constants
ENTTEC_PRO_START = 0x7E
ENTTEC_PRO_END = 0xE7
ENTTEC_PRO_SEND_DMX = 6        # Label: Send DMX Packet
ENTTEC_PRO_GET_PARAMS = 3      # Label: Get Widget Parameters
ENTTEC_PRO_GET_SERIAL = 10     # Label: Get Widget Serial Number
ENTTEC_PRO_SEND_RDM = 7        # Label: Send RDM Packet Request
ENTTEC_PRO_RECEIVE_DMX = 5     # Label: Receive DMX Packet (RDM response comes here too)
ENTTEC_PRO_SEND_RDM_DISCOVERY = 11  # Label: Send RDM Discovery Request
# FTDI VID:PID used by both Open DMX USB and DMX USB Pro
ENTTEC_FTDI_VID = 0x0403
ENTTEC_FTDI_PID = 0x6001


def _enttec_pro_packet(label, data=b''):
    """Build an ENTTEC DMX USB Pro protocol packet.

    Format: [0x7E] [Label] [Data Length LSB] [Data Length MSB] [Data...] [0xE7]
    """
    length = len(data)
    return bytes([ENTTEC_PRO_START, label, length & 0xFF, (length >> 8) & 0xFF]) + data + bytes([ENTTEC_PRO_END])


def _find_enttec_pro_serial_ports():
    """Find candidate serial ports for ENTTEC DMX USB Pro.

    Returns a list of serial port paths, with explicitly configured port first.
    """
    ports = []
    if config.DMX_SERIAL_PORT:
        ports.append(config.DMX_SERIAL_PORT)

    if not SERIAL_AVAILABLE:
        return ports

    # Scan for FTDI serial ports (ENTTEC DMX USB Pro appears as /dev/ttyUSB*)
    try:
        for port_info in serial.tools.list_ports.comports():
            if port_info.vid == ENTTEC_FTDI_VID and port_info.pid == ENTTEC_FTDI_PID:
                if port_info.device not in ports:
                    ports.append(port_info.device)
            elif port_info.vid == ENTTEC_FTDI_VID:
                # Other FTDI PIDs (0x6014, etc.) — try them too
                if port_info.device not in ports:
                    ports.append(port_info.device)
    except Exception as e:
        logger.debug("Serial port enumeration failed: %s", e)

    # Also try common paths as fallback
    for fallback in ['/dev/ttyUSB0', '/dev/ttyUSB1', '/dev/ttyACM0']:
        if fallback not in ports and os.path.exists(fallback):
            ports.append(fallback)

    return ports


def _probe_enttec_pro(ser, retries=2):
    """Probe a serial port to check if an ENTTEC DMX USB Pro is connected.

    Sends a "Get Widget Parameters" request and checks for a valid response.
    Retries up to `retries` times to handle devices that need a moment after
    USB enumeration.  Kept short to avoid disturbing Open DMX USB devices
    (same FTDI VID:PID) that share the serial port in auto mode.
    Returns True if the device responds with the expected Pro protocol reply.
    """
    for attempt in range(retries):
        try:
            # Flush any stale data
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # Send Get Widget Parameters request (label 3, no data)
            probe_request = _enttec_pro_packet(ENTTEC_PRO_GET_PARAMS, b'\x00\x00')
            ser.write(probe_request)
            ser.flush()

            # Wait for response — Pro typically replies within 50-100ms
            time.sleep(0.15)

            # Read available bytes
            response = ser.read(ser.in_waiting or 64)
            if len(response) < 5:
                if attempt < retries - 1:
                    logger.debug("Pro probe attempt %d: short response (%d bytes), retrying...",
                                 attempt + 1, len(response))
                continue

            # Check for valid Pro protocol response
            # Response should start with 0x7E and have label 3
            if response[0] == ENTTEC_PRO_START and response[1] == ENTTEC_PRO_GET_PARAMS:
                data_len = response[2] | (response[3] << 8)
                if len(response) >= 4 + data_len + 1 and response[4 + data_len] == ENTTEC_PRO_END:
                    logger.info("ENTTEC DMX USB Pro detected (firmware v%d.%d)",
                               response[4] if data_len > 0 else 0,
                               response[5] if data_len > 1 else 0)
                    return True

        except Exception as e:
            logger.debug("Pro probe attempt %d failed: %s", attempt + 1, e)

    return False


def _init_enttec_pro():
    """Initialize ENTTEC DMX USB Pro via serial port.

    Caller must hold state.ftdi_lock.
    Returns True on success.
    """
    if not SERIAL_AVAILABLE:
        logger.info("pyserial not available — cannot probe for ENTTEC DMX USB Pro. "
                     "Install with: pip install pyserial")
        return False

    ports = _find_enttec_pro_serial_ports()
    if not ports:
        logger.debug("No candidate serial ports found for ENTTEC DMX USB Pro")
        return False

    logger.info("Searching for ENTTEC DMX USB Pro on %d serial port(s)...", len(ports))
    for port_path in ports:
        try:
            logger.info("  Trying %s...", port_path)
            ser = serial.Serial(
                port=port_path,
                baudrate=57600,         # Pro communicates at 57600 baud (not DMX 250k)
                bytesize=serial.EIGHTBITS,
                stopbits=serial.STOPBITS_ONE,
                parity=serial.PARITY_NONE,
                timeout=1.0,
                write_timeout=1.0,
            )

            if _probe_enttec_pro(ser):
                state.serial_device = ser
                state.dmx_driver = "enttec_pro"
                state.enttec_url = port_path
                state.enttec_last_error = None
                logger.info("ENTTEC DMX USB Pro initialized on %s", port_path)
                return True
            else:
                ser.close()
                logger.info("  %s did not respond as DMX USB Pro", port_path)
        except Exception as e:
            logger.debug("  Failed to open %s: %s", port_path, e)

    return False


def _flush_usb_cache():
    """Flush pyftdi's internal USB device cache to force fresh enumeration."""
    try:
        if UsbTools is not None:
            UsbTools.flush_cache()
    except Exception:
        pass
    try:
        if UsbTools is not None:
            UsbTools.release_all_devices()
    except Exception:
        pass


def _disable_usb_autosuspend():
    """Disable USB autosuspend for FTDI devices to prevent kernel-level disconnects."""
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
                pass
    except Exception:
        pass


def _unbind_ftdi_sio():
    """Unbind the ftdi_sio kernel driver from FTDI USB interfaces.

    When ftdi_sio is loaded (needed for DMX USB Pro), it claims all FTDI
    devices and prevents pyftdi/libusb from opening them.  This function
    detaches ftdi_sio from each bound USB interface via sysfs so that
    pyftdi can claim the device for Open DMX USB mode.

    Only affects the driver binding — does not unload the module, so a
    subsequently plugged-in Pro will still get a serial port.

    Returns True if at least one interface was successfully unbound.
    """
    unbind_path = "/sys/bus/usb/drivers/ftdi_sio/unbind"
    if not os.path.exists(unbind_path):
        logger.info("ftdi_sio not loaded or no devices bound (no unbind needed)")
        return False

    driver_dir = "/sys/bus/usb/drivers/ftdi_sio"
    unbound_any = False
    try:
        entries = [e for e in os.listdir(driver_dir) if ':' in e]
        if not entries:
            logger.info("ftdi_sio loaded but no USB interfaces bound")
            return False

        logger.info("Found %d ftdi_sio binding(s) to release", len(entries))
        for entry in entries:
            try:
                with open(unbind_path, 'w') as f:
                    f.write(entry)
                logger.info("  Unbound ftdi_sio from %s", entry)
                unbound_any = True
            except PermissionError:
                logger.warning("  Cannot unbind ftdi_sio from %s (need root). "
                               "Try: sudo rmmod ftdi_sio  OR set "
                               "DMX_DRIVER=enttec_open and re-run install.sh", entry)
            except OSError as e:
                logger.warning("  Cannot unbind ftdi_sio from %s: %s", entry, e)
    except Exception as e:
        logger.warning("ftdi_sio unbind scan failed: %s", e)

    if unbound_any:
        # Give the USB subsystem time to release the device
        time.sleep(0.5)

    return unbound_any


def _init_enttec_open():
    """Initialize ENTTEC Open DMX USB via pyftdi.

    If the ftdi_sio kernel driver is bound to the FTDI device (e.g. in
    auto mode where ftdi_sio is loaded for Pro support), this function
    unbinds it first so that pyftdi/libusb can claim the device.

    Caller must hold state.ftdi_lock.
    Returns True on success.
    """
    if not FTDI_AVAILABLE:
        logger.info("pyftdi not available — cannot use ENTTEC Open DMX USB. "
                     "Install with: pip install pyftdi")
        state.enttec_last_error = (
            "pyftdi library not installed. "
            "Run: pip install pyftdi   (or re-run install.sh)"
        )
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
            sn = getattr(desc, 'sn', None)
            if sn:
                urls.append(f"ftdi://::{sn}/1")
                urls.append(f"ftdi://::{sn}/2")
        return list(dict.fromkeys(urls))

    try:
        # If ftdi_sio has the device, unbind it so pyftdi/libusb can claim it.
        # This is the normal path in auto mode where ftdi_sio stays loaded for
        # Pro support but the connected hardware turned out to be Open DMX.
        _unbind_ftdi_sio()

        _flush_usb_cache()

        # Enumerate FTDI devices.  After unbinding ftdi_sio (or after a prior
        # serial port close from the Pro probe), the USB subsystem may need
        # time to release the device.  Retry with increasing delays.
        logger.info("Searching for ENTTEC Open DMX USB...")
        devices = []
        for attempt in range(4):
            if attempt > 0:
                delay = 0.3 * attempt  # 0.3s, 0.6s, 0.9s
                logger.info("  FTDI enumeration retry %d (waiting %.1fs)...", attempt, delay)
                time.sleep(delay)
                _flush_usb_cache()
            try:
                devices = Ftdi.list_devices()
            except Exception as enum_err:
                logger.info("  FTDI enumeration attempt %d failed: %s", attempt + 1, enum_err)
                continue
            if devices:
                break

        if not devices:
            # Try to detect if the hardware is present at USB level even though
            # pyftdi can't enumerate it (kernel driver may still be holding it).
            usb_present = False
            try:
                import usb.core
                ftdi_devs = list(usb.core.find(
                    find_all=True, idVendor=ENTTEC_FTDI_VID))
                if ftdi_devs:
                    usb_present = True
                    logger.info("  USB hardware detected (%d FTDI device(s)) but "
                                "pyftdi cannot claim it — ftdi_sio may still be bound",
                                len(ftdi_devs))
            except Exception:
                pass

            if usb_present:
                state.enttec_last_error = (
                    "FTDI USB device detected but cannot be opened. "
                    "The ftdi_sio kernel driver is likely still bound. "
                    "Try: sudo rmmod ftdi_sio  OR set DMX_DRIVER=enttec_open "
                    "and re-run install.sh to blacklist ftdi_sio."
                )
            else:
                state.enttec_last_error = (
                    "No FTDI USB devices found. Check that the ENTTEC Open DMX USB "
                    "is plugged in and the USB cable is working."
                )
            logger.warning("%s", state.enttec_last_error)
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
                state.dmx_driver = "enttec_open"
                state.enttec_url = url
                state.enttec_last_error = None
                logger.info("Opened FTDI device with URL: %s", url)
                break
            except Exception as e:
                last_error = e
                logger.info("  FTDI open failed for %s: %s", url, e)

        if state.ftdi_device is None:
            state.enttec_last_error = (
                "FTDI device(s) found but cannot open any of them. "
                "Check udev permissions (MODE=\"0666\" for FTDI VID/PID) "
                "and that ftdi_sio is unbound. "
                f"Last error: {last_error}"
            )
            logger.error("%s", state.enttec_last_error)
            return False

        # Configure for DMX512
        state.ftdi_device.set_baudrate(250000)
        state.ftdi_device.set_line_property(8, 2, 'N')
        state.ftdi_device.set_flowctrl('')
        state.ftdi_device.set_latency_timer(2)
        state.ftdi_device.purge_tx_buffer()
        state.ftdi_device.purge_rx_buffer()

        try:
            usb_dev = state.ftdi_device.usb_dev
            if usb_dev is not None:
                usb_dev.default_timeout = 1000
        except Exception:
            pass

        _disable_usb_autosuspend()

        logger.info("ENTTEC Open DMX USB initialized successfully")
        return True

    except Exception as e:
        state.enttec_last_error = f"Error initializing ENTTEC Open DMX USB: {e}"
        logger.error("%s", state.enttec_last_error)
        return False


def init_enttec():
    """Initialize the DMX USB interface.

    Tries ENTTEC DMX USB Pro first (serial protocol), then falls back to
    Open DMX USB (raw FTDI).  Override with DMX_DRIVER env var.

    Caller must hold state.ftdi_lock.
    """
    driver = config.DMX_DRIVER.lower()

    if driver == "enttec_pro":
        # Force Pro only
        if _init_enttec_pro():
            return True
        state.enttec_last_error = "ENTTEC DMX USB Pro not found (DMX_DRIVER=enttec_pro)"
        logger.error("%s", state.enttec_last_error)
        return False

    if driver == "enttec_open":
        # Force Open DMX only
        if _init_enttec_open():
            return True
        state.enttec_last_error = "ENTTEC Open DMX USB not found (DMX_DRIVER=enttec_open)"
        logger.error("%s", state.enttec_last_error)
        return False

    # Auto mode: try Pro first, then Open DMX
    logger.info("Auto-detecting DMX USB interface...")
    logger.info("  pyserial available: %s  |  pyftdi available: %s",
                SERIAL_AVAILABLE, FTDI_AVAILABLE)

    if _init_enttec_pro():
        return True

    logger.info("DMX USB Pro not found, trying Open DMX USB...")
    if _init_enttec_open():
        return True

    if not SERIAL_AVAILABLE and not FTDI_AVAILABLE:
        state.enttec_last_error = (
            "No DMX libraries installed. "
            "Run: pip install pyserial pyftdi   (or re-run install.sh)"
        )
    else:
        state.enttec_last_error = (
            "No DMX USB interface found (tried Pro and Open DMX). "
            "Check USB connection and logs for details."
        )
    logger.warning("%s", state.enttec_last_error)
    return False


def _close_dmx_device():
    """Close whatever DMX device is currently open. Caller must hold ftdi_lock."""
    if state.serial_device is not None:
        try:
            state.serial_device.close()
        except Exception:
            pass
        state.serial_device = None
    if state.ftdi_device is not None:
        try:
            state.ftdi_device.close()
        except Exception:
            pass
        state.ftdi_device = None
    state.dmx_driver = None
    state.enttec_url = None


def _dmx_device_connected():
    """Return True if any DMX USB device is currently open."""
    return state.serial_device is not None or state.ftdi_device is not None


def reinit_enttec():
    """Safely close and re-initialize the DMX USB interface.

    Uses ftdi_lock to prevent the refresh thread from using a
    half-closed device.
    """
    with state.ftdi_lock:
        try:
            old_driver = state.dmx_driver
            _close_dmx_device()
            logger.info("Re-initializing DMX USB (was: %s)...", old_driver or "disconnected")
            return init_enttec()
        except Exception as e:
            state.enttec_last_error = f"Re-init failed: {e}"
            logger.error("Error re-initializing DMX USB: %s", e)
            return False


def _send_dmx_frame(frame):
    """Send a DMX frame using the active driver. Caller must hold ftdi_lock."""
    if state.dmx_driver == "enttec_pro" and state.serial_device is not None:
        # ENTTEC DMX USB Pro: wrap in Pro protocol packet
        # Label 6 = Send DMX Packet, data = start code + channel data
        packet = _enttec_pro_packet(ENTTEC_PRO_SEND_DMX, frame)
        state.serial_device.write(packet)
        state.serial_device.flush()
    elif state.dmx_driver == "enttec_open" and state.ftdi_device is not None:
        # ENTTEC Open DMX USB: raw FTDI break + data
        state.ftdi_device.set_break(True)
        state.ftdi_device.set_break(False)
        state.ftdi_device.write_data(frame)
    else:
        raise RuntimeError("No DMX device connected")


def _health_check_enttec_pro():
    """Verify the ENTTEC DMX USB Pro is still responding.

    Sends a Get Widget Parameters probe.  Returns True if the device
    replies correctly, False otherwise.  Caller must hold ftdi_lock.
    """
    if state.dmx_driver != "enttec_pro" or state.serial_device is None:
        return True  # Not using Pro, skip check
    try:
        state.serial_device.reset_input_buffer()
        probe = _enttec_pro_packet(ENTTEC_PRO_GET_PARAMS, b'\x00\x00')
        state.serial_device.write(probe)
        state.serial_device.flush()
        # Pro typically responds within 50-100ms; use 150ms to match the
        # probe timing and avoid false negatives under load.
        time.sleep(0.15)
        response = state.serial_device.read(state.serial_device.in_waiting or 64)
        if len(response) >= 5 and response[0] == ENTTEC_PRO_START and response[1] == ENTTEC_PRO_GET_PARAMS:
            return True
        return False
    except Exception:
        return False


# ============================================
# RDM Communication via ENTTEC DMX USB Pro
# ============================================

def _rdm_read_pro_response(timeout=0.5):
    """Read an ENTTEC Pro protocol response, waiting up to timeout seconds.

    Returns (label, data) tuple or (None, None) on timeout/error.
    Caller must hold ftdi_lock.
    """
    if state.serial_device is None:
        return None, None

    deadline = time.monotonic() + timeout
    buf = bytearray()

    while time.monotonic() < deadline:
        waiting = state.serial_device.in_waiting
        if waiting > 0:
            buf.extend(state.serial_device.read(waiting))
        else:
            time.sleep(0.01)
            continue

        # Try to parse an ENTTEC Pro packet from buffer
        while len(buf) >= 5:
            # Find start byte
            try:
                start_idx = buf.index(ENTTEC_PRO_START)
            except ValueError:
                buf.clear()
                break

            if start_idx > 0:
                del buf[:start_idx]

            if len(buf) < 5:
                break

            label = buf[1]
            data_len = buf[2] | (buf[3] << 8)
            total_len = 4 + data_len + 1  # header + data + end byte

            if len(buf) < total_len:
                break  # Need more data

            if buf[total_len - 1] == ENTTEC_PRO_END:
                data = bytes(buf[4:4 + data_len])
                del buf[:total_len]
                return label, data
            else:
                # Invalid packet, skip start byte and retry
                del buf[0:1]

    return None, None


def _send_rdm_command(rdm_packet, timeout=0.5):
    """Send an RDM command via ENTTEC Pro Label 7 and read the response.

    Args:
        rdm_packet: Complete RDM packet bytes (from rdm_module.build_rdm_packet).
        timeout: Seconds to wait for response.

    Returns:
        rdm_module.RDMResponse object, or None on communication failure.
    Caller must hold ftdi_lock.
    """
    if state.dmx_driver != "enttec_pro" or state.serial_device is None:
        return None

    try:
        state.serial_device.reset_input_buffer()

        # Label 7: Send RDM Packet Request
        # Data payload = the RDM packet (sub-start code through checksum)
        enttec_packet = _enttec_pro_packet(ENTTEC_PRO_SEND_RDM, rdm_packet)
        state.serial_device.write(enttec_packet)
        state.serial_device.flush()

        # Read the ENTTEC Pro response
        label, data = _rdm_read_pro_response(timeout=timeout)

        if label is None or data is None:
            return None

        # Label 7 response contains the RDM response packet
        if label == ENTTEC_PRO_SEND_RDM and len(data) > 0:
            return rdm_module.parse_rdm_response(data)

        return None

    except Exception as e:
        logger.debug("RDM command failed: %s", e)
        return None


def _send_rdm_discovery(rdm_packet, timeout=0.5):
    """Send an RDM discovery packet via ENTTEC Pro Label 11.

    Label 11 is specifically for DISC_UNIQUE_BRANCH — it handles
    the bus turnaround timing and collision detection internally.

    Returns raw response bytes or None.
    Caller must hold ftdi_lock.
    """
    if state.dmx_driver != "enttec_pro" or state.serial_device is None:
        return None

    try:
        state.serial_device.reset_input_buffer()

        enttec_packet = _enttec_pro_packet(ENTTEC_PRO_SEND_RDM_DISCOVERY, rdm_packet)
        state.serial_device.write(enttec_packet)
        state.serial_device.flush()

        label, data = _rdm_read_pro_response(timeout=timeout)

        if label is None or data is None:
            return None

        # Label 11 response: raw discovery response bytes (preamble + encoded UID)
        if label == ENTTEC_PRO_SEND_RDM_DISCOVERY and len(data) > 0:
            return data

        return None

    except Exception as e:
        logger.debug("RDM discovery send failed: %s", e)
        return None


def rdm_discover_devices():
    """Run full RDM discovery to find all devices on the bus.

    Uses binary search tree algorithm:
    1. Send DISC_UN_MUTE broadcast to unmute all
    2. Send DISC_UNIQUE_BRANCH for full UID range
    3. If collision, split range and recurse
    4. If single response, DISC_MUTE that device and continue

    Returns list of discovered RDMDevice objects.
    """
    if state.dmx_driver != "enttec_pro" or state.serial_device is None:
        logger.warning("RDM discovery requires ENTTEC DMX USB Pro")
        return []

    state.rdm_discovery_running = True
    discovered = []
    MAX_DEVICES = 512  # Safety limit

    try:
        with state.ftdi_lock:
            # Step 1: Unmute all devices
            logger.info("RDM Discovery: Sending DISC_UN_MUTE broadcast...")
            unmute_pkt = rdm_module.build_unmute_packet()
            _send_rdm_command(unmute_pkt, timeout=0.3)
            time.sleep(0.05)
            # Send unmute twice per spec
            _send_rdm_command(unmute_pkt, timeout=0.3)
            time.sleep(0.05)

        # Step 2: Binary search discovery
        lower = b'\x00\x00\x00\x00\x00\x00'
        upper = b'\xFF\xFF\xFF\xFF\xFF\xFF'

        _rdm_discover_branch(lower, upper, discovered, depth=0, max_devices=MAX_DEVICES)

        logger.info("RDM Discovery complete: found %d device(s)", len(discovered))

        # Step 3: Fetch device info for each discovered device
        for device in discovered:
            _rdm_fetch_device_info(device)
            device.last_seen = time.monotonic()

        # Update global state
        with state.rdm_lock:
            state.rdm_devices = {d.uid_string: d for d in discovered}
            state.rdm_last_discovery = time.monotonic()

    except Exception as e:
        logger.error("RDM discovery error: %s", e)
    finally:
        state.rdm_discovery_running = False

    return discovered


def _rdm_discover_branch(lower, upper, discovered, depth=0, max_devices=512):
    """Recursive binary search for RDM devices in UID range [lower, upper].

    Args:
        lower: 6-byte lower bound UID
        upper: 6-byte upper bound UID
        discovered: List to append found RDMDevice objects to
        depth: Current recursion depth (safety limit)
        max_devices: Maximum devices to discover
    """
    if depth > 48 or len(discovered) >= max_devices:
        return

    if lower > upper:
        return

    with state.ftdi_lock:
        # Send DISC_UNIQUE_BRANCH for this range
        disc_pkt = rdm_module.build_discovery_packet(lower, upper)
        raw_response = _send_rdm_discovery(disc_pkt, timeout=0.3)

    if raw_response is None or len(raw_response) == 0:
        # No devices in this range
        return

    # Try to parse a single device UID from the response
    uid = rdm_module.parse_discovery_response(raw_response)

    if uid is not None:
        # Got a clean response — single device or dominant collision winner
        # Try to mute this device
        with state.ftdi_lock:
            mute_pkt = rdm_module.build_mute_packet(uid)
            mute_resp = _send_rdm_command(mute_pkt, timeout=0.3)

        if mute_resp is not None and mute_resp.valid:
            device = rdm_module.RDMDevice(uid)
            device.muted = True
            discovered.append(device)
            logger.info("  RDM discovered device: %s", device.uid_string)

            # Continue searching same range for more devices
            _rdm_discover_branch(lower, upper, discovered, depth + 1, max_devices)
        else:
            # Mute failed — could be collision, try splitting
            _rdm_split_and_search(lower, upper, discovered, depth, max_devices)
    else:
        # Collision — response was garbled, split the search range
        _rdm_split_and_search(lower, upper, discovered, depth, max_devices)


def _rdm_split_and_search(lower, upper, discovered, depth, max_devices):
    """Split a UID range in half and search both halves."""
    lower_int = int.from_bytes(lower, 'big')
    upper_int = int.from_bytes(upper, 'big')

    if lower_int >= upper_int:
        return

    mid_int = lower_int + (upper_int - lower_int) // 2
    mid = mid_int.to_bytes(6, 'big')
    mid_plus_one = (mid_int + 1).to_bytes(6, 'big')

    _rdm_discover_branch(lower, mid, discovered, depth + 1, max_devices)
    _rdm_discover_branch(mid_plus_one, upper, discovered, depth + 1, max_devices)


def _rdm_fetch_device_info(device):
    """Fetch standard information about a discovered RDM device."""
    uid = device.uid

    with state.ftdi_lock:
        # GET DEVICE_INFO
        pkt = rdm_module.build_rdm_packet(uid, rdm_module.CC_GET_COMMAND,
                                           rdm_module.PID_DEVICE_INFO)
        resp = _send_rdm_command(pkt, timeout=0.5)
        if resp and resp.valid and resp.is_ack:
            info = rdm_module.parse_device_info(resp.data)
            if info:
                device.device_info = info
                device.dmx_start_address = info.dmx_start_address
                device.current_personality = info.current_personality
                device.personality_count = info.personality_count
                device.sensor_count = info.sensor_count

    time.sleep(0.02)

    with state.ftdi_lock:
        # GET DEVICE_LABEL
        pkt = rdm_module.build_rdm_packet(uid, rdm_module.CC_GET_COMMAND,
                                           rdm_module.PID_DEVICE_LABEL)
        resp = _send_rdm_command(pkt, timeout=0.5)
        if resp and resp.valid and resp.is_ack:
            device.device_label = resp.data.decode('ascii', errors='replace').rstrip('\x00')

    time.sleep(0.02)

    with state.ftdi_lock:
        # GET MANUFACTURER_LABEL
        pkt = rdm_module.build_rdm_packet(uid, rdm_module.CC_GET_COMMAND,
                                           rdm_module.PID_MANUFACTURER_LABEL)
        resp = _send_rdm_command(pkt, timeout=0.5)
        if resp and resp.valid and resp.is_ack:
            device.manufacturer_label = resp.data.decode('ascii', errors='replace').rstrip('\x00')

    time.sleep(0.02)

    with state.ftdi_lock:
        # GET DEVICE_MODEL_DESCRIPTION
        pkt = rdm_module.build_rdm_packet(uid, rdm_module.CC_GET_COMMAND,
                                           rdm_module.PID_DEVICE_MODEL_DESCRIPTION)
        resp = _send_rdm_command(pkt, timeout=0.5)
        if resp and resp.valid and resp.is_ack:
            device.model_description = resp.data.decode('ascii', errors='replace').rstrip('\x00')

    time.sleep(0.02)

    with state.ftdi_lock:
        # GET SOFTWARE_VERSION_LABEL
        pkt = rdm_module.build_rdm_packet(uid, rdm_module.CC_GET_COMMAND,
                                           rdm_module.PID_SOFTWARE_VERSION_LABEL)
        resp = _send_rdm_command(pkt, timeout=0.5)
        if resp and resp.valid and resp.is_ack:
            device.software_version_label = resp.data.decode('ascii', errors='replace').rstrip('\x00')

    # Fetch personality descriptions if available
    if device.personality_count > 0:
        for p in range(1, device.personality_count + 1):
            time.sleep(0.02)
            with state.ftdi_lock:
                pkt = rdm_module.build_rdm_packet(
                    uid, rdm_module.CC_GET_COMMAND,
                    rdm_module.PID_DMX_PERSONALITY_DESCRIPTION,
                    data=rdm_module.build_get_personality_description(p))
                resp = _send_rdm_command(pkt, timeout=0.5)
                if resp and resp.valid and resp.is_ack:
                    desc = rdm_module.parse_dmx_personality_description(resp.data)
                    if desc:
                        device.personalities[p] = (desc['footprint'], desc['description'])

    logger.info("  RDM device %s: %s %s (addr=%d, personality=%d/%d)",
                device.uid_string,
                device.manufacturer_label or "?",
                device.model_description or "?",
                device.dmx_start_address,
                device.current_personality,
                device.personality_count)


def rdm_get_parameter(uid_str, pid):
    """GET a parameter from an RDM device by UID string and PID.

    Returns RDMResponse or None.
    """
    try:
        uid = rdm_module.uid_from_string(uid_str)
    except ValueError:
        return None

    with state.ftdi_lock:
        pkt = rdm_module.build_rdm_packet(uid, rdm_module.CC_GET_COMMAND, pid)
        return _send_rdm_command(pkt, timeout=0.5)


def rdm_set_parameter(uid_str, pid, data=b''):
    """SET a parameter on an RDM device by UID string and PID.

    Returns RDMResponse or None.
    """
    try:
        uid = rdm_module.uid_from_string(uid_str)
    except ValueError:
        return None

    with state.ftdi_lock:
        pkt = rdm_module.build_rdm_packet(uid, rdm_module.CC_SET_COMMAND, pid, data=data)
        return _send_rdm_command(pkt, timeout=0.5)


def rdm_set_dmx_address(uid_str, address):
    """Set the DMX start address of an RDM device."""
    if not 1 <= address <= 512:
        return None
    data = rdm_module.build_set_dmx_address(address)
    resp = rdm_set_parameter(uid_str, rdm_module.PID_DMX_START_ADDRESS, data)
    if resp and resp.valid and resp.is_ack:
        with state.rdm_lock:
            if uid_str in state.rdm_devices:
                state.rdm_devices[uid_str].dmx_start_address = address
    return resp


def rdm_set_personality(uid_str, personality):
    """Set the DMX personality of an RDM device."""
    data = rdm_module.build_set_personality(personality)
    resp = rdm_set_parameter(uid_str, rdm_module.PID_DMX_PERSONALITY, data)
    if resp and resp.valid and resp.is_ack:
        with state.rdm_lock:
            if uid_str in state.rdm_devices:
                state.rdm_devices[uid_str].current_personality = personality
    return resp


def rdm_identify_device(uid_str, on=True):
    """Turn identify mode on/off for an RDM device (makes it blink)."""
    data = rdm_module.build_set_identify(on)
    return rdm_set_parameter(uid_str, rdm_module.PID_IDENTIFY_DEVICE, data)


def rdm_set_device_label(uid_str, label):
    """Set a custom label on an RDM device."""
    data = rdm_module.build_set_device_label(label)
    resp = rdm_set_parameter(uid_str, rdm_module.PID_DEVICE_LABEL, data)
    if resp and resp.valid and resp.is_ack:
        with state.rdm_lock:
            if uid_str in state.rdm_devices:
                state.rdm_devices[uid_str].device_label = label[:32]
    return resp


def rdm_get_sensor_value(uid_str, sensor_num):
    """Read a sensor value from an RDM device."""
    try:
        uid = rdm_module.uid_from_string(uid_str)
    except ValueError:
        return None

    with state.ftdi_lock:
        pkt = rdm_module.build_rdm_packet(
            uid, rdm_module.CC_GET_COMMAND,
            rdm_module.PID_SENSOR_VALUE,
            data=rdm_module.build_get_sensor_value(sensor_num))
        resp = _send_rdm_command(pkt, timeout=0.5)
        if resp and resp.valid and resp.is_ack:
            return rdm_module.parse_sensor_value(resp.data)
    return None


def dmx_refresh_thread():
    """Background thread to continuously send DMX frames via ENTTEC and/or Art-Net."""
    refresh_interval = 1.0 / config.DMX_REFRESH_RATE
    consecutive_errors = 0
    MAX_ERRORS_BEFORE_REINIT = 3
    REINIT_BACKOFF_BASE = 2.0
    offline_backoff = 1.0
    offline_backoff_max = 10.0
    _last_reinit_log = 0
    _last_health_check = time.monotonic()
    HEALTH_CHECK_INTERVAL = 10.0  # seconds between Pro health probes

    logger.info("DMX refresh thread started (%d Hz)", config.DMX_REFRESH_RATE)

    while state.dmx_running:
        try:
            with state.ftdi_lock:
                if _dmx_device_connected():
                    # Always send the full 512-channel universe so that
                    # scenes, test-channel, and Art-Net receiver data
                    # beyond VISIBLE_CHANNELS are actually transmitted.
                    with state.dmx_lock:
                        frame = bytes(state.dmx_data[:513])

                    _send_dmx_frame(frame)

                    consecutive_errors = 0
                    offline_backoff = 1.0

                    # Periodic health check for ENTTEC Pro
                    now_hc = time.monotonic()
                    if now_hc - _last_health_check >= HEALTH_CHECK_INTERVAL:
                        _last_health_check = now_hc
                        if not _health_check_enttec_pro():
                            logger.warning("ENTTEC Pro health check failed - device may be unresponsive")
                            raise RuntimeError("ENTTEC Pro health check failed")
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors <= MAX_ERRORS_BEFORE_REINIT:
                logger.warning("DMX write error (%d/%d): %s",
                               consecutive_errors, MAX_ERRORS_BEFORE_REINIT, e)
                time.sleep(0.1)
            else:
                backoff = min(REINIT_BACKOFF_BASE * (2 ** (consecutive_errors - MAX_ERRORS_BEFORE_REINIT - 1)), 10.0)
                now = time.monotonic()
                if consecutive_errors <= MAX_ERRORS_BEFORE_REINIT + 3 or now - _last_reinit_log > 30:
                    logger.warning("DMX USB disconnected (%d failures). Retrying in %.1fs...",
                                   consecutive_errors, backoff)
                    _last_reinit_log = now
                time.sleep(backoff)
                if reinit_enttec():
                    logger.info("DMX USB re-initialized successfully, resuming output")
                    consecutive_errors = 0

        # Always send Art-Net if enabled, regardless of USB status
        if config.ARTNET_ENABLED:
            send_artnet_frame()

        # If no USB device and it's the only output, back off
        if not _dmx_device_connected() and not config.ARTNET_ENABLED:
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
    """Get current DMX channel values for visible channels as a dict."""
    with state.dmx_lock:
        result = {}
        for i in range(1, config.VISIBLE_CHANNELS + 1):
            result[i] = state.dmx_data[i]
        return result


def get_all_channels():
    """Get all 512 DMX channel values as a dict (for scene saving)."""
    with state.dmx_lock:
        result = {}
        for i in range(1, config.DMX_CHANNELS + 1):
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
        'enttec_connected': _dmx_device_connected(),
        'enttec_driver': state.dmx_driver,
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
        'rdm_supported': state.dmx_driver == "enttec_pro",
        'rdm_device_count': len(state.rdm_devices),
        'rdm_discovery_running': state.rdm_discovery_running,
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
    scene_id = normalize_scene_id(scene_id)
    if not scene_id:
        return jsonify({'error': 'Invalid scene id'}), 400
    if not is_safe_to_operate():
        return jsonify({'error': 'Safety switch is OFF'}), 409
    with state.timer_lock:
        if state.trigger_timer is not None:
            state.trigger_timer.cancel()
            state.trigger_timer = None

    data = request.get_json(silent=True) or {}
    zero_unset = True
    if isinstance(data, dict) and 'zero_unset' in data:
        zero_unset = bool(data.get('zero_unset'))

    if apply_scene(scene_id, zero_unset=zero_unset):
        return jsonify({'success': True, 'scene': scene_id})
    else:
        return jsonify({'error': 'Scene not found'}), 404


@app.route('/api/scene/<scene_id>/off', methods=['POST'])
def api_deactivate_scene(scene_id):
    """Turn off channels contained in a scene."""
    scene_id = normalize_scene_id(scene_id)
    if not scene_id:
        return jsonify({'error': 'Invalid scene id'}), 400
    if scene_id not in config.SCENES:
        return jsonify({'error': 'Scene not found'}), 404
    if not is_safe_to_operate():
        return jsonify({'error': 'Safety switch is OFF'}), 409

    with state.timer_lock:
        if state.trigger_timer is not None:
            state.trigger_timer.cancel()
            state.trigger_timer = None

    scene = config.SCENES[scene_id]
    with state.dmx_lock:
        for channel in scene['channels'].keys():
            ch_int = int(channel)
            if 1 <= ch_int <= config.DMX_CHANNELS:
                state.dmx_data[ch_int] = 0

    if state.current_scene == scene_id:
        state.current_scene = None

    return jsonify({'success': True, 'scene': scene_id, 'channels_off': len(scene['channels'])})


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

    scene_id = normalize_scene_id(data.get('id'))
    name = data.get('name', '')
    raw_channels = data.get('channels', {})

    if not scene_id:
        return jsonify({'error': 'Scene id is required'}), 400

    try:
        channels = parse_scene_channels(raw_channels)
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


@app.route('/api/scenes/<scene_id>', methods=['PUT'])
def api_update_scene(scene_id):
    """Edit an existing scene (rename id/name and optionally replace channels)."""
    scene_id = normalize_scene_id(scene_id)
    if not scene_id or scene_id not in config.SCENES:
        return jsonify({'error': 'Scene not found'}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400

    target_scene_id = normalize_scene_id(data.get('id', scene_id))
    if not target_scene_id:
        return jsonify({'error': 'Invalid scene id'}), 400

    if target_scene_id != scene_id and target_scene_id in config.SCENES:
        return jsonify({'error': 'Scene id already exists'}), 409

    existing_scene = config.SCENES[scene_id]
    name = data.get('name', existing_scene['name'])

    try:
        if 'channels' in data:
            channels = parse_scene_channels(data.get('channels'))
        else:
            channels = dict(existing_scene['channels'])
    except (TypeError, ValueError) as e:
        return jsonify({'error': f'Invalid channel data: {e}'}), 400

    updated_scene = {
        'name': str(name).strip() or target_scene_id,
        'channels': channels
    }

    if target_scene_id == scene_id:
        config.SCENES[scene_id] = updated_scene
    else:
        del config.SCENES[scene_id]
        config.SCENES[target_scene_id] = updated_scene
        if config.TRIGGER_SCENE == scene_id:
            config.TRIGGER_SCENE = target_scene_id
        if config.IDLE_SCENE == scene_id:
            config.IDLE_SCENE = target_scene_id
        if state.current_scene == scene_id:
            state.current_scene = target_scene_id

    save_config()

    if state.current_scene == target_scene_id:
        apply_scene(target_scene_id)

    return jsonify({'success': True, 'id': target_scene_id})


@app.route('/api/scenes/<scene_id>', methods=['DELETE'])
def api_delete_scene(scene_id):
    """Delete a scene"""
    scene_id = normalize_scene_id(scene_id)
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


@app.route('/api/channels/all-values', methods=['GET'])
def api_get_all_channels():
    """Get all 512 DMX channel values (used for scene saving)."""
    return jsonify(get_all_channels())


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
    """Set all DMX channels to a single value."""
    data = request.get_json()
    if not isinstance(data, dict) or 'value' not in data:
        return jsonify({'error': 'Missing value'}), 400

    try:
        value = max(0, min(255, int(data['value'])))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid value'}), 400

    with state.dmx_lock:
        for i in range(1, config.DMX_CHANNELS + 1):
            state.dmx_data[i] = value
    state.current_scene = None
    logger.info("Set all %d DMX channels to %d", config.DMX_CHANNELS, value)
    return jsonify({'success': True, 'value': value, 'channels_updated': config.DMX_CHANNELS})


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


@app.route('/api/config/reset', methods=['POST'])
def api_reset_config():
    """Reset configuration to factory defaults.

    This clears the persisted config file and restores the built-in
    defaults for channel labels, visible channels, etc.  Useful when
    the saved config has a stale decoder layout that overrides the
    correct defaults.
    """
    # Restore defaults from the Config class definition
    config.VISIBLE_CHANNELS = Config.VISIBLE_CHANNELS
    config.CHANNEL_LABELS = dict(Config.CHANNEL_LABELS)
    config.TRIGGER_DURATION = 10.0
    config.TRIGGER_SCENE = None
    config.IDLE_SCENE = None
    config.SCENES = {}

    # Blackout all channels
    with state.dmx_lock:
        for i in range(len(state.dmx_data)):
            state.dmx_data[i] = 0

    save_config()
    logger.info("Configuration reset to factory defaults")
    return jsonify({
        'success': True,
        'visible_channels': config.VISIBLE_CHANNELS,
        'channel_labels': {str(k): v for k, v in config.CHANNEL_LABELS.items()},
    })


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
    # ── RuggedGrade 1200W RGB Stadium Light ──────────────────────────
    # 4-channel RGBW fixtures.  Each fixture occupies 4 consecutive DMX
    # channels: Red, Green, Blue, White.  Addresses increment by 4:
    #
    #   Fixture 1#  → Address   1  (R=1,   G=2,   B=3,   W=4)
    #   Fixture 2#  → Address   5  (R=5,   G=6,   B=7,   W=8)
    #   ...
    #   Fixture 100# → Address 397 (R=397, G=398, B=399, W=400)
    #
    # Supports up to 100 fixtures on a single DMX universe (400 of 512 channels).
    #
    # Product warnings from the channel guide:
    #   - Turn off power before install or changing assembly parts
    #   - Input voltage and lamps must be matched
    #   - Wiring section must be insulated
    #   - Professionals must install and disassemble
    #   - Surge protection required: outdoor = fixture + pole + breaker,
    #     indoor = fixture + breaker
    #
    # Troubleshooting:
    #   Light flickers → Check wiring, confirm steady input voltage,
    #     cover photocell if present to rule out ambient-light triggering
    #   Light does not work → Check wiring, confirm input voltage is in
    #     the fixture's accepted range; call Tech Support if unresolved
    #
    # This is the DEFAULT and RECOMMENDED profile for this project.

    'ruggedgrade-1200w-rgb-stadium-4ch': {
        'name': 'RuggedGrade 1200W RGB Stadium Light – 4ch RGBW',
        'manufacturer': 'RuggedGrade',
        'channels_per_fixture': 4,
        'channel_map': {
            1: 'Red',
            2: 'Green',
            3: 'Blue',
            4: 'White',
        },
    },

    # ── Stadium Pro III 1200W RGBW (RuggedGrade / LEDLightExpert) ────
    # These fixtures use external RGBW DMX decoders.  The decoder's DIP
    # switches or buttons determine the channel mode.  Common modes:
    #
    #   4ch direct:  R, G, B, W  (decoder in 4CH/RGBW mode)
    #   6ch:         Dimmer, R, G, B, W, Strobe
    #   8ch:         Dimmer, R, G, B, W, Strobe, Mode, Speed
    #   8ch alt:     Mode, Dimmer, R, G, B, W, Strobe, Speed
    #
    # Run  python3 diagnose_decoder.py  to auto-detect your decoder's
    # channel layout if colors aren't responding correctly.
    #
    # IMPORTANT: Set your decoder's DMX start address to 001 (all DIP
    # switches off/down) unless you intentionally offset it.

    # 4ch direct — simplest mode, most common on basic decoders
    # Use start_address=1 (or wherever the decoder address is set)
    'stadium-pro-iii-rgbw-4ch': {
        'name': 'Stadium Pro III 1200W RGBW – 4ch Direct',
        'manufacturer': 'RuggedGrade',
        'channels_per_fixture': 4,
        'channel_map': {
            1: 'Red',
            2: 'Green',
            3: 'Blue',
            4: 'White',
        },
    },
    # 6ch mode — adds master dimmer + strobe
    # Dimmer MUST be >0 or RGBW won't light up!
    'stadium-pro-iii-6ch': {
        'name': 'Stadium Pro III 1200W RGBW – 6ch (Dim+RGBW+Strobe)',
        'manufacturer': 'RuggedGrade',
        'channels_per_fixture': 6,
        'channel_map': {
            1: 'Dimmer',
            2: 'Red',
            3: 'Green',
            4: 'Blue',
            5: 'White',
            6: 'Strobe',
        },
    },
    # 8ch full — dimmer, RGBW, strobe, mode, speed
    'stadium-pro-iii-8ch': {
        'name': 'Stadium Pro III 1200W RGBW – 8ch (Dim+RGBW+Strobe+Mode+Speed)',
        'manufacturer': 'RuggedGrade',
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
    # 8ch alt — mode channel first (some decoders use this order)
    'stadium-pro-iii-8ch-alt': {
        'name': 'Stadium Pro III 1200W RGBW – 8ch Alt (Mode+Dim+RGBW+Strobe+Speed)',
        'manufacturer': 'RuggedGrade',
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
# ENTTEC Reconnect
# ============================================

@app.route('/api/reconnect', methods=['POST'])
def api_reconnect():
    """Manually trigger ENTTEC DMX USB reconnection."""
    logger.info("Manual ENTTEC reconnection requested")
    success = reinit_enttec()
    if success:
        return jsonify({
            'success': True,
            'driver': state.dmx_driver,
            'url': state.enttec_url,
        })
    return jsonify({
        'success': False,
        'error': state.enttec_last_error or 'No DMX USB device found',
    }), 503


# ============================================
# RDM API Endpoints
# ============================================

@app.route('/api/rdm/discover', methods=['POST'])
def api_rdm_discover():
    """Run RDM discovery to find all devices on the bus."""
    if state.dmx_driver != "enttec_pro":
        return jsonify({'error': 'RDM requires ENTTEC DMX USB Pro'}), 400
    if state.rdm_discovery_running:
        return jsonify({'error': 'Discovery already in progress'}), 409

    # Run discovery in a background thread so we don't block the HTTP request
    def _discover():
        rdm_discover_devices()

    Thread(target=_discover, daemon=True).start()
    return jsonify({'success': True, 'message': 'Discovery started'})


@app.route('/api/rdm/devices', methods=['GET'])
def api_rdm_devices():
    """List all discovered RDM devices."""
    with state.rdm_lock:
        devices = [d.to_dict() for d in state.rdm_devices.values()]
    return jsonify({
        'devices': devices,
        'discovery_running': state.rdm_discovery_running,
        'last_discovery': state.rdm_last_discovery,
        'device_count': len(devices),
    })


@app.route('/api/rdm/device/<uid_str>', methods=['GET'])
def api_rdm_device_detail(uid_str):
    """Get detailed info for a single RDM device."""
    with state.rdm_lock:
        device = state.rdm_devices.get(uid_str)
    if device is None:
        return jsonify({'error': 'Device not found'}), 404
    return jsonify(device.to_dict())


@app.route('/api/rdm/device/<uid_str>/address', methods=['POST'])
def api_rdm_set_address(uid_str):
    """Set the DMX start address of an RDM device."""
    data = request.get_json(silent=True)
    if not data or 'address' not in data:
        return jsonify({'error': 'Missing address'}), 400
    address = int(data['address'])
    if not 1 <= address <= 512:
        return jsonify({'error': 'Address must be 1-512'}), 400

    resp = rdm_set_dmx_address(uid_str, address)
    if resp and resp.valid and resp.is_ack:
        return jsonify({'success': True, 'address': address})
    elif resp and resp.valid and resp.is_nack:
        return jsonify({'error': f'Device NACK: reason {resp.nack_reason}'}), 400
    return jsonify({'error': 'No response from device'}), 504


@app.route('/api/rdm/device/<uid_str>/personality', methods=['POST'])
def api_rdm_set_personality(uid_str):
    """Set the DMX personality (channel mode) of an RDM device."""
    data = request.get_json(silent=True)
    if not data or 'personality' not in data:
        return jsonify({'error': 'Missing personality'}), 400
    personality = int(data['personality'])

    resp = rdm_set_personality(uid_str, personality)
    if resp and resp.valid and resp.is_ack:
        return jsonify({'success': True, 'personality': personality})
    elif resp and resp.valid and resp.is_nack:
        return jsonify({'error': f'Device NACK: reason {resp.nack_reason}'}), 400
    return jsonify({'error': 'No response from device'}), 504


@app.route('/api/rdm/device/<uid_str>/identify', methods=['POST'])
def api_rdm_identify(uid_str):
    """Toggle identify mode on an RDM device (makes it blink/flash)."""
    data = request.get_json(silent=True)
    on = True
    if data and 'on' in data:
        on = bool(data['on'])

    resp = rdm_identify_device(uid_str, on=on)
    if resp and resp.valid and resp.is_ack:
        return jsonify({'success': True, 'identify': on})
    elif resp and resp.valid and resp.is_nack:
        return jsonify({'error': f'Device NACK: reason {resp.nack_reason}'}), 400
    return jsonify({'error': 'No response from device'}), 504


@app.route('/api/rdm/device/<uid_str>/label', methods=['POST'])
def api_rdm_set_label(uid_str):
    """Set a custom label on an RDM device."""
    data = request.get_json(silent=True)
    if not data or 'label' not in data:
        return jsonify({'error': 'Missing label'}), 400
    label = str(data['label'])[:32]

    resp = rdm_set_device_label(uid_str, label)
    if resp and resp.valid and resp.is_ack:
        return jsonify({'success': True, 'label': label})
    elif resp and resp.valid and resp.is_nack:
        return jsonify({'error': f'Device NACK: reason {resp.nack_reason}'}), 400
    return jsonify({'error': 'No response from device'}), 504


@app.route('/api/rdm/device/<uid_str>/sensors', methods=['GET'])
def api_rdm_sensors(uid_str):
    """Read all sensor values from an RDM device."""
    with state.rdm_lock:
        device = state.rdm_devices.get(uid_str)
    if device is None:
        return jsonify({'error': 'Device not found'}), 404

    sensors = []
    for i in range(device.sensor_count):
        value = rdm_get_sensor_value(uid_str, i)
        if value:
            sensors.append(value)

    return jsonify({'sensors': sensors})


@app.route('/api/rdm/device/<uid_str>/refresh', methods=['POST'])
def api_rdm_refresh_device(uid_str):
    """Re-fetch all info for a single RDM device."""
    with state.rdm_lock:
        device = state.rdm_devices.get(uid_str)
    if device is None:
        return jsonify({'error': 'Device not found'}), 404

    _rdm_fetch_device_info(device)
    device.last_seen = time.monotonic()
    return jsonify(device.to_dict())


# ============================================
# Health Check
# ============================================

@app.route('/api/health')
def api_health():
    healthy = state.dmx_running and state.dmx_thread is not None and state.dmx_thread.is_alive()
    status_code = 200 if healthy else 503
    return jsonify({
        'status': 'ok' if healthy else 'degraded',
        'enttec_connected': _dmx_device_connected(),
        'enttec_driver': state.dmx_driver,
        'enttec_url': state.enttec_url,
        'enttec_last_error': state.enttec_last_error,
        'dmx_running': healthy,
        'artnet_enabled': config.ARTNET_ENABLED,
        'artnet_receiver_enabled': config.ARTNET_RECEIVER_ENABLED,
        'artnet_receiver_active': state.artnet_receiver_running,
        'gpio_available': GPIO_AVAILABLE,
        'gpio_ready': state.gpio_ready,
        'safe_to_operate': is_safe_to_operate(),
        'rdm_supported': state.dmx_driver == "enttec_pro",
        'rdm_device_count': len(state.rdm_devices),
        'rdm_discovery_running': state.rdm_discovery_running,
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

    while state.gpio_running:
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
    state.gpio_running = False
    stop_dmx_refresh()

    with state.timer_lock:
        if state.trigger_timer:
            state.trigger_timer.cancel()

    with state.ftdi_lock:
        _close_dmx_device()

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
        state.gpio_running = True
        Thread(target=_gpio_monitor, daemon=True).start()

    atexit.register(_cleanup)

    outputs = []
    if state.dmx_driver == "enttec_pro":
        outputs.append(f"ENTTEC DMX USB Pro ({state.enttec_url})")
    elif state.dmx_driver == "enttec_open":
        outputs.append(f"ENTTEC Open DMX USB ({state.enttec_url})")
    elif SERIAL_AVAILABLE or FTDI_AVAILABLE:
        outputs.append("DMX USB (retrying)")
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
