"""
RBC EUA — Patch Risk Pivot v2 (Opcao A — camadas separadas)
============================================================
Vol Trigger = regime ESTRUTURAL  → gamma_regime (motor INTACTO)
Risk Pivot  = linha OPERACIONAL  → camada nova, informativa

Modo 1: extrai risk_pivot SPY do PDF (SPX/10 se necessario)
Modo 2: adiciona camada operacional SEM tocar no gamma_regime:
  - operational_regime_line (RP prioritario, VT fallback)
  - operational_regime_source
  - operational_regime (ABOVE_LINE / BELOW_LINE)
  - distance_to_operational_pct
  - regime_zone TRANSITION (±0.15%)
  - regime_strength (moderate/clear/extended)
  - operational_note quando estrutural e operacional DIVERGEM
    (SPY entre Risk Pivot e Vol Trigger = zona intermediaria)
  - warnings em hard_rules

O que NAO muda:
  - gamma_regime continua 100%% baseado no Vol Trigger
  - motor de decisao, textos, entry/stop, next_setup — intactos
  - one_sentence intacto (continua VT, coerente com o motor)

Uso: python3 patch_risk_pivot_v2.py ~/RBC/app.py ~/RBC/templates/index.html
"""
import sys, shutil, ast
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# APP.PY — 4 substituições
# ══════════════════════════════════════════════════════════════════════

# 1. Prompt: adiciona risk_pivot no bloco spy
A1_OLD = '''  "spy": {{
    "reference_price": null,
    "call_wall": null,'''

A1_NEW = '''  "spy": {{
    "reference_price": null,
    "risk_pivot": null,
    "call_wall": null,'''

# 2. Prompt: regra de extração
A2_OLD = '''- risk_pivot_spx: extract the Risk Pivot SPX level if mentioned'''

A2_NEW = '''- risk_pivot_spx: extract the Risk Pivot SPX level if mentioned
- spy.risk_pivot: SPY Risk Pivot level if mentioned; if only SPX Risk Pivot is given, divide by 10 (e.g. SPX 7400 -> SPY 740.0)'''

# 3. Camada operacional ADICIONADA após o bloco de regime original.
#    O bloco gamma_regime original é preservado byte a byte.
A3_OLD = '''    # ── Regime ──
    gamma_regime = (
        "POSITIVE_GAMMA"
        if (vol_trig and float(spot_now) >= float(vol_trig))
        else "NEGATIVE_GAMMA"
    )'''

A3_NEW = '''    # ── Regime ──
    gamma_regime = (
        "POSITIVE_GAMMA"
        if (vol_trig and float(spot_now) >= float(vol_trig))
        else "NEGATIVE_GAMMA"
    )

    # ── Camada OPERACIONAL — Risk Pivot (curso SpotGamma) ─────────────
    # Vol Trigger = regime ESTRUTURAL (gamma_regime acima, motor intacto).
    # Risk Pivot  = linha OPERACIONAL intraday — incorpora posicoes 0DTE.
    # Camadas separadas: o motor decide pelo estrutural; o operacional
    # informa zona de transicao, chase risk e divergencia entre linhas.
    risk_pivot = None
    try:
        _rp = data.get("risk_pivot")
        if _rp:
            risk_pivot = float(_rp)
            if risk_pivot > 2000:  # veio em escala SPX → converte p/ SPY
                risk_pivot = round(risk_pivot / 10, 2)
    except (ValueError, TypeError):
        risk_pivot = None

    operational_regime_line   = risk_pivot or (float(vol_trig) if vol_trig else None)
    operational_regime_source = "RISK_PIVOT" if risk_pivot else ("VOL_TRIGGER" if vol_trig else None)

    distance_to_operational_pct = None
    operational_regime          = None
    regime_zone                 = None
    regime_strength             = None
    if operational_regime_line and spot_now:
        distance_to_operational_pct = round(
            (float(spot_now) - operational_regime_line) / operational_regime_line * 100, 3)
        operational_regime = "ABOVE_LINE" if distance_to_operational_pct >= 0 else "BELOW_LINE"
        _abs_d = abs(distance_to_operational_pct)
        if _abs_d <= 0.15:
            regime_zone     = "TRANSITION"
            regime_strength = "transition"
        elif _abs_d <= 0.35:
            regime_strength = "moderate"
        elif _abs_d <= 0.80:
            regime_strength = "clear"
        else:
            regime_strength = "extended"  # esticado = chase risk

    # Divergencia entre camadas: SPY entre Risk Pivot e Vol Trigger
    operational_note = None
    if risk_pivot and vol_trig and spot_now:
        _s, _vt_v = float(spot_now), float(vol_trig)
        _above_rp = _s >= risk_pivot
        _above_vt = _s >= _vt_v
        if _above_rp != _above_vt:
            if _above_rp:
                operational_note = (
                    f"SPY entre Risk Pivot {risk_pivot} e Vol Trigger {_vt_v} — "
                    f"zona intermediaria: risco operacional controlado, mas regime "
                    f"estrutural ainda negativo. Exigir confirmacao extra.")
            else:
                operational_note = (
                    f"SPY entre Vol Trigger {_vt_v} e Risk Pivot {risk_pivot} — "
                    f"zona intermediaria: regime estrutural positivo, mas linha "
                    f"operacional perdida. Exigir confirmacao extra.")'''

# 4. Hard rules: warnings da camada operacional
A4_OLD = '''    # Hard rules obrigatórias
    hard_rules.append("Saida obrigatoria 12:30 ET se nao houver follow-through.")'''

A4_NEW = '''    # Hard rules obrigatórias
    hard_rules.append("Saida obrigatoria 12:30 ET se nao houver follow-through.")
    if regime_zone == "TRANSITION":
        hard_rules.append(
            f"⚠ SPY a {abs(distance_to_operational_pct):.2f}% da linha operacional "
            f"({operational_regime_source} {operational_regime_line}) — zona de TRANSICAO. "
            f"Toque nao e aceitacao: aguardar 2+ velas fechadas do lado escolhido.")
    elif regime_strength == "extended":
        hard_rules.append(
            f"⚠ SPY esticado {abs(distance_to_operational_pct):.2f}% da linha operacional "
            f"({operational_regime_source} {operational_regime_line}) — chase risk elevado. Nao perseguir.")
    if operational_note:
        hard_rules.append(f"⚠ {operational_note}")'''

# 5. Output: campos da camada operacional no rbc_decision
A5_OLD = '''        "gamma_regime":     gamma_regime,'''

A5_NEW = '''        "gamma_regime":     gamma_regime,
        "risk_pivot":       risk_pivot,
        "operational_regime_line":     operational_regime_line,
        "operational_regime_source":   operational_regime_source,
        "operational_regime":          operational_regime,
        "distance_to_operational_pct": distance_to_operational_pct,
        "regime_zone":      regime_zone,
        "regime_strength":  regime_strength,
        "operational_note": operational_note,'''

# ══════════════════════════════════════════════════════════════════════
# INDEX.HTML — 1 substituição: envia risk_pivot no body do runModo2
# ══════════════════════════════════════════════════════════════════════

H1_OLD = '''        spot_open: document.getElementById('spot_open').value,
        spot_now:  spot_now,'''

H1_NEW = '''        spot_open: document.getElementById('spot_open').value,
        spot_now:  spot_now,
        risk_pivot: (window._pdfData && (
                      (window._pdfData.spy && window._pdfData.spy.risk_pivot) ||
                      (window._pdfData.macro && window._pdfData.macro.risk_pivot_spx
                        ? window._pdfData.macro.risk_pivot_spx / 10 : null)
                    )) || null,'''

# ══════════════════════════════════════════════════════════════════════
# Aplicar
# ══════════════════════════════════════════════════════════════════════

if len(sys.argv) < 3:
    print("Uso: python3 patch_risk_pivot_v2.py ~/RBC/app.py ~/RBC/templates/index.html")
    sys.exit(1)

app_path  = sys.argv[1]
html_path = sys.argv[2]
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

app_patches = [
    (A1_OLD, A1_NEW, "prompt: risk_pivot no bloco spy"),
    (A2_OLD, A2_NEW, "prompt: regra de extracao SPX/10"),
    (A3_OLD, A3_NEW, "camada operacional ADICIONADA (estrutural intacto)"),
    (A4_OLD, A4_NEW, "hard rules: transicao, chase, divergencia"),
    (A5_OLD, A5_NEW, "output: campos operacionais"),
]

acontent = open(app_path).read()
for old, _, label in app_patches:
    n = acontent.count(old)
    if n == 0:
        print(f"ERRO — '{label}' nao encontrado em app.py")
        sys.exit(1)
    if n > 1:
        print(f"ERRO — '{label}' encontrado {n}x (ancora nao unica)")
        sys.exit(1)

hcontent = open(html_path).read()
n = hcontent.count(H1_OLD)
if n != 1:
    print(f"ERRO — ancora frontend encontrada {n}x")
    sys.exit(1)

shutil.copy2(app_path,  app_path.replace(".py",  f"_backup_{ts}.py"))
shutil.copy2(html_path, html_path.replace(".html", f"_backup_{ts}.html"))
print(f"Backups criados ({ts})")

for old, new, label in app_patches:
    acontent = acontent.replace(old, new, 1)
    print(f"✅ app.py — {label}")

ast.parse(acontent)
open(app_path, 'w').write(acontent)

hcontent = hcontent.replace(H1_OLD, H1_NEW, 1)
open(html_path, 'w').write(hcontent)
print("✅ index.html — risk_pivot enviado no body do Modo 2")
print()
print("Verificacao de coerencia: gamma_regime estrutural preservado byte a byte.")
print()
print("Proximo passo:")
print("  git add app.py templates/index.html")
print('  git commit -m "APROVADO: camada operacional Risk Pivot — estrutural intacto (Opcao A)"')
print("  git push")
