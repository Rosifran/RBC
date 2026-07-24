#!/usr/bin/env python3
# RBC — barra de PESO (PUT <--> CALL) no cartao de decisao do Modo 3
# Uso: python3 patch_peso.py   (edita templates/index.html)
import sys, shutil

path = sys.argv[1] if len(sys.argv) > 1 else "templates/index.html"
src = open(path, encoding="utf-8").read()

if "rit.peso" in src:
    print("JA APLICADO — nada a fazer.")
    sys.exit(0)

ANCHOR = "        dh += '<div>' + mark(vMig) + 'MIGRACAO: Put Wall fluxo <b>' + rit.migracao + '</b></div>';"

BLOCK = """
        if (rit.peso !== undefined && rit.peso !== null) {
          const p = Math.max(0, Math.min(100, rit.peso));
          const plado = p > 55 ? 'CALL' : p < 45 ? 'PUT' : 'NEUTRO';
          const pcor  = p > 55 ? '#16a34a' : p < 45 ? '#dc2626' : '#64748b';
          dh += '<div style="margin-top:10px;padding-top:10px;border-top:1px solid #e2e8f0;">'
              + '<div style="display:flex;justify-content:space-between;align-items:baseline;font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px;">'
              + '<span>PUT</span>'
              + '<span style="color:#64748b;">PESO: <b style="color:' + pcor + ';font-size:12px;">' + p + '% ' + plado + '</b> \\u00b7 confianca ' + (rit.peso_conf || '\\u2014') + '</span>'
              + '<span>CALL</span></div>'
              + '<div style="position:relative;height:6px;background:linear-gradient(90deg,#fecaca,#f1f5f9 45%,#f1f5f9 55%,#bbf7d0);border-radius:3px;">'
              + '<div style="position:absolute;top:-3px;left:calc(' + p + '% - 6px);width:12px;height:12px;border-radius:50%;background:' + pcor + ';border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,0.3);"></div>'
              + '</div>'
              + ((rit.peso_up_m !== undefined && rit.peso_dn_m !== undefined)
                 ? '<div style="font-size:10px;color:#94a3b8;margin-top:4px;">verde acima ' + rit.peso_up_m + 'M \\u00b7 vermelho abaixo ' + rit.peso_dn_m + 'M</div>'
                 : '');
          dh += '</div>';
        }
"""

if src.count(ANCHOR) != 1:
    print(f"ABORTADO — ancora aparece {src.count(ANCHOR)}x (esperado 1).")
    print("Nenhuma alteracao feita. Me mande esta saida no chat junto com:")
    print("  grep -n \"MIGRACAO: Put Wall fluxo\" templates/index.html")
    sys.exit(1)

bak = path + ".bak_antes_peso"
shutil.copy2(path, bak)
src = src.replace(ANCHOR, ANCHOR + BLOCK)
open(path, "w", encoding="utf-8").write(src)
print(f"OK — barra de PESO aplicada em {path}. Backup: {bak}")
