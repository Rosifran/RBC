#!/usr/bin/env python3
# RBC — cartao de decisao sobrio: fundo neutro, cor so nos acentos
# Uso: python3 patch_decisao_sobrio.py   (edita templates/index.html)
import sys, shutil

path = sys.argv[1] if len(sys.argv) > 1 else "templates/index.html"
src = open(path, encoding="utf-8").read()

if "cartao sobrio v2" in src:
    print("JA APLICADO — nada a fazer.")
    sys.exit(0)

pairs = [
    # fundo e borda deixam de ser coloridos
    ("        const bg   = isPut ? '#fef2f2' : (isCall ? '#f0fdf4' : '#fffbeb');\n"
     "        const brd  = isPut ? '#fecaca' : (isCall ? '#bbf7d0' : '#fde68a');",
     "        const bg   = '#fff';   // cartao sobrio v2\n"
     "        const brd  = '#e2e8f0';"),
    # separador do alerta em cinza neutro (o texto continua vermelho)
    ("          dh += '<div style=\"margin-top:8px;padding-top:8px;border-top:1px solid ' + brd\n"
     "              + ';color:#dc2626;font-weight:700;\">&#9888; VEREDITO MUDOU: \"'",
     "          dh += '<div style=\"margin-top:8px;padding-top:8px;border-top:1px solid #e2e8f0'\n"
     "              + ';color:#dc2626;font-weight:700;\">&#9888; VEREDITO MUDOU: \"'"),
]

errs = []
for old, _ in pairs:
    if src.count(old) != 1:
        errs.append(f"trecho aparece {src.count(old)}x (esperado 1): {old[:60]}...")
if errs:
    print("ABORTADO — arquivo diferente do esperado:")
    for e in errs:
        print("  -", e)
    print("Nenhuma alteracao feita. Me mande esta saida no chat.")
    sys.exit(1)

bak = path + ".bak_antes_sobrio"
shutil.copy2(path, bak)
for old, new in pairs:
    src = src.replace(old, new)
open(path, "w", encoding="utf-8").write(src)
print(f"OK — cartao sobrio aplicado em {path}. Backup: {bak}")
