"""DTP Experiment Logger - JSONL format for reproducibility."""

import json
import os
import threading
import time
import random
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any, TextIO
from pathlib import Path

from .protocol import DTPPacket, Priority, now_ms


@dataclass
class ExperimentConfig:
    """Experiment configuration for reproducibility."""
    experiment_id: str
    experiment_name: str
    timestamp: str
    seed: int
    packet_payload_bytes: int
    simulation_duration_ms: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    scheduler_type: str
    queue_size: int
    batch_size: int
    batch_timeout_ms: int
    admission_control_enabled: bool
    congestion_control_enabled: bool
    initial_send_rate: float
    loss_model: str
    loss_rate: float
    burst_duration_ms: int = 0
    notes: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PacketEvent:
    """Single packet event for logging."""
    event_type: str
    timestamp_ms: int
    sequence: int
    priority: str
    deadline_ms: int
    latency_ms: Optional[int] = None
    on_time: Optional[bool] = None
    drop_reason: Optional[str] = None
    batch_id: int = 0


class ExperimentLogger:
    """JSONL logger for DTP experiments."""
    
    def __init__(self, 
                 output_dir: str = "./logs",
                 experiment_id: str = None,
                 buffer_size: int = 1000):
        if experiment_id is None:
            experiment_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        self.experiment_id = experiment_id
        self.output_dir = Path(output_dir) / experiment_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self._buffer_size = buffer_size
        self._event_buffer: List[dict] = []
        self._lock = threading.Lock()
        
        self._config_file: Optional[TextIO] = None
        self._events_file: Optional[TextIO] = None
        self._summary_file: Optional[TextIO] = None
        
        self._open_files()
        
        self._event_count = 0
        self._start_time = now_ms()
    
    def _open_files(self):
        self._config_file = open(self.output_dir / "config.jsonl", 'w')
        self._events_file = open(self.output_dir / "events.jsonl", 'w')
        self._summary_file = open(self.output_dir / "summary.jsonl", 'w')
    
    def log_config(self, config: ExperimentConfig):
        self._write_line(self._config_file, config.to_dict())
    
    def log_parameters(self, **params):
        entry = {
            'type': 'parameters',
            'timestamp_ms': now_ms(),
            **params
        }
        self._write_line(self._config_file, entry)
    
    def log_packet_sent(self, packet: DTPPacket):
        event = {
            'type': 'sent',
            'ts': now_ms(),
            'seq': packet.header.sequence,
            'pri': packet.header.priority.name,
            'deadline': packet.header.deadline,
            'batch': packet.header.batch_id,
        }
        self._buffer_event(event)
    
    def log_packet_received(self, packet: DTPPacket):
        event = {
            'type': 'recv',
            'ts': now_ms(),
            'seq': packet.header.sequence,
            'pri': packet.header.priority.name,
            'latency': packet.latency_ms,
            'on_time': packet.is_on_time(),
        }
        self._buffer_event(event)
    
    def log_packet_dropped(self, packet: DTPPacket, reason: str):
        event = {
            'type': 'drop',
            'ts': now_ms(),
            'seq': packet.header.sequence,
            'pri': packet.header.priority.name,
            'reason': reason,
        }
        self._buffer_event(event)
    
    def log_congestion_event(self, congested: bool, rate: float):
        event = {
            'type': 'congestion',
            'ts': now_ms(),
            'congested': congested,
            'rate': rate,
        }
        self._buffer_event(event)
    
    def log_custom_event(self, event_type: str, **data):
        event = {
            'type': event_type,
            'ts': now_ms(),
            **data
        }
        self._buffer_event(event)
    
    def log_summary(self, stats: dict):
        summary = {
            'type': 'summary',
            'experiment_id': self.experiment_id,
            'end_timestamp': datetime.now().isoformat(),
            'duration_ms': now_ms() - self._start_time,
            'total_events': self._event_count,
            'stats': stats,
        }
        self._write_line(self._summary_file, summary)
    
    def log_priority_stats(self, priority: Priority, stats: dict):
        entry = {
            'type': 'priority_stats',
            'priority': priority.name,
            **stats
        }
        self._write_line(self._summary_file, entry)
    
    def _buffer_event(self, event: dict):
        with self._lock:
            self._event_buffer.append(event)
            self._event_count += 1
            
            if len(self._event_buffer) >= self._buffer_size:
                self._flush_events()
    
    def _flush_events(self):
        if not self._event_buffer:
            return
        
        for event in self._event_buffer:
            self._write_line(self._events_file, event)
        
        self._event_buffer.clear()
        self._events_file.flush()
    
    def _write_line(self, file: TextIO, data: dict):
        json.dump(data, file, separators=(',', ':'))
        file.write('\n')
    
    def flush(self):
        with self._lock:
            self._flush_events()
            if self._config_file:
                self._config_file.flush()
            if self._summary_file:
                self._summary_file.flush()
    
    def close(self):
        self.flush()
        
        if self._config_file:
            self._config_file.close()
        if self._events_file:
            self._events_file.close()
        if self._summary_file:
            self._summary_file.close()
    
    @property
    def log_path(self) -> Path:
        return self.output_dir
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def set_seed(seed: int):
    """Set random seed for reproducibility."""
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass


def generate_experiment_id(prefix: str = "exp") -> str:
    """Generate unique experiment ID."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_suffix = random.randint(1000, 9999)
    return f"{prefix}_{timestamp}_{random_suffix}"


class LogReader:
    """Reader for JSONL experiment logs."""
    
    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)
    
    def read_config(self) -> dict:
        config_file = self.log_dir / "config.jsonl"
        if config_file.exists():
            with open(config_file) as f:
                return json.loads(f.readline())
        return {}
    
    def iter_events(self):
        events_file = self.log_dir / "events.jsonl"
        if events_file.exists():
            with open(events_file) as f:
                for line in f:
                    yield json.loads(line)
    
    def read_summary(self) -> dict:
        summary_file = self.log_dir / "summary.jsonl"
        if summary_file.exists():
            with open(summary_file) as f:
                last_line = None
                for line in f:
                    if '"type":"summary"' in line:
                        last_line = line
                if last_line:
                    return json.loads(last_line)
        return {}
    
    def get_events_by_type(self, event_type: str) -> List[dict]:
        return [e for e in self.iter_events() if e.get('type') == event_type]
    
    def get_latencies_by_priority(self) -> Dict[str, List[int]]:
        latencies: Dict[str, List[int]] = {}
        
        for event in self.iter_events():
            if event.get('type') == 'recv' and event.get('latency') is not None:
                pri = event.get('pri', 'UNKNOWN')
                if pri not in latencies:
                    latencies[pri] = []
                latencies[pri].append(event['latency'])
        
        return latencies
    
    def compute_statistics(self) -> dict:
        from statistics import mean, median, stdev
        
        stats = {
            'by_priority': {},
            'total': {'sent': 0, 'received': 0, 'dropped': 0}
        }
        
        latencies_by_pri: Dict[str, List[int]] = {}
        on_time_by_pri: Dict[str, int] = {}
        sent_by_pri: Dict[str, int] = {}
        recv_by_pri: Dict[str, int] = {}
        drop_by_pri: Dict[str, int] = {}
        
        for event in self.iter_events():
            etype = event.get('type')
            pri = event.get('pri', 'UNKNOWN')
            
            if etype == 'sent':
                sent_by_pri[pri] = sent_by_pri.get(pri, 0) + 1
                stats['total']['sent'] += 1
            elif etype == 'recv':
                recv_by_pri[pri] = recv_by_pri.get(pri, 0) + 1
                stats['total']['received'] += 1
                
                if event.get('latency') is not None:
                    if pri not in latencies_by_pri:
                        latencies_by_pri[pri] = []
                    latencies_by_pri[pri].append(event['latency'])
                
                if event.get('on_time'):
                    on_time_by_pri[pri] = on_time_by_pri.get(pri, 0) + 1
            elif etype == 'drop':
                drop_by_pri[pri] = drop_by_pri.get(pri, 0) + 1
                stats['total']['dropped'] += 1
        
        for pri in set(list(sent_by_pri.keys()) + list(recv_by_pri.keys())):
            sent = sent_by_pri.get(pri, 0)
            recv = recv_by_pri.get(pri, 0)
            drop = drop_by_pri.get(pri, 0)
            on_time = on_time_by_pri.get(pri, 0)
            lats = latencies_by_pri.get(pri, [])
            
            pri_stats = {
                'sent': sent,
                'received': recv,
                'dropped': drop,
                'on_time': on_time,
                'delivery_rate': recv / sent if sent > 0 else 0,
                'on_time_rate': on_time / recv if recv > 0 else 0,
            }
            
            if lats:
                sorted_lats = sorted(lats)
                pri_stats['latency'] = {
                    'mean': mean(lats),
                    'median': median(lats),
                    'p50': sorted_lats[len(sorted_lats) // 2],
                    'p95': sorted_lats[min(int(len(sorted_lats) * 0.95), len(sorted_lats) - 1)],
                    'p99': sorted_lats[min(int(len(sorted_lats) * 0.99), len(sorted_lats) - 1)],
                }
                if len(lats) > 1:
                    pri_stats['latency']['stdev'] = stdev(lats)
            
            stats['by_priority'][pri] = pri_stats
        
        return stats
