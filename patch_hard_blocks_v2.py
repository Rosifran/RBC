"""
RBC EUA — Patch Hard Blocks / Intelligence Overlay (curso SpotGamma)
=====================================================================
Camada de inteligencia POS-MOTOR. O motor decide; a camada avalia se
a entrada e limpa (GOOD), merece cautela (CAUTION), e fraca (POOR)
ou deve ser bloqueada (BLOCKED).

intelligence_block = {
  blocked, primary_block, reasons[],
  entry_quality: GOOD | CAUTION | POOR | BLOCKED,
  suggested_action: TRADE_ALLOWED | WAIT | NO_TRADE | DO_NOT_CHASE,
  alternative, report
}

Blocks ativos: B1 MIDDLE_OF_RANGE (POOR, nao bloqueia),
B2 NO_ANCHOR, B4 CALL_INTO_CALL_WALL, B5 PUT_INTO_PUT_WALL,
B9 IMPLIED_MOVE_BOUNDARY, B11 OPERATIONAL_CHASE_RISK,
B12 CALL_IN_UPPER_RANGE (POOR), B13 PUT_IN_LOWER_RANGE (POOR).
Alertas (CAUTION, nao bloqueiam): TRANSITION, divergencia RP/VT.
Extensivel: B3 HIRO (Patch 2), B6/B7 asymmetry (Patch 3),
B8/B10 calendar (Patch 4).

Regras de integracao:
  - decision NO TRADE: sem banner — POOR/CAUTION + WAIT/NO_TRADE
  - decision CALL/PUT + block: BLOCKED — frontend oculta plano/strikes
  - alerta sem block: CAUTION — plano visivel com aviso

NAO altera: decision, entry, stop, targets, next_setup,
Modo 3, Journal, Time Engine.

Uso: python3 patch_hard_blocks_v2.py ~/RBC/app.py ~/RBC/templates/index.html
"""
import sys, shutil, ast
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# APP.PY — 3 substituições
# ══════════════════════════════════════════════════════════════════════

# 1. Função evaluate_hard_blocks após find_trade_anchors
A1_OLD = '''        return {"upside": up, "downside": dn, "anchor_note": note}'''

A1_NEW = '''        return {"upside": up, "downside": dn, "anchor_note": note}

    def evaluate_hard_blocks(decision, gamma_regime, regime_strength, regime_zone,
                             operational_note, location, anchors,
                             at_move_high, at_move_low, next_setup):
        """Hard Blocks — camada de inteligencia pos-motor (curso SpotGamma).
        Nao altera a decisao do motor: avalia a qualidade da entrada."""
        ib = {
            "blocked": False,
            "primary_block": None,
            "reasons": [],
            "entry_quality": None,
            "suggested_action": None,
            "alternative": "",
            "report": "",
        }
        is_call   = bool(decision and "CALL" in decision)
        is_put    = bool(decision and "PUT" in decision)
        is_active = is_call or is_put
        loc = location or {}
        anc = anchors or {}
        ns  = next_setup or {}

        def _set_primary(code):
            if not ib["primary_block"]:
                ib["primary_block"] = code

        # B1 — MIDDLE_OF_RANGE (POOR, nao bloqueia)
        if loc.get("location_zone") == "MIDDLE_OF_RANGE":
            ib["reasons"].append("Preco no meio do range. Sem edge estrutural.")
            _set_primary("MIDDLE_OF_RANGE")
            ib["entry_quality"]    = "POOR"
            ib["suggested_action"] = "WAIT"

        # B2 — NO_ANCHOR (direcao do trade)
        if is_call and (anc.get("upside") or {}).get("quality") == "NONE":
            ib["blocked"] = True
            _set_primary("NO_UPSIDE_ANCHOR")
            ib["reasons"].append("CALL sem ancora superior — sem destino estrutural.")
        if is_put and (anc.get("downside") or {}).get("quality") == "NONE":
            ib["blocked"] = True
            _set_primary("NO_DOWNSIDE_ANCHOR")
            ib["reasons"].append("PUT sem ancora inferior — sem destino estrutural.")

        # B4 — CALL_INTO_CALL_WALL
        if is_call and loc.get("is_near_call_wall"):
            ib["blocked"] = True
            _set_primary("CALL_INTO_CALL_WALL")
            ib["suggested_action"] = "WAIT"
            ib["reasons"].append("CALL colado na Call Wall — resistencia/pinning, nao entrada.")

        # B5 — PUT_INTO_PUT_WALL
        if is_put and loc.get("is_near_put_wall"):
            ib["blocked"] = True
            _set_primary("PUT_INTO_PUT_WALL")
            ib["suggested_action"] = "WAIT"
            ib["reasons"].append("PUT colado no Put Wall — suporte/risco de V-bottom, nao entrada.")

        # B12 — CALL_IN_UPPER_RANGE (POOR, nao bloqueia se longe da CW)
        if is_call and loc.get("location_zone") in ("UPPER_RANGE", "NEAR_RESISTANCE") \
                and not loc.get("is_near_call_wall"):
            ib["entry_quality"]    = "POOR"
            ib["suggested_action"] = "WAIT"
            _set_primary("CALL_IN_UPPER_RANGE")
            ib["reasons"].append(
                "CALL na parte alta do range — assimetria ruim. "
                "Aguardar pullback ou rompimento aceito.")

        # B13 — PUT_IN_LOWER_RANGE (POOR, nao bloqueia se longe da PW)
        if is_put and loc.get("location_zone") in ("LOWER_RANGE", "NEAR_SUPPORT") \
                and not loc.get("is_near_put_wall"):
            ib["entry_quality"]    = "POOR"
            ib["suggested_action"] = "WAIT"
            _set_primary("PUT_IN_LOWER_RANGE")
            ib["reasons"].append(
                "PUT na parte baixa do range — risco de entrada atrasada. "
                "Aguardar reteste/rejeicao ou perda aceita do suporte.")

        # B9 — IMPLIED_MOVE_BOUNDARY
        if is_call and at_move_high:
            ib["blocked"] = True
            _set_primary("CALL_AT_IMPLIED_MOVE_HIGH")
            ib["reasons"].append("Preco ja no topo do 1D implied move — movimento esperado consumido.")
        if is_put and at_move_low:
            ib["blocked"] = True
            _set_primary("PUT_AT_IMPLIED_MOVE_LOW")
            ib["reasons"].append("Preco ja no fundo do 1D implied move — movimento esperado consumido.")

        # B11 — OPERATIONAL_CHASE_RISK
        if regime_strength == "extended":
            ib["reasons"].append("OPERATIONAL_CHASE_RISK")
            _set_primary("OPERATIONAL_CHASE_RISK")
            if is_active:
                ib["blocked"]          = True
                ib["suggested_action"] = "DO_NOT_CHASE"
                ib["entry_quality"]    = "BLOCKED"

        # Alertas (nao bloqueiam): transicao e divergencia de camadas
        if regime_zone == "TRANSITION" and not ib["blocked"]:
            ib["reasons"].append("Zona de transicao — toque nao e aceitacao.")
            if ib["entry_quality"] is None:
                ib["entry_quality"] = "CAUTION"
        if operational_note and not ib["blocked"]:
            ib["reasons"].append(operational_note)
            if ib["entry_quality"] is None:
                ib["entry_quality"] = "CAUTION"

        # Consolidacao
        if ib["blocked"] and is_active:
            ib["entry_quality"] = "BLOCKED"
            if not ib["suggested_action"]:
                ib["suggested_action"] = "WAIT"
        if not is_active:
            # NO TRADE: sem banner vermelho — qualidade POOR/CAUTION
            ib["blocked"] = False
            if ib["entry_quality"] not in ("POOR", "CAUTION"):
                ib["entry_quality"] = "CAUTION"
            if ib["suggested_action"] not in ("WAIT", "NO_TRADE"):
                ib["suggested_action"] = "NO_TRADE" if ib["entry_quality"] == "POOR" else "WAIT"
        if ib["entry_quality"] is None:
            ib["entry_quality"] = "GOOD"
        if ib["suggested_action"] is None:
            ib["suggested_action"] = "TRADE_ALLOWED"

        # Alternativa — vem do proximo setup
        if is_call:
            ib["alternative"] = ns.get("call_setup") or ns.get("no_trade") or ""
        elif is_put:
            ib["alternative"] = ns.get("put_setup") or ns.get("no_trade") or ""
        else:
            ib["alternative"] = ns.get("no_trade") or ""

        # Report estilo mentor
        _r = []
        if ib["entry_quality"] == "GOOD":
            _r.append("Entrada estruturalmente limpa pelas camadas de inteligencia.")
        elif ib["reasons"]:
            _r.append(ib["reasons"][0])
        if loc.get("location_report"):
            _r.append(loc["location_report"])
        ib["report"] = " ".join(_r)

        return ib'''

# 2. Chamada após o next_setup (todas as camadas já calculadas)
A2_OLD = '''    else:
        next_setup = {
            "call_setup":   None,
            "put_setup":    None,
            "no_trade":     "Dados insuficientes — preencher manualmente.",
            "key_level":    None,
            "invalidation": None,
            "context":      None,
        }'''

A2_NEW = '''    else:
        next_setup = {
            "call_setup":   None,
            "put_setup":    None,
            "no_trade":     "Dados insuficientes — preencher manualmente.",
            "key_level":    None,
            "invalidation": None,
            "context":      None,
        }

    # ── Hard Blocks — camada de inteligencia pos-motor ────────────────
    intelligence_block = evaluate_hard_blocks(
        decision, gamma_regime, regime_strength, regime_zone,
        operational_note, location, anchors,
        at_move_high, at_move_low, next_setup)'''

# 3. Output
A3_OLD = '''        "anchors":          anchors,'''

A3_NEW = '''        "anchors":          anchors,
        "intelligence_block": intelligence_block,'''

# ══════════════════════════════════════════════════════════════════════
# INDEX.HTML — 3 substituições
# ══════════════════════════════════════════════════════════════════════

# 1. Bloco INTELLIGENCE OVERLAY após o card Regime
H1_OLD = '''      ${d.anchors.anchor_note ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.anchors.anchor_note}</div>` : ''}
    </div>` : ''}
  </div>

  ${gapHtml}'''

H1_NEW = '''      ${d.anchors.anchor_note ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.anchors.anchor_note}</div>` : ''}
    </div>` : ''}
  </div>

  ${d.intelligence_block ? (() => {
    const ib = d.intelligence_block;
    const q  = ib.entry_quality;
    const qColor = q === 'GOOD' ? '#16a34a' : q === 'CAUTION' ? '#d97706' : q === 'POOR' ? '#ea580c' : '#dc2626';
    const qBg    = q === 'GOOD' ? '#f0fdf4' : q === 'CAUTION' ? '#fffbeb' : q === 'POOR' ? '#fff7ed' : '#fef2f2';
    return `
  <div style="background:${qBg};border:0.5px solid ${qColor};border-left:4px solid ${qColor};border-radius:12px;padding:10px 14px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
      <span style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.05em;">Intelligence Overlay</span>
      <span style="font-size:11px;font-weight:700;color:${qColor};">${q}${ib.suggested_action ? ' · ' + ib.suggested_action.replace(/_/g, ' ') : ''}</span>
    </div>
    ${ib.blocked ? `<div style="font-size:12px;font-weight:700;color:#dc2626;margin-bottom:3px;">🚫 TRADE BLOQUEADO PELA CAMADA DE INTELIGENCIA</div>` : ''}
    ${ib.primary_block ? `<div style="font-size:11px;font-weight:600;color:${qColor};margin-bottom:3px;">${ib.primary_block.replace(/_/g, ' ')}</div>` : ''}
    ${ib.report ? `<div style="font-size:12px;color:#1e293b;line-height:1.5;">${ib.report}</div>` : ''}
    ${ib.alternative ? `<div style="font-size:11px;color:#64748b;margin-top:4px;"><b>Alternativa:</b> ${ib.alternative}</div>` : ''}
  </div>`;
  })() : ''}

  ${gapHtml}'''

# 2. Plano de trade oculto quando blocked (mesmo mecanismo do chase)
H2_OLD = '''  ${!isNo ? `
  <div style="background:#ffffff;border:0.5px solid #e2e8f0;border-radius:12px;overflow:hidden;">
    <div style="padding:8px 12px;font-size:10px;font-weight:500;color:#64748b;text-transform:uppercase;letter-spacing:.05em;border-bottom:0.5px solid #e2e8f0;">Plano de trade</div>'''

H2_NEW = '''  ${!isNo && !(d.intelligence_block && d.intelligence_block.blocked) ? `
  <div style="background:#ffffff;border:0.5px solid #e2e8f0;border-radius:12px;overflow:hidden;">
    <div style="padding:8px 12px;font-size:10px;font-weight:500;color:#64748b;text-transform:uppercase;letter-spacing:.05em;border-bottom:0.5px solid #e2e8f0;">Plano de trade</div>'''

# 3. Strikes ocultos quando blocked
H3_OLD = '''    let strikesHtml = '';
    if (!isNo && !d.chase_warning && sp && lv.vol_trigger) {'''

H3_NEW = '''    let strikesHtml = '';
    if (!isNo && !d.chase_warning && !(d.intelligence_block && d.intelligence_block.blocked) && sp && lv.vol_trigger) {'''

# ══════════════════════════════════════════════════════════════════════
# Aplicar
# ══════════════════════════════════════════════════════════════════════

if len(sys.argv) < 3:
    print("Uso: python3 patch_hard_blocks_v2.py ~/RBC/app.py ~/RBC/templates/index.html")
    sys.exit(1)

app_path  = sys.argv[1]
html_path = sys.argv[2]
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

app_patches = [
    (A1_OLD, A1_NEW, "funcao evaluate_hard_blocks"),
    (A2_OLD, A2_NEW, "chamada apos next_setup"),
    (A3_OLD, A3_NEW, "intelligence_block no output"),
]
html_patches = [
    (H1_OLD, H1_NEW, "bloco INTELLIGENCE OVERLAY"),
    (H2_OLD, H2_NEW, "plano oculto quando blocked"),
    (H3_OLD, H3_NEW, "strikes ocultos quando blocked"),
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
print("Patch 1 do curso COMPLETO: Regime + Location + Anchor + Hard Blocks + Report")
print()
print("Proximo passo:")
print("  git add app.py templates/index.html")
print('  git commit -m "APROVADO: Hard Blocks v2 — B12/B13 range assimetrico — Patch 1 completo"')
print("  git push")
