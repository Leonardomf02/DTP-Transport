"""DTP - Deadline-aware Transport Protocol Backend Module."""

from .protocol import (
    DTPPacket, DTPHeader, Priority, PacketType, Flags,
    now_ms, get_current_time_ms, reset_reference_time,
    DTP_VERSION, DTP_HEADER_SIZE, DTP_DEFAULT_PORT, DTP_MAGIC,
    get_priority_emoji
)

from .scheduler import DTPScheduler, SimpleScheduler, QueueEntry

from .metrics import MetricsCollector

from .rate_control import (
    TokenBucket, AdmissionController, CongestionController, Pacer,
    TokenBucketConfig
)

from .clock_sync import (
    ClockSyncClient, ClockSyncServer, ClockSyncResult,
    sync_with_server, set_global_clock_offset, get_global_clock_offset,
    adjust_remote_timestamp
)

from .logger import (
    ExperimentLogger, ExperimentConfig, LogReader,
    set_seed, generate_experiment_id
)

__version__ = "1.0.0"
__all__ = [
    'DTPPacket', 'DTPHeader', 'Priority', 'PacketType', 'Flags',
    'now_ms', 'get_current_time_ms', 'reset_reference_time',
    'DTP_VERSION', 'DTP_HEADER_SIZE', 'DTP_DEFAULT_PORT', 'DTP_MAGIC',
    'get_priority_emoji',
    'DTPScheduler', 'SimpleScheduler', 'QueueEntry',
    'MetricsCollector',
    'TokenBucket', 'AdmissionController', 'CongestionController', 'Pacer',
    'TokenBucketConfig',
    'ClockSyncClient', 'ClockSyncServer', 'ClockSyncResult',
    'sync_with_server', 'set_global_clock_offset', 'get_global_clock_offset',
    'adjust_remote_timestamp',
    'ExperimentLogger', 'ExperimentConfig', 'LogReader',
    'set_seed', 'generate_experiment_id',
]
