"""
Tests for DTP Protocol
"""

import pytest
import time
from src.protocol import (
    DTPHeader, DTPPacket, Priority, PacketType, Flags,
    DTP_VERSION, DTP_HEADER_SIZE
)
from src.scheduler import DTPScheduler, SimpleScheduler


class TestDTPHeader:
    """Test DTP header serialization"""
    
    def test_header_serialize_deserialize(self):
        """Test header roundtrip"""
        header = DTPHeader(
            priority=Priority.HIGH,
            sequence=1234,
            deadline=100,
            batch_id=5,
            flags=Flags.RELIABLE | Flags.BATCHED,
            packet_type=PacketType.DATA
        )
        
        data = header.serialize()
        assert len(data) == DTP_HEADER_SIZE
        
        restored = DTPHeader.deserialize(data)
        assert restored.version == DTP_VERSION
        assert restored.priority == Priority.HIGH
        assert restored.sequence == 1234
        assert restored.deadline == 100
        assert restored.batch_id == 5
        assert restored.flags == (Flags.RELIABLE | Flags.BATCHED)
        assert restored.packet_type == PacketType.DATA
    
    def test_header_expiry(self):
        """Test deadline expiry checking"""
        # Expired header (deadline in the past)
        header = DTPHeader(
            timestamp=int(time.time() * 1000) - 1000,  # 1 second ago
            deadline=500  # 500ms deadline
        )
        assert header.is_expired()
        
        # Non-expired header
        header = DTPHeader(
            timestamp=int(time.time() * 1000),
            deadline=5000  # 5 second deadline
        )
        assert not header.is_expired()
    
    def test_priority_default_deadlines(self):
        """Test default deadlines by priority"""
        assert Priority.CRITICAL.get_default_deadline_ms() == 50
        assert Priority.HIGH.get_default_deadline_ms() == 100
        assert Priority.MEDIUM.get_default_deadline_ms() == 250
        assert Priority.LOW.get_default_deadline_ms() == 1000


class TestDTPPacket:
    """Test DTP packet"""
    
    def test_packet_create_data(self):
        """Test creating data packet"""
        packet = DTPPacket.create_data(
            payload=b"Hello DTP",
            priority=Priority.CRITICAL,
            sequence=42
        )
        
        assert packet.header.priority == Priority.CRITICAL
        assert packet.header.sequence == 42
        assert packet.payload == b"Hello DTP"
        assert packet.header.packet_type == PacketType.DATA
    
    def test_packet_serialize_deserialize(self):
        """Test packet roundtrip"""
        original = DTPPacket.create_data(
            payload=b"Test payload",
            priority=Priority.MEDIUM,
            sequence=999,
            deadline_ms=200
        )
        
        data = original.serialize()
        restored = DTPPacket.deserialize(data)
        
        assert restored.header.priority == Priority.MEDIUM
        assert restored.header.sequence == 999
        assert restored.header.deadline == 200
        assert restored.payload == b"Test payload"
    
    def test_packet_latency_calculation(self):
        """Test latency calculation"""
        packet = DTPPacket.create_data(
            payload=b"",
            priority=Priority.LOW,
            sequence=1
        )
        
        # Simulate delay
        time.sleep(0.05)  # 50ms
        
        packet.mark_received()
        
        assert packet.receive_time is not None
        assert packet.latency_ms >= 50
        assert packet.latency_ms < 100  # Allow some tolerance


class TestDTPScheduler:
    """Test DTP scheduler"""
    
    def test_scheduler_priority_ordering(self):
        """Test that high priority packets are dequeued first"""
        scheduler = DTPScheduler()
        
        # Add packets in mixed order
        low = DTPPacket.create_data(b"low", Priority.LOW, 1)
        high = DTPPacket.create_data(b"high", Priority.HIGH, 2)
        critical = DTPPacket.create_data(b"critical", Priority.CRITICAL, 3)
        
        scheduler.enqueue(low, allow_batch=False)
        scheduler.enqueue(high, allow_batch=False)
        scheduler.enqueue(critical, allow_batch=False)
        
        # Should come out in priority order (deadline-aware)
        first = scheduler.dequeue()
        assert first.header.priority == Priority.CRITICAL
        
        second = scheduler.dequeue()
        assert second.header.priority == Priority.HIGH
        
        third = scheduler.dequeue()
        assert third.header.priority == Priority.LOW
    
    def test_scheduler_deadline_ordering(self):
        """Test that urgent deadlines are prioritized"""
        scheduler = DTPScheduler()
        
        # Same priority, different deadlines
        long_deadline = DTPPacket.create_data(b"long", Priority.MEDIUM, 1, deadline_ms=1000)
        short_deadline = DTPPacket.create_data(b"short", Priority.MEDIUM, 2, deadline_ms=50)
        
        scheduler.enqueue(long_deadline, allow_batch=False)
        scheduler.enqueue(short_deadline, allow_batch=False)
        
        # Short deadline should come first
        first = scheduler.dequeue()
        assert first.header.deadline == 50
    
    def test_scheduler_drops_expired(self):
        """Test that expired packets are dropped"""
        scheduler = DTPScheduler()
        
        # Create already-expired packet
        expired = DTPPacket.create_data(b"expired", Priority.LOW, 1)
        expired.header.timestamp = int(time.time() * 1000) - 2000  # 2 seconds ago
        expired.header.deadline = 100  # 100ms deadline
        
        # Should be rejected on enqueue
        accepted = scheduler.enqueue(expired, allow_batch=False)
        assert not accepted
    
    def test_scheduler_congestion_mode(self):
        """Test congestion behavior"""
        scheduler = DTPScheduler()
        
        # Add low priority packet
        low = DTPPacket.create_data(b"low", Priority.LOW, 1, deadline_ms=5000)
        scheduler.enqueue(low, allow_batch=False)
        
        # Add high priority packet
        high = DTPPacket.create_data(b"high", Priority.HIGH, 2, deadline_ms=5000)
        scheduler.enqueue(high, allow_batch=False)
        
        # Set congested
        scheduler.set_congested(True)
        
        # Should only get high priority
        first = scheduler.dequeue()
        assert first.header.priority == Priority.HIGH
        
        # Low priority should be skipped
        second = scheduler.dequeue()
        assert second is None or second.header.priority != Priority.LOW


class TestSimpleScheduler:
    """Test simple FIFO scheduler for comparison"""
    
    def test_simple_scheduler_fifo(self):
        """Test FIFO ordering"""
        scheduler = SimpleScheduler()
        
        first = DTPPacket.create_data(b"1", Priority.LOW, 1)
        second = DTPPacket.create_data(b"2", Priority.CRITICAL, 2)
        
        scheduler.enqueue(first)
        scheduler.enqueue(second)
        
        # Should be FIFO regardless of priority
        out1 = scheduler.dequeue()
        assert out1.header.sequence == 1
        
        out2 = scheduler.dequeue()
        assert out2.header.sequence == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
