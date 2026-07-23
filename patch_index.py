#!/usr/bin/env python3
# RBC — aplica a Edicao 3 (bloco de decisao do ritual) no templates/index.html
# Uso: python3 patch_index.py            (edita templates/index.html)
#      python3 patch_index.py <arquivo>  (edita outro arquivo, para teste)
import sys, shutil, os

path = sys.argv[1] if len(sys.argv) > 1 else "templates/index.html"
src = open(path, encoding="utf-8").read()

if 'id="radar-decisao"' in src:
    print("JA APLICADO — nada a fazer. Nenhuma alteracao feita.")
    sys.exit(0)

HTML_DIV = '  <div id="radar-decisao" style="display:none;border-radius:10px;padding:14px 16px;margin-bottom:10px;font-size:13px;line-height:1.8;border:1px solid transparent;"></div>\n\n'

JS_BLOCK = """
      // ── BLOCO DE DECISAO (ritual do Modo 6) ──
      const dec = document.getElementById('radar-decisao');
      const rit = dp.ritual;
      if (dec && rit && rit.veredito) {
        const isPut  = rit.veredito.indexOf('PUT') >= 0;
        const isCall = rit.veredito.indexOf('CALL') >= 0;
        const cor  = isPut ? '#dc2626' : (isCall ? '#16a34a' : '#d97706');
        const bg   = isPut ? '#fef2f2' : (isCall ? '#f0fdf4' : '#fffbeb');
        const brd  = isPut ? '#fecaca' : (isCall ? '#bbf7d0' : '#fde68a');
        const mark = ok => ok
          ? '<span style="color:' + cor + ';font-weight:700;">&#9679;</span> '
          : '<span style="color:#cbd5e1;">&#9675;</span> ';
        const side = isPut ? 'PUT' : (isCall ? 'CALL' : null);
        const vLado = side ? rit.lado === side : false;
        const vBat  = side ? (side === 'PUT' ? rit.batalha_gex_m < 0 : rit.batalha_gex_m > 0) : false;
        const vMig  = side ? (side === 'PUT' ? rit.migracao === 'DESCENDO' : rit.migracao === 'SUBINDO') : false;
        let dh = '<div style="font-size:16px;font-weight:700;color:' + cor + ';margin-bottom:6px;">'
               + (isPut || isCall ? 'VEREDITO: ' : '') + rit.veredito + '</div>';
        dh += '<div>' + mark(vLado) + 'LADO: <b>' + rit.lado + '</b>'
            + (rit.vt_fluxo ? ' (spot vs VT fluxo ' + Number(rit.vt_fluxo).toFixed(2) + ')' : '') + '</div>';
        dh += '<div>' + mark(vBat) + 'BATALHA: <b>' + rit.batalha_strike + '</b> ('
            + (rit.batalha_gex_m > 0 ? '+' : '') + rit.batalha_gex_m + 'M) a '
            + rit.batalha_dist + ' pts</div>';
        dh += '<div>' + mark(vMig) + 'MIGRACAO: Put Wall fluxo <b>' + rit.migracao + '</b></div>';
        if (rit.veredito_mudou && rit.veredito_anterior) {
          dh += '<div style="margin-top:8px;padding-top:8px;border-top:1px solid ' + brd
              + ';color:#dc2626;font-weight:700;">&#9888; VEREDITO MUDOU: "'
              + rit.veredito_anterior + '" &rarr; "' + rit.veredito
              + '" — reavaliar posicao</div>';
        }
        dec.style.background = bg;
        dec.style.borderColor = brd;
        dec.innerHTML = dh;
        dec.style.display = 'block';
      } else if (dec) {
        dec.style.display = 'none';
      }
"""

ANCHOR_HTML = '<div id="radar-header"'
ANCHOR_JS = "if (!spot) { hdr.innerHTML = 'Sem dados. Rode <code>intraday_gamma.py</code>.'; return; }"

errs = []
if src.count(ANCHOR_HTML) != 1:
    errs.append(f"ancora HTML aparece {src.count(ANCHOR_HTML)}x (esperado 1)")
if src.count(ANCHOR_JS) != 1:
    errs.append(f"ancora JS aparece {src.count(ANCHOR_JS)}x (esperado 1)")
if errs:
    print("ABORTADO — arquivo diferente do esperado:")
    for e in errs:
        print("  -", e)
    print("Nenhuma alteracao feita. Me mande esta saida no chat.")
    sys.exit(1)

bak = path + ".bak_antes_ritual"
shutil.copy2(path, bak)

i = src.find(ANCHOR_HTML)
j = src.rfind("\n", 0, i) + 1
src = src[:j] + HTML_DIV + src[j:]

k = src.find(ANCHOR_JS) + len(ANCHOR_JS)
src = src[:k] + "\n" + JS_BLOCK + src[k:]

open(path, "w", encoding="utf-8").write(src)
n = len(src.splitlines())
print(f"OK — patch aplicado em {path} ({n} linhas). Backup: {bak}")
