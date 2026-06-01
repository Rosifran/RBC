# RBC — Risk Bridge Capital

Plataforma de decisão operacional para opções 0DTE SPY.

> Decisão com contexto + risco + disciplina + dados.

---

## Status Atual

| Módulo | Status |
|---|---|
| Modo 1 — PDF SpotGamma → Dashboard | ✅ Funcionando |
| Modo 2 — Análise de Abertura | 🔧 Em desenvolvimento |
| Modo 3 — Decisão Operacional 0DTE | ✅ Funcionando |
| Trade Journal | ⏳ Próximo |
| IBKR API | ⏳ Futuro |
| Brasil / OpLab | ⏳ Futuro |

---

## Fluxo Diário

9:00  — Sobe PDF SpotGamma no Modo 1
9:25  — Atualiza SPY/IBKR no Modo 3
9:30  — Modo 3 decide: CALL OK / PUT OK / WAIT / NO TRADE
10:30 — Encerra ou ignora
Fim   — Journal

---

## Roadmap

### Fase 1 — RBC 0DTE SPY funcional
- [x] Modo 1: PDF → Score + Regime + Key Levels + Plano
- [x] Modo 3: Veredito operacional com trigger/target/stop
- [ ] Modo 2: análise de abertura funcional
- [ ] Trade Journal básico
- [ ] Checklist de entrada

### Fase 2 — Rotina de trading
- [ ] Checklist de entrada
- [ ] Controle: 1 trade/dia, stop -50%, target +75%, horário limite
- [ ] Journal com histórico, acertos, erros

### Fase 3 — Dados reais
- [ ] IBKR API ou upload manual
- [ ] Spot ao vivo, option chain, IV real
- [ ] Modo 3 com liquidez, spread, delta, theta

### Fase 4 — Motor quantitativo
- [ ] Market Regime Score
- [ ] Option Quality Score
- [ ] Trade Quality: A / B / C / No Trade

### Fase 5 — Brasil com OpLab API
- [ ] PETR4, VALE3, BOVA11
- [ ] Estratégias: call/put, trava, covered call, proteção

### Fase 6 — Plataforma unificada EUA + Brasil
- [ ] US + Brazil Options
- [ ] Risk Engine completo
- [ ] Journal completo

---

## Codex RBC

1 trade por dia
Stop: -50%
Target: +75%
Saída obrigatória: 12:00 ET
Score menor que 3 = não opera
Dentro da No-Trade Zone = não entra
Estado emocional ruim = não opera

---

## Stack

- Backend: Python / Flask
- Frontend: HTML / JS
- Deploy: Railway
- PDF: pdfplumber + Claude API
- Dados: SpotGamma Founder Note diário

---

## Site

https://web-production-00b33.up.railway.app
