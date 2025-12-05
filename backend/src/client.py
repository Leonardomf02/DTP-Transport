"""DTP Client - Sends traffic with priority scheduling."""

import socket
import threading
import time
import random
from typing import Optional, Callable
from enum import Enum

from .protocol import (
    DTPPacket, DTPHeader, Priority, PacketType, Flags,
    DTP_DEFAULT_PORT, get_priority_emoji, get_current_time_ms, now_ms
)
from .scheduler import DTPScheduler, SimpleScheduler
from .metrics import MetricsCollector


class ClientMode(Enum):
    DTP = "dtp"
    UDP_RAW = "udp_raw"


class TrafficProfile:
    """Defines the traffic mix to generate."""
    
    def __init__(self,
                 critical_count: int = 50,
                 high_count: int = 200,
                 medium_count: int = 500,
                 low_count: int = 1000,
                 burst_size: int = 20,
                 burst_interval_ms: int = 100):
        self.critical_count = critical_count
        self.high_count = high_count
        self.medium_count = medium_count
        self.low_count = low_count
        self.burst_size = burst_size
        self.burst_interval_ms = burst_interval_ms
    
    @property
    def total_packets(self) -> int:
        return (self.critical_count + self.high_count + 
                self.medium_count + self.low_count)
    
    def get_counts(self) -> dict:
        return {
            Priority.CRITICAL: self.critical_count,
            Priority.HIGH: self.high_count,
            Priority.MEDIUM: self.medium_count,
            Priority.LOW: self.low_count,
        }


class DTPClient:
    """DTP Client that generates and sends traffic."""
    
    def __init__(self,
                 host: str = '127.0.0.1',
                 port: int = DTP_DEFAULT_PORT,
                 metrics: Optional[MetricsCollector] = None,
                 mode: ClientMode = ClientMode.DTP):
        self.host = host
        self.port = port
        self.metrics = metrics or MetricsCollector()
        self.mode = mode
        
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._paused = False
        self._send_thread: Optional[threading.Thread] = None
        self._recv_thread: Optional[threading.Thread] = None
        
        if mode == ClientMode.DTP:
            self._scheduler = DTPScheduler()
        else:
            self._scheduler = SimpleScheduler()
        
        self._sequence = 0
        self._sequence_lock = threading.Lock()
        self._profile = TrafficProfile()
        
        self._on_congestion: Optional[Callable] = None
        self._on_packet_sent: Optional[Callable] = None
        
        self._packets_sent = 0
        self._packets_to_send = 0
    
    def set_mode(self, mode: ClientMode):
        self.mode = mode
        if mode == ClientMode.DTP:
            self._scheduler = DTPScheduler()
        else:
            self._scheduler = SimpleScheduler()
    
    def set_profile(self, profile: TrafficProfile):
        self._profile = profile
    
    def set_on_congestion(self, callback: Callable):
        self._on_congestion = callback
    
    def set_on_packet_sent(self, callback: Callable):
        self._on_packet_sent = callback
    
    def start(self):
        if self._running:
            return
        
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.settimeout(0.1)
        
        self._running = True
        
        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()
    
    def stop(self):
        self._running = False
        self._scheduler.clear()
        
        if self._send_thread:
            self._send_thread.join(timeout=1.0)
        if self._recv_thread:
            self._recv_thread.join(timeout=1.0)
        if self._socket:
            self._socket.close()
            self._socket = None
    
    def run_simulation(self, profile: Optional[TrafficProfile] = None):
        if profile:
            self._profile = profile
        
        self._packets_to_send = self._profile.total_packets
        self._packets_sent = 0
        
        self._send_thread = threading.Thread(target=self._simulation_loop, daemon=True)
        self._send_thread.start()
    
    def _simulation_loop(self):
        counts = self._profile.get_counts()
        simulation_duration_ms = 2000
        
        generation_schedule = []
        for priority, count in counts.items():
            for i in range(count):
                time_offset = random.uniform(0, simulation_duration_ms)
                generation_schedule.append((time_offset, priority))
        
        generation_schedule.sort(key=lambda x: x[0])
        
        sender_running = threading.Event()
        sender_running.set()
        packets_sent_counter = [0]
        
        def sender_loop():
            empty_streak = 0
            while sender_running.is_set() or self._scheduler.queue_size > 0:
                if self._paused:
                    time.sleep(0.01)
                    continue
                
                packet = self._scheduler.dequeue()
                if packet:
                    self._send_packet(packet)
                    packets_sent_counter[0] += 1
                    empty_streak = 0
                    
                    delay = 1.0 / self._scheduler.send_rate
                    time.sleep(delay)
                else:
                    empty_streak += 1
                    if empty_streak > 100 and not sender_running.is_set():
                        break
                    time.sleep(0.001)
        
        sender_thread = threading.Thread(target=sender_loop, daemon=True)
        sender_thread.start()
        
        start_time = now_ms()
        packet_index = 0
        seq = 0
        
        while packet_index < len(generation_schedule) and self._running:
            current_time = now_ms() - start_time
            
            while packet_index < len(generation_schedule):
                scheduled_time, priority = generation_schedule[packet_index]
                
                if scheduled_time > current_time:
                    break
                
                payload = f"DTP-{priority.name}-{seq}".encode()
                packet = DTPPacket.create_data(
                    payload=payload,
                    priority=priority,
                    sequence=seq,
                    deadline_ms=priority.get_default_deadline_ms()
                )
                
                if priority == Priority.LOW:
                    packet.header.flags |= Flags.DROPPABLE
                
                self._scheduler.enqueue(packet)
                self.metrics.record_sent(packet)
                
                seq += 1
                packet_index += 1
            
            time.sleep(0.001)
        
        self._scheduler.flush_all()
        sender_running.clear()
        sender_thread.join(timeout=10.0)
        
        self._packets_sent = packets_sent_counter[0]

    def _generate_traffic(self) -> list:
        packets = []
        counts = self._profile.get_counts()
        
        for priority, count in counts.items():
            for i in range(count):
                seq = self._next_sequence()
                payload = f"DTP-{priority.name}-{seq}".encode()
                
                packet = DTPPacket.create_data(
                    payload=payload,
                    priority=priority,
                    sequence=seq,
                    deadline_ms=priority.get_default_deadline_ms()
                )
                
                if priority == Priority.LOW:
                    packet.header.flags |= Flags.DROPPABLE
                
                packets.append(packet)
        
        random.shuffle(packets)
        return packets
    
    def _send_packet(self, packet: DTPPacket):
        try:
            data = packet.serialize()
            self._socket.sendto(data, (self.host, self.port))
            
            if self._on_packet_sent:
                self._on_packet_sent(packet)
                
        except Exception as e:
            pass
    
    def _receive_loop(self):
        while self._running:
            try:
                data, addr = self._socket.recvfrom(2048)
                self._handle_response(data)
            except socket.timeout:
                continue
            except Exception:
                pass
    
    def _handle_response(self, data: bytes):
        try:
            packet = DTPPacket.deserialize(data)
            
            if packet.header.packet_type == PacketType.CONGESTION:
                self._scheduler.set_congested(True)
                
                if self._on_congestion:
                    self._on_congestion(True)
                
                threading.Timer(1.0, self._clear_congestion).start()
                
            elif packet.header.packet_type == PacketType.ACK:
                pass
                
        except Exception:
            pass
    
    def _clear_congestion(self):
        self._scheduler.set_congested(False)
        if self._on_congestion:
            self._on_congestion(False)
    
    def _next_sequence(self) -> int:
        with self._sequence_lock:
            seq = self._sequence
            self._sequence = (self._sequence + 1) % 65536
            return seq
    
    def pause(self):
        self._paused = True
    
    def resume(self):
        self._paused = False
    
    @property
    def progress(self) -> float:
        if self._packets_to_send == 0:
            return 0.0
        return self._packets_sent / self._packets_to_send
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def is_sending(self) -> bool:
        return self._send_thread is not None and self._send_thread.is_alive()
    
    def get_stats(self) -> dict:
        return {
            'mode': self.mode.value,
            'sent': self._packets_sent,
            'total': self._packets_to_send,
            'progress': round(self.progress * 100, 1),
            'queue_size': self._scheduler.queue_size,
            'scheduler': self._scheduler.get_stats()
        }
