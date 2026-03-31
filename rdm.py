"""
RDM (Remote Device Management) Protocol Module — ANSI E1.20-2010

Provides packet building, parsing, discovery, and standard parameter
access for two-way communication with RDM-capable fixtures over DMX512-A.

Used by the main app to communicate with fixtures via the ENTTEC DMX USB Pro
widget (Labels 7 and 11).
"""

import struct
import logging
from collections import namedtuple

logger = logging.getLogger("dmx.rdm")

# ============================================
# RDM Constants
# ============================================

# Start codes
RDM_START_CODE = 0xCC       # DMX start code for RDM
RDM_SUB_START_CODE = 0x01   # RDM sub-start code

# Broadcast UIDs
RDM_BROADCAST_UID = b'\xFF\xFF\xFF\xFF\xFF\xFF'
RDM_ALL_MANUFACTURERS = b'\xFF\xFF\xFF\xFF\xFF\xFF'

# Command Classes (CC)
CC_DISCOVERY_COMMAND = 0x10
CC_DISCOVERY_COMMAND_RESPONSE = 0x11
CC_GET_COMMAND = 0x20
CC_GET_COMMAND_RESPONSE = 0x21
CC_SET_COMMAND = 0x30
CC_SET_COMMAND_RESPONSE = 0x31

# Response Types
RESPONSE_TYPE_ACK = 0x00
RESPONSE_TYPE_ACK_TIMER = 0x01
RESPONSE_TYPE_NACK_REASON = 0x02
RESPONSE_TYPE_ACK_OVERFLOW = 0x03

# NACK Reason Codes
NACK_UNKNOWN_PID = 0x0000
NACK_FORMAT_ERROR = 0x0001
NACK_HARDWARE_FAULT = 0x0002
NACK_PROXY_REJECT = 0x0003
NACK_WRITE_PROTECT = 0x0004
NACK_UNSUPPORTED_COMMAND_CLASS = 0x0005
NACK_DATA_OUT_OF_RANGE = 0x0006
NACK_BUFFER_FULL = 0x0007
NACK_PACKET_SIZE_UNSUPPORTED = 0x0008
NACK_SUB_DEVICE_OUT_OF_RANGE = 0x0009
NACK_PROXY_BUFFER_FULL = 0x000A

# Discovery PIDs
PID_DISC_UNIQUE_BRANCH = 0x0001
PID_DISC_MUTE = 0x0002
PID_DISC_UN_MUTE = 0x0003

# Network Management PIDs
PID_PROXIED_DEVICES = 0x0010
PID_PROXIED_DEVICE_COUNT = 0x0011
PID_COMMS_STATUS = 0x0015

# Status PIDs
PID_QUEUED_MESSAGE = 0x0020
PID_STATUS_MESSAGES = 0x0030
PID_STATUS_ID_DESCRIPTION = 0x0031
PID_CLEAR_STATUS_ID = 0x0032
PID_SUB_DEVICE_STATUS_REPORT_THRESHOLD = 0x0033

# RDM Information PIDs
PID_SUPPORTED_PARAMETERS = 0x0050
PID_PARAMETER_DESCRIPTION = 0x0051

# Product Information PIDs
PID_DEVICE_INFO = 0x0060
PID_PRODUCT_DETAIL_ID_LIST = 0x0070
PID_DEVICE_MODEL_DESCRIPTION = 0x0080
PID_MANUFACTURER_LABEL = 0x0081
PID_DEVICE_LABEL = 0x0082
PID_FACTORY_DEFAULTS = 0x0090
PID_LANGUAGE_CAPABILITIES = 0x00A0
PID_LANGUAGE = 0x00A1
PID_SOFTWARE_VERSION_LABEL = 0x00C0
PID_BOOT_SOFTWARE_VERSION_ID = 0x00C1
PID_BOOT_SOFTWARE_VERSION_LABEL = 0x00C2

# DMX512 Setup PIDs
PID_DMX_PERSONALITY = 0x00E0
PID_DMX_PERSONALITY_DESCRIPTION = 0x00E1
PID_DMX_START_ADDRESS = 0x00F0
PID_SLOT_INFO = 0x0120
PID_SLOT_DESCRIPTION = 0x0121
PID_DEFAULT_SLOT_VALUE = 0x0122

# Sensor PIDs
PID_SENSOR_DEFINITION = 0x0200
PID_SENSOR_VALUE = 0x0201
PID_RECORD_SENSORS = 0x0202

# Power/Lamp PIDs
PID_DEVICE_HOURS = 0x0400
PID_LAMP_HOURS = 0x0401
PID_LAMP_STRIKES = 0x0402
PID_LAMP_STATE = 0x0403
PID_LAMP_ON_MODE = 0x0404
PID_DEVICE_POWER_CYCLES = 0x0405

# Display PIDs
PID_DISPLAY_INVERT = 0x0500
PID_DISPLAY_LEVEL = 0x0501

# Configuration PIDs
PID_PAN_INVERT = 0x0600
PID_TILT_INVERT = 0x0601
PID_PAN_TILT_SWAP = 0x0602

# Control PIDs
PID_IDENTIFY_DEVICE = 0x1000
PID_RESET_DEVICE = 0x1001
PID_POWER_STATE = 0x1010
PID_PERFORM_SELFTEST = 0x1020
PID_SELF_TEST_DESCRIPTION = 0x1021
PID_CAPTURE_PRESET = 0x1030
PID_PRESET_PLAYBACK = 0x1031

# Human-readable PID names for logging/UI
PID_NAMES = {
    PID_DISC_UNIQUE_BRANCH: "DISC_UNIQUE_BRANCH",
    PID_DISC_MUTE: "DISC_MUTE",
    PID_DISC_UN_MUTE: "DISC_UN_MUTE",
    PID_SUPPORTED_PARAMETERS: "SUPPORTED_PARAMETERS",
    PID_DEVICE_INFO: "DEVICE_INFO",
    PID_DEVICE_MODEL_DESCRIPTION: "DEVICE_MODEL_DESCRIPTION",
    PID_MANUFACTURER_LABEL: "MANUFACTURER_LABEL",
    PID_DEVICE_LABEL: "DEVICE_LABEL",
    PID_SOFTWARE_VERSION_LABEL: "SOFTWARE_VERSION_LABEL",
    PID_DMX_PERSONALITY: "DMX_PERSONALITY",
    PID_DMX_PERSONALITY_DESCRIPTION: "DMX_PERSONALITY_DESCRIPTION",
    PID_DMX_START_ADDRESS: "DMX_START_ADDRESS",
    PID_SENSOR_DEFINITION: "SENSOR_DEFINITION",
    PID_SENSOR_VALUE: "SENSOR_VALUE",
    PID_DEVICE_HOURS: "DEVICE_HOURS",
    PID_LAMP_HOURS: "LAMP_HOURS",
    PID_DEVICE_POWER_CYCLES: "DEVICE_POWER_CYCLES",
    PID_IDENTIFY_DEVICE: "IDENTIFY_DEVICE",
    PID_RESET_DEVICE: "RESET_DEVICE",
    PID_POWER_STATE: "POWER_STATE",
    PID_FACTORY_DEFAULTS: "FACTORY_DEFAULTS",
    PID_SLOT_INFO: "SLOT_INFO",
}

# Product categories
PRODUCT_CATEGORY_FIXTURE = 0x0100
PRODUCT_CATEGORY_FIXTURE_FIXED = 0x0101
PRODUCT_CATEGORY_FIXTURE_MOVING_YOKE = 0x0102
PRODUCT_CATEGORY_FIXTURE_MOVING_MIRROR = 0x0103

# ============================================
# Data Structures
# ============================================

RDMDeviceInfo = namedtuple('RDMDeviceInfo', [
    'rdm_protocol_version',
    'device_model_id',
    'product_category',
    'software_version_id',
    'dmx_footprint',
    'current_personality',
    'personality_count',
    'dmx_start_address',
    'sub_device_count',
    'sensor_count',
])


class RDMDevice:
    """Represents a discovered RDM device on the bus."""

    def __init__(self, uid):
        self.uid = uid                      # 6-byte UID
        self.manufacturer_id = uid[:2]      # First 2 bytes
        self.device_id = uid[2:]            # Last 4 bytes
        self.muted = False
        self.device_info = None             # RDMDeviceInfo
        self.device_label = ""
        self.manufacturer_label = ""
        self.model_description = ""
        self.software_version_label = ""
        self.dmx_start_address = 0
        self.current_personality = 0
        self.personality_count = 0
        self.personalities = {}             # {num: (footprint, description)}
        self.sensor_count = 0
        self.sensors = {}                   # {index: definition}
        self.supported_pids = []
        self.last_seen = 0                  # timestamp

    @property
    def uid_hex(self):
        """Return UID as hex string like '0x1234:0x56789ABC'."""
        mfr = int.from_bytes(self.manufacturer_id, 'big')
        dev = int.from_bytes(self.device_id, 'big')
        return f"0x{mfr:04X}:0x{dev:08X}"

    @property
    def uid_string(self):
        """Return UID as compact hex string like '1234:56789ABC'."""
        mfr = int.from_bytes(self.manufacturer_id, 'big')
        dev = int.from_bytes(self.device_id, 'big')
        return f"{mfr:04X}:{dev:08X}"

    def to_dict(self):
        """Serialize to JSON-safe dict."""
        d = {
            'uid': self.uid_string,
            'manufacturer_id': f"0x{int.from_bytes(self.manufacturer_id, 'big'):04X}",
            'device_id': f"0x{int.from_bytes(self.device_id, 'big'):08X}",
            'device_label': self.device_label,
            'manufacturer_label': self.manufacturer_label,
            'model_description': self.model_description,
            'software_version_label': self.software_version_label,
            'dmx_start_address': self.dmx_start_address,
            'current_personality': self.current_personality,
            'personality_count': self.personality_count,
            'sensor_count': self.sensor_count,
        }
        if self.personalities:
            d['personalities'] = {
                str(k): {'footprint': v[0], 'description': v[1]}
                for k, v in self.personalities.items()
            }
        if self.device_info:
            d['device_info'] = {
                'rdm_protocol_version': f"{self.device_info.rdm_protocol_version >> 8}.{self.device_info.rdm_protocol_version & 0xFF}",
                'device_model_id': f"0x{self.device_info.device_model_id:04X}",
                'product_category': f"0x{self.device_info.product_category:04X}",
                'software_version_id': f"0x{self.device_info.software_version_id:08X}",
                'dmx_footprint': self.device_info.dmx_footprint,
                'sub_device_count': self.device_info.sub_device_count,
                'sensor_count': self.device_info.sensor_count,
            }
        return d


# ============================================
# UID Helpers
# ============================================

def uid_from_string(uid_str):
    """Parse a UID string like '1234:56789ABC' to 6-byte bytes."""
    parts = uid_str.split(':')
    if len(parts) != 2:
        raise ValueError(f"Invalid UID format: {uid_str}")
    mfr = int(parts[0], 16)
    dev = int(parts[1], 16)
    return struct.pack('>HI', mfr, dev)


def uid_to_string(uid_bytes):
    """Convert 6-byte UID to string like '1234:56789ABC'."""
    mfr = int.from_bytes(uid_bytes[:2], 'big')
    dev = int.from_bytes(uid_bytes[2:6], 'big')
    return f"{mfr:04X}:{dev:08X}"


def uid_compare(a, b):
    """Compare two 6-byte UIDs. Returns -1, 0, or 1."""
    if a < b:
        return -1
    elif a > b:
        return 1
    return 0


# ============================================
# RDM Packet Building
# ============================================

# Default controller UID — manufacturer ID 0x7FF0 (prototype range), device 0x00000001
CONTROLLER_UID = b'\x7F\xF0\x00\x00\x00\x01'

_transaction_number = 0


def _next_transaction():
    """Get next transaction number (0-255, wrapping)."""
    global _transaction_number
    tn = _transaction_number
    _transaction_number = (_transaction_number + 1) & 0xFF
    return tn


def build_rdm_packet(dest_uid, command_class, pid, data=b'',
                     sub_device=0, port_id=1, source_uid=None):
    """Build a complete RDM packet with checksum.

    Returns packet bytes starting at the RDM sub-start code (0x01).
    The ENTTEC Pro expects everything after the DMX start code (0xCC)
    to be passed as data for Label 7/11.
    """
    if source_uid is None:
        source_uid = CONTROLLER_UID

    tn = _next_transaction()
    pdl = len(data)
    # RDM message length field counts bytes from Sub-Start Code through
    # Parameter Data (it does NOT include the 2-byte checksum).
    # Base size with no parameter data is 23 bytes.
    msg_length = 23 + pdl

    packet = bytearray()
    packet.append(RDM_SUB_START_CODE)           # Slot 0: Sub-start code
    packet.append(msg_length)                    # Slot 1: Message length
    packet.extend(dest_uid[:6])                  # Slots 2-7: Destination UID
    packet.extend(source_uid[:6])                # Slots 8-13: Source UID
    packet.append(tn)                            # Slot 14: Transaction number
    packet.append(port_id)                       # Slot 15: Port ID / Response type
    packet.append(0)                             # Slot 16: Message count
    packet.extend(struct.pack('>H', sub_device)) # Slots 17-18: Sub-device
    packet.append(command_class)                 # Slot 19: Command class
    packet.extend(struct.pack('>H', pid))        # Slots 20-21: Parameter ID
    packet.append(pdl)                           # Slot 22: Parameter data length
    if pdl > 0:
        packet.extend(data)                      # Slots 23+: Parameter data

    # Checksum: sum of all bytes from sub-start code, mod 0x10000
    checksum = sum(packet) & 0xFFFF
    packet.extend(struct.pack('>H', checksum))   # Last 2 bytes: checksum

    return bytes(packet)


def build_discovery_packet(lower_uid, upper_uid, source_uid=None):
    """Build a DISC_UNIQUE_BRANCH discovery packet.

    Args:
        lower_uid: 6-byte lower bound UID
        upper_uid: 6-byte upper bound UID

    Returns packet bytes for the ENTTEC Pro Label 11 (discovery).
    """
    data = lower_uid[:6] + upper_uid[:6]
    return build_rdm_packet(
        RDM_BROADCAST_UID,
        CC_DISCOVERY_COMMAND,
        PID_DISC_UNIQUE_BRANCH,
        data=data,
        source_uid=source_uid,
    )


def build_mute_packet(dest_uid, source_uid=None):
    """Build a DISC_MUTE packet to mute a device from discovery."""
    return build_rdm_packet(
        dest_uid,
        CC_DISCOVERY_COMMAND,
        PID_DISC_MUTE,
        source_uid=source_uid,
    )


def build_unmute_packet(dest_uid=None, source_uid=None):
    """Build a DISC_UN_MUTE packet. Broadcast to unmute all."""
    if dest_uid is None:
        dest_uid = RDM_BROADCAST_UID
    return build_rdm_packet(
        dest_uid,
        CC_DISCOVERY_COMMAND,
        PID_DISC_UN_MUTE,
        source_uid=source_uid,
    )


# ============================================
# RDM Packet Parsing
# ============================================

class RDMResponse:
    """Parsed RDM response packet."""

    def __init__(self):
        self.valid = False
        self.source_uid = b'\x00' * 6
        self.dest_uid = b'\x00' * 6
        self.transaction_number = 0
        self.response_type = 0
        self.message_count = 0
        self.sub_device = 0
        self.command_class = 0
        self.pid = 0
        self.pdl = 0
        self.data = b''
        self.checksum_ok = False
        self.nack_reason = None

    @property
    def is_ack(self):
        return self.response_type == RESPONSE_TYPE_ACK

    @property
    def is_nack(self):
        return self.response_type == RESPONSE_TYPE_NACK_REASON

    @property
    def source_uid_string(self):
        return uid_to_string(self.source_uid)


def parse_rdm_response(data):
    """Parse an RDM response packet.

    Args:
        data: Raw bytes starting from sub-start code (0x01).
              May or may not include leading 0xCC start code.

    Returns:
        RDMResponse object (check .valid for success).
    """
    resp = RDMResponse()

    if not data or len(data) < 2:
        return resp

    # Skip 0xCC start code if present
    offset = 0
    if data[0] == RDM_START_CODE:
        offset = 1

    if len(data) - offset < 26:  # Minimum RDM response: 24 header + 2 checksum
        return resp

    raw = data[offset:]

    if raw[0] != RDM_SUB_START_CODE:
        return resp

    msg_length = raw[1]
    if len(raw) < msg_length + 2:  # +2 for checksum
        return resp

    # Verify checksum
    packet_data = raw[:msg_length]
    expected_checksum = struct.unpack('>H', raw[msg_length:msg_length + 2])[0]
    actual_checksum = sum(packet_data) & 0xFFFF
    resp.checksum_ok = (expected_checksum == actual_checksum)

    if not resp.checksum_ok:
        logger.debug("RDM checksum mismatch: expected 0x%04X, got 0x%04X",
                     expected_checksum, actual_checksum)
        return resp

    # Parse header fields
    resp.dest_uid = bytes(raw[2:8])
    resp.source_uid = bytes(raw[8:14])
    resp.transaction_number = raw[14]
    resp.response_type = raw[15]
    resp.message_count = raw[16]
    resp.sub_device = struct.unpack('>H', raw[17:19])[0]
    resp.command_class = raw[19]
    resp.pid = struct.unpack('>H', raw[20:22])[0]
    resp.pdl = raw[22]

    if resp.pdl > 0 and len(raw) >= 23 + resp.pdl:
        resp.data = bytes(raw[23:23 + resp.pdl])

    # Parse NACK reason if applicable
    if resp.response_type == RESPONSE_TYPE_NACK_REASON and resp.pdl >= 2:
        resp.nack_reason = struct.unpack('>H', resp.data[:2])[0]

    resp.valid = True
    return resp


def parse_discovery_response(data):
    """Parse a discovery response (DISC_UNIQUE_BRANCH reply).

    Discovery responses use a special encoding:
    - 7 preamble bytes of 0xFE
    - 1 separator byte of 0xAA
    - 12 encoded UID bytes (6 pairs of encoded/complement)
    - 4 encoded checksum bytes

    Returns the 6-byte UID or None if invalid.
    """
    if not data:
        return None

    # Find the 0xAA separator (preamble is 0-7 bytes of 0xFE)
    sep_idx = -1
    for i in range(min(len(data), 8)):
        if data[i] == 0xAA:
            sep_idx = i
            break
    if sep_idx < 0:
        # No separator found in first 8 bytes
        return None

    encoded = data[sep_idx + 1:]
    if len(encoded) < 16:  # 12 UID + 4 checksum
        return None

    # Decode UID: each byte is (encoded[i] & encoded[i+1])
    uid = bytearray(6)
    for i in range(6):
        uid[i] = encoded[i * 2] & encoded[i * 2 + 1]

    # Decode and verify checksum
    cs_data = encoded[12:16]
    if len(cs_data) >= 4:
        cs_hi = cs_data[0] & cs_data[1]
        cs_lo = cs_data[2] & cs_data[3]
        received_cs = (cs_hi << 8) | cs_lo
        calculated_cs = sum(uid) & 0xFFFF
        if received_cs != calculated_cs:
            logger.debug("Discovery response checksum mismatch for UID %s",
                        uid_to_string(uid))
            # Some fixtures get the checksum wrong; still return the UID
            # but log the mismatch for debugging

    return bytes(uid)


# ============================================
# Standard Parameter Parsers
# ============================================

def parse_device_info(data):
    """Parse DEVICE_INFO response data (19 bytes)."""
    if len(data) < 19:
        return None
    return RDMDeviceInfo(
        rdm_protocol_version=struct.unpack('>H', data[0:2])[0],
        device_model_id=struct.unpack('>H', data[2:4])[0],
        product_category=struct.unpack('>H', data[4:6])[0],
        software_version_id=struct.unpack('>I', data[6:10])[0],
        dmx_footprint=struct.unpack('>H', data[10:12])[0],
        current_personality=data[12],
        personality_count=data[13],
        dmx_start_address=struct.unpack('>H', data[14:16])[0],
        sub_device_count=struct.unpack('>H', data[16:18])[0],
        sensor_count=data[18],
    )


def parse_dmx_personality(data):
    """Parse DMX_PERSONALITY response data."""
    if len(data) < 2:
        return None
    return {
        'current_personality': data[0],
        'personality_count': data[1],
    }


def parse_dmx_personality_description(data):
    """Parse DMX_PERSONALITY_DESCRIPTION response data."""
    if len(data) < 3:
        return None
    return {
        'personality': data[0],
        'footprint': struct.unpack('>H', data[1:3])[0],
        'description': data[3:].decode('ascii', errors='replace').rstrip('\x00'),
    }


def parse_sensor_definition(data):
    """Parse SENSOR_DEFINITION response data."""
    if len(data) < 13:
        return None
    return {
        'sensor_number': data[0],
        'type': data[1],
        'unit': data[2],
        'prefix': data[3],
        'range_min': struct.unpack('>h', data[4:6])[0],
        'range_max': struct.unpack('>h', data[6:8])[0],
        'normal_min': struct.unpack('>h', data[8:10])[0],
        'normal_max': struct.unpack('>h', data[10:12])[0],
        'supports_recording': data[12],
        'description': data[13:].decode('ascii', errors='replace').rstrip('\x00') if len(data) > 13 else '',
    }


def parse_sensor_value(data):
    """Parse SENSOR_VALUE response data."""
    if len(data) < 9:
        return None
    result = {
        'sensor_number': data[0],
        'present_value': struct.unpack('>h', data[1:3])[0],
        'lowest_value': struct.unpack('>h', data[3:5])[0],
        'highest_value': struct.unpack('>h', data[5:7])[0],
        'recorded_value': struct.unpack('>h', data[7:9])[0],
    }
    return result


def parse_slot_info(data):
    """Parse SLOT_INFO response data. Returns list of slot defs."""
    slots = []
    # Each slot is 5 bytes: slot_offset(2) + slot_type(1) + slot_label_id(2)
    for i in range(0, len(data) - 4, 5):
        slots.append({
            'slot_offset': struct.unpack('>H', data[i:i + 2])[0],
            'slot_type': data[i + 2],
            'slot_label_id': struct.unpack('>H', data[i + 3:i + 5])[0],
        })
    return slots


# ============================================
# Standard Parameter Builders (SET data)
# ============================================

def build_set_dmx_address(address):
    """Build SET DMX_START_ADDRESS data."""
    return struct.pack('>H', address)


def build_set_identify(on):
    """Build SET IDENTIFY_DEVICE data."""
    return bytes([1 if on else 0])


def build_set_device_label(label):
    """Build SET DEVICE_LABEL data."""
    return label.encode('ascii', errors='replace')[:32]


def build_set_personality(personality_num):
    """Build SET DMX_PERSONALITY data."""
    return bytes([personality_num])


def build_get_personality_description(personality_num):
    """Build GET DMX_PERSONALITY_DESCRIPTION data."""
    return bytes([personality_num])


def build_get_sensor_definition(sensor_num):
    """Build GET SENSOR_DEFINITION data."""
    return bytes([sensor_num])


def build_get_sensor_value(sensor_num):
    """Build GET SENSOR_VALUE data."""
    return bytes([sensor_num])
