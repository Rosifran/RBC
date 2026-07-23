"""
RBC EUA — Patch Modo 2 Logic Fix (5 inconsistencias)
=====================================================
P1. score["justification"] do Modo 1 usa reference_price do PDF →
    aparece como "Negative Gamma — SPY below VT" mesmo quando SPY
    atual esta acima do VT no Modo 2.
    Fix: Modo 2 sobrescreve o justification com o regime ATUAL
    (calculado por spot_now vs vol_trigger).

P2. next_setup POSITIVE_GAMMA: put_setup usa Call Wall distante (800)
    como teto operacional — irrelevante para 0DTE com SPY 748.
    Fix: teto operacional = primeiro nivel relevante acima do SPY
    (combo ou 1D move high), nao a Call Wall bruta.

P3. call_trigger em NEGATIVE_GAMMA: "Confirm above {zero_gamma}"
    quando o nivel principal e o Vol Trigger.
    Fix: confirmacao principal acima do VT; ZG como suporte secundario
    (mencionado somente se diferente do VT).

P4. timing TOO_EARLY antes das 9:45: o bloqueio existe mas o label
    do score nao deixa claro que e horario, nao setup ruim.
    Fix: quando TOO_EARLY, score_justification menciona horario.

P5. next_setup put_setup mistura SPX/Call Wall distante com operacional.
    Fix: teto do put_setup = proximo nivel relevante (combo / 1D move),
    nao call_wall. Founder alerts permanecem separados (sem alteracao
    de frontend).

NAO altera: motor (decision/entry/stop/targets), evaluate_hard_blocks,
calendar_risk, vol_premium, flow_proxy, journal, Modo 3, Modo 5.

Uso: python3 patch_modo2_logic.py ~/RBC/app.py
"""
import sys, shutil, ast
from datetime import datetime

# ── P1: sobrescrever justification no Modo 2 com regime ATUAL ─────────
# Ancora: bloco que calcula gamma_regime por spot_now (ja existente)
P1_OLD = '''    _pw  = put_wall
    _ref = spy.get("reference_price") or spot_now'''

P1_NEW = '''    # P1 fix: sobrescreve justification com regime ATUAL (spot_now vs VT)
    # O Modo 1 escreve com reference_price do PDF — pode estar desatualizado
    if vol_trig and spot_now:
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
                f"({_dist_pct}%). Aguardar aceitacao de lado.")

    _pw  = put_wall
    _ref = spy.get("reference_price") or spot_now'''

# ── P2+P5: next_setup POSITIVE_GAMMA — teto operacional real ──────────
P2_OLD = '''    elif gamma_regime == "POSITIVE_GAMMA":
        next_setup = {
            "call_setup":   f"SPY retestar {_key_level} e segurar — entrada CALL REVERSAL perto do piso.",
            "put_setup":    f"SPY se aproximar de {_cw} e rejeitar — entrada PUT REVERSAL perto do teto.",
            "no_trade":     f"SPY no meio da faixa {_vt}–{_cw} — sem edge estrutural.",
            "key_level":    _key_level,
            "invalidation": f"Viés CALL perde força se SPY perder {_key_level}. Viés PUT perde força se SPY superar {_cw}.",
            "context":      "POSITIVE GAMMA — dealers sustentam range. Reversões nos extremos.",
        }'''

P2_NEW = '''    elif gamma_regime == "POSITIVE_GAMMA":
        # P2/P5 fix: teto operacional = proximo nivel relevante acima do SPY,
        # nao a Call Wall bruta (pode estar 50+ pts longe em 0DTE).
        _all_up = sorted([c for c in ([move_1d_high] + list(combos) + ([float(_cw)] if _cw else []))
                          if c and spot_now and float(c) > float(spot_now)])
        _teto_op = _all_up[0] if _all_up else _cw   # primeiro nivel relevante acima
        _teto_str = str(_teto_op) if _teto_op else str(_cw)
        _cw_str   = str(_cw) if _cw else "Call Wall"
        next_setup = {
            "call_setup":   f"SPY retestar {_key_level} e segurar — entrada CALL REVERSAL perto do piso.",
            "put_setup":    (f"SPY se aproximar de {_teto_str} e rejeitar — "
                             f"entrada PUT REVERSAL perto do teto operacional."
                             + (f" (Call Wall estrutural: {_cw_str})" if _teto_op != _cw else "")),
            "no_trade":     f"SPY no meio da faixa {_vt}–{_teto_str} — sem edge estrutural.",
            "key_level":    _key_level,
            "invalidation": (f"Viés CALL perde força se SPY perder {_key_level}. "
                             f"Viés PUT perde força se SPY superar {_teto_str}."),
            "context":      "POSITIVE GAMMA — dealers sustentam range. Reversões nos extremos.",
        }'''

# ── P3: call_trigger NEGATIVE_GAMMA — confirmacao acima do VT ─────────
P3_OLD = '''        vt_str = vol_trig or zero_g
        zg_str = zero_g or vol_trig
        if vt_str and zg_str and vt_str != zg_str:
            parsed["plan"]["call_trigger"] = (
                f"SPY reclaim {vt_str} with acceptance. "
                f"Confirm above {zg_str}. "
                f"Targets: {call_wall or 'Call Wall'}."
            )
        elif vt_str:
            parsed["plan"]["call_trigger"] = (
                f"SPY reclaim {vt_str} with acceptance. "
                f"Target: {call_wall or 'Call Wall'}. "
                f"Do not chase call above Call Wall."
            )'''

P3_NEW = '''        # P3 fix: confirmacao principal acima do VT (nivel mais alto);
        # ZG mencionado como suporte secundario somente se diferente do VT.
        vt_str = vol_trig or zero_g
        zg_str = zero_g or vol_trig
        # proximo alvo acima do VT (combo ou 1D move), nao a Call Wall bruta
        _tgts_neg = sorted([c for c in combos if vol_trig and c > float(vol_trig)])
        _t1_neg   = _tgts_neg[0] if _tgts_neg else call_wall
        _t2_neg   = _tgts_neg[1] if len(_tgts_neg) >= 2 else call_wall
        _tgt_str  = f"{_t1_neg}, then {_t2_neg}" if _t1_neg and _t2_neg and _t1_neg != _t2_neg else str(_t1_neg or call_wall or "Call Wall")
        if vt_str and zg_str and str(vt_str) != str(zg_str):
            parsed["plan"]["call_trigger"] = (
                f"SPY reclaim {vt_str} with acceptance. "
                f"Confirm above {vt_str} (ZG {zg_str} = secondary support). "
                f"Targets: {_tgt_str}."
            )
        elif vt_str:
            parsed["plan"]["call_trigger"] = (
                f"SPY reclaim {vt_str} with acceptance. "
                f"Targets: {_tgt_str}."
            )'''

# ── P4: timing TOO_EARLY menciona horario no justification ────────────
P4_OLD = '''        if hhmm < 945:
            timing_quality = "TOO_EARLY"
            early_entry_ok = False
        elif hhmm <= 1015:
            timing_quality = "OK"
            early_entry_ok = True'''

P4_NEW = '''        if hhmm < 945:
            timing_quality = "TOO_EARLY"
            early_entry_ok = False
            # P4 fix: deixa claro que e horario, nao qualidade do setup
            _now_str = f"{now_et.hour:02d}:{now_et.minute:02d} ET"
            if parsed.get("score") and parsed["score"].get("justification"):
                parsed["score"]["justification"] += (
                    f" | HORARIO: {_now_str} — aguardar 9:45 ET para avaliar setup.")
        elif hhmm <= 1015:
            timing_quality = "OK"
            early_entry_ok = True'''

# ══════════════════════════════════════════════════════════════════════
if len(sys.argv) < 2:
    print("Uso: python3 patch_modo2_logic.py ~/RBC/app.py")
    sys.exit(1)

path = sys.argv[1]
patches = [
    (P1_OLD, P1_NEW, "P1: justification com regime atual (spot_now vs VT)"),
    (P2_OLD, P2_NEW, "P2+P5: next_setup teto operacional real"),
    (P3_OLD, P3_NEW, "P3: call_trigger confirmacao acima do VT"),
    (P4_OLD, P4_NEW, "P4: TOO_EARLY menciona horario"),
]

content = open(path).read()
for old, _, label in patches:
    n = content.count(old)
    if n != 1:
        print(f"ERRO — '{label}': ancora encontrada {n}x")
        sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(path, path.replace(".py", f"_backup_{ts}.py"))
print(f"Backup criado ({ts})")

for old, new, label in patches:
    content = content.replace(old, new, 1)
    print(f"✅ {label}")

ast.parse(content)
open(path, 'w').write(content)
print()
print("Validar:")
print("  1. Modo 2 com SPY 748 + VT 747 → justification deve dizer POSITIVE GAMMA")
print("  2. next_setup PUT deve mostrar nivel proximo (combo/1D), nao 800")
print("  3. call_trigger: 'Confirm above 747', nao 'Confirm above 745'")
print("  4. Antes das 9:45: justification inclui horario ET")
print()
print("  git add app.py")
print('  git commit -m "APROVADO: Modo 2 logic fix — P1-P5 regime/labels/teto"')
print("  git push")
