# 🧪 Como Testar o DTP

## TL;DR - Execução Rápida

```bash
cd backend
pip install -r requirements.txt
python run_all_tests.py
```

**Tempo:** ~8 segundos  
**Output esperado:** CRITICAL 18% → 100% (+82% melhoria)

---

## O que é Testado?

Este script (`run_all_tests.py`) executa **3 testes essenciais** que validam o funcionamento core do protocolo:

### ✅ TESTE 1: FIFO vs DTP
**O que valida:** Performance do scheduler DTP vs FIFO tradicional

**Como funciona:**
- Gera 1000 pacotes misturados (50 CRITICAL, 150 HIGH, 300 MEDIUM, 500 LOW)
- Processa com FIFO puro
- Processa com DTP (EDF + batching)
- Compara on-time delivery rates

**Resultado esperado:**
```
Priority     FIFO      DTP       Melhoria
CRITICAL     18.0%     100.0%    +82.0%
HIGH         38.0%     100.0%    +62.0%
MEDIUM       82.0%     100.0%    +18.0%
LOW          100.0%    100.0%    0.0%
```

### ✅ TESTE 2: Priority Ordering
**O que valida:** EDF scheduler funciona corretamente

**Como funciona:**
- Cria 3 pacotes: 2 MEDIUM (diferentes timestamps) e 1 CRITICAL
- Enqueue em ordem aleatória
- Verifica ordem de dequeue

**Resultado esperado:**
- CRITICAL enviado primeiro (prioridade mais alta)
- MEDIUMs enviados por ordem de absolute deadline

### ✅ TESTE 3: Timestamp Consistency
**O que valida:** Sistema de tempo monotónico

**Como funciona:**
- Chama `now_ms()` 3 vezes com delays de 100ms
- Verifica que tempo sempre cresce
- Valida precisão (~±5ms)

**Resultado esperado:**
- t1 ≈ 0ms
- t2 ≈ 102ms (diferença ~100ms)
- t3 ≈ 207ms (diferença ~105ms)

---

## Troubleshooting

### Erro: "ModuleNotFoundError: No module named 'src'"
```bash
# Certifica-te que estás no diretório backend
cd backend
python run_all_tests.py
```

### Erro: "No module named 'dataclasses'"
```bash
# Python versão antiga, atualiza para 3.10+
python3 --version  # Deve ser >= 3.10
```

### Resultados diferentes dos esperados
- Normal pequenas variações (±2%) devido a timing do sistema
- Se CRITICAL < 95% on-time no DTP → problema sério, reporta!

---

## Para a Defesa

**O que dizer:**
> "Implementei 3 testes que validam o protocolo. O principal mostra que o DTP melhora a entrega de pacotes críticos em 82% comparado com FIFO."

**Como demonstrar:**
1. Abre terminal
2. `cd backend && python run_all_tests.py`
3. Aponta para linha: `CRITICAL: 18% → 100% (+82%)`
4. Explica: "FIFO não respeita deadlines, DTP usa EDF para priorizar"

**Tempo total da demo:** ~10 segundos (8s de testes + 2s de explicação)

---

## Arquivos Relevantes

- `run_all_tests.py` - **O ÚNICO script necessário**
- `src/protocol.py` - Formato de pacotes
- `src/scheduler.py` - Implementação EDF
- `src/metrics.py` - Coletor de estatísticas

**NÃO PRECISAS DE:**
- Frontend (React dashboard é opcional)
- API (só para visualização web)
- Docker
- Bases de dados

---

## FAQ

**Q: Preciso de instalar outras coisas?**  
A: Não. Só Python 3.10+ e `pip install -r requirements.txt`

**Q: Funciona no Windows?**  
A: Sim, mas usa PowerShell: `python run_all_tests.py`

**Q: E se quiser ver logs detalhados?**  
A: O script já mostra tudo o que importa. Se quiseres JSONL científicos, existe `run_experiments.py` mas é overkill.

**Q: Quanto tempo demora?**  
A: 8 segundos para os 3 testes completos.

**Q: Posso correr N vezes?**  
A: Sim! O seed=42 garante reprodutibilidade (resultados idênticos).
