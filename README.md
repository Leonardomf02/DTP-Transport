# DTP - Deadline-aware Transport Protocol

Protocolo de transporte com suporte a prioridades e deadlines para tráfego sensível a latência.

## 🎯 Problema que Resolve

Em aplicações modernas (VR, gaming, telemedicina, carros autónomos), diferentes tipos de tráfego têm requisitos diferentes:

- **Mensagens críticas** (alarmes, controlo) → devem chegar em < 500ms
- **Tráfego real-time** (vídeo, gaming) → deadline de ~1500ms
- **Streaming** → tolerância de ~3000ms
- **Bulk data** (logs, sync) → pode esperar até 6 segundos

UDP tradicional trata todos os pacotes igual. O DTP adiciona:

- **Priorização** - Pacotes importantes passam à frente (EDF scheduling)
- **Deadlines** - Pacotes expirados são descartados (não congestionam)
- **Batching** - Tráfego low-priority é agrupado (batch_size=10, timeout=50ms)
- **Adaptação** - Taxa de envio ajusta-se à congestão (AIMD)

## 📁 Estrutura

```
DTP-Transport/
├── backend/
│   ├── src/
│   │   ├── protocol.py     # Header DTP, serialização binária
│   │   ├── scheduler.py    # DTPScheduler (EDF) + SimpleScheduler (FIFO)
│   │   ├── server.py       # Servidor UDP
│   │   ├── client.py       # Cliente com tráfego misto
│   │   ├── simulation.py   # Motor de simulação
│   │   ├── metrics.py      # Coleta de estatísticas
│   │   ├── rate_control.py # Token bucket, AIMD, Pacer
│   │   ├── clock_sync.py   # Sincronização de relógios
│   │   └── logger.py       # Logging estruturado JSONL
│   ├── api.py              # FastAPI + WebSocket
│   ├── run_all_tests.py    # Suite de testes comparativos
│   └── tests/
├── frontend/
│   └── src/
│       ├── App.jsx         # Dashboard React
│       └── App.css
└── start.sh
```

## 🚀 Quick Start

```bash
# 1. Clonar e entrar no diretório
git clone https://github.com/Leonardomf02/DTP-Transport.git
cd DTP-Transport

# 2. Dar permissão ao script
chmod +x start.sh

# 3. Executar testes (DTP vs FIFO)
./start.sh
```

## 📦 Header DTP (24 bytes)

```
 0       1       2       3       4       5       6       7
+-------+-------+-------+-------+-------+-------+-------+-------+
| Magic (0xDEAD)|  Ver  | Type  |  Pri  | Flags |    Sequence   |
+-------+-------+-------+-------+-------+-------+-------+-------+
|                      Timestamp (64 bits)                      |
+-------+-------+-------+-------+-------+-------+-------+-------+
|            Deadline (32 bits)           |    Payload Length   |
+-------+-------+-------+-------+-------+-------+-------+-------+
|   Batch ID    |                    Payload ...                |
+-------+-------+-------+-------+-------+-------+-------+-------+
```

### Prioridades

| Nível | Nome | Deadline Default | Uso |
|-------|------|------------------|-----|
| 0 | CRITICAL | 500ms | Alarmes, controlo |
| 1 | HIGH | 1500ms | Real-time, gaming |
| 2 | MEDIUM | 3000ms | Streaming |
| 3 | LOW | 6000ms | Logs, sync, bulk |

## 📈 Resultados Experimentais

Comparação DTP vs FIFO (200 pacotes, seed=42):

| Prioridade | FIFO On-Time | DTP On-Time | Melhoria |
|------------|--------------|-------------|----------|
| CRITICAL   | 20.0%        | 100.0%      | **+80.0%** |
| HIGH       | 36.7%        | 100.0%      | **+63.3%** |
| MEDIUM     | 65.0%        | 100.0%      | **+35.0%** |
| LOW        | 100.0%       | 100.0%      | 0.0% |

O DTP consegue **100% on-time delivery** para todas as prioridades através do scheduling EDF (Earliest Deadline First).

## 🛠️ Tech Stack

- **Backend**: Python 3.10+, FastAPI, UDP sockets, heapq
- **Frontend**: React 18, Vite, Recharts
- **Comunicação**: WebSocket para métricas em tempo real

## 📚 Referências

- Shi, Y., et al. (2019). *Deadline-Aware Transport in Datacenters*. APNet.
- Hong, C. Y., et al. (2012). *Finishing Flows Quickly with Preemptive Scheduling*. SIGCOMM.
- Liu, C. L., & Layland, J. W. (1973). *Scheduling Algorithms for Multiprogramming*. JACM.
- RFC 9000 — QUIC: A UDP-Based Multiplexed and Secure Transport.
- RFC 8289 — Controlled Delay Active Queue Management.

---

**Arquiteturas Avançadas de Redes | UBI 2025/2026**
