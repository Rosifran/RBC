"""
Fix P1 — corrige NameError: parsed não definido no Modo 2.
No escopo da rota modo2, o dicionário é 'sg', não 'parsed'.
Também garante que sg['score'] existe antes de escrever.

Uso: python3 fix_p1_scope.py ~/RBC/app.py
"""
import sys, shutil, ast
from datetime import datetime

OLD = '''    if vol_trig and spot_now:
        _spot_f = float(spot_now)
        _vt_f   = float(vol_trig)
        _dist_pct = round(abs(_spot_f - _vt_f) / _vt_f * 100, 2)
        if gamma_regime == "POSITIVE_GAMMA":
            parsed["score"] = parsed.get("score") or {}
            parsed["score"]["justification"] = (
                f"Positive Gamma regime — SPY {_spot_f} acima do Vol Trigger {_vt_f} "
                f"(+{_dist_pct}%). Dealers sustentam range. Reversoes nos extremos.")
        elif gamma_regime == "NEGATIVE_GAMMA":
            parsed["score"]["justification"] = (
                f"Negative Gamma regime — SPY {_spot_f} abaixo do Vol Trigger {_vt_f} "
                f"(-{_dist_pct}%). Mercado fragil, dealers amplificam moves.")
        elif gamma_regime == "TRANSITION":
            parsed["score"]["justification"] = (
                f"Zona de transicao — SPY {_spot_f} perto do Vol Trigger {_vt_f} "
                f"({_dist_pct}%). Aguardar aceitacao de lado.")'''

NEW = '''    if vol_trig and spot_now:
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

if len(sys.argv) < 2:
    print("Uso: python3 fix_p1_scope.py ~/RBC/app.py")
    sys.exit(1)

path = sys.argv[1]
content = open(path).read()

n = content.count(OLD)
if n != 1:
    print(f"ERRO — ancora encontrada {n}x")
    sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(path, path.replace(".py", f"_backup_{ts}.py"))
print(f"Backup criado ({ts})")

content = content.replace(OLD, NEW, 1)
ast.parse(content)
open(path, 'w').write(content)

print("✅ P1: parsed → sg (escopo Modo 2 correto)")
print()
print("  git add app.py")
print('  git commit -m "fix: P1 scope — sg em vez de parsed no Modo 2"')
print("  git push")
