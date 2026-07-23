"""
RBC EUA — Patch Location Engine v3 (compativel com Risk Pivot v2)
==================================================================
Ordem das camadas preservada nas hard_rules:
  1. Saida obrigatoria 12:30 ET          (original)
  2. Warnings Risk Pivot / operacional   (Risk Pivot v2 — INTACTOS)
  3. Warnings do Location Engine         (este patch — ADICIONADOS APOS)

Output location completo:
  nearest_support, nearest_support_type,
  nearest_resistance, nearest_resistance_type,
  distance_to_support, distance_to_resistance,
  range_position, location_zone, location_quality,
  location_warning, location_report,
  is_near_call_wall, is_near_put_wall, is_near_vol_trigger,
  is_near_risk_pivot, is_near_zero_gamma

Risk Pivot incluido nos niveis SO para o Location Engine
(all_lvls original intacto — alvos nao mudam).

NAO altera: decision, entry, stop, targets, next_setup, Modo 3, Journal.

Uso: python3 patch_location_engine_v3.py ~/RBC/app.py ~/RBC/templates/index.html
"""
import sys, shutil, ast
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# APP.PY — 4 substituições
# ══════════════════════════════════════════════════════════════════════

# 1. Função analyze_trade_location junto aos helpers existentes
A1_OLD = '''    def _safe_t2_put(t1, candidates):
        # t2 PUT: next level below t1. Fallback: t1 - 2
        opts = sorted([l for l in candidates if float(l) < float(t1)], reverse=True)
        return opts[0] if opts else round(float(t1) - 2, 2)'''

A1_NEW = '''    def _safe_t2_put(t1, candidates):
        # t2 PUT: next level below t1. Fallback: t1 - 2
        opts = sorted([l for l in candidates if float(l) < float(t1)], reverse=True)
        return opts[0] if opts else round(float(t1) - 2, 2)

    def _level_type(v, s, rp, m1h, m1l):
        """Classifica o tipo de um nivel para o Location Engine."""
        if v is None:
            return None
        vf = float(v)
        if s.get('call_wall')   and vf == float(s['call_wall']):   return 'CALL_WALL'
        if s.get('put_wall')    and vf == float(s['put_wall']):    return 'PUT_WALL'
        if s.get('vol_trigger') and vf == float(s['vol_trigger']): return 'VOL_TRIGGER'
        if s.get('zero_gamma')  and vf == float(s['zero_gamma']):  return 'ZERO_GAMMA'
        if rp  and vf == float(rp):  return 'RISK_PIVOT'
        if m1h and vf == float(m1h): return '1D_MOVE_HIGH'
        if m1l and vf == float(m1l): return '1D_MOVE_LOW'
        return 'COMBO/LEVEL'

    def analyze_trade_location(spot, levels, near, s, rp=None, m1h=None, m1l=None):
        """Location Engine — curso SpotGamma.
        Posicao do spot no micro-range entre os niveis reais do dia.
        Informativo: nao decide, nao altera o motor."""
        if not spot or not levels:
            return None
        spot_f = float(spot)
        sups = [float(l) for l in levels if float(l) < spot_f]
        ress = [float(l) for l in levels if float(l) > spot_f]
        n_sup = max(sups) if sups else None
        n_res = min(ress) if ress else None

        loc = {
            "nearest_support":         n_sup,
            "nearest_support_type":    _level_type(n_sup, s, rp, m1h, m1l),
            "nearest_resistance":      n_res,
            "nearest_resistance_type": _level_type(n_res, s, rp, m1h, m1l),
            "distance_to_support":     round(spot_f - n_sup, 2) if n_sup is not None else None,
            "distance_to_resistance":  round(n_res - spot_f, 2) if n_res is not None else None,
            "range_position":          None,
            "location_zone":           None,
            "location_quality":        None,
            "location_warning":        None,
            "location_report":         None,
            "is_near_call_wall":   bool(s.get('call_wall')   and abs(spot_f - float(s['call_wall']))   <= near),
            "is_near_put_wall":    bool(s.get('put_wall')    and abs(spot_f - float(s['put_wall']))    <= near),
            "is_near_vol_trigger": bool(s.get('vol_trigger') and abs(spot_f - float(s['vol_trigger'])) <= near),
            "is_near_risk_pivot":  bool(rp                   and abs(spot_f - float(rp))               <= near),
            "is_near_zero_gamma":  bool(s.get('zero_gamma')  and abs(spot_f - float(s['zero_gamma']))  <= near),
        }

        if n_sup is not None and n_res is not None and n_res > n_sup:
            rpos = (spot_f - n_sup) / (n_res - n_sup)
            loc["range_position"] = round(rpos, 2)
            if rpos <= 0.25:
                loc["location_zone"] = "NEAR_SUPPORT"
            elif rpos <= 0.40:
                loc["location_zone"] = "LOWER_RANGE"
            elif rpos <= 0.60:
                loc["location_zone"] = "MIDDLE_OF_RANGE"
            elif rpos <= 0.75:
                loc["location_zone"] = "UPPER_RANGE"
            else:
                loc["location_zone"] = "NEAR_RESISTANCE"

        # Qualidade da localizacao
        # DANGEROUS sobrepoe tudo: colado em wall = zona de armadilha,
        # nao de entrada (CALL atrasado na CW / PUT atrasado na PW).
        _z = loc["location_zone"]
        if loc["is_near_call_wall"] or loc["is_near_put_wall"]:
            loc["location_quality"] = "DANGEROUS"
        elif _z in ("NEAR_SUPPORT", "NEAR_RESISTANCE"):
            loc["location_quality"] = "STRONG"   # perto de nivel decisivo comum
        elif _z in ("LOWER_RANGE", "UPPER_RANGE"):
            loc["location_quality"] = "MEDIUM"
        elif _z == "MIDDLE_OF_RANGE":
            loc["location_quality"] = "WEAK"

        # Warning contextual (prioridade: walls > meio do range)
        if loc["is_near_call_wall"]:
            loc["location_warning"] = ("Preco perto do Call Wall — evitar CALL atrasado.")
        elif loc["is_near_put_wall"]:
            loc["location_warning"] = ("Preco perto do Put Wall — evitar PUT atrasado; "
                                       "risco de bounce/V-bottom.")
        elif _z == "MIDDLE_OF_RANGE":
            loc["location_warning"] = ("Preco entre suporte e resistencia, sem edge "
                                       "estrutural claro. Aguardar aproximacao de nivel "
                                       "ou confirmacao.")

        # Relatorio descritivo
        if n_sup is not None and n_res is not None and loc["range_position"] is not None:
            loc["location_report"] = (
                f"SPY {spot_f} entre {n_sup} ({loc['nearest_support_type']}) e "
                f"{n_res} ({loc['nearest_resistance_type']}) — posicao "
                f"{loc['range_position']} ({_z}). Qualidade: {loc['location_quality']}.")

        return loc'''

# 2. Chamada após os alertas 1D Move (risk_pivot já definido neste ponto)
A2_OLD = '''    # ── Alertas 1D Move ──
    at_move_high = bool(move_1d_high and abs(float(spot_now) - float(move_1d_high)) <= near_level)
    at_move_low  = bool(move_1d_low  and abs(float(spot_now) - float(move_1d_low))  <= near_level)'''

A2_NEW = '''    # ── Alertas 1D Move ──
    at_move_high = bool(move_1d_high and abs(float(spot_now) - float(move_1d_high)) <= near_level)
    at_move_low  = bool(move_1d_low  and abs(float(spot_now) - float(move_1d_low))  <= near_level)

    # ── Location Engine (curso SpotGamma) ─────────────────────────────
    # Risk Pivot e 1D Moves incluidos nos niveis SO aqui —
    # all_lvls original intacto (alvos nao mudam).
    _loc_levels = all_lvls[:]
    if risk_pivot:
        _loc_levels.append(risk_pivot)
    if move_1d_high:
        _loc_levels.append(float(move_1d_high))
    if move_1d_low:
        _loc_levels.append(float(move_1d_low))
    location = analyze_trade_location(
        spot_now, _loc_levels, near_level, spy,
        rp=risk_pivot, m1h=move_1d_high, m1l=move_1d_low)'''

# 3. Warnings de localização APÓS os warnings operacionais do Risk Pivot v2
A3_OLD = '''    if operational_note:
        hard_rules.append(f"⚠ {operational_note}")'''

A3_NEW = '''    if operational_note:
        hard_rules.append(f"⚠ {operational_note}")
    # ── Warnings do Location Engine (apos camada operacional) ─────────
    if location:
        if location.get("location_warning"):
            hard_rules.append(f"⚠ LOCATION: {location['location_warning']}")
        if decision and "CALL" in decision and location.get("location_zone") == "NEAR_RESISTANCE" \\
                and not location.get("is_near_call_wall"):
            hard_rules.append(
                f"⚠ LOCATION: CALL colado na resistencia "
                f"{location['nearest_resistance']} ({location['nearest_resistance_type']}) "
                f"— exigir rompimento com aceitacao (2+ velas fechadas acima).")
        if decision and "PUT" in decision and location.get("location_zone") == "NEAR_SUPPORT" \\
                and not location.get("is_near_put_wall"):
            hard_rules.append(
                f"⚠ LOCATION: PUT colado no suporte "
                f"{location['nearest_support']} ({location['nearest_support_type']}) "
                f"— aguardar perda do nivel com aceitacao abaixo.")'''

# 4. Output: location no rbc_decision
A4_OLD = '''        "operational_note": operational_note,'''

A4_NEW = '''        "operational_note": operational_note,
        "location":         location,'''

# ══════════════════════════════════════════════════════════════════════
# INDEX.HTML — 1 substituição: bloco Localização no card Regime
# ══════════════════════════════════════════════════════════════════════

H1_OLD = '''      ${d.operational_note ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.operational_note}</div>` : ''}
    </div>` : ''}
  </div>'''

H1_NEW = '''      ${d.operational_note ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.operational_note}</div>` : ''}
    </div>` : ''}
    ${d.location && d.location.range_position !== null && d.location.range_position !== undefined ? `
    <div style="margin-top:6px;padding:8px 10px;background:#fafafa;border:0.5px solid #e2e8f0;border-radius:8px;">
      <div style="font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px;">Localização ${d.location.location_quality ? `<span style="float:right;color:${d.location.location_quality === 'DANGEROUS' ? '#dc2626' : d.location.location_quality === 'STRONG' ? '#16a34a' : d.location.location_quality === 'MEDIUM' ? '#d97706' : '#64748b'};">${d.location.location_quality}</span>` : ''}</div>
      <div style="font-size:12px;color:#1e293b;line-height:1.5;">Suporte <b>${d.location.nearest_support}</b> <span style="color:#94a3b8;font-size:10px;">${d.location.nearest_support_type || ''}</span> · posição <b>${d.location.range_position}</b>${d.location.location_zone === 'MIDDLE_OF_RANGE' ? ` <span style="color:#dc2626;font-weight:600;">· MEIO DO RANGE</span>` : d.location.location_zone === 'NEAR_RESISTANCE' ? ` <span style="color:#d97706;font-weight:600;">· colado na resistência</span>` : d.location.location_zone === 'NEAR_SUPPORT' ? ` <span style="color:#d97706;font-weight:600;">· colado no suporte</span>` : d.location.location_zone === 'UPPER_RANGE' ? ` · parte alta` : ` · parte baixa`} · Resistência <b>${d.location.nearest_resistance}</b> <span style="color:#94a3b8;font-size:10px;">${d.location.nearest_resistance_type || ''}</span></div>
      ${d.location.location_warning ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.location.location_warning}</div>` : ''}
    </div>` : ''}
  </div>'''

# ══════════════════════════════════════════════════════════════════════
# Aplicar
# ══════════════════════════════════════════════════════════════════════

if len(sys.argv) < 3:
    print("Uso: python3 patch_location_engine_v3.py ~/RBC/app.py ~/RBC/templates/index.html")
    sys.exit(1)

app_path  = sys.argv[1]
html_path = sys.argv[2]
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

app_patches = [
    (A1_OLD, A1_NEW, "funcoes _level_type + analyze_trade_location"),
    (A2_OLD, A2_NEW, "chamada do Location Engine (com risk_pivot)"),
    (A3_OLD, A3_NEW, "warnings APOS camada operacional (ordem preservada)"),
    (A4_OLD, A4_NEW, "location no output"),
]

acontent = open(app_path).read()
for old, _, label in app_patches:
    n = acontent.count(old)
    if n != 1:
        print(f"ERRO — '{label}': ancora encontrada {n}x em app.py")
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
print("✅ index.html — bloco Localizacao (tipos + qualidade + warning)")
print()
print("Ordem das hard_rules: saida 12:30 → Risk Pivot/operacional → Location")
print()
print("Proximo passo:")
print("  git add app.py templates/index.html")
print('  git commit -m "APROVADO: Location Engine v3 — DANGEROUS nos walls + 1D moves"')
print("  git push")
