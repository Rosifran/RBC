"""
RBC EUA — Fix Intelligence Overlay pos-teste (2 bugs achados na validacao)
===========================================================================
Bug 1 (testes A e 772.50): primary_block mostrava o block INFORMATIVO
  (MIDDLE_OF_RANGE) quando um block BLOQUEANTE (PUT_INTO_PUT_WALL,
  OPERATIONAL_CHASE_RISK) tambem acionava.
  Fix: blocks bloqueantes sobrepoem o primary de blocks informativos.
  Informativos: MIDDLE_OF_RANGE, CALL_IN_UPPER_RANGE, PUT_IN_LOWER_RANGE.

Bug 2 (teste B, cosmetico): reason "OPERATIONAL_CHASE_RISK" cru no report.
  Fix: frase legivel mantendo o tag.

So evaluate_hard_blocks() e tocada. Motor e todo o resto intactos.

Uso: python3 patch_overlay_fix.py ~/RBC/app.py
"""
import sys, shutil, ast
from datetime import datetime

PATCHES = [
    # F1 — _set_primary com precedencia de bloqueantes
    ('''        def _set_primary(code):
            if not ib["primary_block"]:
                ib["primary_block"] = code''',
     '''        _INFO_BLOCKS = ("MIDDLE_OF_RANGE", "CALL_IN_UPPER_RANGE", "PUT_IN_LOWER_RANGE")

        def _set_primary(code, blocking=False):
            if not ib["primary_block"]:
                ib["primary_block"] = code
            elif blocking and ib["primary_block"] in _INFO_BLOCKS:
                ib["primary_block"] = code''',
     "_set_primary com precedencia"),

    # F2 — B2 upside
    ('''            _set_primary("NO_UPSIDE_ANCHOR")''',
     '''            _set_primary("NO_UPSIDE_ANCHOR", blocking=True)''',
     "B2 upside blocking"),

    # F3 — B2 downside
    ('''            _set_primary("NO_DOWNSIDE_ANCHOR")''',
     '''            _set_primary("NO_DOWNSIDE_ANCHOR", blocking=True)''',
     "B2 downside blocking"),

    # F4 — B4
    ('''            _set_primary("CALL_INTO_CALL_WALL")''',
     '''            _set_primary("CALL_INTO_CALL_WALL", blocking=True)''',
     "B4 blocking"),

    # F5 — B5
    ('''            _set_primary("PUT_INTO_PUT_WALL")''',
     '''            _set_primary("PUT_INTO_PUT_WALL", blocking=True)''',
     "B5 blocking"),

    # F6 — B9 high
    ('''            _set_primary("CALL_AT_IMPLIED_MOVE_HIGH")''',
     '''            _set_primary("CALL_AT_IMPLIED_MOVE_HIGH", blocking=True)''',
     "B9 high blocking"),

    # F7 — B9 low
    ('''            _set_primary("PUT_AT_IMPLIED_MOVE_LOW")''',
     '''            _set_primary("PUT_AT_IMPLIED_MOVE_LOW", blocking=True)''',
     "B9 low blocking"),

    # F8 — B11: frase legivel + blocking
    ('''        if regime_strength == "extended":
            ib["reasons"].append("OPERATIONAL_CHASE_RISK")
            _set_primary("OPERATIONAL_CHASE_RISK")''',
     '''        if regime_strength == "extended":
            ib["reasons"].append(
                "OPERATIONAL_CHASE_RISK — SPY esticado da linha operacional "
                "(Risk Pivot). Nao perseguir.")
            _set_primary("OPERATIONAL_CHASE_RISK", blocking=True)''',
     "B11 frase legivel + blocking"),
]

if len(sys.argv) < 2:
    print("Uso: python3 patch_overlay_fix.py ~/RBC/app.py")
    sys.exit(1)

path = sys.argv[1]
content = open(path).read()

for old, _, label in PATCHES:
    n = content.count(old)
    if n != 1:
        print(f"ERRO — '{label}': ancora encontrada {n}x")
        sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(path, path.replace(".py", f"_backup_{ts}.py"))
print(f"Backup criado ({ts})")

for old, new, label in PATCHES:
    content = content.replace(old, new, 1)
    print(f"✅ {label}")

ast.parse(content)
open(path, 'w').write(content)
print()
print("Proximo passo:")
print("  git add app.py")
print('  git commit -m "APROVADO: fix overlay — precedencia do primary_block + frase do chase"')
print("  git push")
