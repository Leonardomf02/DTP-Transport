"""DTP Server - Receives and processes packets."""

import socket
import threading
import time
import random
from typing import Optional, Callable

from .protocol import (
    DTPPacket, DTPHeader, Priority, PacketType, Flags,
    DTP_DEFAULT_PORT, DTP_HEADER_SIZE, get_priority_emoji
)
from .metrics import MetricsCollector


class DTPServer:
    """DTP Server that receives and processes packets."""
    
    def __init__(self, 
                 host: str = '127.0.0.1',
                 port: int = DTP_DEFAULT_PORT,
                 metrics: Optional[MetricsCollector] = None,
                 simulate_congestion: bool = True):
        self.host = host
        self.port = port
        self.metrics = metrics or MetricsCollector()
        self.simulate_congestion = simulate_congestion
        
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        self._congestion_level = 0.0
        self._base_processing_delay_ms = 1
        
        self._on_packet_received: Optional[Callable] = None
        self._on_congestion_change: Optional[Callable] = None
        
        self._packets_processed = 0
        self._packets_dropped = 0
    
    def set_on_packet_received(self, callback: Callable):
        self._on_packet_received = callback
    
    def set_on_congestion_change(self, callback: Callable):
        self._on_congestion_change = callback
    
    def start(self):
        if self._running:
            return
        
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        
        self._socket.bind((self.host, self.port))
        self._socket.settimeout(0.1)
        
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        self._running = False
        
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        
        if self._socket:
            try:
                self._socket.close()
            except:
                pass
            self._socket = None
    
    def _receive_loop(self):
        while self._running:
            try:
                data, addr = self._socket.recvfrom(2048)
                self._handle_packet(data, addr)
            except socket.timeout:
                continue
            except Exception:
                pass
    
    def _handle_packet(self, data: bytes, addr: tuple):
        try:
            packet = DTPPacket.deserialize(data)
            packet.mark_received()
            
            if packet.header.is_expired():
                self._packets_dropped += 1
                self.metrics.record_dropped(packet, "expired_on_arrival")
                return
            
            self._simulate_processing(packet)
            self._update_congestion()
            
            self.metrics.record_received(packet)
            self._packets_processed += 1
            
            if self._on_packet_received:
                self._on_packet_received(packet)
            
            if packet.header.flags & Flags.RELIABLE:
                self._send_ack(packet, addr)
                
        except Exception:
            pass
    
    def _simulate_processing(self, packet: DTPPacket):
        if not self.simulate_congestion:
            return
        
        delay = self._base_processing_delay_ms
        
        if self._congestion_level > 0:
            priority_factor = (packet.header.priority + 1) * 2
            congestion_delay = self._congestion_level * priority_factor * 10
            delay += congestion_delay
        
        jitter = random.uniform(0, delay * 0.2)
        delay += jitter
        
        if delay > 0:
            time.sleep(delay / 1000)
    
    def _update_congestion(self):
        if not self.simulate_congestion:
            return
        
        old_level = self._congestion_level
        change = random.uniform(-0.05, 0.08)
        self._congestion_level = max(0.0, min(1.0, self._congestion_level + change))
        
        if abs(self._congestion_level - old_level) > 0.2:
            if self._on_congestion_change:
                self._on_congestion_change(self._congestion_level)
    
    def _send_ack(self, packet: DTPPacket, addr: tuple):
        ack = DTPPacket.create_ack(packet.header.sequence, packet.header.priority)
        self._socket.sendto(ack.serialize(), addr)
    
    def set_congestion_level(self, level: float):
        self._congestion_level = max(0.0, min(1.0, level))
    
    @property
    def congestion_level(self) -> float:
        return self._congestion_level
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    def get_stats(self) -> dict:
        return {
            'processed': self._packets_processed,
            'dropped': self._packets_dropped,
            'congestion_level': round(self._congestion_level, 2)
        }
