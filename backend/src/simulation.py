"""DTP Simulation Engine - Coordinates server and client for demonstration."""

import threading
import time
import asyncio
from typing import Optional, Callable, List
from dataclasses import dataclass
from enum import Enum

from .protocol import Priority, reset_reference_time
from .server import DTPServer
from .client import DTPClient, ClientMode, TrafficProfile
from .metrics import MetricsCollector


class SimulationState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


@dataclass
class SimulationConfig:
    """Configuration for simulation."""
    mode: ClientMode = ClientMode.DTP
    critical_count: int = 50
    high_count: int = 200
    medium_count: int = 500
    low_count: int = 1000
    simulate_congestion: bool = True
    congestion_level: float = 0.3


class SimulationEngine:
    """Manages DTP simulation for demonstration."""
    
    def __init__(self, 
                 host: str = '127.0.0.1',
                 port: int = 4433):
        self.host = host
        self.port = port
        
        self._server: Optional[DTPServer] = None
        self._client: Optional[DTPClient] = None
        self._metrics: Optional[MetricsCollector] = None
        
        self._state = SimulationState.IDLE
        self._config = SimulationConfig()
        
        self._results: dict = {}
        
        self._on_state_change: Optional[Callable] = None
        self._on_metrics_update: Optional[Callable] = None
        self._on_event: Optional[Callable] = None
        
        self._update_thread: Optional[threading.Thread] = None
        self._running = False
    
    def set_on_state_change(self, callback: Callable):
        self._on_state_change = callback
    
    def set_on_metrics_update(self, callback: Callable):
        self._on_metrics_update = callback
    
    def set_on_event(self, callback: Callable):
        self._on_event = callback
    
    def configure(self, config: SimulationConfig):
        self._config = config
    
    def start(self, config: Optional[SimulationConfig] = None):
        if self._state == SimulationState.RUNNING:
            return
        
        if config:
            self._config = config
        
        reset_reference_time()
        
        self._metrics = MetricsCollector()
        
        self._server = DTPServer(
            host=self.host,
            port=self.port,
            metrics=self._metrics,
            simulate_congestion=self._config.simulate_congestion
        )
        self._server.set_congestion_level(self._config.congestion_level)
        self._server.start()
        
        time.sleep(0.1)
        
        mode = self._config.mode
        self._client = DTPClient(
            host=self.host,
            port=self.port,
            metrics=self._metrics,
            mode=mode
        )
        self._client.start()
        
        profile = TrafficProfile(
            critical_count=self._config.critical_count,
            high_count=self._config.high_count,
            medium_count=self._config.medium_count,
            low_count=self._config.low_count
        )
        
        self._running = True
        self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self._update_thread.start()
        
        self._state = SimulationState.RUNNING
        self._notify_state_change()
        
        self._client.run_simulation(profile)
        
        threading.Thread(target=self._monitor_completion, daemon=True).start()
    
    def stop(self):
        self._running = False
        
        if self._client:
            self._client.stop()
            self._client = None
        
        if self._server:
            self._server.stop()
            self._server = None
        
        self._state = SimulationState.IDLE
        self._notify_state_change()
    
    def pause(self):
        if self._client:
            self._client.pause()
        self._state = SimulationState.PAUSED
        self._notify_state_change()
    
    def resume(self):
        if self._client:
            self._client.resume()
        self._state = SimulationState.RUNNING
        self._notify_state_change()
    
    def _monitor_completion(self):
        while self._running and self._client:
            if self._client.is_sending:
                time.sleep(0.1)
            else:
                time.sleep(0.5)
                self._state = SimulationState.COMPLETED
                self._notify_state_change()
                
                mode_key = self._config.mode.value
                self._results[mode_key] = self.get_results()
                
                break
    
    def _update_loop(self):
        while self._running:
            if self._metrics and self._on_metrics_update:
                self._on_metrics_update(self.get_current_metrics())
            time.sleep(0.1)
    
    def _notify_state_change(self):
        if self._on_state_change:
            self._on_state_change(self._state.value)
    
    def get_current_metrics(self) -> dict:
        if not self._metrics:
            return {}
        
        result = {
            'state': self._state.value,
            'mode': self._config.mode.value,
            'stats': self._metrics.get_current_stats(),
            'latency_data': self._metrics.get_latency_data(),
            'throughput_data': self._metrics.get_throughput_data(),
            'recent_packets': self._metrics.get_recent_packets(15),
            'events': self._metrics.get_recent_events(20),
        }
        
        if self._client:
            result['client'] = self._client.get_stats()
        
        if self._server:
            result['server'] = self._server.get_stats()
        
        return result
    
    def get_results(self) -> dict:
        if not self._metrics:
            return {}
        
        return {
            'mode': self._config.mode.value,
            'summary': self._metrics.get_comparison_summary(),
            'stats': self._metrics.get_current_stats(),
        }
    
    def get_comparison(self) -> dict:
        return {
            'dtp': self._results.get('dtp', {}),
            'udp_raw': self._results.get('udp_raw', {}),
        }
    
    def clear_results(self):
        self._results = {}
    
    @property
    def state(self) -> SimulationState:
        return self._state
    
    @property
    def is_running(self) -> bool:
        return self._state == SimulationState.RUNNING
