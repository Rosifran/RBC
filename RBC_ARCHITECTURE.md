# RBC — Risk Bridge Capital | Architecture v1.0
_Atualizado: 2026-06-09_

---

## Infraestrutura

| Componente | Detalhe |
|---|---|
| Scanner EUA | `~/RBC/rbc_0dte_scanner.py` v1.5-beta |
| App EUA | `https://web-production-00b33.up.railway.app` |
| GitHub EUA | `github.com/Rosifran/RBC` |
| Scanner Brasil | `~/RBC-Brasil/rbc_br_scanner.py` v2.1 |
| App Brasil | `https://web-production-c928f.up.railway.app` |
| GitHub Brasil | repositório separado (RBC-Brasil) |
| Banco de dados | PostgreSQL Railway (captivating-tenderness) |
| Dados mercado | TradingView webhooks → `/api/tv/quote` → PostgreSQL |

---

## Capital

- **$47k** SGOV (IBKR) → ~$204/mês
- **$3k** cash 0DTE EUA
- **R$2.750** Brasil

---

## Fluxo diário EUA

```
Manhã     → Modo 1: upload PDF SpotGamma → extrai níveis + regime
9:45      → Modo 2: VIX + SPY (botão TradingView) → decisão
10:00     → Modo 3: strike + prêmio + execução
16:01     → TradingView webhook → OHLC automático no journal
Tarde     → PM Note PDF → Journal Modo 4
```

---

## Arquitetura dos Modos EUA

### Modo 1 — Pré-mercado
- **Input:** PDF SpotGamma
- **Output:** níveis extraídos via Claude API → JSON
- **Campos:** `reference_price`, `vol_trigger`, `zero_gamma`, `call_wall`, `put_wall`, `combos`, `spy_levels`, `founder_alerts`, `key_events`
- **Regra:** LLM só extrai níveis. Python decide o plano.
- **Regime:** `reference_price < vol_trigger` → `NEGATIVE_GAMMA`

### Modo 2 — Abertura
- **Input:** SPY agora, VIX agora (manual ou botão TradingView)
- **Output:** decisão operacional + cockpit de acompanhamento
- **Decisões possíveis:** `CALL REVERSAL`, `PUT REVERSAL`, `CALL BREAKOUT SMALL`, `PUT TREND`, `NO TRADE`
- **Chase warning:** ativo se SPY já distante do nível-chave → oculta plano e strikes
- **Bloco "Próximo Setup":** sempre presente — CALL/PUT/NO TRADE/NÍVEL-CHAVE/INVALIDAÇÃO
- **Alvos PUT TREND:** só combos/spy_levels abaixo do spot, dentro de 8 pts. Put Wall = nota de suporte extremo, nunca alvo.

### Modo 3 — Operacional
- **Input:** herda decisão do Modo 2 automaticamente
- **Campos manuais:** prêmio, strike, horário de entrada
- **Output:** checklist de execução — strike sugerido ATM/ideal/OTM, alvo +75%, stop -50%, saída 12:30 ET

### Modo 4 — Journal
- **Input:** TradingView webhook (OHLC automático às 16:01 ET) + PM Note PDF
- **Tabela:** `trade_journal` (PostgreSQL)

### Modo 5 — Swing
Modo 5 — Swing (atualizado 2026-06-10)

- Input: scanner IBKR local (us_swing_ibkr.py)
- Universo: NVDA, AAPL, META, AMZN, AMD, UBER, PLTR, SOFI, BAC, XLF, QQQ, SPY
- Camada Capital Fit (capital_fit_engine.py v1.4): classifica cada contrato
  por adequação ao capital (1 contrato, custo ideal $150-350, stop -35%,
  risco máx $250). Buckets: IDEAL_FOR_ONE_CONTRACT / ACCEPTABLE / CHEAP_SLOW /
  EXPENSIVE / BETTER_AS_SPREAD / REPROVO / DADOS_INSUFICIENTES (WAIT).
  OI=0 do feed = ausente; liquidez não confirmada rebaixa, não reprova.
- Output: terminal (bloco abaixo do Score detalhe) + swing_scans (PostgreSQL,
  capital_fit dentro de contracts/raw) + dashboard compacto no app
  (linha-resumo por ticker/direção, melhor contrato por capital fit,
  detalhes expandem no clique)
- Patches: patch_capital_fit.py, patch_capital_fit_v2.py,
  patch_modo5_universe_layout.py

---

## Tabelas PostgreSQL

### `trade_journal`
Journal diário de trades EUA. Campos principais:
`date`, `call_wall`, `put_wall`, `vol_trigger`, `zero_gamma`, `c3`, `c4`, `c1`, `open_spy`, `close_spy`, `modo2_decision`, `entry_level`, `target_1`, `target_2`, `stop_level`, `trade_path`, `pm_note_summary`, `pm_hiro`, `pm_vix_close`, `pm_cor1m_close`

### `market_quotes`
Quote intraday SPY e VIX via TradingView (1 min).
`symbol VARCHAR(10) PRIMARY KEY`, `price NUMERIC(10,4)`, `tv_time TIMESTAMP`, `received_at TIMESTAMP`
Fresh = `received_at` < 30 min atrás.

### `swing_scans`
Resultados do scanner Modo 5.

---

## TradingView Webhooks

| Alerta | Frequência | Payload |
|---|---|---|
| RBC Quote — SPY | 1 min | `{"symbol":"SPY","price":"{{close}}","time":"{{time}}"}` |
| RBC Quote — VIX | 1 min | `{"symbol":"VIX","price":"{{close}}","time":"{{time}}"}` |
| RBC Close Day | 1D | `{"event":"close_day","date":"...","open":...,"high":...,"low":...,"close":...}` |

URL webhook: `https://web-production-00b33.up.railway.app/api/tv/quote`

---

## Lógica 0DTE EUA (Codex RBC)

```
Regime    → SPY vs Vol Trigger
           ref_price < vol_trigger → NEGATIVE_GAMMA (frágil)
           ref_price >= vol_trigger → POSITIVE_GAMMA (sustentado)

NEGATIVE GAMMA:
  CALL    → reclaim de VT/ZG com aceitação. Alvo: Call Wall.
  PUT     → rejeição de VT ou aceitação abaixo. Alvos: combos próximos.
  NO TRADE → SPY entre referência e VT sem direção clara.

POSITIVE GAMMA:
  CALL REVERSAL  → SPY perto do Vol Trigger (piso)
  PUT REVERSAL   → SPY perto da Call Wall (teto)
  CALL BREAKOUT  → SPY acima do C4, abaixo da Call Wall
  NO TRADE       → meio da faixa

Timing  → 9:30 observa | 9:45-10:00 entra | 12:30 sai obrigatório
Prêmio  → alvo +75% | stop -50%
Gate emocional → evento importante no dia → não opera
Chase warning → movimento já aconteceu → não perseguir
```

---

## Scanner Brasil v2.1

- **Ativos:** PETR4, VALE3, BOVA11, PRIO3
- **Capital:** R$2.000 (SMALL mode — só compra direta)
- **Estratégia:** tendência curta + média alinhadas → COMPRA CALL ou COMPRA PUT
- **Gates:** IV Rank, DTE (14-35 dias), liquidez, spread, theta, delta
- **Janela:** 10:15–16:30 BRT
- **Vencimento:** 14-35 dias

### Lógica `explain_missing_conditions` (v2.1)
- Se `estrategia_tipo == "REPROVO"` → retorna `🔴 REPROVO` imediatamente (fix 08/06)
- Gate fechado → identifica qual check falhou especificamente (fix 08/06)

---

## Rotas principais app.py (EUA)

| Rota | Método | Função |
|---|---|---|
| `/api/modo1` | POST | Processa PDF SpotGamma |
| `/api/modo2` | POST | Análise de abertura |
| `/api/modo3` | POST | Análise operacional |
| `/api/tv/quote` | POST/GET | Quote SPY/VIX TradingView |
| `/api/webhook` | POST | Eventos TradingView (journal) |
| `/api/parse-pm-pdf` | POST | PM Note PDF → journal |
| `/api/modo5/latest` | GET | Último scan swing |

---

## Patches aplicados (08/06/2026)

| Arquivo | Patch | Descrição |
|---|---|---|
| `rbc_br_scanner.py` | `patch_explain_fix.py` | explain_missing REPROVO early return |
| `app.py` | `patch_modo1_plan.py` | Modo 1 regime-aware NEGATIVE_GAMMA |
| `app.py` | `patch_tv_quote.py` | Endpoint /api/tv/quote (memória) |
| `app.py` | `patch_market_quotes_pg.py` | market_quotes PostgreSQL |
| `app.py` | `patch_put_targets_v2.py` | PUT TREND alvos próximos |
| `app.py` | `patch_next_setup_v2.py` | next_setup cockpit |
| `templates/index.html` | `patch_modo3_form.py` | Modo 3 simplificado |
| `templates/index.html` | `patch_modo2_tv_btn.py` | Botão TradingView Modo 2 |
| `templates/index.html` | `patch_tv_dedup.py` | Remove botão duplicado |
| `templates/index.html` | `patch_put_targets_v2.py` | Chase warning oculta plano/strikes |
| `templates/index.html` | `patch_next_setup_v2.py` | Bloco próximo setup |

---

## Pendências

- [ ] Botão TradingView Modo 2 — "Erro ao buscar" (investigar CORS ou resposta)
- [ ] Plano de Trade ainda aparece com ENTRADA/STOP em chase warning (verificar frontend)
- [ ] `git config --global` — configurar nome/email do committer
- [ ] `.gitignore` — adicionar backups `*_backup_*.py` e `*_backup_*.html`

---

## Como usar este documento em novo chat

```
Cole o resumo do início do chat + este arquivo completo.
Comando para carregar: cat ~/RBC/RBC_ARCHITECTURE.md
O Claude entra direto no nível certo sem mapear o código do zero.
Patches 11/06: patch_ui_layout.py (largura global 860->1280px),
patch_modo2_cockpit.py (Modo 2 cockpit: hero Acao Agora, alertas max 3, accordion).
HIRO/TRACE: Etapa A standalone no repo (flow_context_engine.py); Etapas B/C pausadas — sem acesso ao HIRO/TRACE; Flow Proxy SPY×VIX cobre o papel.
```
