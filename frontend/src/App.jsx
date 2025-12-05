import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, BarChart, Bar, PieChart, Pie, Cell, AreaChart, Area
} from 'recharts';
import './App.css';

// Priority colors
const PRIORITY_COLORS = {
  CRITICAL: '#ef4444',
  HIGH: '#f97316',
  MEDIUM: '#eab308',
  LOW: '#22c55e'
};

// Priority deadlines (match backend protocol.py)
const PRIORITY_DEADLINES = {
  CRITICAL: 500,
  HIGH: 1500,
  MEDIUM: 3000,
  LOW: 6000
};

// API URL
const API_BASE = '';

function App() {
  // State
  const [connected, setConnected] = useState(false);
  const [simulationState, setSimulationState] = useState('idle');
  const [mode, setMode] = useState('dtp');
  const [metrics, setMetrics] = useState(null);
  const [comparison, setComparison] = useState({ dtp: null, udp_raw: null });
  const [events, setEvents] = useState([]);
  const [config, setConfig] = useState({
    critical_count: 50,
    high_count: 200,
    medium_count: 500,
    low_count: 1000,
    simulate_congestion: true,
    congestion_level: 0.3
  });
  
  // Test results history
  const [testHistory, setTestHistory] = useState([]);
  const [showTestPanel, setShowTestPanel] = useState(false);

  // WebSocket ref
  const wsRef = useRef(null);
  const eventsEndRef = useRef(null);

  // Connect WebSocket
  useEffect(() => {
    const connectWs = () => {
      const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;
      const ws = new WebSocket(wsUrl);
      
      ws.onopen = () => {
        console.log('WebSocket connected');
        setConnected(true);
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'metrics') {
            setMetrics(data.data);
            setSimulationState(data.data.state || 'idle');
            if (data.data.events) {
              setEvents(data.data.events.slice(-20));
            }
            
            // Record test result when simulation completes
            if (data.data.state === 'completed' && data.data.stats) {
              const result = {
                timestamp: new Date().toLocaleTimeString(),
                mode: data.data.mode,
                stats: data.data.stats,
                summary: data.data.stats.by_priority
              };
              setTestHistory(prev => [...prev.slice(-9), result]);
            }
          }
        } catch (e) {
          console.error('WS parse error:', e);
        }
      };
      
      ws.onclose = () => {
        console.log('WebSocket disconnected');
        setConnected(false);
        setTimeout(connectWs, 2000);
      };
      
      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
      };
      
      wsRef.current = ws;
    };
    
    connectWs();
    
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  // Auto-scroll events
  useEffect(() => {
    if (eventsEndRef.current) {
      const container = eventsEndRef.current.parentElement;
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    }
  }, [events]);

  // API calls
  const startSimulation = async () => {
    try {
      const response = await fetch(`${API_BASE}/simulation/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...config, mode })
      });
      const data = await response.json();
      console.log('Started:', data);
    } catch (error) {
      console.error('Start error:', error);
    }
  };

  const stopSimulation = async () => {
    try {
      await fetch(`${API_BASE}/simulation/stop`, { method: 'POST' });
    } catch (error) {
      console.error('Stop error:', error);
    }
  };

  const pauseSimulation = async () => {
    try {
      await fetch(`${API_BASE}/simulation/pause`, { method: 'POST' });
    } catch (error) {
      console.error('Pause error:', error);
    }
  };

  const resumeSimulation = async () => {
    try {
      await fetch(`${API_BASE}/simulation/resume`, { method: 'POST' });
    } catch (error) {
      console.error('Resume error:', error);
    }
  };

  const fetchComparison = async () => {
    try {
      const response = await fetch(`${API_BASE}/comparison`);
      const data = await response.json();
      setComparison(data);
    } catch (error) {
      console.error('Comparison error:', error);
    }
  };

  const clearComparison = async () => {
    try {
      await fetch(`${API_BASE}/comparison/clear`, { method: 'POST' });
      setComparison({ dtp: null, udp_raw: null });
      setTestHistory([]);
    } catch (error) {
      console.error('Clear error:', error);
    }
  };

  const startSimulationWithMode = async (selectedMode) => {
    try {
      const response = await fetch(`${API_BASE}/simulation/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...config, mode: selectedMode })
      });
      const data = await response.json();
      console.log('Started:', data);
    } catch (error) {
      console.error('Start error:', error);
    }
  };

  // Format latency data for chart
  const formatLatencyData = () => {
    if (!metrics?.latency_data) return [];
    
    const allTimes = new Set();
    Object.values(metrics.latency_data).forEach(data => {
      data.forEach(([time]) => allTimes.add(time));
    });
    
    const sortedTimes = Array.from(allTimes).sort((a, b) => a - b).slice(-50);
    
    return sortedTimes.map(time => {
      const point = { time: Math.round(time / 1000) };
      Object.entries(metrics.latency_data).forEach(([priority, data]) => {
        const match = data.find(([t]) => t === time);
        if (match) {
          point[priority] = match[1];
        }
      });
      return point;
    });
  };

  // Format stats for bar chart
  const formatStatsData = () => {
    if (!metrics?.stats?.by_priority) return [];
    
    return Object.entries(metrics.stats.by_priority).map(([priority, stats]) => ({
      priority,
      avg_latency: stats.avg_latency_ms,
      on_time_rate: stats.on_time_rate,
      deadline: PRIORITY_DEADLINES[priority],
      color: PRIORITY_COLORS[priority]
    }));
  };

  // Get priority emoji
  const getPriorityEmoji = (priority) => {
    const emojis = {
      CRITICAL: '🔴',
      HIGH: '🟠',
      MEDIUM: '🟡',
      LOW: '🟢'
    };
    return emojis[priority] || '⚪';
  };

  // Calculate test verdicts
  const getTestVerdicts = () => {
    const verdicts = {
      priorityOrdering: { pass: false, details: '' },
      deadlineCompliance: { pass: false, details: '' },
      dtpImprovement: { pass: false, details: '' }
    };

    if (!metrics?.stats?.by_priority) return verdicts;

    const stats = metrics.stats.by_priority;
    
    // Test 1: Priority Ordering - CRITICAL should have lowest latency
    const latencies = {
      CRITICAL: stats.CRITICAL?.avg_latency_ms || 0,
      HIGH: stats.HIGH?.avg_latency_ms || 0,
      MEDIUM: stats.MEDIUM?.avg_latency_ms || 0,
      LOW: stats.LOW?.avg_latency_ms || 0
    };
    
    const priorityOrderCorrect = 
      latencies.CRITICAL <= latencies.HIGH &&
      latencies.HIGH <= latencies.MEDIUM &&
      latencies.MEDIUM <= latencies.LOW;
    
    verdicts.priorityOrdering = {
      pass: priorityOrderCorrect,
      details: `CRITICAL(${latencies.CRITICAL.toFixed(0)}ms) ≤ HIGH(${latencies.HIGH.toFixed(0)}ms) ≤ MEDIUM(${latencies.MEDIUM.toFixed(0)}ms) ≤ LOW(${latencies.LOW.toFixed(0)}ms)`
    };

    // Test 2: Deadline Compliance - CRITICAL should have >90% on-time
    const criticalOnTime = stats.CRITICAL?.on_time_rate || 0;
    const highOnTime = stats.HIGH?.on_time_rate || 0;
    
    verdicts.deadlineCompliance = {
      pass: criticalOnTime >= 90 && highOnTime >= 80,
      details: `CRITICAL: ${criticalOnTime.toFixed(1)}% on-time, HIGH: ${highOnTime.toFixed(1)}% on-time`
    };

    // Test 3: DTP Improvement (need comparison data)
    if (comparison.dtp?.summary && comparison.udp_raw?.summary) {
      const dtpCritical = comparison.dtp.summary.CRITICAL?.on_time_rate || 0;
      const udpCritical = comparison.udp_raw.summary.CRITICAL?.on_time_rate || 0;
      const improvement = dtpCritical - udpCritical;
      
      verdicts.dtpImprovement = {
        pass: improvement > 10,
        details: `DTP: ${dtpCritical.toFixed(1)}% vs FIFO: ${udpCritical.toFixed(1)}% (+${improvement.toFixed(1)}%)`
      };
    }

    return verdicts;
  };

  const verdicts = getTestVerdicts();

  // Get client/server info
  const clientInfo = metrics?.client || {};
  const serverInfo = metrics?.server || {};
  const progress = clientInfo.progress || 0;
  const queueSize = clientInfo.queue_size || 0;
  const congestionLevel = serverInfo.congestion_level || 0;

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-title">
          <h1>🚀 DTP - Deadline-aware Transport Protocol</h1>
          <span className={`status-badge ${connected ? 'connected' : 'disconnected'}`}>
            {connected ? '● Connected' : '○ Disconnected'}
          </span>
        </div>
        <p className="header-subtitle">Simulação de Tráfego com Prioridades e Deadlines</p>
      </header>

      {/* Progress Bar */}
      {simulationState !== 'idle' && (
        <div className="progress-section">
          <div className="progress-info">
            <span className="progress-label">
              {simulationState === 'running' ? '🔄 A executar...' : 
               simulationState === 'paused' ? '⏸️ Pausado' : 
               simulationState === 'completed' ? '✅ Concluído' : ''}
            </span>
            <span className="progress-stats">
              Modo: <strong>{mode === 'dtp' ? '🟢 DTP' : '🔴 FIFO'}</strong> | 
              Progresso: <strong>{progress}%</strong> | 
              Fila: <strong>{queueSize}</strong> | 
              Congestão: <strong>{(congestionLevel * 100).toFixed(0)}%</strong>
            </span>
          </div>
          <div className="progress-bar">
            <div 
              className={`progress-fill ${simulationState}`} 
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Controls */}
      <section className="controls">
        <div className="control-group">
          <label>Modo:</label>
          <select value={mode} onChange={(e) => setMode(e.target.value)} disabled={simulationState === 'running'}>
            <option value="dtp">🟢 COM DTP (Deadline-aware)</option>
            <option value="udp_raw">🔴 SEM DTP (FIFO Puro)</option>
          </select>
        </div>

        <div className="control-group">
          <label>Congestão:</label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={config.congestion_level}
            onChange={(e) => setConfig({ ...config, congestion_level: parseFloat(e.target.value) })}
            disabled={simulationState === 'running'}
          />
          <span>{Math.round(config.congestion_level * 100)}%</span>
        </div>

        <div className="button-group">
          <button 
            className="btn btn-start" 
            onClick={startSimulation}
            disabled={simulationState === 'running'}
          >
            ▶️ Iniciar
          </button>
          <button 
            className="btn btn-stop" 
            onClick={stopSimulation}
            disabled={simulationState === 'idle'}
          >
            ⏹️ Parar
          </button>
          <button 
            className="btn btn-pause" 
            onClick={pauseSimulation}
            disabled={simulationState !== 'running'}
          >
            ⏸️ Pausar
          </button>
          <button 
            className="btn btn-resume" 
            onClick={resumeSimulation}
            disabled={simulationState !== 'paused'}
          >
            ▶️ Retomar
          </button>
          <button 
            className="btn btn-compare" 
            onClick={fetchComparison}
          >
            📊 Ver Comparação
          </button>
          <button 
            className="btn btn-clear" 
            onClick={clearComparison}
          >
            🗑️ Limpar
          </button>
          <button 
            className="btn btn-test" 
            onClick={() => setShowTestPanel(!showTestPanel)}
          >
            🧪 {showTestPanel ? 'Ocultar' : 'Ver'} Testes
          </button>
        </div>
      </section>

      {/* Test Panel */}
      {showTestPanel && (
        <section className="test-panel">
          <h2>🧪 Painel de Testes - Validação do Protocolo DTP</h2>
          
          <div className="test-grid">
            {/* Test 1: Priority Ordering */}
            <div className={`test-card ${verdicts.priorityOrdering.pass ? 'pass' : 'fail'}`}>
              <div className="test-header">
                <span className="test-icon">{verdicts.priorityOrdering.pass ? '✅' : '❌'}</span>
                <h3>Teste 1: Priority Ordering (EDF)</h3>
              </div>
              <p className="test-description">
                Verifica se pacotes CRITICAL têm menor latência que HIGH, que por sua vez tem menor que MEDIUM, etc.
              </p>
              <div className="test-result">
                <code>{verdicts.priorityOrdering.details || 'Aguardando dados...'}</code>
              </div>
              <div className="test-status">
                {verdicts.priorityOrdering.pass ? 
                  '✓ Prioridades respeitadas - EDF funcionando!' : 
                  '✗ Ordem de prioridades não respeitada'}
              </div>
            </div>

            {/* Test 2: Deadline Compliance */}
            <div className={`test-card ${verdicts.deadlineCompliance.pass ? 'pass' : 'fail'}`}>
              <div className="test-header">
                <span className="test-icon">{verdicts.deadlineCompliance.pass ? '✅' : '❌'}</span>
                <h3>Teste 2: Deadline Compliance</h3>
              </div>
              <p className="test-description">
                CRITICAL deve ter ≥90% de entregas no prazo. HIGH deve ter ≥80%.
              </p>
              <div className="test-result">
                <code>{verdicts.deadlineCompliance.details || 'Aguardando dados...'}</code>
              </div>
              <div className="test-status">
                {verdicts.deadlineCompliance.pass ? 
                  '✓ Deadlines cumpridos adequadamente!' : 
                  '✗ Deadlines não cumpridos'}
              </div>
            </div>

            {/* Test 3: DTP vs FIFO */}
            <div className={`test-card ${verdicts.dtpImprovement.pass ? 'pass' : 'pending'}`}>
              <div className="test-header">
                <span className="test-icon">{verdicts.dtpImprovement.pass ? '✅' : '⏳'}</span>
                <h3>Teste 3: DTP vs FIFO</h3>
              </div>
              <p className="test-description">
                DTP deve melhorar em ≥10% a taxa de entrega no prazo vs FIFO puro.
              </p>
              <div className="test-result">
                <code>{verdicts.dtpImprovement.details || 'Execute simulações com DTP e FIFO para comparar'}</code>
              </div>
              <div className="test-status">
                {verdicts.dtpImprovement.pass ? 
                  '✓ DTP demonstra melhoria significativa!' : 
                  '⏳ Execute ambos os modos para comparar'}
              </div>
            </div>
          </div>

          {/* Deadline Reference */}
          <div className="deadline-reference">
            <h4>📋 Deadlines por Prioridade (Referência)</h4>
            <div className="deadline-grid">
              {Object.entries(PRIORITY_DEADLINES).map(([pri, deadline]) => (
                <div key={pri} className="deadline-item">
                  <span className="deadline-emoji">{getPriorityEmoji(pri)}</span>
                  <span className="deadline-name">{pri}</span>
                  <span className="deadline-value">{deadline}ms</span>
                </div>
              ))}
            </div>
          </div>

          {/* Test History */}
          {testHistory.length > 0 && (
            <div className="test-history">
              <h4>📜 Histórico de Testes</h4>
              <div className="history-list">
                {testHistory.map((test, idx) => (
                  <div key={idx} className={`history-item ${test.mode}`}>
                    <span className="history-time">{test.timestamp}</span>
                    <span className="history-mode">
                      {test.mode === 'dtp' ? '🟢 DTP' : '🔴 FIFO'}
                    </span>
                    <span className="history-stat">
                      CRITICAL: {test.summary?.CRITICAL?.on_time_rate?.toFixed(1) || 0}%
                    </span>
                    <span className="history-stat">
                      Total: {test.stats?.total?.on_time_rate?.toFixed(1) || 0}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Main Grid */}
      <main className="main-grid">
        {/* Latency Chart */}
        <section className="card latency-chart">
          <h2>📈 Latência por Prioridade (ms)</h2>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={formatLatencyData()}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="time" stroke="#888" label={{ value: 'Tempo (s)', position: 'bottom' }} />
              <YAxis stroke="#888" label={{ value: 'ms', angle: -90, position: 'left' }} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#1a1a2e', border: '1px solid #333' }}
                labelStyle={{ color: '#fff' }}
              />
              <Legend />
              {Object.entries(PRIORITY_COLORS).map(([priority, color]) => (
                <Line 
                  key={priority}
                  type="monotone" 
                  dataKey={priority} 
                  stroke={color}
                  strokeWidth={2}
                  dot={false}
                  name={`${getPriorityEmoji(priority)} ${priority} (${PRIORITY_DEADLINES[priority]}ms)`}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </section>

        {/* Stats Overview */}
        <section className="card stats-overview">
          <h2>📊 Estatísticas</h2>
          {metrics?.stats ? (
            <div className="stats-grid">
              <div className="stat-box">
                <span className="stat-label">Throughput</span>
                <span className="stat-value">{metrics.stats.throughput || 0} pkt/s</span>
              </div>
              <div className="stat-box">
                <span className="stat-label">Total Enviados</span>
                <span className="stat-value">{metrics.stats.total?.sent || 0}</span>
              </div>
              <div className="stat-box">
                <span className="stat-label">Total Recebidos</span>
                <span className="stat-value">{metrics.stats.total?.received || 0}</span>
              </div>
              <div className="stat-box highlight">
                <span className="stat-label">% No Prazo</span>
                <span className="stat-value">{metrics.stats.total?.on_time_rate || 0}%</span>
              </div>
            </div>
          ) : (
            <p className="no-data">Aguardando dados...</p>
          )}
        </section>

        {/* Priority Stats - Latency vs Deadline */}
        <section className="card priority-stats">
          <h2>⏱️ Latência vs Deadline</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={formatStatsData()} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis type="number" stroke="#888" />
              <YAxis type="category" dataKey="priority" stroke="#888" width={80} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#1a1a2e', border: '1px solid #333' }}
                formatter={(value, name) => {
                  if (name === 'avg_latency') return [`${value.toFixed(1)} ms`, 'Latência Média'];
                  if (name === 'deadline') return [`${value} ms`, 'Deadline'];
                  return [value, name];
                }}
              />
              <Legend />
              <Bar dataKey="avg_latency" fill="#4f46e5" name="Latência Média">
                {formatStatsData().map((entry, index) => (
                  <Cell key={index} fill={entry.color} />
                ))}
              </Bar>
              <Bar dataKey="deadline" fill="#666" name="Deadline" opacity={0.3} />
            </BarChart>
          </ResponsiveContainer>
        </section>

        {/* On-Time Rate */}
        <section className="card ontime-stats">
          <h2>✅ Taxa de Entrega no Prazo</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={formatStatsData()} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis type="number" domain={[0, 100]} stroke="#888" />
              <YAxis type="category" dataKey="priority" stroke="#888" width={80} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#1a1a2e', border: '1px solid #333' }}
                formatter={(value) => [`${value.toFixed(1)}%`, 'No Prazo']}
              />
              <Bar dataKey="on_time_rate" fill="#22c55e">
                {formatStatsData().map((entry, index) => (
                  <Cell key={index} fill={entry.on_time_rate >= 80 ? '#22c55e' : entry.on_time_rate >= 50 ? '#eab308' : '#ef4444'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </section>

        {/* Event Log */}
        <section className="card event-log">
          <h2>📜 Event Log</h2>
          <div className="events-container">
            {events.length > 0 ? (
              events.map((event, index) => (
                <div key={index} className={`event-item ${event.type}`}>
                  <span className="event-time">{(event.time / 1000).toFixed(2)}s</span>
                  <span className={`event-priority priority-${event.priority?.toLowerCase()}`}>
                    {event.priority && getPriorityEmoji(event.priority)}
                  </span>
                  <span className="event-type">{event.type}</span>
                  {event.sequence && <span className="event-seq">seq={event.sequence}</span>}
                  {event.latency && <span className="event-latency">{event.latency}ms</span>}
                  {event.reason && <span className="event-reason">({event.reason})</span>}
                </div>
              ))
            ) : (
              <p className="no-data">Nenhum evento ainda...</p>
            )}
            <div ref={eventsEndRef} />
          </div>
        </section>

        {/* Recent Packets */}
        <section className="card recent-packets">
          <h2>📦 Pacotes Recentes</h2>
          <div className="packets-table">
            <div className="packets-header">
              <span>Pri</span>
              <span>Seq</span>
              <span>Latência</span>
              <span>Deadline</span>
              <span>Status</span>
            </div>
            {metrics?.recent_packets?.map((packet, index) => (
              <div key={index} className={`packet-row ${packet.on_time ? 'on-time' : 'late'}`}>
                <span>{getPriorityEmoji(packet.priority)}</span>
                <span>{packet.sequence}</span>
                <span>{packet.latency}ms</span>
                <span>{packet.deadline}ms</span>
                <span>{packet.on_time ? '✓' : '⚠️'}</span>
              </div>
            ))}
          </div>
        </section>
      </main>

      {/* Comparison Section */}
      {(comparison.dtp || comparison.udp_raw) && (
        <section className="comparison-section">
          <h2>🆚 Comparação: DTP vs FIFO Puro</h2>
          <div className="comparison-grid">
            {/* DTP Results */}
            <div className="comparison-card dtp">
              <h3>🟢 COM DTP (Deadline-aware)</h3>
              {comparison.dtp?.summary ? (
                <div className="comparison-stats">
                  {Object.entries(comparison.dtp.summary).map(([priority, stats]) => (
                    <div key={priority} className="comparison-row">
                      <span>{getPriorityEmoji(priority)} {priority}</span>
                      <span>{stats.avg_latency}ms avg</span>
                      <span className={stats.on_time_rate >= 80 ? 'good' : stats.on_time_rate >= 50 ? 'warn' : 'bad'}>
                        {stats.on_time_rate}% ✓
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="no-data">Execute simulação com DTP</p>
              )}
            </div>

            {/* UDP Results */}
            <div className="comparison-card udp">
              <h3>🔴 SEM DTP (FIFO Puro)</h3>
              {comparison.udp_raw?.summary ? (
                <div className="comparison-stats">
                  {Object.entries(comparison.udp_raw.summary).map(([priority, stats]) => (
                    <div key={priority} className="comparison-row">
                      <span>{getPriorityEmoji(priority)} {priority}</span>
                      <span>{stats.avg_latency}ms avg</span>
                      <span className={stats.on_time_rate >= 80 ? 'good' : stats.on_time_rate >= 50 ? 'warn' : 'bad'}>
                        {stats.on_time_rate}% ✓
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="no-data">Execute simulação com FIFO Puro</p>
              )}
            </div>
          </div>

          {/* Improvement Summary */}
          {comparison.dtp?.summary && comparison.udp_raw?.summary && (
            <div className="improvement-summary">
              <h4>📈 Melhoria com DTP</h4>
              <div className="improvement-grid">
                {Object.keys(comparison.dtp.summary).map(priority => {
                  const dtpRate = comparison.dtp.summary[priority]?.on_time_rate || 0;
                  const udpRate = comparison.udp_raw.summary[priority]?.on_time_rate || 0;
                  const improvement = dtpRate - udpRate;
                  return (
                    <div key={priority} className={`improvement-item ${improvement > 0 ? 'positive' : 'negative'}`}>
                      <span>{getPriorityEmoji(priority)} {priority}</span>
                      <span className="improvement-value">
                        {improvement > 0 ? '+' : ''}{improvement.toFixed(1)}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Footer */}
      <footer className="footer">
        <p>DTP - Deadline-aware Transport Protocol | Arquiteturas Avançadas de Redes | UBI 2025</p>
      </footer>
    </div>
  );
}

export default App;
