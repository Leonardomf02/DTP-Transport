"""DTP Scheduler - Priority queue with deadline-aware scheduling."""

import threading
import heapq
import time
from typing import Optional, List, Dict
from dataclasses import dataclass, field

from .protocol import DTPPacket, Priority, Flags, now_ms


@dataclass(order=True)
class QueueEntry:
    """Entry in the priority queue."""
    sort_key: tuple = field(compare=True)
    packet: DTPPacket = field(compare=False)
    enqueue_time: int = field(compare=False)


class DTPScheduler:
    """
    Deadline-aware priority scheduler using EDF (Earliest Deadline First).
    
    Packets are scheduled based on:
    1. Priority (CRITICAL > HIGH > MEDIUM > LOW)
    2. Time to deadline (urgent packets first)
    3. Arrival order (FIFO within same urgency)
    """
    
    def __init__(self, queue_size: int = 1000, batch_size: int = 10, batch_timeout_ms: int = 50):
        self._queue: List[QueueEntry] = []
        self._lock = threading.Lock()
        self._max_size = queue_size
        
        self._batch_size = batch_size
        self._batch_timeout_ms = batch_timeout_ms
        self._current_batch: List[DTPPacket] = []
        self._batch_start_time: Optional[int] = None
        self._batch_id = 0
        
        self._send_rate = 500.0
        self._congested = False
        
        self._stats = {
            'enqueued': 0,
            'dequeued': 0,
            'dropped_full': 0,
            'dropped_expired': 0,
            'batches_sent': 0
        }
        self._enqueue_order = 0
    
    def enqueue(self, packet: DTPPacket) -> bool:
        """Add packet to scheduler queue."""
        with self._lock:
            if len(self._queue) >= self._max_size:
                if packet.header.priority == Priority.LOW and packet.header.flags & Flags.DROPPABLE:
                    self._stats['dropped_full'] += 1
                    return False
                self._drop_lowest_priority()
            
            ttd = packet.header.time_to_deadline()
            sort_key = (
                packet.header.priority.value,
                -ttd,
                self._enqueue_order
            )
            
            entry = QueueEntry(
                sort_key=sort_key,
                packet=packet,
                enqueue_time=now_ms()
            )
            
            heapq.heappush(self._queue, entry)
            self._enqueue_order += 1
            self._stats['enqueued'] += 1
            
            return True
    
    def dequeue(self) -> Optional[DTPPacket]:
        """Get next packet to send."""
        with self._lock:
            while self._queue:
                entry = heapq.heappop(self._queue)
                packet = entry.packet
                
                if packet.header.is_expired():
                    self._stats['dropped_expired'] += 1
                    continue
                
                self._stats['dequeued'] += 1
                return packet
            
            return None
    
    def _drop_lowest_priority(self):
        """Drop lowest priority packet when queue is full."""
        if not self._queue:
            return
        
        lowest_idx = -1
        lowest_pri = -1
        
        for i, entry in enumerate(self._queue):
            pri = entry.packet.header.priority.value
            if pri > lowest_pri:
                lowest_pri = pri
                lowest_idx = i
        
        if lowest_idx >= 0:
            del self._queue[lowest_idx]
            heapq.heapify(self._queue)
            self._stats['dropped_full'] += 1
    
    def add_to_batch(self, packet: DTPPacket) -> Optional[List[DTPPacket]]:
        """Add packet to current batch, return batch if ready."""
        with self._lock:
            if self._batch_start_time is None:
                self._batch_start_time = now_ms()
            
            self._current_batch.append(packet)
            
            batch_ready = (
                len(self._current_batch) >= self._batch_size or
                (now_ms() - self._batch_start_time) >= self._batch_timeout_ms
            )
            
            if batch_ready:
                return self._flush_batch()
            
            return None
    
    def _flush_batch(self) -> List[DTPPacket]:
        """Flush current batch."""
        if not self._current_batch:
            return []
        
        self._batch_id += 1
        batch = self._current_batch
        
        for pkt in batch:
            pkt.header.flags |= Flags.BATCHED
            pkt.header.batch_id = self._batch_id
        
        self._current_batch = []
        self._batch_start_time = None
        self._stats['batches_sent'] += 1
        
        return batch
    
    def flush_all(self) -> List[DTPPacket]:
        """Flush any remaining batch."""
        with self._lock:
            return self._flush_batch()
    
    def set_congested(self, congested: bool):
        """Set congestion state."""
        self._congested = congested
        if congested:
            self._send_rate = max(50, self._send_rate * 0.5)
        else:
            self._send_rate = min(1000, self._send_rate * 1.2)
    
    def clear(self):
        """Clear all queued packets."""
        with self._lock:
            self._queue.clear()
            self._current_batch.clear()
            self._batch_start_time = None
    
    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)
    
    @property
    def send_rate(self) -> float:
        return self._send_rate
    
    @property
    def is_congested(self) -> bool:
        return self._congested
    
    def get_stats(self) -> dict:
        with self._lock:
            return {
                **self._stats,
                'queue_size': len(self._queue),
                'send_rate': self._send_rate,
                'congested': self._congested
            }


class SimpleScheduler:
    """Simple FIFO scheduler for comparison (no priority awareness)."""
    
    def __init__(self, queue_size: int = 1000):
        self._queue: List[DTPPacket] = []
        self._lock = threading.Lock()
        self._max_size = queue_size
        self._send_rate = 500.0
        self._congested = False
        
        self._stats = {
            'enqueued': 0,
            'dequeued': 0,
            'dropped': 0
        }
    
    def enqueue(self, packet: DTPPacket) -> bool:
        """Add packet to queue (FIFO)."""
        with self._lock:
            if len(self._queue) >= self._max_size:
                self._stats['dropped'] += 1
                return False
            
            self._queue.append(packet)
            self._stats['enqueued'] += 1
            return True
    
    def dequeue(self) -> Optional[DTPPacket]:
        """Get next packet (FIFO order)."""
        with self._lock:
            if self._queue:
                self._stats['dequeued'] += 1
                return self._queue.pop(0)
            return None
    
    def set_congested(self, congested: bool):
        self._congested = congested
        if congested:
            self._send_rate = max(50, self._send_rate * 0.5)
        else:
            self._send_rate = min(1000, self._send_rate * 1.2)
    
    def flush_all(self):
        pass
    
    def clear(self):
        with self._lock:
            self._queue.clear()
    
    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)
    
    @property
    def send_rate(self) -> float:
        return self._send_rate
    
    @property
    def is_congested(self) -> bool:
        return self._congested
    
    def get_stats(self) -> dict:
        with self._lock:
            return {
                **self._stats,
                'queue_size': len(self._queue),
                'send_rate': self._send_rate,
                'congested': self._congested
            }
