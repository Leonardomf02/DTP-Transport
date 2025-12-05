"""DTP Clock Synchronization - 3-way handshake for clock offset estimation."""

import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List
from statistics import median

from .protocol import now_ms, reset_reference_time

SYNC_REQ = 0x01
SYNC_RESP = 0x02
SYNC_ACK = 0x03

SYNC_PACKET_FORMAT = '>B q q q'
SYNC_PACKET_SIZE = 25


@dataclass
class ClockSyncResult:
    """Result of clock synchronization."""
    offset_ms: float
    rtt_ms: float
    accuracy_ms: float
    samples: int
    
    def adjust_timestamp(self, remote_ts: int) -> int:
        return int(remote_ts + self.offset_ms)
    
    def adjust_latency(self, latency_ms: int) -> int:
        return int(latency_ms - self.offset_ms)


class ClockSyncClient:
    """Client-side clock synchronization."""
    
    def __init__(self, server_host: str, server_port: int = 4434):
        self.server_host = server_host
        self.server_port = server_port
        self._socket: Optional[socket.socket] = None
        self._result: Optional[ClockSyncResult] = None
        self._lock = threading.Lock()
    
    def sync(self, num_samples: int = 5, timeout_ms: int = 1000) -> Optional[ClockSyncResult]:
        offsets: List[float] = []
        rtts: List[float] = []
        
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.settimeout(timeout_ms / 1000.0)
            
            for i in range(num_samples):
                result = self._sync_round()
                if result:
                    offset, rtt = result
                    offsets.append(offset)
                    rtts.append(rtt)
                    time.sleep(0.01)
            
            if not offsets:
                return None
            
            median_offset = median(offsets)
            median_rtt = median(rtts)
            
            self._result = ClockSyncResult(
                offset_ms=median_offset,
                rtt_ms=median_rtt,
                accuracy_ms=median_rtt / 2,
                samples=len(offsets)
            )
            
            return self._result
            
        except Exception:
            return None
        finally:
            if self._socket:
                self._socket.close()
                self._socket = None
    
    def _sync_round(self) -> Optional[Tuple[float, float]]:
        try:
            t1 = now_ms()
            
            packet = struct.pack(SYNC_PACKET_FORMAT, SYNC_REQ, t1, 0, 0)
            self._socket.sendto(packet, (self.server_host, self.server_port))
            
            data, _ = self._socket.recvfrom(SYNC_PACKET_SIZE)
            
            t4 = now_ms()
            
            ptype, t1_echo, t2, t3 = struct.unpack(SYNC_PACKET_FORMAT, data)
            
            if ptype != SYNC_RESP or t1_echo != t1:
                return None
            
            offset = ((t2 - t1) + (t3 - t4)) / 2.0
            rtt = (t4 - t1) - (t3 - t2)
            
            return (offset, rtt)
            
        except socket.timeout:
            return None
        except Exception:
            return None
    
    @property
    def result(self) -> Optional[ClockSyncResult]:
        return self._result
    
    @property
    def offset_ms(self) -> float:
        return self._result.offset_ms if self._result else 0.0


class ClockSyncServer:
    """Server-side clock synchronization responder."""
    
    def __init__(self, port: int = 4434):
        self.port = port
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._requests_handled = 0
    
    def start(self):
        if self._running:
            return
        
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(('', self.port))
        self._socket.settimeout(0.5)
        
        self._running = True
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._socket:
            self._socket.close()
            self._socket = None
    
    def _serve_loop(self):
        while self._running:
            try:
                data, addr = self._socket.recvfrom(SYNC_PACKET_SIZE)
                
                t2 = now_ms()
                
                ptype, t1, _, _ = struct.unpack(SYNC_PACKET_FORMAT, data)
                
                if ptype == SYNC_REQ:
                    t3 = now_ms()
                    
                    response = struct.pack(SYNC_PACKET_FORMAT, SYNC_RESP, t1, t2, t3)
                    self._socket.sendto(response, addr)
                    
                    self._requests_handled += 1
                    
            except socket.timeout:
                continue
            except Exception:
                pass
    
    @property
    def requests_handled(self) -> int:
        return self._requests_handled


_global_clock_offset: float = 0.0
_clock_sync_lock = threading.Lock()


def set_global_clock_offset(offset_ms: float):
    global _global_clock_offset
    with _clock_sync_lock:
        _global_clock_offset = offset_ms


def get_global_clock_offset() -> float:
    with _clock_sync_lock:
        return _global_clock_offset


def adjust_remote_timestamp(remote_ts: int) -> int:
    return int(remote_ts + _global_clock_offset)


def sync_with_server(host: str, port: int = 4434, samples: int = 5) -> Optional[ClockSyncResult]:
    client = ClockSyncClient(host, port)
    result = client.sync(num_samples=samples)
    
    if result:
        set_global_clock_offset(result.offset_ms)
    
    return result
