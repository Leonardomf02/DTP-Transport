"""
DTP Rate Limiting and Congestion Control

Implements:
1. Token Bucket for admission control (limits CRITICAL/HIGH burst)
2. Congestion control with multiplicative decrease on loss
3. Pacing for smooth transmission

This prevents:
- DoS from CRITICAL traffic floods
- Network saturation
- Unfair starvation of lower priorities
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable
from collections import defaultdict

from .protocol import Priority, now_ms


@dataclass
class TokenBucketConfig:
    """Configuration for a token bucket"""
    rate: float           # Tokens per second (refill rate)
    burst: int            # Maximum bucket size (burst capacity)
    initial: int = None   # Initial tokens (defaults to burst)
    
    def __post_init__(self):
        if self.initial is None:
            self.initial = self.burst


class TokenBucket:
    """
    Token Bucket rate limiter.
    
    Allows bursts up to 'burst' size, with sustained rate of 'rate' tokens/sec.
    
    Usage:
        bucket = TokenBucket(rate=100, burst=50)  # 100 pkt/s, burst of 50
        if bucket.consume():
            send_packet()
        else:
            drop_or_queue()
    """
    
    def __init__(self, rate: float, burst: int, initial: int = None):
        """
        Args:
            rate: Tokens per second (refill rate)
            burst: Maximum bucket capacity
            initial: Initial token count (defaults to burst)
        """
        self.rate = rate
        self.burst = burst
        self._tokens = initial if initial is not None else burst
        self._last_update = now_ms()
        self._lock = threading.Lock()
        
        # Statistics
        self._total_consumed = 0
        self._total_rejected = 0
    
    def _refill(self):
        """Refill tokens based on elapsed time"""
        current_time = now_ms()
        elapsed_ms = current_time - self._last_update
        
        if elapsed_ms > 0:
            # Add tokens based on elapsed time
            new_tokens = (elapsed_ms / 1000.0) * self.rate
            self._tokens = min(self.burst, self._tokens + new_tokens)
            self._last_update = current_time
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from the bucket.
        
        Args:
            tokens: Number of tokens to consume (default 1)
            
        Returns:
            True if tokens were consumed, False if bucket is empty
        """
        with self._lock:
            self._refill()
            
            if self._tokens >= tokens:
                self._tokens -= tokens
                self._total_consumed += tokens
                return True
            else:
                self._total_rejected += tokens
                return False
    
    def try_consume_or_wait(self, tokens: int = 1, max_wait_ms: int = 100) -> bool:
        """
        Try to consume tokens, waiting if necessary.
        
        Args:
            tokens: Number of tokens to consume
            max_wait_ms: Maximum time to wait in milliseconds
            
        Returns:
            True if tokens were consumed within timeout
        """
        start = now_ms()
        
        while True:
            if self.consume(tokens):
                return True
            
            elapsed = now_ms() - start
            if elapsed >= max_wait_ms:
                return False
            
            # Wait for tokens to refill
            wait_time = min(10, max_wait_ms - elapsed) / 1000.0
            time.sleep(wait_time)
    
    @property
    def available_tokens(self) -> float:
        """Get current available tokens"""
        with self._lock:
            self._refill()
            return self._tokens
    
    @property
    def stats(self) -> dict:
        """Get bucket statistics"""
        with self._lock:
            return {
                'rate': self.rate,
                'burst': self.burst,
                'available': self._tokens,
                'consumed': self._total_consumed,
                'rejected': self._total_rejected,
            }
    
    def reset(self):
        """Reset bucket to full"""
        with self._lock:
            self._tokens = self.burst
            self._last_update = now_ms()


class AdmissionController:
    """
    Admission control for DTP traffic.
    
    Implements per-priority token buckets to prevent any single
    priority from starving others.
    
    Default limits:
    - CRITICAL: 50 pkt/s, burst 20 (emergency only!)
    - HIGH: 200 pkt/s, burst 50
    - MEDIUM: 500 pkt/s, burst 100
    - LOW: 1000 pkt/s, burst 200 (or unlimited)
    """
    
    # Default rate limits per priority
    DEFAULT_LIMITS = {
        Priority.CRITICAL: TokenBucketConfig(rate=50, burst=20),
        Priority.HIGH: TokenBucketConfig(rate=200, burst=50),
        Priority.MEDIUM: TokenBucketConfig(rate=500, burst=100),
        Priority.LOW: TokenBucketConfig(rate=1000, burst=200),
    }
    
    def __init__(self, 
                 limits: Dict[Priority, TokenBucketConfig] = None,
                 enable_critical_limit: bool = True):
        """
        Args:
            limits: Custom limits per priority (or use defaults)
            enable_critical_limit: Whether to limit CRITICAL (for testing)
        """
        self._limits = limits or self.DEFAULT_LIMITS
        self._enable_critical_limit = enable_critical_limit
        
        # Create buckets
        self._buckets: Dict[Priority, TokenBucket] = {}
        for priority, config in self._limits.items():
            self._buckets[priority] = TokenBucket(
                rate=config.rate,
                burst=config.burst,
                initial=config.initial
            )
        
        # Statistics
        self._stats = {p: {'admitted': 0, 'rejected': 0} for p in Priority}
        self._lock = threading.Lock()
    
    def admit(self, priority: Priority) -> bool:
        """
        Check if a packet with given priority should be admitted.
        
        Args:
            priority: Packet priority
            
        Returns:
            True if packet should be admitted, False to reject
        """
        # CRITICAL bypass if disabled
        if priority == Priority.CRITICAL and not self._enable_critical_limit:
            with self._lock:
                self._stats[priority]['admitted'] += 1
            return True
        
        bucket = self._buckets.get(priority)
        if bucket is None:
            return True  # No limit for this priority
        
        admitted = bucket.consume()
        
        with self._lock:
            if admitted:
                self._stats[priority]['admitted'] += 1
            else:
                self._stats[priority]['rejected'] += 1
        
        return admitted
    
    def get_stats(self) -> dict:
        """Get admission statistics"""
        with self._lock:
            return {
                'by_priority': {
                    p.name: {
                        **self._stats[p],
                        'bucket': self._buckets[p].stats if p in self._buckets else None
                    }
                    for p in Priority
                }
            }
    
    def reset(self):
        """Reset all buckets and stats"""
        for bucket in self._buckets.values():
            bucket.reset()
        with self._lock:
            self._stats = {p: {'admitted': 0, 'rejected': 0} for p in Priority}


class CongestionController:
    """
    Congestion control with token bucket pacing and AIMD.
    
    Features:
    - Token bucket for pacing (smooth output)
    - Additive Increase on success (ACKs received)
    - Multiplicative Decrease on loss (packet loss detected)
    
    Algorithm:
    - Start with initial_rate
    - On ACK: rate += additive_increase (up to max_rate)
    - On loss: rate *= (1 - multiplicative_decrease)
    - Pacing bucket enforces current rate
    """
    
    def __init__(self,
                 initial_rate: float = 500,      # Initial packets/second
                 min_rate: float = 50,           # Minimum rate
                 max_rate: float = 5000,         # Maximum rate
                 additive_increase: float = 10,  # Packets/s increase per ACK window
                 multiplicative_decrease: float = 0.5,  # Decrease factor on loss
                 loss_threshold: float = 0.02):  # Loss rate threshold for decrease
        
        self.initial_rate = initial_rate
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.additive_increase = additive_increase
        self.multiplicative_decrease = multiplicative_decrease
        self.loss_threshold = loss_threshold
        
        # Current state
        self._current_rate = initial_rate
        self._pacing_bucket = TokenBucket(rate=initial_rate, burst=int(initial_rate / 10))
        
        # Loss tracking (sliding window)
        self._sent_count = 0
        self._ack_count = 0
        self._loss_count = 0
        self._window_start = now_ms()
        self._window_size_ms = 1000  # 1 second window
        
        # State
        self._congested = False
        self._last_decrease_time = 0
        self._decrease_cooldown_ms = 500  # Don't decrease too often
        
        self._lock = threading.Lock()
    
    def can_send(self) -> bool:
        """
        Check if we can send a packet (pacing).
        
        Returns:
            True if sending is allowed by pacing
        """
        return self._pacing_bucket.consume()
    
    def wait_for_token(self, max_wait_ms: int = 100) -> bool:
        """
        Wait for pacing token.
        
        Args:
            max_wait_ms: Maximum wait time
            
        Returns:
            True if token acquired
        """
        return self._pacing_bucket.try_consume_or_wait(max_wait_ms=max_wait_ms)
    
    def on_packet_sent(self):
        """Called when a packet is sent"""
        with self._lock:
            self._sent_count += 1
    
    def on_ack_received(self, count: int = 1):
        """
        Called when ACKs are received.
        
        Args:
            count: Number of ACKs received
        """
        with self._lock:
            self._ack_count += count
            
            # Check if we should increase rate (additive increase)
            if self._ack_count >= 10:  # Every 10 ACKs
                self._increase_rate()
                self._ack_count = 0
    
    def on_loss_detected(self, count: int = 1):
        """
        Called when packet loss is detected.
        
        Args:
            count: Number of lost packets
        """
        with self._lock:
            self._loss_count += count
            self._check_and_decrease()
    
    def on_timeout(self):
        """Called on RTO timeout (major congestion signal)"""
        with self._lock:
            # More aggressive decrease on timeout
            current_time = now_ms()
            if current_time - self._last_decrease_time > self._decrease_cooldown_ms:
                self._current_rate = max(
                    self.min_rate,
                    self._current_rate * (1 - self.multiplicative_decrease * 1.5)
                )
                self._update_bucket()
                self._congested = True
                self._last_decrease_time = current_time
    
    def _increase_rate(self):
        """Additive increase"""
        if not self._congested:
            self._current_rate = min(
                self.max_rate,
                self._current_rate + self.additive_increase
            )
            self._update_bucket()
    
    def _check_and_decrease(self):
        """Check loss rate and apply multiplicative decrease if needed"""
        current_time = now_ms()
        
        # Check window
        if current_time - self._window_start >= self._window_size_ms:
            # Calculate loss rate
            total = self._sent_count
            if total > 0:
                loss_rate = self._loss_count / total
                
                if loss_rate > self.loss_threshold:
                    # Multiplicative decrease
                    if current_time - self._last_decrease_time > self._decrease_cooldown_ms:
                        self._current_rate = max(
                            self.min_rate,
                            self._current_rate * (1 - self.multiplicative_decrease)
                        )
                        self._update_bucket()
                        self._congested = True
                        self._last_decrease_time = current_time
                else:
                    # No congestion
                    self._congested = False
            
            # Reset window
            self._sent_count = 0
            self._ack_count = 0
            self._loss_count = 0
            self._window_start = current_time
    
    def _update_bucket(self):
        """Update pacing bucket with new rate"""
        self._pacing_bucket = TokenBucket(
            rate=self._current_rate,
            burst=max(10, int(self._current_rate / 10))
        )
    
    @property
    def current_rate(self) -> float:
        """Current sending rate in packets/second"""
        return self._current_rate
    
    @property
    def is_congested(self) -> bool:
        """Whether we're in congestion state"""
        return self._congested
    
    def get_stats(self) -> dict:
        """Get congestion control statistics"""
        with self._lock:
            return {
                'current_rate': self._current_rate,
                'min_rate': self.min_rate,
                'max_rate': self.max_rate,
                'congested': self._congested,
                'sent_in_window': self._sent_count,
                'lost_in_window': self._loss_count,
                'bucket': self._pacing_bucket.stats,
            }
    
    def reset(self):
        """Reset to initial state"""
        with self._lock:
            self._current_rate = self.initial_rate
            self._pacing_bucket = TokenBucket(
                rate=self.initial_rate,
                burst=int(self.initial_rate / 10)
            )
            self._sent_count = 0
            self._ack_count = 0
            self._loss_count = 0
            self._congested = False


class Pacer:
    """
    Simple packet pacer for smooth transmission.
    
    Ensures packets are sent at a regular interval rather than
    in bursts, reducing buffer bloat and jitter.
    """
    
    def __init__(self, packets_per_second: float = 1000):
        """
        Args:
            packets_per_second: Target send rate
        """
        self._rate = packets_per_second
        self._interval_ms = 1000.0 / packets_per_second
        self._last_send_time = 0
        self._lock = threading.Lock()
    
    def wait_for_next_slot(self) -> float:
        """
        Wait until the next send slot.
        
        Returns:
            Actual wait time in milliseconds
        """
        with self._lock:
            current_time = now_ms()
            time_since_last = current_time - self._last_send_time
            
            if time_since_last < self._interval_ms:
                wait_ms = self._interval_ms - time_since_last
                time.sleep(wait_ms / 1000.0)
                self._last_send_time = now_ms()
                return wait_ms
            else:
                self._last_send_time = current_time
                return 0
    
    def set_rate(self, packets_per_second: float):
        """Update pacing rate"""
        with self._lock:
            self._rate = packets_per_second
            self._interval_ms = 1000.0 / packets_per_second
    
    @property
    def rate(self) -> float:
        return self._rate
