"""
RBC EUA — patch PUT TREND alvos + chase warning frontend
Patch 1 (app.py):
  - PUT TREND: alvos só abaixo do spot_now
  - Fallback: None (não usa vol_trig - 3 que pode estar acima do spot)
  - Put Wall só como nota, nunca alvo
  - Valida t1/t2 >= spot_now → seta None
Patch 2 (index.html):
  - Strikes sugeridos: não mostrar se chase_warning
  - Plano de trade: não mostrar entry/stop/targets se chase_warning
Uso: python3 patch_put_targets_v2.py ~/RBC/app.py ~/RBC/templates/index.html
"""
import sys, shutil, ast
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# PATCH 1 — app.py: PUT TREND alvos corretos
# ══════════════════════════════════════════════════════════════════════

OLD_APP = '''    elif gamma_regime == "NEGATIVE_GAMMA" and vol_trig:
        # Abaixo do Vol Trigger → PUT TREND
        decision = "PUT TREND"
        reason   = (f"SPY below Vol Trigger {vol_trig}."
                    " Negative gamma — dealers amplify the move downward.")
        entry    = f"Buy put OTM. SPY accepted below {vol_trig}."
        stop     = f"SPY closes back above {vol_trig}."
        dns      = _below(all_lvls, spot_now, 2)
        t1       = dns[0] if dns else round(float(vol_trig) - 3, 2)
        t2       = _safe_t2_put(t1, all_lvls)
        op_score = min(3, m1_score + 1)
        hard_rules.append(f"EXIT PUT immediately if SPY recovers {vol_trig}.")
        if at_move_low:
            hard_rules.append(
                f"⚠ SPY at 1D Move Low {move_1d_low} — bounce possible. Monitor closely.")'''

NEW_APP = '''    elif gamma_regime == "NEGATIVE_GAMMA" and vol_trig:
        # Abaixo do Vol Trigger → PUT TREND
        decision = "PUT TREND"
        reason   = (f"SPY below Vol Trigger {vol_trig}."
                    " Negative gamma — dealers amplify the move downward.")
        stop     = f"SPY closes back above {vol_trig}."

        # Alvos PUT TREND: só combos e spy_levels ABAIXO do spot_now
        # Put Wall nunca é alvo automático — é suporte extremo estrutural
        _put_candidates = sorted(
            [l for l in (spy.get('combos') or []) + (spy.get('spy_levels') or [])
             if isinstance(l, (int, float)) and float(l) < float(spot_now)],
            reverse=True
        )
        # Filtra só níveis próximos (dentro de 8 pts)
        _put_nearby = [l for l in _put_candidates
                       if float(spot_now) - float(l) <= 8.0]

        t1 = _put_nearby[0] if _put_nearby else None
        t2 = _put_nearby[1] if len(_put_nearby) >= 2 else None

        # Validação final: nunca alvo acima ou igual ao spot
        if t1 and float(t1) >= float(spot_now): t1 = None
        if t2 and float(t2) >= float(spot_now): t2 = None

        # Put Wall como nota de suporte extremo
        pw_note = f" Put Wall {put_wall} = suporte extremo." if put_wall else ""
        entry   = f"Buy put OTM. SPY accepted below {vol_trig}.{pw_note}"

        op_score = min(3, m1_score + 1)
        hard_rules.append(f"EXIT PUT immediately if SPY recovers {vol_trig}.")
        if at_move_low:
            hard_rules.append(
                f"⚠ SPY at 1D Move Low {move_1d_low} — bounce possible. Monitor closely.")'''

# ══════════════════════════════════════════════════════════════════════
# PATCH 2 — index.html: esconde strikes e plano se chase_warning
# ══════════════════════════════════════════════════════════════════════

OLD_HTML = '''    // Strikes sugeridos (so se nao for NO TRADE)
    let strikesHtml = '';
    if (!isNo && sp && lv.vol_trigger) {'''

NEW_HTML = '''    // Strikes sugeridos (so se nao for NO TRADE e sem chase warning)
    let strikesHtml = '';
    if (!isNo && !d.chase_warning && sp && lv.vol_trigger) {'''

# Esconde bloco Plano de Trade se chase_warning
OLD_PLAN = '''    ${row('#16a34a', 'Entrada',  m2d.entry)}
    ${row('#dc2626', 'Stop',     m2d.stop)}
    ${row('#3b82f6', 'Target 1', m2d.target_1)}
    ${row('#8b5cf6', 'Target 2', m2d.target_2)}
    ${row('#dc2626', 'Risco',    m2d.risk)}
    ${row('#94a3b8', 'Score PDF', score ? score+'/5' : '—')}'''

NEW_PLAN = '''    ${m2d.chase_warning ? '' : row('#16a34a', 'Entrada',  m2d.entry)}
    ${m2d.chase_warning ? '' : row('#dc2626', 'Stop',     m2d.stop)}
    ${m2d.chase_warning ? '' : row('#3b82f6', 'Target 1', m2d.target_1)}
    ${m2d.chase_warning ? '' : row('#8b5cf6', 'Target 2', m2d.target_2)}
    ${row('#dc2626', 'Risco',    m2d.risk)}
    ${row('#94a3b8', 'Score PDF', score ? score+'/5' : '—')}'''

# ══════════════════════════════════════════════════════════════════════
# Aplicar
# ══════════════════════════════════════════════════════════════════════

if len(sys.argv) < 3:
    print("Uso: python3 patch_put_targets_v2.py ~/RBC/app.py ~/RBC/templates/index.html")
    sys.exit(1)

app_path  = sys.argv[1]
html_path = sys.argv[2]
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

# app.py
acontent = open(app_path).read()
if OLD_APP not in acontent:
    print("ERRO — bloco PUT TREND não encontrado em app.py")
    sys.exit(1)
shutil.copy2(app_path, app_path.replace(".py", f"_backup_{ts}.py"))
acontent = acontent.replace(OLD_APP, NEW_APP, 1)
ast.parse(acontent)
open(app_path, 'w').write(acontent)
print("✅ app.py — PUT TREND alvos corrigidos")

# index.html
hcontent = open(html_path).read()
errors = []
for old, label in [(OLD_HTML, "strikes chase guard"), (OLD_PLAN, "plano chase guard")]:
    if old not in hcontent:
        errors.append(label)
if errors:
    print(f"ERRO — não encontrado em index.html: {', '.join(errors)}")
    sys.exit(1)
shutil.copy2(html_path, html_path.replace(".html", f"_backup_{ts}.html"))
hcontent = hcontent.replace(OLD_HTML, NEW_HTML, 1)
hcontent = hcontent.replace(OLD_PLAN, NEW_PLAN, 1)
open(html_path, 'w').write(hcontent)
print("✅ index.html — strikes e plano ocultos quando chase_warning")
print()
print("Próximo passo:")
print("  git add app.py templates/index.html")
print('  git commit -m "APROVADO: PUT TREND alvos próximos + chase warning oculta plano e strikes"')
print("  git push")
