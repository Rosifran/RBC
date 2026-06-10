#!/usr/bin/env python3
"""
patch_capital_fit.py — Integra o Capital Fit Engine ao Modo 5 Swing.
Rodar de dentro de ~/RBC:  python3 patch_capital_fit.py

PATCH A — us_swing_ibkr.py
    1 chamada a enrich_scan_results(results) no main(), depois do scan e
    antes de save_results() + PostgreSQL. Não toca em IBKR, score, tickers.

PATCH B — templates/index.html
    Corrige modo5IsMarketOpen(): regex esperava "YYYYMMDD_HHMM" mas o
    timestamp real é "YYYY-MM-DD HH:MM ET" → nunca casava → sempre
    "MERCADO FECHADO". Agora aceita os dois formatos.

PATCH C — templates/index.html
    Bloco CAPITAL FIT dentro do card do contrato (abaixo de Vol/OI/Spread).
    Só renderiza se c.capital_fit existir → compatível com scans antigos.

PATCH D — capital_fit_engine.py (adaptação de mapeamento, regra GPT #1)
    O scanner usa 0 como sentinela de dado ausente (bid=0 quando não vem;
    ask cai para close fora do pregão). bid<=0 passa a contar como ausente
    → DADOS_INSUFICIENTES/WAIT, em vez de gerar spread falso e REPROVO.

Idempotente: detecta se cada patch já foi aplicado e pula.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
TS = datetime.now().strftime('%Y%m%d_%H%M%S')


def backup(path: Path) -> None:
    dst = path.with_name(f"{path.stem}_backup_{TS}{path.suffix}")
    shutil.copy2(path, dst)
    print(f"  backup: {dst.name}")


def apply(path: Path, old: str, new: str, label: str, marker: str) -> bool:
    text = path.read_text(encoding='utf-8')
    if marker in text:
        print(f"  {label}: ja aplicado — pulando.")
        return False
    if old not in text:
        print(f"  {label}: ANCHOR NAO ENCONTRADO em {path.name} — abortado. Nada alterado neste arquivo.")
        return False
    if text.count(old) != 1:
        print(f"  {label}: anchor aparece {text.count(old)}x em {path.name} — abortado por seguranca.")
        return False
    path.write_text(text.replace(old, new), encoding='utf-8')
    print(f"  {label}: OK")
    return True


# ════════════════════════════════════════════════════════════════════
# PATCH A — scanner: enriquecer results antes de salvar
# ════════════════════════════════════════════════════════════════════
SCANNER = ROOT / 'us_swing_ibkr.py'

A_OLD = """    ib.disconnect()
    save_results(results)"""

A_NEW = """    ib.disconnect()

    # Capital Fit Engine — camada de adequacao de capital (nao altera score tecnico)
    try:
        from capital_fit_engine import enrich_scan_results
        enrich_scan_results(results)
        print("  Capital Fit aplicado aos contratos.")
    except Exception as cf_err:
        print(f"  Aviso: capital_fit indisponivel — {cf_err}")

    save_results(results)"""

# ════════════════════════════════════════════════════════════════════
# PATCH B — frontend: fix modo5IsMarketOpen (formato do timestamp)
# ════════════════════════════════════════════════════════════════════
INDEX = ROOT / 'templates' / 'index.html'

B_OLD = """    const m = scanTime.match(/([0-9]{8})_([0-9]{2})([0-9]{2})/);
    if (!m) return false;
    const hhmm = parseInt(m[2]) * 100 + parseInt(m[3]);
    return hhmm >= 930 && hhmm < 1600;"""

B_NEW = """    // Aceita "2026-06-10 10:34 ET" (formato real do scanner) e "20260610_1034" (legado)
    let hh = null, mm = null;
    let m = scanTime.match(/\\b([0-9]{2}):([0-9]{2})\\b/);
    if (m) { hh = m[1]; mm = m[2]; }
    else {
      m = scanTime.match(/[0-9]{8}_([0-9]{2})([0-9]{2})/);
      if (m) { hh = m[1]; mm = m[2]; }
    }
    if (hh === null) return false;
    const hhmm = parseInt(hh) * 100 + parseInt(mm);
    return hhmm >= 930 && hhmm < 1600;"""

# ════════════════════════════════════════════════════════════════════
# PATCH C — frontend: helper + bloco CAPITAL FIT no card do contrato
# ════════════════════════════════════════════════════════════════════
C1_OLD = """  function modo5ContractVerdict(c, marketOpen) {
    if (marketOpen) return c.verdict || 'REPROVO';
    // Mercado fechado — dados incompletos nao reprovam definitivamente
    const hasData = c.delta && c.delta !== 0 && c.iv_pct && c.iv_pct > 0 && c.volume > 0;
    if (!hasData) return 'AGUARDAR';
    return c.verdict || 'AGUARDAR';
  }"""

C1_NEW = C1_OLD + """

  function modo5CapitalFitBlock(c) {
    const cf = c.capital_fit;
    if (!cf) return '';
    const palette = {
      'APROVO_CAPITAL':      {bg:'#f0fdf4', fg:'#16a34a', icon:'\\u{1F7E2}'},
      'MONITORAR':           {bg:'#fffbeb', fg:'#d97706', icon:'\\u{1F7E1}'},
      'REPROVO_CAPITAL':     {bg:'#fef2f2', fg:'#dc2626', icon:'\\u{1F534}'},
      'DADOS_INSUFICIENTES': {bg:'#f8fafc', fg:'#64748b', icon:'\\u26AA'},
    };
    const st = palette[cf.capital_status] || palette['DADOS_INSUFICIENTES'];
    const cost = cf.contract_cost != null ? '$' + Math.round(cf.contract_cost) : 'N/A';
    const risk = cf.risk_at_stop  != null ? '$' + Math.round(cf.risk_at_stop)  : 'N/A';
    return `<div style="margin-top:6px;padding:6px 8px;background:${st.bg};border-radius:6px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">
          <span style="font-size:9px;font-weight:600;color:${st.fg};text-transform:uppercase;">Capital Fit \\u00B7 ${cf.cost_bucket || ''}</span>
          <span style="font-size:9px;color:${st.fg};font-weight:600;">${st.icon} ${cf.capital_status || ''}</span>
        </div>
        <div style="font-size:9px;color:#64748b;">Custo ${cost} \\u00B7 Risco no stop ${risk} \\u00B7 Estrutura: ${cf.preferred_structure || '\\u2014'}</div>
        <div style="font-size:9px;color:#94a3b8;margin-top:2px;font-style:italic;">${cf.rosi_note || ''}</div>
      </div>`;
  }"""

C2_OLD = """              <div style="margin-top:4px;font-size:9px;color:#94a3b8;">
                Vol ${c.volume?.toLocaleString() || '0'} \u00b7 OI ${c.open_interest?.toLocaleString() || '0'} \u00b7 Spread ${c.spread_pct || '\u2014'}%
              </div>
            </div>`;"""

C2_NEW = """              <div style="margin-top:4px;font-size:9px;color:#94a3b8;">
                Vol ${c.volume?.toLocaleString() || '0'} \u00b7 OI ${c.open_interest?.toLocaleString() || '0'} \u00b7 Spread ${c.spread_pct || '\u2014'}%
              </div>
              ${modo5CapitalFitBlock(c)}
            </div>`;"""

# ════════════════════════════════════════════════════════════════════
# PATCH D — engine: bid<=0 conta como ausente (sentinela 0 do scanner)
# ════════════════════════════════════════════════════════════════════
ENGINE = ROOT / 'capital_fit_engine.py'

D_OLD = """    if bid is None or bid < 0:
        missing.append("bid")"""

D_NEW = """    if bid is None or bid <= 0:
        # scanner usa 0 como sentinela de ausente; ask cai p/ close fora do pregao
        missing.append("bid")"""


def main():
    print("patch_capital_fit.py — integracao Capital Fit no Modo 5\n")

    for f in (SCANNER, INDEX, ENGINE):
        if not f.exists():
            print(f"ERRO: {f} nao encontrado. Rode de dentro de ~/RBC.")
            sys.exit(1)
    if not (ROOT / 'capital_fit_engine.py').exists():
        print("ERRO: capital_fit_engine.py nao esta em ~/RBC.")
        sys.exit(1)

    print("[A] us_swing_ibkr.py — enrich_scan_results no main()")
    backup(SCANNER)
    apply(SCANNER, A_OLD, A_NEW, "PATCH A", "enrich_scan_results(results)")

    print("\n[B+C] templates/index.html — fix MERCADO FECHADO + bloco CAPITAL FIT")
    backup(INDEX)
    apply(INDEX, B_OLD, B_NEW, "PATCH B", "formato real do scanner")
    apply(INDEX, C1_OLD, C1_NEW, "PATCH C1 (helper)", "modo5CapitalFitBlock")
    apply(INDEX, C2_OLD, C2_NEW, "PATCH C2 (card)", "${modo5CapitalFitBlock(c)}")

    print("\n[D] capital_fit_engine.py — bid<=0 = ausente (mapeamento)")
    backup(ENGINE)
    apply(ENGINE, D_OLD, D_NEW, "PATCH D", "sentinela de ausente")

    print("\nValidando sintaxe Python...")
    import py_compile
    for f in (SCANNER, ENGINE):
        py_compile.compile(str(f), doraise=True)
        print(f"  {f.name}: sintaxe OK")

    print("""
Pronto. Proximos passos:
  1. Rodar o scanner com TWS aberto:  python3 us_swing_ibkr.py
  2. Conferir o bloco CAPITAL FIT no terminal/JSON salvo
  3. Commit + push (Railway redeploya o index.html):
       git add us_swing_ibkr.py templates/index.html capital_fit_engine.py patch_capital_fit.py
       git commit -m "Modo 5: integra Capital Fit Engine + fix MERCADO FECHADO"
       git push
  4. Atualizar o Modo 5 no app e conferir o card
""")


if __name__ == '__main__':
    main()
