# DTP - Deadline-aware Transport Protocol
## Código Essencial da Implementação

Este documento contém a lógica mais importante de cada módulo do protocolo DTP.

---

# ⚠️ CHANGELOG - Correções Aplicadas (Dezembro 2025)

| Bug | Descrição | Correção |
|-----|-----------|----------|
| **#1** | Mistura de `time.time()` com `get_current_time_ms()` causava batch timeout a NUNCA funcionar | Sistema unificado com `time.monotonic()` via `now_ms()` |
| **#2** | Sort key usava deadline relativo - pacotes com mesmo deadline duration ordenados errado | Agora usa `absolute_deadline = timestamp + deadline` |
| **#3** | Busy-loop quando congestionado e apenas pacotes LOW na fila | Retorna `None` imediatamente, deixa caller dormir |
| **#4** | Índice p95 podia sair fora do range | Adicionado `min(idx, len-1)` |

---

# 📦 1. PROTOCOL.PY - Definição do Protocolo

## 1.1 Sistema de Timestamps Unificado (CORRIGIDO ✅)
```python
# ==============================================================================
# UNIFIED TIME SYSTEM - Using time.monotonic() to avoid clock jumps
# ==============================================================================
# Reference time for relative timestamps (reset at simulation start)
# Uses monotonic clock to avoid issues with system time changes
_reference_time_monotonic = {'value': int(time.monotonic() * 1000)}

def now_ms() -> int:
    """
    Get current time in milliseconds using MONOTONIC clock.
    This is the ONLY time function that should be used internally.
    Returns time relative to reference (starts at 0 after reset).
    """
    now = int(time.monotonic() * 1000)
    return now - _reference_time_monotonic['value']


def get_current_time_ms() -> int:
    """
    Alias for now_ms() - for backward compatibility.
    Get current time in milliseconds (relative to reference).
    """
    return now_ms()


def reset_reference_time():
    """
    Reset reference time (call at start of simulation).
    After this call, now_ms() will return 0.
    """
    _reference_time_monotonic['value'] = int(time.monotonic() * 1000)
    print(f"🕐 Reference time reset (monotonic): {_reference_time_monotonic['value']}")
```

**Porquê `time.monotonic()`?**
- `time.time()` pode saltar para trás/frente com ajustes de sistema (NTP, etc.)
- `time.monotonic()` é monotónico - nunca salta, sempre cresce
- Função única `now_ms()` garante consistência em todo o código

---

## 1.2 Sistema de Prioridades com Deadlines
```python
class Priority(IntEnum):
    """Message priority levels"""
    CRITICAL = 0  # Alarms, control messages - must arrive ASAP
    HIGH = 1      # Real-time, gaming, video calls
    MEDIUM = 2    # Streaming, interactive
    LOW = 3       # Sync, logs, bulk transfers
    
    def get_default_deadline_ms(self) -> int:
        """Default deadline based on priority"""
        defaults = {
            Priority.CRITICAL: 500,    # 500ms
            Priority.HIGH: 1500,       # 1.5 seconds
            Priority.MEDIUM: 3000,     # 3 seconds
            Priority.LOW: 6000,        # 6 seconds
        }
        return defaults[self]
```

**Porquê IntEnum?** Permite comparação numérica direta: `CRITICAL(0) < HIGH(1) < MEDIUM(2) < LOW(3)`. Valores menores = maior prioridade.

---

## 1.3 Formato do Header DTP (16 bytes)
```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|    Version    |   Priority    |      Sequence Number          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     Timestamp (ms offset)                     |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                   Deadline (ms from now)                      |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          Batch ID             |    Flags      |    Type       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

## 1.4 Serialização do Header
```python
def serialize(self) -> bytes:
    """Serialize header to bytes"""
    return struct.pack(
        '>BBHIIBBH',  # Big-endian
        self.version,           # B: 1 byte
        self.priority,          # B: 1 byte
        self.sequence & 0xFFFF, # H: 2 bytes
        self.timestamp & 0xFFFFFFFF,  # I: 4 bytes
        self.deadline & 0xFFFFFFFF,   # I: 4 bytes
        self.flags,             # B: 1 byte
        self.packet_type,       # B: 1 byte
        self.batch_id & 0xFFFF  # H: 2 bytes
    )  # Total: 16 bytes

@classmethod
def deserialize(cls, data: bytes) -> 'DTPHeader':
    """Deserialize header from bytes"""
    version, priority, sequence, timestamp, deadline, flags, packet_type, batch_id = struct.unpack(
        '>BBHIIBBH',
        data[:DTP_HEADER_SIZE]
    )
    return cls(
        version=version,
        priority=Priority(priority),
        sequence=sequence,
        timestamp=timestamp,
        deadline=deadline,
        batch_id=batch_id,
        flags=flags,
        packet_type=PacketType(packet_type)
    )
```

---

## 1.5 Verificação de Expiração
```python
def is_expired(self) -> bool:
    """Check if packet deadline has passed"""
    now = get_current_time_ms()
    return now > (self.timestamp + self.deadline)

def time_remaining_ms(self) -> int:
    """Time remaining until deadline (can be negative)"""
    now = get_current_time_ms()
    return (self.timestamp + self.deadline) - now
```

**Fórmula:** `expirado = tempo_atual > (timestamp_criação + deadline)`

---

# 🗓️ 2. SCHEDULER.PY - Escalonador com Prioridades

## 2.1 Estrutura do Pacote na Fila (Sort Key) - CORRIGIDO ✅
```python
@dataclass(order=True)
class ScheduledPacket:
    """Wrapper for packets in the priority queue"""
    # Sort key: (priority, absolute_deadline, sequence)
    # Priority first ensures CRITICAL always goes before HIGH, etc.
    # Absolute deadline ensures earlier deadlines are processed first (EDF)
    sort_key: tuple = field(compare=True)
    packet: DTPPacket = field(compare=False)
    enqueue_time: int = field(compare=False)
    
    @classmethod
    def from_packet(cls, packet: DTPPacket) -> 'ScheduledPacket':
        """Create scheduled packet with proper sort key"""
        # Sort by: priority first (lower = more important), then ABSOLUTE deadline, then sequence
        # absolute_deadline = timestamp + deadline (when it expires)
        # This ensures packets closer to expiry are sent first within same priority
        enqueue_time = now_ms()
        absolute_deadline = packet.header.timestamp + packet.header.deadline
        sort_key = (packet.header.priority, absolute_deadline, packet.header.sequence)
        return cls(
            sort_key=sort_key,
            packet=packet,
            enqueue_time=enqueue_time
        )
```

**Sort Key = (priority, absolute_deadline, sequence)** - CORRIGIDO!
- **1º Priority:** CRITICAL(0) sempre antes de HIGH(1), etc.
- **2º Absolute Deadline:** `timestamp + deadline` = momento real de expiração (EDF correto!)
- **3º Sequence:** Ordem de chegada como desempate final

**Bug anterior:** Usava deadline relativo, pacotes criados mais tarde com mesmo deadline duration eram processados na ordem errada.

---

## 2.2 Enqueue - Adicionar à Fila
```python
def enqueue(self, packet: DTPPacket, allow_batch: bool = True) -> bool:
    """Add packet to scheduler queue"""
    with self._lock:
        # High priority packets always get queued (CRITICAL and HIGH)
        # Only check expiry for lower priority packets
        if packet.header.priority > Priority.HIGH:
            # Check if already expired for MEDIUM and LOW
            if packet.header.is_expired():
                self._stats['dropped_expired'] += 1
                return False
        
        # Check queue capacity
        if len(self._queue) >= self._max_queue_size:
            # Try to drop lowest priority expired packet
            if not self._drop_lowest_priority():
                # For high priority, drop a low priority packet even if not expired
                if packet.header.priority <= Priority.HIGH:
                    self._drop_lowest_priority_any()
                else:
                    return False
        
        # Batch low-priority packets if not congested
        if (allow_batch and 
            packet.header.priority == Priority.LOW and
            not (packet.header.flags & Flags.EXPEDITED)):
            return self._add_to_batch(packet)
        
        # Add directly to queue
        scheduled = ScheduledPacket.from_packet(packet)
        heapq.heappush(self._queue, scheduled)  # O(log n)
        return True
```

**Regras de Enqueue:**
1. CRITICAL/HIGH: Sempre aceites (nunca expiram no enqueue)
2. MEDIUM/LOW: Verificar expiração antes de aceitar
3. Se fila cheia: Drop LOW priority para fazer espaço para HIGH
4. LOW packets podem ser agrupados em batches

---

## 2.3 ⭐ DEQUEUE - A Função Mais Importante ⭐ (CORRIGIDO ✅)
```python
def dequeue(self) -> Optional[DTPPacket]:
    """
    Get next packet to send based on deadline and priority
    
    Returns None if queue is empty or all packets expired
    """
    with self._lock:
        # Flush any pending batches that timed out
        self._check_batch_timeouts()
        
        # If queue is empty but we have batches pending, flush them all
        if not self._queue and any(self._batch_buffer.values()):
            for priority in list(self._batch_buffer.keys()):
                if self._batch_buffer.get(priority):
                    self._flush_batch(priority)
        
        while self._queue:
            scheduled = heapq.heappop(self._queue)
            packet = scheduled.packet
            
            # Check expiry based on priority:
            # - CRITICAL: NEVER expires (must always be delivered)
            # - HIGH: 2x tolerance (only drop if very late)
            # - MEDIUM/LOW: Normal expiry
            if packet.header.priority == Priority.CRITICAL:
                # CRITICAL packets are NEVER dropped due to expiry
                pass
            elif packet.header.priority == Priority.HIGH:
                # HIGH packets have 2x deadline tolerance
                current_time = now_ms()
                extended_deadline = packet.header.timestamp + (packet.header.deadline * 2)
                if current_time > extended_deadline:
                    self._stats['dropped_expired'] += 1
                    continue
            elif packet.header.priority == Priority.MEDIUM:
                if packet.header.is_expired():
                    self._stats['dropped_expired'] += 1
                    continue
            elif packet.header.is_expired():
                # LOW packets use normal expiry
                self._stats['dropped_expired'] += 1
                continue
            
            # If congested, skip LOW priority unless EXPEDITED
            # BUT: don't re-push infinitely to avoid busy-loop - just return None
            if (self._congested and 
                packet.header.priority == Priority.LOW and
                not (packet.header.flags & Flags.EXPEDITED)):
                # Put back in queue and return None to let caller sleep
                # This avoids busy-loop when only LOW packets remain
                heapq.heappush(self._queue, scheduled)
                return None  # Signal to caller to wait
            
            self._stats['dequeued'] += 1
            return packet
        
        return None  # Queue empty
```

### Regras de Expiração no Dequeue:
| Prioridade | Regra de Expiração |
|------------|-------------------|
| **CRITICAL** | **NUNCA expira** - sempre entregue |
| **HIGH** | Expira após **2x o deadline** (tolerância extra) |
| **MEDIUM** | Expira após **1x o deadline** (normal) |
| **LOW** | Expira após **1x o deadline** (normal) |

### Correção do Busy-Loop (IMPORTANTE!):
**Bug anterior:** Quando congestionado com apenas pacotes LOW, o código fazia:
```python
# ERRADO - loop infinito!
while True:
    packet = heappop()
    if congested and LOW:
        heappush(packet)  # push de volta
        continue  # volta ao início - NUNCA sai!
```

**Correção:** Agora retorna `None` imediatamente, deixando o caller dormir.

---

## 2.4 Batching de Pacotes LOW Priority (CORRIGIDO ✅)
```python
def _add_to_batch(self, packet: DTPPacket) -> bool:
    """Add packet to batch buffer"""
    priority = packet.header.priority
    
    # Start batch timer if first packet - usa now_ms() para consistência!
    if priority not in self._batch_start_time:
        self._batch_start_time[priority] = now_ms()  # CORRIGIDO: era time.time()
    
    self._batch_buffer[priority].append(packet)
    
    # Check if batch is ready to send
    batch = self._batch_buffer[priority]
    start_time = self._batch_start_time[priority]
    current_time = now_ms()  # CORRIGIDO: era get_current_time_ms() com unidades diferentes
    
    # Flush batch when: size reached OR timeout expired
    if (len(batch) >= self._batch_size or
        current_time - start_time >= self._batch_timeout_ms):
        self._flush_batch(priority)
    
    return True

def _check_batch_timeouts(self):
    """Flush batches that have timed out"""
    current_time = now_ms()  # CORRIGIDO: timing consistente
    for priority in list(self._batch_start_time.keys()):
        if priority in self._batch_buffer and self._batch_buffer[priority]:
            start_time = self._batch_start_time.get(priority, current_time)
            if current_time - start_time >= self._batch_timeout_ms:
                self._flush_batch(priority)
```

**Bug anterior:** `_batch_start_time` guardava `time.time() * 1000` (absoluto em ms), mas a comparação usava `get_current_time_ms()` (relativo). Diferença de ~54 anos em milissegundos = timeout NUNCA disparava!

def _flush_batch(self, priority: Priority):
    """Flush batch buffer to queue"""
    batch = self._batch_buffer[priority]
    if not batch:
        return
    
    self._current_batch_id += 1
    
    # Mark all packets in batch with same batch_id
    for packet in batch:
        packet.header.batch_id = self._current_batch_id
        packet.header.flags |= Flags.BATCHED
        scheduled = ScheduledPacket.from_packet(packet)
        heapq.heappush(self._queue, scheduled)
    
    # Clear batch buffer
    self._batch_buffer[priority] = []
```

**Batching:** Agrupa pacotes LOW em lotes de N pacotes ou após timeout, reduzindo overhead.

---

## 2.5 SimpleScheduler (FIFO para Comparação)
```python
class SimpleScheduler:
    """Simple FIFO scheduler (no DTP features) for comparison"""
    
    def enqueue(self, packet: DTPPacket, allow_batch: bool = True) -> bool:
        with self._lock:
            if len(self._queue) >= self._max_queue_size:
                return False
            self._queue.append(packet)  # FIFO: append no fim
            return True
    
    def dequeue(self) -> Optional[DTPPacket]:
        with self._lock:
            if self._queue:
                return self._queue.pop(0)  # FIFO: remove do início
            return None
```

**Diferença:** SimpleScheduler ignora prioridades - envia na ordem de chegada (FIFO).

---

# 📤 3. CLIENT.PY - Geração e Envio de Tráfego

## 3.1 Perfil de Tráfego
```python
class TrafficProfile:
    """Defines the traffic mix to generate"""
    
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
```

---

## 3.2 Loop de Simulação com Threads Paralelas
```python
def _simulation_loop(self):
    """Main simulation loop - generates and sends traffic CONTINUOUSLY"""
    
    # Create schedule: (time_offset, priority) for each packet
    generation_schedule = []
    for priority, count in counts.items():
        for i in range(count):
            time_offset = random.uniform(0, simulation_duration_ms)
            generation_schedule.append((time_offset, priority))
    
    # Sort by time
    generation_schedule.sort(key=lambda x: x[0])
    
    # Start sender thread FIRST - sends packets as they're enqueued
    sender_running = threading.Event()
    sender_running.set()
    
    def sender_loop():
        """Continuously send packets from the queue"""
        while sender_running.is_set() or self._scheduler.queue_size > 0:
            packet = self._scheduler.dequeue()
            if packet:
                self._send_packet(packet)
                # Rate limiting
                delay = 1.0 / self._scheduler.send_rate
                time.sleep(delay)
            else:
                time.sleep(0.001)
    
    # Start sender thread
    sender_thread = threading.Thread(target=sender_loop, daemon=True)
    sender_thread.start()
    
    # Generate packets according to schedule
    while packet_index < len(generation_schedule):
        scheduled_time, priority = generation_schedule[packet_index]
        
        if scheduled_time > current_time:
            break  # Wait for this packet's time
        
        # Create packet with timestamp = NOW
        packet = DTPPacket.create_data(
            payload=payload,
            priority=priority,
            sequence=seq,
            deadline_ms=priority.get_default_deadline_ms()
        )
        
        # Enqueue - sender thread picks it up immediately!
        self._scheduler.enqueue(packet)
        self.metrics.record_sent(packet)
```

**Arquitetura:**
1. **Thread 1 (Generator):** Gera pacotes ao longo do tempo simulado
2. **Thread 2 (Sender):** Consome da fila e envia continuamente

**Porquê paralelo?** Se gerassemos tudo primeiro, os CRITICAL teriam timestamps antigos e pareceriam atrasados.

---

## 3.3 Envio de Pacote (Sem Modificar Timestamp!)
```python
def _send_packet(self, packet: DTPPacket):
    """Send a single packet"""
    # NOTE: Do NOT update timestamp here!
    # Timestamp was set at enqueue time to measure total latency
    # (queue time + network time). Updating here would only measure
    # network time and negate the benefit of DTP prioritization.
    
    data = packet.serialize()
    self._socket.sendto(data, (self.host, self.port))
```

**IMPORTANTE:** O timestamp é definido na criação, não no envio. Isto mede latência total (fila + rede).

---

# 🖥️ 4. SERVER.PY - Receção de Pacotes

## 4.1 Processamento de Pacote Recebido
```python
def _handle_packet(self, data: bytes, addr: tuple):
    """Handle received packet"""
    packet = DTPPacket.deserialize(data)
    packet.mark_received()  # Calcula latência
    
    # Check if expired
    if packet.header.is_expired():
        self._packets_dropped += 1
        self.metrics.record_dropped(packet, "expired_on_arrival")
        return
    
    # Simulate processing delay based on congestion
    self._simulate_processing(packet)
    
    # Record metrics
    self.metrics.record_received(packet)
    
    # Send ACK if reliable
    if packet.header.flags & Flags.RELIABLE:
        self._send_ack(packet, addr)
```

---

## 4.2 Cálculo de Latência (em protocol.py)
```python
def mark_received(self):
    """Mark packet as received and calculate latency"""
    self.receive_time = get_current_time_ms()
    self.latency_ms = self.receive_time - self.header.timestamp
    
    # Sanity check
    if self.latency_ms < 0 or self.latency_ms > 60000:
        self.latency_ms = max(0, min(self.latency_ms, 60000))

def is_on_time(self) -> bool:
    """Check if packet arrived before deadline"""
    return self.latency_ms <= self.header.deadline
```

**Latência = receive_time - timestamp**

---

# 📊 5. METRICS.PY - Recolha de Estatísticas

## 5.1 Estatísticas por Prioridade
```python
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
        """Taxa de entrega = recebidos / enviados"""
        if self.total_packets == 0:
            return 0.0
        return self.received_packets / self.total_packets
    
    @property
    def on_time_rate(self) -> float:
        """Taxa de pontualidade = a tempo / recebidos"""
        if self.received_packets == 0:
            return 0.0
        return self.on_time_packets / self.received_packets
    
    @property
    def p95_latency(self) -> float:
        """Percentil 95 da latência - CORRIGIDO ✅"""
        if len(self.latencies) < 20:
            return max(self.latencies) if self.latencies else 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        # Protect against index out of range - CORRIGIDO!
        idx = min(idx, len(sorted_latencies) - 1)
        return sorted_latencies[idx]
```

**Bug anterior:** `int(len * 0.95)` podia retornar índice igual ao tamanho da lista (fora do range).

---

## 5.2 Registo de Métricas
```python
def record_received(self, packet: DTPPacket):
    """Record that a packet was received"""
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
```

---

# 🎯 RESUMO: Fluxo Completo DTP

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT                                    │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   GENERATOR  │───▶│  SCHEDULER   │───▶│   SENDER     │       │
│  │ (cria pkts)  │    │  (heap por   │    │ (envia UDP)  │       │
│  │              │    │  prioridade) │    │              │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│                              │                    │              │
│                              ▼                    │              │
│                    ┌──────────────┐               │              │
│                    │   DEQUEUE    │               │              │
│                    │ - CRITICAL:  │               │              │
│                    │   nunca drop │               │              │
│                    │ - HIGH: 2x   │               │              │
│                    │ - MED/LOW:1x │               │              │
│                    └──────────────┘               │              │
└───────────────────────────────────────────────────┼──────────────┘
                                                    │
                                           UDP/IP   │
                                                    ▼
┌───────────────────────────────────────────────────┼──────────────┐
│                        SERVER                     │              │
│                                                   │              │
│  ┌──────────────┐    ┌──────────────┐    ┌───────▼──────┐       │
│  │   METRICS    │◀───│  PROCESSOR   │◀───│   RECEIVER   │       │
│  │ (estatísticas│    │ (verifica    │    │ (recebe UDP) │       │
│  │  latência)   │    │  deadline)   │    │              │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

---

# ✅ RESULTADOS ESPERADOS

| Métrica | DTP | UDP FIFO |
|---------|-----|----------|
| CRITICAL nos primeiros 10 | 10/10 | ~1/10 |
| CRITICAL delivery rate | 100% | ~95% |
| CRITICAL avg latency | <100ms | ~500ms |
| Ordem de envio | Por prioridade | Aleatória |

---

**Documento gerado em:** Dezembro 2025  
**Última atualização:** 5 Dezembro 2025 (correções de bugs críticos)  
**Projeto:** DTP - Deadline-aware Transport Protocol  
**Disciplina:** Redes de Computadores - UBI

---

# 🧪 TESTES DE VERIFICAÇÃO DAS CORREÇÕES

Todos os testes passaram após as correções:

| Teste | Descrição | Resultado |
|-------|-----------|-----------|
| 1 | `now_ms()` usa monotonic | ✅ PASSOU |
| 2 | Sort key com absolute_deadline | ✅ PASSOU |
| 3 | Batch timeout funciona | ✅ PASSOU |
| 4 | Sem busy-loop quando congested | ✅ PASSOU |
| 5 | Prioridade correta (1000 pacotes) | ✅ PASSOU |
| 6 | p95 proteção índice | ✅ PASSOU |
| 7 | MetricsCollector consistente | ✅ PASSOU |

---

# 🆕 6. NOVOS MÓDULOS (Adicionados após crítica)

## 6.1 CLOCK_SYNC.PY - Sincronização de Relógios Distribuídos

Para testes entre máquinas diferentes, é essencial estimar o offset entre relógios.

### Protocolo de 3-Way Handshake:
```python
"""
1. Client envia SYNC_REQ com t1 (timestamp local)
2. Server recebe em t2, responde SYNC_RESP com (t1, t2, t3)
3. Client recebe em t4

offset = ((t2 - t1) + (t3 - t4)) / 2
RTT = (t4 - t1) - (t3 - t2)
"""

@dataclass
class ClockSyncResult:
    offset_ms: float      # Estimated clock offset (local - remote)
    rtt_ms: float         # Round-trip time
    accuracy_ms: float    # Estimated accuracy (RTT/2)
    samples: int          # Number of samples used
    
    def adjust_timestamp(self, remote_ts: int) -> int:
        """Adjust a remote timestamp to local time"""
        return int(remote_ts + self.offset_ms)
```

### Uso:
```python
from src.clock_sync import ClockSyncServer, ClockSyncClient, sync_with_server

# No servidor
server = ClockSyncServer(port=4434)
server.start()

# No cliente
result = sync_with_server("192.168.1.10", port=4434, samples=5)
# result.offset_ms = diferença de relógio estimada
```

---

## 6.2 RATE_CONTROL.PY - Controlo de Taxa e Admissão

### 6.2.1 Token Bucket
```python
class TokenBucket:
    """
    Rate limiter que permite bursts até 'burst' size,
    com taxa sustentada de 'rate' tokens/sec.
    """
    
    def __init__(self, rate: float, burst: int):
        self.rate = rate    # Tokens por segundo
        self.burst = burst  # Capacidade máxima
        self._tokens = burst
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Tenta consumir tokens. Retorna True se sucesso.
        """
        self._refill()  # Adiciona tokens baseado no tempo
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False
```

### 6.2.2 Admission Controller (Previne DoS de CRITICAL)
```python
class AdmissionController:
    """
    Controlo de admissão por prioridade com token buckets.
    
    Limites padrão:
    - CRITICAL: 50 pkt/s, burst 20 (emergência apenas!)
    - HIGH: 200 pkt/s, burst 50
    - MEDIUM: 500 pkt/s, burst 100
    - LOW: 1000 pkt/s, burst 200
    """
    
    DEFAULT_LIMITS = {
        Priority.CRITICAL: TokenBucketConfig(rate=50, burst=20),
        Priority.HIGH: TokenBucketConfig(rate=200, burst=50),
        Priority.MEDIUM: TokenBucketConfig(rate=500, burst=100),
        Priority.LOW: TokenBucketConfig(rate=1000, burst=200),
    }
    
    def admit(self, priority: Priority) -> bool:
        """Verifica se pacote deve ser admitido"""
        return self._buckets[priority].consume()
```

**Porquê?** Sem isto, um flood de CRITICAL pode causar starvation das outras prioridades.

### 6.2.3 Congestion Controller (AIMD)
```python
class CongestionController:
    """
    Controlo de congestionamento com:
    - Token bucket para pacing (saída suave)
    - Additive Increase on ACK
    - Multiplicative Decrease on loss
    """
    
    def __init__(self,
                 initial_rate: float = 500,      # pkt/s inicial
                 min_rate: float = 50,           # mínimo
                 max_rate: float = 5000,         # máximo
                 additive_increase: float = 10,  # aumento por janela de ACKs
                 multiplicative_decrease: float = 0.5):  # fator de redução
        ...
    
    def on_ack_received(self, count: int = 1):
        """Aumenta taxa gradualmente"""
        # rate += additive_increase
    
    def on_loss_detected(self, count: int = 1):
        """Reduz taxa multiplicativamente"""
        # rate *= (1 - multiplicative_decrease)
```

---

## 6.3 LOGGER.PY - Logging JSONL para Reprodutibilidade

### Formato JSONL (um JSON por linha):
```json
{"type":"sent","ts":123,"seq":1,"pri":"CRITICAL","deadline":500}
{"type":"recv","ts":145,"seq":1,"pri":"CRITICAL","latency":22,"on_time":true}
{"type":"drop","ts":200,"seq":5,"pri":"LOW","reason":"expired"}
```

### Uso:
```python
from src.logger import ExperimentLogger, ExperimentConfig, set_seed

# Seed para reprodutibilidade
set_seed(42)

# Criar logger
with ExperimentLogger("./logs", "exp_001") as logger:
    logger.log_config(config)
    
    for packet in packets:
        logger.log_packet_sent(packet)
        # ... enviar ...
        logger.log_packet_received(packet)
    
    logger.log_summary(metrics.get_stats())

# Ler logs depois
from src.logger import LogReader
reader = LogReader("./logs/exp_001")
stats = reader.compute_statistics()
```

### Ficheiros gerados:
- `config.jsonl` - Parâmetros do experimento
- `events.jsonl` - Eventos por pacote
- `summary.jsonl` - Estatísticas finais

---

## 6.4 Regra de Timestamp para Batching

**Decisão implementada:** O timestamp é definido no momento de **criação do pacote**, NÃO no flush do batch.

**Razão:** Queremos medir a latência total desde que a aplicação criou o pacote até à entrega. Se usássemos timestamp no flush, pacotes que esperaram 50ms no batch buffer pareceriam ter latência 0ms após o flush.

```python
# Em DTPHeader.__post_init__:
if self.timestamp == 0:
    self.timestamp = now_ms()  # Timestamp na CRIAÇÃO
```

---

# 📊 7. SCRIPT DE EXPERIMENTOS

## run_experiments.py

```bash
# Listar cenários disponíveis
python run_experiments.py --list

# Cenários disponíveis:
#   baseline_fifo: Baseline FIFO
#   baseline_dtp: Baseline DTP
#   dtp_no_cc: DTP (EDF + Batching only)
#   dtp_full: DTP + Rate Control
#   dtp_loss_1pct: DTP + 1% Random Loss
#   fifo_loss_1pct: FIFO + 1% Random Loss
#   dtp_burst_loss: DTP + Burst Loss

# Executar um cenário (5 runs, 30 segundos cada)
python run_experiments.py --scenario baseline_dtp --runs 5 --duration 30

# Executar todos os cenários
python run_experiments.py --all --runs 5 --duration 120
```

### Parâmetros fixos (conforme recomendado):
- Packet payload: 512 B
- Queue size: 1000 packets
- Batch size: 10, timeout: 50 ms

### Métricas recolhidas por prioridade:
- `total_sent`, `received`, `dropped_expired`, `on_time_count`
- `on_time_rate = on_time_count / received`
- Latency: p50, p95, p99
- Goodput útil

---

# 📈 RESULTADOS EXPERIMENTAIS (Exemplo)

```
COMPARAÇÃO FIFO vs DTP (1000 pacotes, misturados)
================================================================
Priority   FIFO on_time    DTP on_time     Melhoria  
--------------------------------------------------
CRITICAL         18.0%         100.0%     +82.0%
HIGH             36.7%         100.0%     +63.3%
MEDIUM           81.7%         100.0%     +18.3%
LOW             100.0%         100.0%      +0.0%
```

**Conclusão:** DTP melhora drasticamente a pontualidade de CRITICAL (+82%) e HIGH (+63%) em comparação com FIFO.

---

**Última atualização:** 5 Dezembro 2025  
**Novos módulos:** clock_sync.py, rate_control.py, logger.py, run_experiments.py
