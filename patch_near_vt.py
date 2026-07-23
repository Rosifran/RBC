"""
RBC EUA — Patch Near VT (calibração de label/justification)
============================================================
Âncora atualizada para bater com o estado real do app.py (linhas 1761-1779).

FIX: quando 0 <= dist_pts < 1.00 (acima do VT mas perto),
label muda para POSITIVE GAMMA / NEAR VT — Aguardar confirmação.

O que NÃO muda: gamma_regime, motor, decision, entry, stop, targets,
Journal, Modo 1, Modo 3, Modo 5, frontend.

Uso: python3 patch_near_vt.py ~/RBC/app.py
"""
import sys, shutil, ast
from datetime import datetime

NEAR_VT_PONTOS = 1.00

OLD = '''    # P1 fix: sobrescreve justification com regime ATUAL (spot_now vs VT)
    # O Modo 1 escreve com reference_price do PDF — pode estar desatualizado
    if vol_trig and spot_now:
        _spot_f = float(spot_now)
        _vt_f   = float(vol_trig)
        _dist_pct = round(abs(_spot_f - _vt_f) / _vt_f * 100, 2)
        sg["score"] = sg.get("score") or {}
        if gamma_regime == "POSITIVE_GAMMA":
            sg["score"]["justification"] = (
                f"Positive Gamma regime — SPY {_spot_f} acima do Vol Trigger {_vt_f} "
                f"(+{_dist_pct}%). Dealers sustentam range. Reversoes nos extremos.")
        elif gamma_regime == "NEGATIVE_GAMMA":
            sg["score"]["justification"] = (
                f"Negative Gamma regime — SPY {_spot_f} abaixo do Vol Trigger {_vt_f} "
                f"(-{_dist_pct}%). Mercado fragil, dealers amplificam moves.")
        elif gamma_regime == "TRANSITION":
            sg["score"]["justification"] = (
                f"Zona de transicao — SPY {_spot_f} perto do Vol Trigger {_vt_f} "
                f"({_dist_pct}%). Aguardar aceitacao de lado.")'''

NEW = '''    # P1 fix: sobrescreve justification com regime ATUAL (spot_now vs VT)
    # O Modo 1 escreve com reference_price do PDF — pode estar desatualizado
    # Near VT: 0 <= dist_pts < 1.00 → acima do VT mas perto demais para Positive limpo
    if vol_trig and spot_now:
        _spot_f   = float(spot_now)
        _vt_f     = float(vol_trig)
        _dist_pts = round(_spot_f - _vt_f, 2)
        _dist_pct = round(abs(_dist_pts) / _vt_f * 100, 2)
        _near_vt  = 0 <= _dist_pts < 1.00
        sg["score"] = sg.get("score") or {}
        if gamma_regime == "POSITIVE_GAMMA" and _near_vt:
            sg["score"]["justification"] = (
                f"POSITIVE GAMMA / NEAR VT — SPY {_spot_f} apenas {_dist_pts:+.2f} pt "
                f"acima do Vol Trigger {_vt_f} ({_dist_pct}%). "
                f"Aguardar aceitacao/fechamento acima do nivel para confirmar regime.")
            sg["score"]["near_vt"] = True
            sg["score"]["near_vt_dist_pts"] = _dist_pts
        elif gamma_regime == "POSITIVE_GAMMA":
            sg["score"]["justification"] = (
                f"Positive Gamma regime — SPY {_spot_f} acima do Vol Trigger {_vt_f} "
                f"(+{_dist_pct}%). Dealers sustentam range. Reversoes nos extremos.")
            sg["score"]["near_vt"] = False
            sg["score"]["near_vt_dist_pts"] = _dist_pts
        elif gamma_regime == "NEGATIVE_GAMMA":
            sg["score"]["justification"] = (
                f"Negative Gamma regime — SPY {_spot_f} abaixo do Vol Trigger {_vt_f} "
                f"(-{_dist_pct}%). Mercado fragil, dealers amplificam moves.")
            sg["score"]["near_vt"] = False
            sg["score"]["near_vt_dist_pts"] = _dist_pts
        elif gamma_regime == "TRANSITION":
            sg["score"]["justification"] = (
                f"Zona de transicao — SPY {_spot_f} perto do Vol Trigger {_vt_f} "
                f"({_dist_pct}%). Aguardar aceitacao de lado.")'''

if len(sys.argv) < 2:
    print("Uso: python3 patch_near_vt.py ~/RBC/app.py")
    sys.exit(1)

path = sys.argv[1]
try:
    content = open(path).read()
except FileNotFoundError:
    print(f"ERRO — arquivo não encontrado: {path}")
    sys.exit(1)

n = content.count(OLD)
if n == 0:
    print("ERRO — âncora não encontrada no arquivo.")
    print("Verificar com:")
    print("  sed -n '1761,1779p' ~/RBC/app.py")
    sys.exit(1)
elif n > 1:
    print(f"ERRO — âncora encontrada {n}x (ambígua). Abortando.")
    sys.exit(1)

try:
    ast.parse("def _t():\n" + "\n".join("    " + l for l in NEW.strip().split("\n")))
except SyntaxError as e:
    print(f"ERRO de sintaxe no patch: {e}")
    sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = path.replace(".py", f"_backup_nearvt_{ts}.py")
shutil.copy2(path, backup)
print(f"Backup: {backup}")

content_new = content.replace(OLD, NEW, 1)

try:
    ast.parse(content_new)
except SyntaxError as e:
    print(f"ERRO — app.py ficou inválido após patch: {e}")
    print("Backup preservado. Nenhuma alteração foi salva.")
    sys.exit(1)

open(path, "w").write(content_new)
print(f"✅ Patch aplicado — NEAR VT threshold: {NEAR_VT_PONTOS} ponto(s)")
print()
print("Cenários:")
print("  SPY 747.49 / VT 747.00 → dist +0.49 < 1.00 → POSITIVE GAMMA / NEAR VT ⚠")
print("  SPY 749.00 / VT 747.00 → dist +2.00 >= 1.00 → POSITIVE GAMMA limpo ✅")
print("  SPY 746.50 / VT 747.00 → NEGATIVE GAMMA (inalterado) ✅")
print()
print("Próximos passos:")
print("  git diff app.py")
print("  git add app.py")
print('  git commit -m "calibrate: Modo 2 NEAR VT label quando 0 <= dist < 1pt acima do VT"')
print("  git push")
