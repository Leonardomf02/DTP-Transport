"""DTP Protocol - Deadline-aware Transport Protocol packet format and utilities."""

import struct
import time
from enum import IntEnum
from dataclasses import dataclass
from typing import Optional

DTP_VERSION = 1
DTP_HEADER_SIZE = 24
DTP_DEFAULT_PORT = 4433
DTP_MAGIC = 0xDEAD

_reference_time_ms: int = 0


def now_ms() -> int:
    """Get current time in milliseconds (monotonic)."""
    return int(time.monotonic() * 1000)


def get_current_time_ms() -> int:
    """Alias for now_ms()."""
    return now_ms()


def reset_reference_time():
    """Reset reference time to current time."""
    global _reference_time_ms
    _reference_time_ms = now_ms()


class Priority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    
    def get_default_deadline_ms(self) -> int:
        deadlines = {
            Priority.CRITICAL: 500,
            Priority.HIGH: 1500,
            Priority.MEDIUM: 3000,
            Priority.LOW: 6000
        }
        return deadlines.get(self, 6000)


class PacketType(IntEnum):
    DATA = 0
    ACK = 1
    NACK = 2
    CONGESTION = 3
    KEEPALIVE = 4


class Flags(IntEnum):
    NONE = 0x00
    RELIABLE = 0x01
    DROPPABLE = 0x02
    BATCHED = 0x04
    COMPRESSED = 0x08
    ENCRYPTED = 0x10


def get_priority_emoji(priority: Priority) -> str:
    emojis = {
        Priority.CRITICAL: "🔴",
        Priority.HIGH: "🟠",
        Priority.MEDIUM: "🟡",
        Priority.LOW: "🟢"
    }
    return emojis.get(priority, "⚪")


@dataclass
class DTPHeader:
    """DTP packet header."""
    version: int = DTP_VERSION
    packet_type: PacketType = PacketType.DATA
    priority: Priority = Priority.MEDIUM
    flags: int = Flags.NONE
    sequence: int = 0
    timestamp: int = 0
    deadline: int = 3000
    payload_length: int = 0
    batch_id: int = 0
    
    def pack(self) -> bytes:
        return struct.pack(
            '>HBBBBHIQHH',
            DTP_MAGIC,
            self.version,
            self.packet_type,
            self.priority,
            self.flags,
            self.sequence,
            self.timestamp,
            self.deadline,
            self.payload_length,
            self.batch_id
        )
    
    @classmethod
    def unpack(cls, data: bytes) -> 'DTPHeader':
        if len(data) < DTP_HEADER_SIZE:
            raise ValueError(f"Header too short: {len(data)} < {DTP_HEADER_SIZE}")
        
        magic, version, ptype, priority, flags, seq, ts, deadline, plen, batch = struct.unpack(
            '>HBBBBHIQHH', data[:DTP_HEADER_SIZE]
        )
        
        if magic != DTP_MAGIC:
            raise ValueError(f"Invalid magic: {magic:#x}")
        
        return cls(
            version=version,
            packet_type=PacketType(ptype),
            priority=Priority(priority),
            flags=flags,
            sequence=seq,
            timestamp=ts,
            deadline=deadline,
            payload_length=plen,
            batch_id=batch
        )
    
    def is_expired(self) -> bool:
        if self.timestamp == 0:
            return False
        elapsed = now_ms() - self.timestamp
        return elapsed > self.deadline
    
    def time_to_deadline(self) -> int:
        if self.timestamp == 0:
            return self.deadline
        elapsed = now_ms() - self.timestamp
        return max(0, self.deadline - elapsed)


class DTPPacket:
    """Complete DTP packet with header and payload."""
    
    def __init__(self, header: DTPHeader, payload: bytes = b''):
        self.header = header
        self.payload = payload
        self._received_at: Optional[int] = None
    
    @classmethod
    def create_data(cls, payload: bytes, priority: Priority = Priority.MEDIUM,
                    sequence: int = 0, deadline_ms: int = None) -> 'DTPPacket':
        if deadline_ms is None:
            deadline_ms = priority.get_default_deadline_ms()
        
        header = DTPHeader(
            packet_type=PacketType.DATA,
            priority=priority,
            sequence=sequence,
            timestamp=now_ms(),
            deadline=deadline_ms,
            payload_length=len(payload)
        )
        return cls(header, payload)
    
    @classmethod
    def create_ack(cls, sequence: int, priority: Priority = Priority.MEDIUM) -> 'DTPPacket':
        header = DTPHeader(
            packet_type=PacketType.ACK,
            priority=priority,
            sequence=sequence,
            timestamp=now_ms(),
            payload_length=0
        )
        return cls(header)
    
    @classmethod
    def create_congestion(cls, level: float = 1.0) -> 'DTPPacket':
        header = DTPHeader(
            packet_type=PacketType.CONGESTION,
            priority=Priority.CRITICAL,
            timestamp=now_ms(),
            payload_length=4
        )
        payload = struct.pack('>f', level)
        return cls(header, payload)
    
    def serialize(self) -> bytes:
        return self.header.pack() + self.payload
    
    @classmethod
    def deserialize(cls, data: bytes) -> 'DTPPacket':
        header = DTPHeader.unpack(data)
        payload = data[DTP_HEADER_SIZE:DTP_HEADER_SIZE + header.payload_length]
        return cls(header, payload)
    
    def mark_received(self):
        self._received_at = now_ms()
    
    @property
    def receive_time(self) -> Optional[int]:
        """Alias for _received_at for compatibility."""
        return self._received_at
    
    @property
    def latency_ms(self) -> Optional[int]:
        if self._received_at is None or self.header.timestamp == 0:
            return None
        return self._received_at - self.header.timestamp
    
    def is_on_time(self) -> bool:
        lat = self.latency_ms
        if lat is None:
            return True
        return lat <= self.header.deadline
    
    def __repr__(self):
        return (f"DTPPacket(seq={self.header.sequence}, "
                f"pri={self.header.priority.name}, "
                f"deadline={self.header.deadline}ms)")
