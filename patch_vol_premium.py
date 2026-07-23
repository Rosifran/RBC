"""
RBC EUA — Patch Volatility Premium Engine (curso SpotGamma)
============================================================
A conta do Brent: implied_rv = VIX - 3.5 (spread historico).

  premium_state: RV1M < implied-2 = EXPENSIVE | > implied+2 = CHEAP | FAIR
  rv_trend:      RV5D > RV1M+2 = ACCELERATING | < RV1M-2 = COOLING | STABLE

Leituras combinadas:
  EXPENSIVE+ACCELERATING → caro porem justificado; compra exige direcao clara
  EXPENSIVE+STABLE       → opcoes caras; preferir spread/estrutura
  CHEAP                  → compra direta favorecida

Inputs: 2 campos OPCIONAIS no Modo 2 (RV 1M %, RV 5D % — da tela SpotGamma).
Vazios = modulo nao roda, nada aparece (zero poluicao).
Exibicao: 1 linha dentro do box Linha Operacional (card Regime).
Overlay: EXPENSIVE → reasons + GOOD→CAUTION (padrao aprovado do calendar).
Output: vol_premium completo — pronto para o Asymmetry Engine (Patch 3).

NAO altera: motor, decision, entry/stop/targets, next_setup,
evaluate_hard_blocks, calendar, Modo 3, Journal.

Uso: python3 patch_vol_premium.py ~/RBC/app.py ~/RBC/templates/index.html
"""
import sys, shutil, ast
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# APP.PY — 3 substituições
# ══════════════════════════════════════════════════════════════════════

# 1. Função analyze_vol_premium (módulo-level, antes das rotas do calendar)
A1_OLD = '''@app.route("/api/calendar", methods=["POST"])'''

A1_NEW = '''def analyze_vol_premium(vix_now, rv_1m, rv_5d, spread=3.5):
    """Volatility Premium — VIX vs Realized Vol (curso SpotGamma).
    implied_rv = VIX - spread historico. Compara com RV 1M e RV 5D."""
    try:
        vix = float(vix_now) if vix_now not in (None, "") else None
        r1  = float(rv_1m)  if rv_1m  not in (None, "") else None
        r5  = float(rv_5d)  if rv_5d  not in (None, "") else None
    except (ValueError, TypeError):
        return None
    if not vix or r1 is None:
        return None

    implied_rv = round(vix - spread, 1)
    if r1 < implied_rv - 2:
        premium_state = "EXPENSIVE"
    elif r1 > implied_rv + 2:
        premium_state = "CHEAP"
    else:
        premium_state = "FAIR"

    rv_trend = None
    if r5 is not None:
        if r5 > r1 + 2:
            rv_trend = "ACCELERATING"
        elif r5 < r1 - 2:
            rv_trend = "COOLING"
        else:
            rv_trend = "STABLE"

    note = None
    if premium_state == "EXPENSIVE" and rv_trend == "ACCELERATING":
        note = (f"Vol premium: VIX {vix} caro vs RV1M {r1}%, mas RV5D {r5}% "
                f"acelerando — caro porem justificado. Nao vender vol; "
                f"compra exige direcao muito clara.")
    elif premium_state == "EXPENSIVE":
        note = (f"Vol premium: VIX {vix} caro vs RV1M {r1}% (esperado ~{implied_rv}%) "
                f"— opcoes caras. Preferir spread/estrutura ou exigir edge maior.")
    elif premium_state == "CHEAP":
        note = (f"Vol premium: VIX {vix} barato vs RV1M {r1}% — "
                f"compra direta favorecida.")

    return {
        "vix": vix, "spread": spread, "implied_rv": implied_rv,
        "rv_1m": r1, "rv_5d": r5,
        "premium_state": premium_state, "rv_trend": rv_trend,
        "note": note,
    }


@app.route("/api/calendar", methods=["POST"])'''

# 2. Integração no Modo 2 (após o ajuste do calendar)
A2_OLD = '''    # Calendar ajusta a qualidade (regra aprovada: sem bloquear ate o Score)
    if calendar_risk.get("risk_level") in ("HIGH", "EXTREME"):
        if calendar_risk.get("note"):
            intelligence_block["reasons"].append(calendar_risk["note"])
        if intelligence_block.get("entry_quality") == "GOOD":
            intelligence_block["entry_quality"] = "CAUTION"'''

A2_NEW = '''    # Calendar ajusta a qualidade (regra aprovada: sem bloquear ate o Score)
    if calendar_risk.get("risk_level") in ("HIGH", "EXTREME"):
        if calendar_risk.get("note"):
            intelligence_block["reasons"].append(calendar_risk["note"])
        if intelligence_block.get("entry_quality") == "GOOD":
            intelligence_block["entry_quality"] = "CAUTION"

    # ── Volatility Premium (VIX vs RV — curso SpotGamma) ──────────────
    vol_premium = analyze_vol_premium(
        vix_now, data.get("rv_1m"), data.get("rv_5d"))
    if vol_premium and vol_premium.get("premium_state") == "EXPENSIVE":
        if vol_premium.get("note"):
            intelligence_block["reasons"].append(vol_premium["note"])
        if intelligence_block.get("entry_quality") == "GOOD":
            intelligence_block["entry_quality"] = "CAUTION"'''

# 3. Output
A3_OLD = '''        "calendar_risk":    calendar_risk,'''

A3_NEW = '''        "calendar_risk":    calendar_risk,
        "vol_premium":      vol_premium,'''

# ══════════════════════════════════════════════════════════════════════
# INDEX.HTML — 3 substituições
# ══════════════════════════════════════════════════════════════════════

# 1. Dois campos opcionais no form do Modo 2 (após SPY — abertura)
H1_OLD = '''      <div class="form-group">
        <label class="form-label">SPY — abertura</label>
        <input class="form-input" id="spot_open" type="number" step="0.01" placeholder="Preenchido pelo PDF">
        <span class="form-hint">Auto-preenchido pelo Modo 1</span>
      </div>'''

H1_NEW = '''      <div class="form-group">
        <label class="form-label">SPY — abertura</label>
        <input class="form-input" id="spot_open" type="number" step="0.01" placeholder="Preenchido pelo PDF">
        <span class="form-hint">Auto-preenchido pelo Modo 1</span>
      </div>
      <div class="form-group">
        <label class="form-label">RV 1M %</label>
        <input class="form-input" id="rv_1m" type="number" step="0.1" placeholder="ex: 13.0">
        <span class="form-hint">Realized Vol 1 mês (SpotGamma) — opcional</span>
      </div>
      <div class="form-group">
        <label class="form-label">RV 5D %</label>
        <input class="form-input" id="rv_5d" type="number" step="0.1" placeholder="ex: 20.0">
        <span class="form-hint">Realized Vol 5 dias — opcional</span>
      </div>'''

# 2. Body do runModo2 envia os campos
H2_OLD = '''        spot_open: document.getElementById('spot_open').value,
        spot_now:  spot_now,'''

H2_NEW = '''        spot_open: document.getElementById('spot_open').value,
        spot_now:  spot_now,
        rv_1m: parseFloat(document.getElementById('rv_1m').value) || null,
        rv_5d: parseFloat(document.getElementById('rv_5d').value) || null,'''

# 3. Linha no box Linha Operacional (card Regime)
H3_OLD = '''      ${d.operational_note ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.operational_note}</div>` : ''}
    </div>` : ''}'''

H3_NEW = '''      ${d.operational_note ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.operational_note}</div>` : ''}
      ${d.vol_premium ? `<div style="font-size:11px;color:#475569;margin-top:4px;padding-top:4px;border-top:0.5px solid #e0e7ff;">Vol Premium: VIX <b>${d.vol_premium.vix}</b> → RV esperada ~${d.vol_premium.implied_rv}% · RV1M ${d.vol_premium.rv_1m}% <span style="font-weight:600;color:${d.vol_premium.premium_state === 'EXPENSIVE' ? '#dc2626' : d.vol_premium.premium_state === 'CHEAP' ? '#16a34a' : '#64748b'};">${d.vol_premium.premium_state === 'EXPENSIVE' ? 'CARO' : d.vol_premium.premium_state === 'CHEAP' ? 'BARATO' : 'JUSTO'}</span>${(d.vol_premium.rv_5d !== null && d.vol_premium.rv_5d !== undefined) ? ` · RV5D ${d.vol_premium.rv_5d}%${d.vol_premium.rv_trend === 'ACCELERATING' ? ` <span style="color:#d97706;font-weight:600;">acelerando</span>` : d.vol_premium.rv_trend === 'COOLING' ? ' esfriando' : ' estável'}` : ''}</div>` : ''}
    </div>` : ''}'''

# ══════════════════════════════════════════════════════════════════════
# Aplicar
# ══════════════════════════════════════════════════════════════════════

if len(sys.argv) < 3:
    print("Uso: python3 patch_vol_premium.py ~/RBC/app.py ~/RBC/templates/index.html")
    sys.exit(1)

app_path, html_path = sys.argv[1], sys.argv[2]
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

app_patches = [
    (A1_OLD, A1_NEW, "funcao analyze_vol_premium"),
    (A2_OLD, A2_NEW, "integracao Modo 2 (EXPENSIVE → CAUTION)"),
    (A3_OLD, A3_NEW, "vol_premium no output"),
]
html_patches = [
    (H1_OLD, H1_NEW, "inputs RV 1M / RV 5D (opcionais)"),
    (H2_OLD, H2_NEW, "body runModo2 envia rv_1m/rv_5d"),
    (H3_OLD, H3_NEW, "linha Vol Premium no card Regime"),
]

acontent = open(app_path).read()
for old, _, label in app_patches:
    n = acontent.count(old)
    if n != 1:
        print(f"ERRO — '{label}': ancora encontrada {n}x em app.py")
        sys.exit(1)

hcontent = open(html_path).read()
for old, _, label in html_patches:
    n = hcontent.count(old)
    if n != 1:
        print(f"ERRO — '{label}': ancora encontrada {n}x em index.html")
        sys.exit(1)

shutil.copy2(app_path,  app_path.replace(".py",  f"_backup_{ts}.py"))
shutil.copy2(html_path, html_path.replace(".html", f"_backup_{ts}.html"))
print(f"Backups criados ({ts})")

for old, new, label in app_patches:
    acontent = acontent.replace(old, new, 1)
    print(f"✅ app.py — {label}")

ast.parse(acontent)
open(app_path, 'w').write(acontent)

for old, new, label in html_patches:
    hcontent = hcontent.replace(old, new, 1)
    print(f"✅ index.html — {label}")

open(html_path, 'w').write(hcontent)
print()
print("Teste de hoje (a aula do Brent): VIX 21.59 + RV1M 13 + RV5D 20")
print("  → esperado: CARO · acelerando — 'caro porem justificado'")
print()
print("Proximo passo:")
print("  git add app.py templates/index.html")
print('  git commit -m "APROVADO: Volatility Premium Engine — VIX vs RV"')
print("  git push")
