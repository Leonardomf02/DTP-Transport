# DTP - Deadline-aware Transport Protocol

Protocolo de transporte com suporte a prioridades e deadlines para tráfego sensível a latência.

## 🎯 Problema que Resolve

Em aplicações modernas (VR, gaming, telemedicina, carros autónomos), diferentes tipos de tráfego têm requisitos diferentes:

- **Mensagens críticas** (alarmes, controlo) → devem chegar em < 50ms
- **Tráfego real-time** (vídeo, gaming) → deadline de ~100ms
- **Streaming** → tolerância de ~250ms
- **Bulk data** (logs, sync) → pode esperar até 1 segundo

UDP tradicional trata todos os pacotes igual. O DTP adiciona:

- **Priorização** - Pacotes importantes passam à frente
- **Deadlines** - Pacotes expirados são descartados (não congestionam)
- **Batching** - Tráfego low-priority é agrupado
- **Adaptação** - Taxa de envio ajusta-se à congestão

## 📁 Estrutura

```
DTP-Transport/
├── backend/
│   ├── src/
│   │   ├── protocol.py   # Header DTP, serialização
│   │   ├── scheduler.py  # Fila deadline-aware
│   │   ├── server.py     # Servidor UDP
│   │   ├── client.py     # Cliente com tráfego misto
│   │   ├── simulation.py # Motor de simulação
│   │   └── metrics.py    # Coleta de métricas
│   ├── api.py            # FastAPI + WebSocket
│   └── tests/
├── frontend/
│   └── src/
│       ├── App.jsx       # Dashboard React
│       └── App.css
├── docs/
│   └── DTP_RFC.md        # Mini-RFC do protocolo
└── start.sh
```

## 🚀 Quick Start

```bash
# 1. Dar permissão ao script
chmod +x start.sh

# 2. Iniciar (backend + frontend)
./start.sh

# 3. Abrir no browser
open http://localhost:5173
```

## 📊 Dashboard

O dashboard mostra em tempo real:

- **Latência por prioridade** - Gráfico de linhas
- **Taxa de entrega no prazo** - Barras por prioridade
- **Throughput** - Pacotes por segundo
- **Event log** - Eventos em tempo real
- **Comparação** - DTP vs UDP Puro lado a lado

## 🎬 Demo

1. **Abrir dashboard** em `http://localhost:5173`
2. **Selecionar modo**: "COM DTP" ou "SEM DTP"
3. **Clicar Iniciar** → vê métricas em tempo real
4. **Repetir com outro modo** para comparar
5. **Ver Comparação** → mostra diferença

## 📦 Header DTP (16 bytes)

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|    Version    |   Priority    |          Sequence Number      |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Timestamp (ms)                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Deadline (ms)                            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          Batch ID             |     Flags     |    Type       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Prioridades

| Nível | Nome | Deadline Default | Uso |
|-------|------|------------------|-----|
| 0 | CRITICAL | 50ms | Alarmes, controlo |
| 1 | HIGH | 100ms | Real-time, gaming |
| 2 | MEDIUM | 250ms | Streaming |
| 3 | LOW | 1000ms | Logs, sync, bulk |

## 📈 Resultados Esperados

| Métrica | Sem DTP | Com DTP | Melhoria |
|---------|---------|---------|----------|
| Latência CRITICAL | ~80ms | ~10ms | **8x** |
| Latência HIGH | ~60ms | ~20ms | **3x** |
| Deadlines cumpridos | ~65% | ~95% | **+30%** |

## 🛠️ Tech Stack

- **Backend**: Python 3.11+, FastAPI, UDP sockets
- **Frontend**: React 18, Vite, Recharts
- **Comunicação**: WebSocket para métricas em tempo real

## 📚 Referências

- RFC 9000 - QUIC (conceitos de deadline)
- "Deadline-Aware Datacenter TCP" (SIGCOMM)
- "pFabric: Minimal Near-Optimal Datacenter Transport"
- "HULL: High bandwidth Ultra-Low Latency"

---

**Arquiteturas Avançadas de Redes | UBI 2025/2026**
