"""
RBC EUA — Patch Anchor Engine v2 (curso SpotGamma)
================================================
"Sem ancora, nao existe trade bem estruturado." — Brent

Calcula o destino estrutural em CADA direcao (CALL e PUT):
  - anchor price + type (CALL_WALL, PUT_WALL, COMBO, 1D_MOVE, SPY_LEVEL)
  - anchor_quality: HIGH (walls) | MEDIUM (combos/1D moves) |
                    LOW (spy_levels) | NONE (sem destino = sem edge)
  - distance_pts / distance_pct (espaco ate o alvo)
  - reached: preco ja colado na ancora = alvo consumido = chase

Warnings nas hard_rules APOS os do Location Engine.
Bloco visual "Ancoras" no card Regime, apos Localizacao.

NAO altera: decision, entry, stop, targets, next_setup, Modo 3, Journal.
Risk Pivot e linha de regime — NAO entra como ancora (correto).

Uso: python3 patch_anchor_engine_v2.py ~/RBC/app.py ~/RBC/templates/index.html
"""
import sys, shutil, ast
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# APP.PY — 4 substituições
# ══════════════════════════════════════════════════════════════════════

# 0. Helper de niveis de gamma + _level_type reconhece ABS/LARGE_GAMMA
A0_OLD = """    def _level_type(v, s, rp, m1h, m1l):
        \"\"\"Classifica o tipo de um nivel para o Location Engine.\"\"\"
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
        return 'COMBO/LEVEL'"""

A0_NEW = """    def _abs_large_gamma(s):
        \"\"\"Extrai absolute gamma strike e large gamma levels (se existirem).
        Defensivo: cobre os nomes do blueprint e formatos num/dict.\"\"\"
        abs_g = (s.get('absolute_gamma_strike') or s.get('absolute_gamma')
                 or s.get('abs_gamma'))
        abs_g = float(abs_g) if isinstance(abs_g, (int, float)) else None
        larges = []
        raw = list(s.get('large_gamma_levels') or [])
        for i in (1, 2, 3, 4):
            v = s.get(f'large_gamma_{i}')
            if v is not None:
                raw.append(v)
        for g in raw:
            if isinstance(g, (int, float)):
                larges.append(float(g))
            elif isinstance(g, dict):
                gv = g.get('level') or g.get('price') or g.get('strike')
                if isinstance(gv, (int, float)):
                    larges.append(float(gv))
        return abs_g, larges

    def _level_type(v, s, rp, m1h, m1l):
        \"\"\"Classifica o tipo de um nivel para o Location Engine.\"\"\"
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
        _ag, _lgs = _abs_large_gamma(s)
        if _ag and vf == _ag:
            return 'ABS_GAMMA'
        if any(vf == g for g in _lgs):
            return 'LARGE_GAMMA'
        return 'COMBO/LEVEL'"""

# 1. Função find_trade_anchors após analyze_trade_location
A1_OLD = '''                f"{loc['range_position']} ({_z}). Qualidade: {loc['location_quality']}.")

        return loc'''

A1_NEW = '''                f"{loc['range_position']} ({_z}). Qualidade: {loc['location_quality']}.")

        return loc

    def find_trade_anchors(spot, s, near, m1h=None, m1l=None):
        """Anchor Engine — curso SpotGamma.
        Destino estrutural do trade em cada direcao.
        Sem ancora = sem edge. Ancora ja alcancada = chase."""
        if not spot:
            return None
        spot_f = float(spot)

        cands = []
        if s.get('call_wall'):
            cands.append((float(s['call_wall']), 'CALL_WALL', 'HIGH'))
        if s.get('put_wall'):
            cands.append((float(s['put_wall']), 'PUT_WALL', 'HIGH'))
        _ag, _lgs = _abs_large_gamma(s)
        if _ag:
            cands.append((_ag, 'ABS_GAMMA', 'HIGH'))
        for g in _lgs:
            cands.append((g, 'LARGE_GAMMA', 'HIGH'))
        for c in (s.get('combos') or s.get('combo_strikes') or []):
            if isinstance(c, (int, float)):
                cands.append((float(c), 'COMBO', 'MEDIUM'))
        if m1h:
            cands.append((float(m1h), '1D_MOVE_HIGH', 'MEDIUM'))
        if m1l:
            cands.append((float(m1l), '1D_MOVE_LOW', 'MEDIUM'))
        for l in (s.get('spy_levels') or []):
            if isinstance(l, (int, float)):
                cands.append((float(l), 'SPY_LEVEL', 'LOW'))

        ups = sorted([c for c in cands if c[0] > spot_f], key=lambda x: x[0])
        dns = sorted([c for c in cands if c[0] < spot_f], key=lambda x: -x[0])

        def _mk(lst):
            if not lst:
                return {"price": None, "type": None, "quality": "NONE",
                        "distance_pts": None, "distance_pct": None, "reached": False}
            price, typ, qual = lst[0]
            dist = round(abs(price - spot_f), 2)
            return {
                "price": price, "type": typ, "quality": qual,
                "distance_pts": dist,
                "distance_pct": round(dist / spot_f * 100, 3),
                "reached": dist <= near,
            }

        up, dn = _mk(ups), _mk(dns)
        note = None
        if up["quality"] == "NONE" and dn["quality"] == "NONE":
            note = "Sem ancoras estruturais em nenhuma direcao — sem destino definido."
        elif up["quality"] == "NONE":
            note = "CALL sem ancora superior clara — trade possivel mas sem destino estrutural."
        elif dn["quality"] == "NONE":
            note = "PUT sem ancora inferior clara — trade possivel mas sem destino estrutural."
        return {"upside": up, "downside": dn, "anchor_note": note}'''

# 2. Chamada após o Location Engine
A2_OLD = '''    location = analyze_trade_location(
        spot_now, _loc_levels, near_level, spy,
        rp=risk_pivot, m1h=move_1d_high, m1l=move_1d_low)'''

A2_NEW = '''    location = analyze_trade_location(
        spot_now, _loc_levels, near_level, spy,
        rp=risk_pivot, m1h=move_1d_high, m1l=move_1d_low)

    # ── Anchor Engine (curso SpotGamma) ───────────────────────────────
    anchors = find_trade_anchors(
        spot_now, spy, near_level, m1h=move_1d_high, m1l=move_1d_low)'''

# 3. Warnings APÓS os do Location Engine
A3_OLD = '''        if decision and "PUT" in decision and location.get("location_zone") == "NEAR_SUPPORT" \\
                and not location.get("is_near_put_wall"):
            hard_rules.append(
                f"⚠ LOCATION: PUT colado no suporte "
                f"{location['nearest_support']} ({location['nearest_support_type']}) "
                f"— aguardar perda do nivel com aceitacao abaixo.")'''

A3_NEW = '''        if decision and "PUT" in decision and location.get("location_zone") == "NEAR_SUPPORT" \\
                and not location.get("is_near_put_wall"):
            hard_rules.append(
                f"⚠ LOCATION: PUT colado no suporte "
                f"{location['nearest_support']} ({location['nearest_support_type']}) "
                f"— aguardar perda do nivel com aceitacao abaixo.")
    # ── Warnings do Anchor Engine (apos Location) ─────────────────────
    if anchors:
        if anchors.get("anchor_note"):
            hard_rules.append(f"⚠ ANCHOR: {anchors['anchor_note']}")
        if decision and "CALL" in decision and anchors["upside"]["reached"]:
            hard_rules.append(
                f"⚠ ANCHOR: ancora superior {anchors['upside']['price']} "
                f"({anchors['upside']['type']}) ja alcancada — alvo consumido, chase risk.")
        if decision and "PUT" in decision and anchors["downside"]["reached"]:
            hard_rules.append(
                f"⚠ ANCHOR: ancora inferior {anchors['downside']['price']} "
                f"({anchors['downside']['type']}) ja alcancada — alvo consumido, chase risk.")'''

# 4. Output: anchors no rbc_decision
A4_OLD = '''        "location":         location,'''

A4_NEW = '''        "location":         location,
        "anchors":          anchors,'''

# ══════════════════════════════════════════════════════════════════════
# INDEX.HTML — bloco Âncoras após Localização no card Regime
# ══════════════════════════════════════════════════════════════════════

H1_OLD = '''      ${d.location.location_warning ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.location.location_warning}</div>` : ''}
    </div>` : ''}
  </div>'''

H1_NEW = '''      ${d.location.location_warning ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.location.location_warning}</div>` : ''}
    </div>` : ''}
    ${d.anchors ? `
    <div style="margin-top:6px;padding:8px 10px;background:#fafafa;border:0.5px solid #e2e8f0;border-radius:8px;">
      <div style="font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px;">Âncoras</div>
      <div style="font-size:12px;color:#1e293b;line-height:1.7;">↑ CALL: ${d.anchors.upside.quality === 'NONE' ? `<span style="color:#dc2626;font-weight:600;">sem âncora — sem destino estrutural</span>` : `<b>${d.anchors.upside.price}</b> <span style="color:#94a3b8;font-size:10px;">${d.anchors.upside.type}</span> · ${d.anchors.upside.distance_pts} pts <span style="color:${d.anchors.upside.quality === 'HIGH' ? '#16a34a' : d.anchors.upside.quality === 'MEDIUM' ? '#d97706' : '#64748b'};font-weight:600;">${d.anchors.upside.quality}</span>${d.anchors.upside.reached ? ` <span style="color:#dc2626;font-weight:600;">· JÁ ALCANÇADA</span>` : ''}`}<br>↓ PUT: ${d.anchors.downside.quality === 'NONE' ? `<span style="color:#dc2626;font-weight:600;">sem âncora — sem destino estrutural</span>` : `<b>${d.anchors.downside.price}</b> <span style="color:#94a3b8;font-size:10px;">${d.anchors.downside.type}</span> · ${d.anchors.downside.distance_pts} pts <span style="color:${d.anchors.downside.quality === 'HIGH' ? '#16a34a' : d.anchors.downside.quality === 'MEDIUM' ? '#d97706' : '#64748b'};font-weight:600;">${d.anchors.downside.quality}</span>${d.anchors.downside.reached ? ` <span style="color:#dc2626;font-weight:600;">· JÁ ALCANÇADA</span>` : ''}`}</div>
      ${d.anchors.anchor_note ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.anchors.anchor_note}</div>` : ''}
    </div>` : ''}
  </div>'''

# ══════════════════════════════════════════════════════════════════════
# Aplicar
# ══════════════════════════════════════════════════════════════════════

if len(sys.argv) < 3:
    print("Uso: python3 patch_anchor_engine_v2.py ~/RBC/app.py ~/RBC/templates/index.html")
    sys.exit(1)

app_path  = sys.argv[1]
html_path = sys.argv[2]
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

app_patches = [
    (A0_OLD, A0_NEW, "_abs_large_gamma + _level_type reconhece ABS/LARGE_GAMMA"),
    (A1_OLD, A1_NEW, "funcao find_trade_anchors"),
    (A2_OLD, A2_NEW, "chamada do Anchor Engine (apos Location)"),
    (A3_OLD, A3_NEW, "warnings APOS os do Location"),
    (A4_OLD, A4_NEW, "anchors no output"),
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
print("✅ index.html — bloco Ancoras no card Regime")
print()
print("Ordem das hard_rules: 12:30 → Risk Pivot → Location → Anchor")
print()
print("Proximo passo:")
print("  git add app.py templates/index.html")
print('  git commit -m "APROVADO: Anchor Engine v2 — ABS/LARGE_GAMMA como ancoras HIGH"')
print("  git push")
