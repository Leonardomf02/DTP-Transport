"""
DTP Automated Test Runner
Executes baseline tests for DTP vs FIFO scheduler comparison.
"""

import sys
import os
import random
import time
import threading
import socket
from datetime import datetime
from statistics import mean, median, stdev
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.protocol import (
    DTPPacket, Priority, PacketType, Flags, now_ms,
    reset_reference_time, get_priority_emoji
)
from src.scheduler import DTPScheduler, SimpleScheduler
from src.metrics import MetricsCollector
from src.logger import ExperimentLogger, ExperimentConfig

TEST_PORT_BASE = 8020


def run_scheduler_baseline_test(
    scheduler_type: str = "DTP",
    total_packets: int = 200,
    seed: int = 42
) -> Dict:
    """Run a baseline test with specified scheduler."""
    
    random.seed(seed)
    reset_reference_time()
    
    experiment_id = f"Baseline_{scheduler_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
    logger = ExperimentLogger(output_dir="./logs", experiment_id=experiment_id)
    
    config = ExperimentConfig(
        experiment_id=experiment_id,
        experiment_name=f"Baseline {scheduler_type} Test",
        timestamp=datetime.now().isoformat(),
        seed=seed,
        packet_payload_bytes=64,
        simulation_duration_ms=2000,
        critical_count=int(total_packets * 0.05),
        high_count=int(total_packets * 0.15),
        medium_count=int(total_packets * 0.30),
        low_count=int(total_packets * 0.50),
        scheduler_type=scheduler_type,
        queue_size=1000,
        batch_size=10,
        batch_timeout_ms=50,
        admission_control_enabled=False,
        congestion_control_enabled=False,
        initial_send_rate=500.0,
        loss_model="none",
        loss_rate=0.0
    )
    logger.log_config(config)
    
    # Create scheduler
    if scheduler_type == "DTP":
        scheduler = DTPScheduler(queue_size=1000)
    else:
        scheduler = SimpleScheduler(queue_size=1000)
    
    metrics = MetricsCollector()
    
    # Generate packets
    packets = []
    packet_counts = {
        Priority.CRITICAL: config.critical_count,
        Priority.HIGH: config.high_count,
        Priority.MEDIUM: config.medium_count,
        Priority.LOW: config.low_count
    }
    
    seq = 0
    for priority, count in packet_counts.items():
        for _ in range(count):
            packet = DTPPacket.create_data(
                payload=f"TEST-{priority.name}-{seq}".encode(),
                priority=priority,
                sequence=seq,
                deadline_ms=priority.get_default_deadline_ms()
            )
            if priority == Priority.LOW:
                packet.header.flags |= Flags.DROPPABLE
            packets.append(packet)
            seq += 1
    
    random.shuffle(packets)
    
    # Enqueue all
    for pkt in packets:
        scheduler.enqueue(pkt)
        metrics.record_sent(pkt)
        logger.log_packet_sent(pkt)
    
    # Process with delays
    processed = 0
    base_delay_ms = 5
    
    while scheduler.queue_size > 0 or processed < total_packets:
        packet = scheduler.dequeue()
        if packet is None:
            break
            
        # Simulate processing delay
        priority_factor = (packet.header.priority.value + 1)
        jitter = random.uniform(0, 5)
        delay_ms = base_delay_ms * priority_factor + jitter
        time.sleep(delay_ms / 1000.0)
        
        packet.mark_received()
        metrics.record_received(packet)
        logger.log_packet_received(packet)
        
        processed += 1
    
    # Get final stats
    stats = metrics.get_current_stats()
    by_priority = stats.get('by_priority', {})
    
    logger.log_summary(stats)
    logger.close()
    
    return {
        'scheduler': scheduler_type,
        'total_sent': stats.get('total_sent', 0),
        'total_received': stats.get('total_received', 0),
        'by_priority': by_priority,
        'experiment_id': experiment_id,
        'log_path': str(logger.log_path)
    }


def print_test_results(results: Dict, title: str = "Test Results"):
    """Print formatted test results."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    
    print(f"\nScheduler: {results['scheduler']}")
    print(f"Packets: {results['total_received']}/{results['total_sent']}")
    
    print(f"\n{'Priority':<12} {'Sent':>6} {'Recv':>6} {'OnTime':>8} {'Deadline':>10} {'Avg Lat':>10}")
    print("-" * 60)
    
    priority_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    deadlines = {'CRITICAL': 500, 'HIGH': 1500, 'MEDIUM': 3000, 'LOW': 6000}
    
    for pri_name in priority_order:
        pri_stats = results['by_priority'].get(pri_name, {})
        sent = pri_stats.get('sent', 0)
        recv = pri_stats.get('received', 0)
        on_time = pri_stats.get('on_time', 0)
        on_time_pct = (on_time / recv * 100) if recv > 0 else 0
        deadline = deadlines.get(pri_name, 0)
        avg_lat = pri_stats.get('latency', {}).get('mean', 0)
        
        print(f"{pri_name:<12} {sent:>6} {recv:>6} {on_time_pct:>7.1f}% {deadline:>9}ms {avg_lat:>9.1f}ms")
    
    print(f"\nLog: {results.get('log_path', 'N/A')}")


def run_comparison_test():
    """Run comparison between DTP and FIFO schedulers."""
    print("\n" + "="*70)
    print("  DTP vs FIFO Scheduler Comparison Test")
    print("="*70)
    
    test_config = {
        'total_packets': 200,
        'seed': 42
    }
    
    print(f"\nConfig: {test_config['total_packets']} packets, seed={test_config['seed']}")
    
    # Run FIFO test
    print("\nRunning FIFO baseline...")
    fifo_results = run_scheduler_baseline_test(
        scheduler_type="FIFO",
        **test_config
    )
    print_test_results(fifo_results, "FIFO Results")
    
    time.sleep(0.5)
    
    # Run DTP test
    print("\nRunning DTP baseline...")
    dtp_results = run_scheduler_baseline_test(
        scheduler_type="DTP",
        **test_config
    )
    print_test_results(dtp_results, "DTP Results")
    
    # Print comparison
    print("\n" + "="*70)
    print("  Comparison Summary")
    print("="*70)
    
    priority_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    
    print(f"\n{'Priority':<12} {'FIFO OnTime':>14} {'DTP OnTime':>14} {'Improvement':>14}")
    print("-" * 56)
    
    for pri in priority_order:
        fifo_stats = fifo_results['by_priority'].get(pri, {})
        dtp_stats = dtp_results['by_priority'].get(pri, {})
        
        fifo_recv = fifo_stats.get('received', 0)
        dtp_recv = dtp_stats.get('received', 0)
        
        fifo_on_time = fifo_stats.get('on_time', 0)
        dtp_on_time = dtp_stats.get('on_time', 0)
        
        fifo_pct = (fifo_on_time / fifo_recv * 100) if fifo_recv > 0 else 0
        dtp_pct = (dtp_on_time / dtp_recv * 100) if dtp_recv > 0 else 0
        
        improvement = dtp_pct - fifo_pct
        imp_str = f"+{improvement:.1f}%" if improvement > 0 else f"{improvement:.1f}%"
        
        print(f"{pri:<12} {fifo_pct:>13.1f}% {dtp_pct:>13.1f}% {imp_str:>14}")
    
    print("\n" + "="*70)
    
    return {'fifo': fifo_results, 'dtp': dtp_results}


if __name__ == "__main__":
    run_comparison_test()
