#!/usr/bin/env python3
# RBC — linha de status do radar com a mesma zona morta (+-0.30) do ritual
# Uso: python3 patch_status_zona.py   (edita templates/index.html)
import sys, shutil

path = sys.argv[1] if len(sys.argv) > 1 else "templates/index.html"
src = open(path, encoding="utf-8").read()

if "vtf - 0.30" in src:
    print("JA APLICADO — nada a fazer.")
    sys.exit(0)

OLD_CALC = "      const lado = vtf ? (spot < vtf ? 'PUT' : 'CALL') : '\u2014';"
NEW_CALC = "      const lado = vtf ? (spot < vtf - 0.30 ? 'PUT' : spot > vtf + 0.30 ? 'CALL' : 'NA LINHA') : '\u2014';"

OLD_COLOR = "' \u00b7 Lado: <b style=\"color:' + (lado==='PUT'?'#dc2626':'#16a34a') + '\">' + lado + '</b>'"
NEW_COLOR = "' \u00b7 Lado: <b style=\"color:' + (lado==='PUT'?'#dc2626':lado==='CALL'?'#16a34a':'#d97706') + '\">' + lado + '</b>'"

errs = []
if src.count(OLD_CALC) != 1:
    errs.append(f"calculo do lado aparece {src.count(OLD_CALC)}x (esperado 1)")
if src.count(OLD_COLOR) != 1:
    errs.append(f"cor do lado aparece {src.count(OLD_COLOR)}x (esperado 1)")
if errs:
    print("ABORTADO — arquivo diferente do esperado:")
    for e in errs:
        print("  -", e)
    print("Nenhuma alteracao feita. Me mande esta saida no chat junto com:")
    print("  grep -n \"const lado\" templates/index.html")
    sys.exit(1)

bak = path + ".bak_antes_statuszona"
shutil.copy2(path, bak)
src = src.replace(OLD_CALC, NEW_CALC).replace(OLD_COLOR, NEW_COLOR)
open(path, "w", encoding="utf-8").write(src)
print(f"OK — linha de status alinhada com a zona morta. Backup: {bak}")
