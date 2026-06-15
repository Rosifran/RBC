# RBC — Risk Bridge Capital | Architecture v2.0
_Atualizado: 2026-06-11_

---

## Infraestrutura

| Componente | Detalhe |
|---|---|
| App EUA | `~/RBC/app.py` + `~/RBC/templates/index.html` |
| URL EUA | `https://web-production-00b33.up.railway.app` |
| GitHub EUA | `github.com/Rosifran/RBC` |
| Scanner Brasil | `~/RBC-Brasil/rbc_br_scanner.py` v2.1 |
| URL Brasil | `https://web-production-c928f.up.railway.app` |
| GitHub Brasil | `github.com/Rosifran/RBC-Brasil` |
| Banco de dados | PostgreSQL Railway |
| Dados mercado | TradingView webhooks 1min → `/api/tv/quote` → PostgreSQL |
| Deploy | Railway Auto Deploy (push → deploy automático) |

---

## Capital

- **$47k** SGOV (IBKR) → ~$204/mês
- **$3k** cash 0DTE EUA
- **R$2.750** Brasil (compra direta 14-35 DTE)

---

## Fluxo diário EUA

```
Manhã     → Modo 1: upload PDF SpotGamma → extrai níveis + Risk Pivot
            📅 Colar calendário SpotGamma (área colapsada no Modo 1) — 1x/semana
9:45      → Modo 2: botão TradingView + RV 1M/5D (SpotGamma) → cockpit completo
10:00     → Modo 3: strike + prêmio + execução
16:01     → TradingView webhook → OHLC automático no journal
Tarde     → PM Note PDF → Journal Modo 4
```

---

## Tabelas PostgreSQL

| Tabela | Conteúdo |
|---|---|
| `trade_journal` | Journal diário 0DTE EUA |
| `market_quotes` | Último quote SPY/VIX (upsert) |
| `quote_history` | Histórico intraday SPY/VIX (INSERT 1min, retenção 3 dias) |
| `calendar_events` | Calendário econômico (upsert por data+evento) |
| `swing_scans` | Resultados scanner Modo 5 |

---

## Arquitetura dos Modos EUA

### Modo 1 — Pré-mercado
- **Input:** PDF SpotGamma
- **Output:** níveis extraídos via Claude API → JSON
- **Campos:** `reference_price`, `vol_trigger`, `zero_gamma`, `call_wall`, `put_wall`, `combos`, `spy_levels`, `absolute_gamma_strike`, `large_gamma_levels`, `large_gamma_1-4`, `founder_alerts`, `key_events`, `risk_pivot` (SPX/10)
- **Área colapsada:** `📅 Calendário econômico` — colar texto do SpotGamma → Salvar (upsert no PG)
- **Regime:** `reference_price < vol_trigger` → `NEGATIVE_GAMMA`

### Modo 2 — Abertura (cockpit completo)
- **Input:** SPY agora (botão TradingView ou manual), VIX agora, RV 1M % (opcional), RV 5D % (opcional)
- **Cadeia de inteligência:**
```
Regime estrutural (Vol Trigger)
  └ Linha Operacional (Risk Pivot) → transição, chase, divergência RP/VT
      └ Location Engine → posição no range, qualidade, tipos de nível
          └ Anchor Engine → destino estrutural, ABS/LARGE gamma, chase check
              └ Hard Blocks B1-B13 → Intelligence Overlay
                  └ Calendar Risk → eventos hoje/amanhã, OPEX, VIX exp
                      └ Vol Premium → VIX vs RV 1M/5D
                          └ Flow Proxy → SPY × VIX intraday 30min
```
- **Decisions:** `CALL REVERSAL`, `PUT REVERSAL`, `CALL BREAKOUT SMALL`, `PUT TREND`, `NO TRADE`
- **Intelligence Overlay:** GOOD (verde) / CAUTION (amarelo) / POOR (laranja) / BLOCKED (vermelho)
- **Plano/Strikes:** ocultos quando `blocked = true`

### Modo 3 — Operacional
- Herda decisão do Modo 2
- Strike ATM/ideal/OTM, alvo +75%, stop -50%, saída 12:30 ET

### Modo 4 — Journal
- TradingView webhook (OHLC 16:01 ET) + PM Note PDF
- Tabela `trade_journal`

### Modo 5 — Swing
- Scanner IBKR TWS: AAPL, AMD, AMZN, BAC, META, NVDA, PLTR, QQQ, SOFI, UBER, XLF
- 14-35 DTE, stop -35%, alvo 1 +40%, alvo 2 +80%

---

## Intelligence Layer — Detalhe (Patch 1 SpotGamma)

### Risk Pivot
- Extraído do PDF como SPX/10 → `risk_pivot`
- Linha Operacional no card Regime: SPY vs RP → `operational_regime` ABOVE/BELOW_LINE
- `regime_strength`: moderate ≤0.35% / clear ≤0.80% / extended >0.80%
- `operational_note` quando SPY entre RP e VT (divergência)

### Location Engine
- `location_zone`: NEAR_SUPPORT / LOWER_RANGE / MIDDLE_OF_RANGE / UPPER_RANGE / NEAR_RESISTANCE
- `location_quality`: DANGEROUS / STRONG / MEDIUM / WEAK
- `nearest_support/resistance` com tipos: CALL_WALL / PUT_WALL / VOL_TRIGGER / ZERO_GAMMA / RISK_PIVOT / 1D_MOVE / COMBO / ABS_GAMMA / LARGE_GAMMA

### Anchor Engine
- Âncoras em cada direção (upside/downside): preço, tipo, qualidade, distância pts/pct, `reached`
- Fontes: CALL_WALL, PUT_WALL, ABS_GAMMA, LARGE_GAMMA (todos HIGH), COMBO/1D_MOVE (MEDIUM), SPY_LEVEL (LOW)
- RP, VT, ZG **não** são âncoras
- `reached = true` → "alvo consumido, chase risk"

### Hard Blocks (evaluate_hard_blocks)
| Block | Condição | Efeito |
|---|---|---|
| B1 MIDDLE_OF_RANGE | location_zone == MIDDLE | POOR, não bloqueia |
| B2 NO_ANCHOR | âncora na direção = NONE | BLOCKED |
| B4 CALL_INTO_CALL_WALL | CALL + is_near_call_wall | BLOCKED |
| B5 PUT_INTO_PUT_WALL | PUT + is_near_put_wall | BLOCKED |
| B9 IMPLIED_MOVE_BOUNDARY | preço no limite do 1D move | BLOCKED |
| B11 OPERATIONAL_CHASE_RISK | regime_strength == extended | BLOCKED + DO_NOT_CHASE |
| B12 CALL_IN_UPPER_RANGE | CALL em UPPER/NEAR_RESISTANCE sem CW | POOR |
| B13 PUT_IN_LOWER_RANGE | PUT em LOWER/NEAR_SUPPORT sem PW | POOR |
| Alertas | TRANSITION, divergência RP/VT | CAUTION |

**Precedência do primary_block:** bloqueantes (B2/B4/B5/B9/B11) sobrepõem informativos (B1/B12/B13).

### Calendar Risk Engine
- Fontes: texto colado do SpotGamma (parser automático) + OPEX (3ª sexta calculado) + VIX exp (3ª sexta mês seguinte −30d calculado)
- Severidade: CPI/FOMC/Payroll = 3 · PCE/PPI/GDP = 2 · Retail/Michigan = 1
- Risco: EXTREME (score −3) / HIGH (−2) / MEDIUM (−1) / LOW (0)
- HIGH/EXTREME → rebaixa GOOD→CAUTION (nunca bloqueia sozinho)
- Badge no card Decisão + linha no overlay
- Aviso `needs_update` quando cobertura < 7 dias

**Junho/2026 no banco:**
- 10/06: CPI (EXTREME)
- 11/06: PPI (MEDIUM)
- 17/06: FOMC + VIX expiration (EXTREME — mesma semana)
- 19/06: OPEX (calculado)
- 25/06: Core PCE (HIGH)

### Volatility Premium Engine
- `implied_rv = VIX − 3.5` (spread histórico do Brent)
- `premium_state`: EXPENSIVE (RV1M < implied−2) / CHEAP (>implied+2) / FAIR
- `rv_trend`: ACCELERATING (RV5D > RV1M+2) / COOLING / STABLE
- EXPENSIVE → reasons + GOOD→CAUTION
- Campos opcionais no Modo 2 (RV 1M %, RV 5D % — da tela SpotGamma)
- Linha no box Linha Operacional

### Flow Proxy Engine (Patch 2 adaptado)
- Proxy honesto do HIRO — confirma direção, não antecipa
- Histórico: `quote_history` (INSERT a cada webhook 1min, retenção 3 dias)
- Janela: 30 min · mínimo 3 amostras (invisível sem histórico)
- Estados: CONFIRMING_UP / FRAGILE_UP / CONFIRMING_DOWN / SQUEEZE_RISK / NEUTRAL
- Contradição com a direção do trade → reasons + GOOD→CAUTION (nunca bloqueia)
- Linha no box Linha Operacional

---

## Swing v2 — Edge Direcional (PENDENTE APLICAR)

**Arquivo:** `patch_swing_v2.py` — **baixado, NÃO aplicado ainda**

**3 correções:**
1. `edge_summary` direcional: Skew e P/C espelhados por direção. Favorável = score 2 apenas. FAVORÁVEL exige 2+ fatores a favor, zero contra, e ao menos 1 fator direcional (Skew ou P/C) a favor
2. Verdict integrado: APROVO = edge FAVORÁVEL + contrato ≥8. Edge NEUTRO → AGUARDAR mesmo com contrato 8/10
3. Invalidação declarada: `PUT invalida se fechar ACIMA de $X` (spot ± 0.5 × move semanal esperado via IV)

**Para aplicar:**
```bash
cd ~/RBC
python3 patch_swing_v2.py us_swing_ibkr.py
python3 us_swing_ibkr.py   # validar com TWS aberto — NVDA não deve aprovar CALL e PUT juntos
git add us_swing_ibkr.py
git commit -m "APROVADO: Swing v2 — edge direcional, verdict integrado, invalidacao"
git push
```

**Próximo (Swing 3):** event risk FOMC/OPEX na janela DTE + tendência de preço do ativo

---

## Rotas principais app.py (EUA)

| Rota | Método | Função |
|---|---|---|
| `/api/modo1` | POST | Processa PDF SpotGamma |
| `/api/modo2` | POST | Análise de abertura (cockpit completo) |
| `/api/modo3` | POST | Análise operacional |
| `/api/tv/quote` | POST | Quote TradingView → market_quotes + quote_history |
| `/api/tv/quote` | GET | Retorna último quote (fresh < 30min) |
| `/api/calendar` | POST | Salva calendário SpotGamma (upsert) |
| `/api/calendar` | GET | Retorna analyze_calendar_risk() |
| `/api/webhook` | POST | Eventos TradingView (journal) |
| `/api/parse-pm-pdf` | POST | PM Note PDF → journal |
| `/api/modo5/latest` | GET | Último scan swing |

---

## Patches aplicados (ordem cronológica)

| Data | Arquivo(s) | Patch | Status |
|---|---|---|---|
| 08/06 | `rbc_br_scanner.py` | explain_missing REPROVO early return | ✅ |
| 08/06 | `app.py` | patch_datetime_fix | ✅ |
| 08/06 | `app.py` | patch_risk_pivot_v2 (Opção A) | ✅ |
| 08/06 | `index.html` | patch_operational_display + fix_preview | ✅ |
| 09/06 | `app.py` + `index.html` | patch_location_engine_v3 | ✅ |
| 09/06 | `index.html` | patch_location_display_official | ✅ |
| 09/06 | `app.py` + `index.html` | patch_anchor_engine_v2 (ABS/LARGE_GAMMA) | ✅ |
| 10/06 | `app.py` + `index.html` | patch_hard_blocks_v2 (B1-B13) | ✅ |
| 10/06 | `app.py` | patch_overlay_fix (precedência primary + frase chase) | ✅ |
| 10/06 | `app.py` + `index.html` + `journal.py` | patch_calendar_risk (Patch 4) | ✅ |
| 10/06 | `app.py` + `index.html` | patch_vol_premium | ✅ |
| 11/06 | `app.py` + `index.html` + `journal.py` | patch_flow_proxy (Patch 2 adaptado) | ✅ |
| 11/06 | `us_swing_ibkr.py` | **patch_swing_v2** | ⏳ PENDENTE |

---

## Pendências

- [ ] **Swing v2:** aplicar `patch_swing_v2.py` + validar com TWS aberto
- [ ] **Swing 3:** event risk FOMC/OPEX na janela DTE do contrato
- [ ] **Flow Proxy:** validar em produção (dados reais amanhã 9:40+)
- [ ] **Calendar:** colar calendário de julho no início do mês (sistema avisa quando necessário)
- [ ] **Decision Score 0-10** (desbloqueia bloqueio por calendar)
- [ ] **Journal Mistake Tags** (CHASE, MIDDLE_OF_RANGE, etc.)
- [ ] **Brasil:** Bear Call Spread mostrando débito em vez de crédito
- [ ] **Cosmético:** frase crua "Put Wall = suporte extremo" na ENTRADA
- [ ] **git config --global** — configurar nome/email do committer
- [ ] **Lição NVDA (11/06):** PUT 195P aberta +5.5% — decidir antes de 16/06 sobre FOMC 17/06 (realizar parcial, sair ou carregar consciente)

---

## Como usar este documento em novo chat

```
Cole este arquivo no início do chat.
O Claude entra no nível certo sem mapear o código do zero.
Comando para recarregar: cat ~/RBC/RBC_ARCHITECTURE.md
```
