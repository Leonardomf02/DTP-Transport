"""
DTP Metrics Collection and Analysis

Collects and analyzes:
- Latency per priority level
- Throughput (packets/second)
- Deadline compliance rate
- Queue statistics
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Deque
from collections import deque, defaultdict
from statistics import mean, median, stdev

from .protocol import DTPPacket, Priority, get_current_time_ms, now_ms


@dataclass
class PacketMetric:
    """Metrics for a single packet"""
    sequence: int
    priority: Priority
    send_time: int      # ms
    receive_time: int   # ms
    deadline: int       # ms
    latency: int        # ms
    on_time: bool
    batch_id: int = 0
    dropped: bool = False


@dataclass
class PriorityStats:
    """Aggregated statistics for a priority level"""
    priority: Priority
    total_packets: int = 0
    received_packets: int = 0
    dropped_packets: int = 0
    on_time_packets: int = 0
    late_packets: int = 0
    latencies: List[int] = field(default_factory=list)
    
    @property
    def delivery_rate(self) -> float:
        if self.total_packets == 0:
            return 0.0
        return self.received_packets / self.total_packets
    
    @property
    def on_time_rate(self) -> float:
        if self.received_packets == 0:
            return 0.0
        return self.on_time_packets / self.received_packets
    
    @property
    def avg_latency(self) -> float:
        if not self.latencies:
            return 0.0
        return mean(self.latencies)
    
    @property
    def median_latency(self) -> float:
        if not self.latencies:
            return 0.0
        return median(self.latencies)
    
    @property
    def p95_latency(self) -> float:
        if len(self.latencies) < 20:
            return max(self.latencies) if self.latencies else 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        # Protect against index out of range
        idx = min(idx, len(sorted_latencies) - 1)
        return sorted_latencies[idx]
    
    @property
    def p99_latency(self) -> float:
        """99th percentile latency (useful for outlier detection)"""
        if len(self.latencies) < 20:
            return max(self.latencies) if self.latencies else 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.99)
        idx = min(idx, len(sorted_latencies) - 1)
        return sorted_latencies[idx]
    
    def to_dict(self) -> dict:
        return {
            'priority': self.priority.name,
            'total': self.total_packets,
            'received': self.received_packets,
            'dropped': self.dropped_packets,
            'on_time': self.on_time_packets,
            'late': self.late_packets,
            'delivery_rate': round(self.delivery_rate * 100, 1),
            'on_time_rate': round(self.on_time_rate * 100, 1),
            'avg_latency_ms': round(self.avg_latency, 2),
            'median_latency_ms': round(self.median_latency, 2),
            'p95_latency_ms': round(self.p95_latency, 2),
            'p99_latency_ms': round(self.p99_latency, 2),
        }


class MetricsCollector:
    """
    Collects metrics during simulation
    """
    
    def __init__(self, window_size: int = 100):
        self._lock = threading.Lock()
        self._window_size = window_size
        
        # Per-priority statistics
        self._stats: Dict[Priority, PriorityStats] = {
            p: PriorityStats(priority=p) for p in Priority
        }
        
        # Recent packets for real-time display
        self._recent_packets: Deque[PacketMetric] = deque(maxlen=window_size)
        
        # Throughput tracking
        self._throughput_window: Deque[int] = deque(maxlen=100)  # timestamps
        self._last_throughput_calc = 0
        self._current_throughput = 0.0
        
        # Time series data for charts
        self._latency_history: Dict[Priority, Deque[tuple]] = {
            p: deque(maxlen=200) for p in Priority
        }
        self._throughput_history: Deque[tuple] = deque(maxlen=200)
        
        # Start time (using monotonic clock for consistency)
        self._start_time = now_ms()
        
        # Events log
        self._events: Deque[dict] = deque(maxlen=100)
    
    def record_sent(self, packet: DTPPacket):
        """Record that a packet was sent"""
        with self._lock:
            self._stats[packet.header.priority].total_packets += 1
    
    def record_received(self, packet: DTPPacket):
        """Record that a packet was received"""
        # Note: packet should already have mark_received() called
        if packet.receive_time is None:
            packet.mark_received()
        
        with self._lock:
            priority = packet.header.priority
            stats = self._stats[priority]
            
            stats.received_packets += 1
            
            # Only record valid latencies
            if packet.latency_ms is not None and packet.latency_ms >= 0:
                stats.latencies.append(packet.latency_ms)
            
            on_time = packet.is_on_time()
            if on_time:
                stats.on_time_packets += 1
            else:
                stats.late_packets += 1
            
            # Record metric
            metric = PacketMetric(
                sequence=packet.header.sequence,
                priority=priority,
                send_time=packet.header.timestamp,
                receive_time=packet.receive_time or 0,
                deadline=packet.header.deadline,
                latency=packet.latency_ms or 0,
                on_time=on_time,
                batch_id=packet.header.batch_id
            )
            self._recent_packets.append(metric)
            
            # Update latency history
            elapsed = now_ms() - self._start_time
            if packet.latency_ms is not None and packet.latency_ms >= 0:
                self._latency_history[priority].append((elapsed, packet.latency_ms))
            
            # Update throughput (using monotonic time)
            self._throughput_window.append(now_ms())
            self._update_throughput()
            
            # Add event for received packet (sample 1 in 10 to not flood)
            if stats.received_packets % 10 == 1:
                self._events.append({
                    'time': elapsed,
                    'type': 'received',
                    'priority': priority.name,
                    'sequence': packet.header.sequence,
                    'latency': packet.latency_ms,
                    'on_time': on_time
                })
    
    def record_dropped(self, packet: DTPPacket, reason: str = "expired"):
        """Record that a packet was dropped"""
        with self._lock:
            priority = packet.header.priority
            self._stats[priority].dropped_packets += 1
            
            # Log event (using monotonic time)
            elapsed = now_ms() - self._start_time
            self._events.append({
                'time': elapsed,
                'type': 'dropped',
                'priority': priority.name,
                'sequence': packet.header.sequence,
                'reason': reason
            })
    
    def record_event(self, event_type: str, details: dict):
        """Record a general event"""
        with self._lock:
            self._events.append({
                'time': now_ms() - self._start_time,
                'type': event_type,
                **details
            })
    
    def _update_throughput(self):
        """Calculate current throughput"""
        current_time = now_ms()
        if current_time - self._last_throughput_calc < 100:  # Update every 100ms
            return
        
        self._last_throughput_calc = current_time
        
        # Count packets in last second
        cutoff = current_time - 1000
        recent = [t for t in self._throughput_window if t > cutoff]
        self._current_throughput = len(recent)
        
        # Add to history
        elapsed = current_time - self._start_time
        self._throughput_history.append((elapsed, self._current_throughput))
    
    def get_current_stats(self) -> dict:
        """Get current statistics snapshot"""
        with self._lock:
            # Calculate overall stats
            total_sent = sum(s.total_packets for s in self._stats.values())
            total_received = sum(s.received_packets for s in self._stats.values())
            total_on_time = sum(s.on_time_packets for s in self._stats.values())
            
            return {
                'elapsed_ms': now_ms() - self._start_time,
                'throughput': self._current_throughput,
                'total': {
                    'sent': total_sent,
                    'received': total_received,
                    'on_time': total_on_time,
                    'delivery_rate': round(total_received / max(1, total_sent) * 100, 1),
                    'on_time_rate': round(total_on_time / max(1, total_received) * 100, 1),
                },
                'by_priority': {
                    p.name: self._stats[p].to_dict() for p in Priority
                }
            }
    
    def get_latency_data(self) -> dict:
        """Get latency time series for charts"""
        with self._lock:
            return {
                p.name: list(self._latency_history[p])
                for p in Priority
            }
    
    def get_throughput_data(self) -> list:
        """Get throughput time series for charts"""
        with self._lock:
            return list(self._throughput_history)
    
    def get_recent_events(self, count: int = 20) -> list:
        """Get recent events for log display"""
        with self._lock:
            return list(self._events)[-count:]
    
    def get_recent_packets(self, count: int = 10) -> list:
        """Get recent packet metrics"""
        with self._lock:
            packets = list(self._recent_packets)[-count:]
            return [
                {
                    'sequence': p.sequence,
                    'priority': p.priority.name,
                    'latency': p.latency,
                    'deadline': p.deadline,
                    'on_time': p.on_time,
                    'batched': p.batch_id > 0
                }
                for p in packets
            ]
    
    def get_comparison_summary(self) -> dict:
        """Get summary suitable for comparison display"""
        with self._lock:
            return {
                p.name: {
                    'avg_latency': round(self._stats[p].avg_latency, 1),
                    'p95_latency': round(self._stats[p].p95_latency, 1),
                    'on_time_rate': round(self._stats[p].on_time_rate * 100, 1),
                    'total': self._stats[p].total_packets,
                    'received': self._stats[p].received_packets,
                }
                for p in Priority
            }
    
    def reset(self):
        """Reset all metrics"""
        with self._lock:
            self._stats = {p: PriorityStats(priority=p) for p in Priority}
            self._recent_packets.clear()
            self._throughput_window.clear()
            self._latency_history = {p: deque(maxlen=200) for p in Priority}
            self._throughput_history.clear()
            self._events.clear()
            self._start_time = now_ms()
            self._current_throughput = 0.0
