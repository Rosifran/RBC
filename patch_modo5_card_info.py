#!/usr/bin/env python3
"""
patch_modo5_card_info.py — Card do Modo 5 com a informacao que faltava.
Rodar de dentro de ~/RBC:  python3 patch_modo5_card_info.py

Problema (Rosi, 11/06): o card nao mostrava vencimento (teve que procurar a
PUT no TWS), nem o criterio/tese da entrada, nem a invalidacao.

Mudancas (APENAS frontend — templates/index.html):
  P1 — linha-resumo: vencimento "02/07 (22d)" junto do strike/premio
  P2 — linha-resumo: chip do EDGE direcional (FAVORAVEL/NEUTRO/DESFAVORAVEL)
       + chip vermelho da INVALIDACAO (quando o scan tiver — Swing v2)
  P3 — detalhes expandidos: bloco "Tese" (overall_note) + "Invalidacao"
       (invalid_note) em destaque, ANTES dos fatores e contratos

Compatibilidade: scans antigos sem os campos do v2 renderizam igual a hoje
(os blocos novos so aparecem se o campo existir).
Nao mexe: backend, scanner, decisoes, scores, Capital Fit. Backup automatico.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
INDEX = ROOT / 'templates' / 'index.html'
TS = datetime.now().strftime('%Y%m%d_%H%M%S')
MARKER = "card_info_v2"

# ── P1: vencimento na linha-resumo + consts de edge/invalidacao ──────
P1_OLD = r'''        const bcTxt = bc
          ? `${bc.strike}${dir === 'CALL' ? 'C' : 'P'} \u00B7 $${bc.entry_price?.toFixed(2) ?? '\u2014'}${bcf?.contract_cost != null ? ' ($' + Math.round(bcf.contract_cost) + ')' : ''}`
          : 'sem contratos';'''

P1_NEW = r'''        // card_info_v2 — vencimento, edge e invalidacao na linha-resumo
        const bcExp  = bc?.expiration
          ? bc.expiration.replace(/([0-9]{4})([0-9]{2})([0-9]{2})/, '$3/$2') : '';
        const bcVenc = bcExp && bc?.dte ? `${bcExp} (${bc.dte}d)`
                     : (bc?.dte ? `${bc.dte}d` : bcExp);
        const bcTxt = bc
          ? `${bc.strike}${dir === 'CALL' ? 'C' : 'P'} \u00B7 $${bc.entry_price?.toFixed(2) ?? '\u2014'}${bcf?.contract_cost != null ? ' ($' + Math.round(bcf.contract_cost) + ')' : ''}${bcVenc ? ' \u00B7 ' + bcVenc : ''}`
          : 'sem contratos';
        const _evRaw = edge.verdict || '';
        const _ev    = _evRaw.replace('EDGE ', '');
        const _evCol = _evRaw.includes('FAVORAVEL') ? '#16a34a'
                     : _evRaw.includes('NEUTRO')    ? '#d97706'
                     : _evRaw.includes('DESFAVORAVEL') ? '#dc2626' : '#94a3b8';
        const _inv   = scan.invalid_note || null;'''

# ── P2: chips de edge + invalidacao na linha-resumo ──────────────────
P2_OLD = r'''            ${bcf ? `<span style="font-size:9px;color:#64748b;">${bcf.preferred_structure}</span>` : ''}
          </div>'''

P2_NEW = r'''            ${bcf ? `<span style="font-size:9px;color:#64748b;">${bcf.preferred_structure}</span>` : ''}
            ${_ev && _ev !== 'INCOMPLETO' ? `<span style="font-size:9px;color:${_evCol};font-weight:600;border:0.5px solid ${_evCol};padding:1px 6px;border-radius:20px;">EDGE ${_ev}</span>` : ''}
            ${_inv ? `<span style="font-size:9px;color:#dc2626;font-weight:600;background:#fef2f2;border:0.5px solid #fecaca;padding:1px 6px;border-radius:20px;">\u26a0 ${_inv}</span>` : ''}
          </div>'''

# ── P3: tese + invalidacao em destaque no topo dos detalhes ──────────
P3_OLD = r'''        html += `<div id="${detId}" style="display:none;padding:0 14px 12px 14px;">`;

        // Edge'''

P3_NEW = r'''        html += `<div id="${detId}" style="display:none;padding:0 14px 12px 14px;">`;

        // Tese (overall_note) + Invalidacao (invalid_note) — Swing v2
        if (scan.overall_note || scan.invalid_note) {
          const _hasInv = !!scan.invalid_note;
          html += `<div style="background:${_hasInv ? '#fef2f2' : '#f8fafc'};border:0.5px solid ${_hasInv ? '#fecaca' : '#e2e8f0'};border-left:3px solid ${_hasInv ? '#dc2626' : '#94a3b8'};border-radius:8px;padding:8px 10px;margin-bottom:8px;">`;
          if (scan.overall_note) html += `<div style="font-size:11px;color:#1e293b;font-weight:500;line-height:1.4;">Tese: ${scan.overall_note}</div>`;
          if (scan.invalid_note) html += `<div style="font-size:11px;color:#dc2626;font-weight:700;margin-top:${scan.overall_note ? 4 : 0}px;">\u26a0 Invalidacao: ${scan.invalid_note}</div>`;
          html += `</div>`;
        }

        // Edge'''


def apply(old, new, label):
    text = INDEX.read_text(encoding='utf-8')
    n = text.count(old)
    if n != 1:
        print(f"  {label}: anchor encontrado {n}x (esperado 1) — abortado.")
        sys.exit(1)
    INDEX.write_text(text.replace(old, new), encoding='utf-8')
    print(f"  {label}: OK")


def main():
    print("patch_modo5_card_info.py — vencimento + edge + tese + invalidacao\n")
    if not INDEX.exists():
        print("ERRO: templates/index.html nao encontrado. Rode de dentro de ~/RBC.")
        sys.exit(1)
    if MARKER in INDEX.read_text(encoding='utf-8'):
        print("  ja aplicado — nada a fazer.")
        return

    dst = INDEX.with_name(f"index_backup_{TS}.html")
    shutil.copy2(INDEX, dst)
    print(f"  backup: templates/{dst.name}\n")

    apply(P1_OLD, P1_NEW, "P1 (vencimento na linha-resumo)")
    apply(P2_OLD, P2_NEW, "P2 (chips edge + invalidacao)")
    apply(P3_OLD, P3_NEW, "P3 (tese em destaque nos detalhes)")

    print("""
Proximos passos:
  git add templates/index.html patch_modo5_card_info.py
  git commit -m "Modo 5: card mostra vencimento, edge, tese e invalidacao (Swing v2)"
  git push
Apos deploy verde no Railway: Cmd+Shift+R no Modo 5.
Nota: tese e invalidacao aparecem no PROXIMO scan com mercado aberto
(o scan de hoje 16:05 foi pos-fechamento, iv_ann=0 -> sem invalidacao).
""")


if __name__ == '__main__':
    main()
