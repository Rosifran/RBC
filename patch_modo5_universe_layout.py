#!/usr/bin/env python3
"""
patch_modo5_universe_layout.py (v3) — Universo expandido + layout compacto.
Rodar de dentro de ~/RBC:  python3 patch_modo5_universe_layout.py
Pré-requisito: patch_capital_fit.py (v1) aplicado. Independente do v2.

U1 — us_swing_ibkr.py: DEFAULT_TICKERS passa de 4 para 12 ativos
     (aprovado: + AMD, UBER, PLTR, SOFI, BAC, XLF, QQQ, SPY; sem TSLA/MSFT).
     Pills do frontend são dinâmicos — atualizam sozinhos no próximo scan.

L1 — index.html: helpers modo5Toggle (expandir/recolher) e
     modo5BestContract (melhor contrato por capital fit, depois score).

L2 — index.html: cada ticker+direção vira UMA linha-resumo compacta:
     direção · melhor contrato (strike, prêmio, custo) · score · bucket ·
     estrutura · capital_status · status final. Clique expande.

L3 — index.html: detalhes (edge, top_contracts, entry/stop/alvos,
     capital fit completo) ficam ocultos até o clique. Nada foi removido.

Não mexe: IBKR, score técnico, filtros técnicos, Capital Fit engine,
seleção de contratos, lógica de risco. Idempotente, com backups.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
SCANNER = ROOT / 'us_swing_ibkr.py'
INDEX = ROOT / 'templates' / 'index.html'
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
    n = text.count(old)
    if n != 1:
        print(f"  {label}: anchor encontrado {n}x (esperado 1) — abortado.")
        return False
    path.write_text(text.replace(old, new), encoding='utf-8')
    print(f"  {label}: OK")
    return True


# ════════════════════════════════════════════════════════════════════
# U1 — universo de tickers
# ════════════════════════════════════════════════════════════════════
U1_OLD = "DEFAULT_TICKERS = ['NVDA', 'AAPL', 'META', 'AMZN']"

U1_NEW = """DEFAULT_TICKERS = [
    'NVDA', 'AAPL', 'META', 'AMZN',   # big tech (caros — geralmente spread)
    'AMD', 'UBER', 'PLTR', 'SOFI',    # meio-termo acessivel
    'BAC', 'XLF', 'QQQ', 'SPY',       # financeiros/ETFs
]"""

# ════════════════════════════════════════════════════════════════════
# L1 — helpers: toggle + melhor contrato
# ════════════════════════════════════════════════════════════════════
L1_OLD = """
  function renderModo5(ticker, dir) {"""

L1_NEW = """
  function modo5Toggle(id) {
    const d  = document.getElementById(id);
    const ch = document.getElementById(id + '-ch');
    if (!d) return;
    const open = d.style.display !== 'none';
    d.style.display = open ? 'none' : 'block';
    if (ch) ch.textContent = open ? '\\u25B8' : '\\u25BE';
  }

  const M5_BUCKET_PRIO = {IDEAL_FOR_ONE_CONTRACT:0, ACCEPTABLE:1, CHEAP_SLOW:2,
                          EXPENSIVE:3, BETTER_AS_SPREAD:4, DADOS_INSUFICIENTES:5, REPROVO:6};

  function modo5BestContract(contracts) {
    if (!contracts || !contracts.length) return null;
    return [...contracts].sort((a, b) => {
      const pa = M5_BUCKET_PRIO[a.capital_fit?.cost_bucket] ?? 9;
      const pb = M5_BUCKET_PRIO[b.capital_fit?.cost_bucket] ?? 9;
      if (pa !== pb) return pa - pb;
      return (b.score || 0) - (a.score || 0);
    })[0];
  }

  function renderModo5(ticker, dir) {"""

# ════════════════════════════════════════════════════════════════════
# L2 — linha-resumo compacta no lugar do header DIR/verdict
# ════════════════════════════════════════════════════════════════════
L2_OLD = """        html += `<div style="padding:10px 14px;border-bottom:0.5px solid #f1f5f9;">`;
        html += `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-size:12px;font-weight:500;color:${dirColor};">${dir}</span>
          <span style="font-size:11px;background:${vBg};color:${vColor};padding:2px 10px;border-radius:20px;font-weight:500;">${vIcon} ${verdict}</span>
        </div>`;"""

L2_NEW = """        // ── Linha-resumo compacta (clique para expandir detalhes) ──
        const bc    = modo5BestContract(scan.top_contracts);
        const bcf   = bc?.capital_fit || null;
        const cfPal = {APROVO_CAPITAL:['#f0fdf4','#16a34a'], MONITORAR:['#fffbeb','#d97706'],
                       REPROVO_CAPITAL:['#fef2f2','#dc2626'], DADOS_INSUFICIENTES:['#f8fafc','#64748b']};
        const cfCol = cfPal[bcf?.capital_status] || cfPal.DADOS_INSUFICIENTES;
        const detId = `m5d-${tkr}-${dir}`;
        const bcTxt = bc
          ? `${bc.strike}${dir === 'CALL' ? 'C' : 'P'} \\u00B7 $${bc.entry_price?.toFixed(2) ?? '\\u2014'}${bcf?.contract_cost != null ? ' ($' + Math.round(bcf.contract_cost) + ')' : ''}`
          : 'sem contratos';
        html += `<div style="border-bottom:0.5px solid #f1f5f9;">`;
        html += `<div onclick="modo5Toggle('${detId}')" style="padding:10px 14px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;cursor:pointer;">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span id="${detId}-ch" style="font-size:10px;color:#94a3b8;">\\u25B8</span>
            <span style="font-size:12px;font-weight:600;color:${dirColor};min-width:32px;">${dir}</span>
            <span style="font-size:12px;font-weight:500;color:#1e293b;">${bcTxt}</span>
            ${bc ? `<span style="font-size:10px;color:#64748b;">${bc.score}/10</span>` : ''}
            ${bcf ? `<span style="font-size:9px;background:${cfCol[0]};color:${cfCol[1]};padding:2px 8px;border-radius:20px;font-weight:600;">${bcf.cost_bucket}</span>` : ''}
            ${bcf ? `<span style="font-size:9px;color:#64748b;">${bcf.preferred_structure}</span>` : ''}
          </div>
          <div style="display:flex;align-items:center;gap:6px;">
            ${bcf ? `<span style="font-size:9px;color:${cfCol[1]};font-weight:600;">${bcf.capital_status}</span>` : ''}
            <span style="font-size:11px;background:${vBg};color:${vColor};padding:2px 10px;border-radius:20px;font-weight:500;">${vIcon} ${verdict}</span>
          </div>
        </div>`;
        // ── Detalhes (ocultos por padrao) ──
        html += `<div id="${detId}" style="display:none;padding:0 14px 12px 14px;">`;"""

# ════════════════════════════════════════════════════════════════════
# L3 — fechar div de detalhes + wrapper
# ════════════════════════════════════════════════════════════════════
L3_OLD = """        }
        html += `</div>`;
      });
      html += `</div>`;
    });"""

L3_NEW = """        }
        html += `</div></div>`; // fecha detalhes + wrapper da linha
      });
      html += `</div>`;
    });"""


def main():
    print("patch_modo5_universe_layout.py (v3) — universo + layout compacto\n")
    for f in (SCANNER, INDEX):
        if not f.exists():
            print(f"ERRO: {f} nao encontrado. Rode de dentro de ~/RBC.")
            sys.exit(1)
    if "modo5CapitalFitBlock" not in INDEX.read_text(encoding='utf-8'):
        print("ERRO: patch v1 nao aplicado no index.html. Rode patch_capital_fit.py antes.")
        sys.exit(1)

    print("[U1] us_swing_ibkr.py — universo 4 -> 12 tickers")
    backup(SCANNER)
    apply(SCANNER, U1_OLD, U1_NEW, "U1", "meio-termo acessivel")

    print("\n[L1-L3] templates/index.html — layout compacto com expansao")
    backup(INDEX)
    apply(INDEX, L1_OLD, L1_NEW, "L1 (helpers toggle/best)", "modo5BestContract")
    apply(INDEX, L2_OLD, L2_NEW, "L2 (linha-resumo)", "Linha-resumo compacta")
    apply(INDEX, L3_OLD, L3_NEW, "L3 (fechamento divs)", "fecha detalhes + wrapper")

    import py_compile
    py_compile.compile(str(SCANNER), doraise=True)
    print("\n  us_swing_ibkr.py: sintaxe OK")
    print("""
Pronto. Proximos passos:
  1. python3 us_swing_ibkr.py        (scan com 12 tickers — demora ~3x mais)
  2. git add us_swing_ibkr.py templates/index.html patch_modo5_universe_layout.py
     git commit -m "Modo 5: universo 12 tickers + dashboard compacto com expansao"
     git push
  3. Apos deploy: Cmd+Shift+R no Modo 5 e rodar novo scan
""")


if __name__ == '__main__':
    main()
