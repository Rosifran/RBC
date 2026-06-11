"""
RBC EUA — Modo 2 | Flow Context Engine v1.0 (Etapa A — standalone)
===================================================================
Camada de confirmação de fluxo HIRO/TRACE para a decisão 0DTE.

Filosofia: níveis SpotGamma dizem ONDE; HIRO/TRACE dizem SE o fluxo
confirma. Regra central: "If HIRO does not confirm, it is not my trade."

Etapa A: motor isolado. NÃO integra com Modo 2/3/dashboard.
- Todos os campos são OPCIONAIS. Vazio/None/inválido -> NOT_AVAILABLE.
- Se nada for fornecido (flow_provided=False), adjustment=0, sem blocks:
  o sistema continua funcionando exatamente como hoje.
- WATCH_ONLY é um PORTÃO (flow_gate) sobre a decisão existente — o enum
  de decisões (CALL REVERSAL, PUT REVERSAL, CALL BREAKOUT SMALL,
  PUT TREND, NO TRADE) não é alterado.

Interface principal:
    fc = build_flow_context(direction='CALL', hiro_trend='UP', ...)
    gated = apply_flow_to_decision('CALL REVERSAL', fc)
"""

NA = "NOT_AVAILABLE"

# ============================================================
# CONFIG — pesos e limiares (ajustar aqui, não na lógica)
# ============================================================
CONFIG = {
    "hiro_confirm_score": 2,        # HIRO confirma a direção
    "divergence_penalty": -2,       # divergência contra a direção
    "neg_gamma_accel_score": 2,     # gamma negativo na direção do movimento
    "pos_gamma_caution_score": -1,  # gamma positivo contra, perto de wall
    "charm_score": 1,               # charm com OI HIGH
    "oi_low_threshold": 5000,
    "oi_medium_threshold": 10000,
}

# Valores permitidos por campo (spec). Fora disso -> NOT_AVAILABLE.
ALLOWED = {
    "hiro_trend": {"UP", "DOWN", "FLAT", "MIXED", NA},
    "hiro_price_confirmation": {
        "CONFIRMING_UP", "CONFIRMING_DOWN",
        "DIVERGENCE_UP_PRICE_NOT_RESPONDING",
        "DIVERGENCE_DOWN_PRICE_NOT_RESPONDING", "NEUTRAL", NA,
    },
    "price_response_to_flow": {"RESPONDING", "NOT_RESPONDING", "UNCLEAR", NA},
    "trace_gamma_above": {
        "NEGATIVE_GAMMA_ABOVE", "POSITIVE_GAMMA_ABOVE",
        "MIXED_ABOVE", "LIGHT_ABOVE", NA,
    },
    "trace_gamma_below": {
        "NEGATIVE_GAMMA_BELOW", "POSITIVE_GAMMA_BELOW",
        "MIXED_BELOW", "LIGHT_BELOW", NA,
    },
    "trace_charm_context": {
        "BUYING_PRESSURE", "SELLING_PRESSURE", "MIXED", "LIGHT",
        "IRRELEVANT_WITHOUT_SIZE", NA,
    },
    "trace_oi_strength": {"LOW", "MEDIUM", "HIGH", NA},
}

MSG_NOT_PROVIDED = ("HIRO/TRACE not provided. Decision based only on price, "
                    "VIX and SpotGamma levels.")
MSG_BEAR_DIV = ("Bearish divergence: HIRO is rising, but price is not "
                "responding. Avoid CALL chase. If HIRO rolls over, downside "
                "risk increases.")
MSG_BULL_DIV = ("Bullish divergence: HIRO is falling, but price is holding. "
                "Avoid PUT chase. If HIRO turns up, squeeze risk increases.")
MSG_UP_ACCEL = "Potential upside acceleration: negative gamma above + HIRO rising."
MSG_DOWN_ACCEL = "Potential downside acceleration: negative gamma below + HIRO falling."
MSG_CHARM_NO_SIZE = "Charm exists but there is not enough size behind it."
MSG_OI_LOW = ("Strike has low OI; level may not be strong enough for trade "
              "decision.")


def _norm(field, value):
    """Normaliza input: None/''/inválido -> NOT_AVAILABLE."""
    if value is None:
        return NA
    v = str(value).strip().upper().replace(" ", "_")
    return v if v in ALLOWED[field] else NA


# ============================================================
# HELPER 1 — classify_oi_strength
# ============================================================
def classify_oi_strength(oi_value):
    """LOW < 5.000 <= MEDIUM < 10.000 <= HIGH. None -> NOT_AVAILABLE."""
    if oi_value is None:
        return NA
    try:
        oi = float(oi_value)
    except (TypeError, ValueError):
        return NA
    if oi < CONFIG["oi_low_threshold"]:
        return "LOW"
    if oi < CONFIG["oi_medium_threshold"]:
        return "MEDIUM"
    return "HIGH"


# ============================================================
# HELPER 2 — detect_hiro_price_divergence
# ============================================================
def detect_hiro_price_divergence(hiro_trend, hiro_price_confirmation,
                                 price_response_to_flow):
    """NONE | BEARISH_DIVERGENCE | BULLISH_DIVERGENCE."""
    t = _norm("hiro_trend", hiro_trend)
    c = _norm("hiro_price_confirmation", hiro_price_confirmation)
    r = _norm("price_response_to_flow", price_response_to_flow)
    if (t == "UP" and c == "DIVERGENCE_UP_PRICE_NOT_RESPONDING"
            and r == "NOT_RESPONDING"):
        return "BEARISH_DIVERGENCE"
    if (t == "DOWN" and c == "DIVERGENCE_DOWN_PRICE_NOT_RESPONDING"
            and r == "NOT_RESPONDING"):
        return "BULLISH_DIVERGENCE"
    return "NONE"


# ============================================================
# HELPER 3 — evaluate_hiro_confirmation
# ============================================================
def evaluate_hiro_confirmation(direction, hiro_trend, hiro_price_confirmation,
                               price_response_to_flow):
    """
    direction: 'CALL' | 'PUT' | None.
    Retorna {confirms, adjustment_score, warning, rationale}.
    """
    t = _norm("hiro_trend", hiro_trend)
    c = _norm("hiro_price_confirmation", hiro_price_confirmation)
    r = _norm("price_response_to_flow", price_response_to_flow)
    out = {"confirms": False, "adjustment_score": 0,
           "warning": None, "rationale": None}

    if direction not in ("CALL", "PUT") or NA == t == c == r:
        return out

    div = detect_hiro_price_divergence(t, c, r)
    if direction == "CALL":
        if t == "UP" and c == "CONFIRMING_UP" and r == "RESPONDING":
            out.update(confirms=True,
                       adjustment_score=CONFIG["hiro_confirm_score"],
                       rationale="HIRO confirms CALL: flow up, price responding.")
        elif div == "BEARISH_DIVERGENCE":
            out.update(adjustment_score=CONFIG["divergence_penalty"],
                       warning=MSG_BEAR_DIV,
                       rationale="Positive flow is not moving price higher. "
                                 "If HIRO rolls over, downside risk can increase.")
    else:  # PUT
        if t == "DOWN" and c == "CONFIRMING_DOWN" and r == "RESPONDING":
            out.update(confirms=True,
                       adjustment_score=CONFIG["hiro_confirm_score"],
                       rationale="HIRO confirms PUT: flow down, price responding.")
        elif div == "BULLISH_DIVERGENCE":
            out.update(adjustment_score=CONFIG["divergence_penalty"],
                       warning=MSG_BULL_DIV,
                       rationale="Negative flow is not breaking price lower. "
                                 "If HIRO turns up, squeeze risk can increase.")
    return out


# ============================================================
# HELPER 4 — evaluate_trace_gamma_context
# ============================================================
def evaluate_trace_gamma_context(direction, trace_gamma_above,
                                 trace_gamma_below, hiro_trend=None,
                                 near_call_wall=False, near_put_wall=False):
    """
    Aceleração: gamma NEGATIVO na direção do movimento + HIRO na direção.
    Contenção: gamma POSITIVO contra a direção, perto da wall -> cautela.
    Retorna {adjustment_score, warning, rationale}.
    """
    ga = _norm("trace_gamma_above", trace_gamma_above)
    gb = _norm("trace_gamma_below", trace_gamma_below)
    t = _norm("hiro_trend", hiro_trend)
    out = {"adjustment_score": 0, "warning": None, "rationale": None}
    if direction not in ("CALL", "PUT"):
        return out

    if direction == "CALL":
        if ga == "NEGATIVE_GAMMA_ABOVE" and t == "UP":
            out.update(adjustment_score=CONFIG["neg_gamma_accel_score"],
                       warning=MSG_UP_ACCEL,
                       rationale="Dealers may need to buy into strength; "
                                 "upside can accelerate.")
        elif ga == "POSITIVE_GAMMA_ABOVE" and near_call_wall:
            out.update(adjustment_score=CONFIG["pos_gamma_caution_score"],
                       warning="Positive gamma above near Call Wall: "
                               "resistance/absorption likely. Avoid CALL chase.",
                       rationale="Positive gamma favors containment; "
                                 "upside may be capped near the wall.")
    else:  # PUT
        if gb == "NEGATIVE_GAMMA_BELOW" and t == "DOWN":
            out.update(adjustment_score=CONFIG["neg_gamma_accel_score"],
                       warning=MSG_DOWN_ACCEL,
                       rationale="Dealers may need to sell into weakness; "
                                 "downside can accelerate.")
        elif gb == "POSITIVE_GAMMA_BELOW" and near_put_wall:
            out.update(adjustment_score=CONFIG["pos_gamma_caution_score"],
                       warning="Positive gamma below near Put Wall: "
                               "support/absorption likely. Avoid late PUT chase.",
                       rationale="Positive gamma favors containment; "
                                 "downside may be absorbed near the wall.")
    return out


# ============================================================
# HELPER 5 — evaluate_charm_context
# ============================================================
def evaluate_charm_context(direction, trace_charm_context, trace_oi_strength):
    """Charm só pontua com OI HIGH. Retorna {adjustment_score, rationale}."""
    ch = _norm("trace_charm_context", trace_charm_context)
    oi = _norm("trace_oi_strength", trace_oi_strength)
    out = {"adjustment_score": 0, "rationale": None}
    if ch == "IRRELEVANT_WITHOUT_SIZE":
        out["rationale"] = MSG_CHARM_NO_SIZE
        return out
    if oi != "HIGH":
        if ch in ("BUYING_PRESSURE", "SELLING_PRESSURE"):
            out["rationale"] = MSG_CHARM_NO_SIZE
        return out
    if direction == "CALL" and ch == "BUYING_PRESSURE":
        out.update(adjustment_score=CONFIG["charm_score"],
                   rationale="Charm buying pressure with HIGH OI supports CALL.")
    elif direction == "PUT" and ch == "SELLING_PRESSURE":
        out.update(adjustment_score=CONFIG["charm_score"],
                   rationale="Charm selling pressure with HIGH OI supports PUT.")
    return out


# ============================================================
# HELPER 6 — build_flow_context
# ============================================================
def build_flow_context(direction=None, hiro_trend=None,
                       hiro_price_confirmation=None,
                       price_response_to_flow=None, trace_gamma_above=None,
                       trace_gamma_below=None, trace_charm_context=None,
                       trace_oi_strength=None, oi_value=None,
                       near_call_wall=False, near_put_wall=False):
    """
    Monta o bloco flow_context completo.
    direction: direção candidata da decisão atual ('CALL'/'PUT'/None).
    oi_value: se fornecido e trace_oi_strength ausente, classifica via helper.
    """
    t = _norm("hiro_trend", hiro_trend)
    c = _norm("hiro_price_confirmation", hiro_price_confirmation)
    r = _norm("price_response_to_flow", price_response_to_flow)
    ga = _norm("trace_gamma_above", trace_gamma_above)
    gb = _norm("trace_gamma_below", trace_gamma_below)
    ch = _norm("trace_charm_context", trace_charm_context)
    oi = _norm("trace_oi_strength", trace_oi_strength)
    if oi == NA and oi_value is not None:
        oi = classify_oi_strength(oi_value)

    provided = any(v != NA for v in (t, c, r, ga, gb, ch, oi))

    fc = {
        "hiro_trend": t,
        "hiro_price_confirmation": c,
        "price_response_to_flow": r,
        "trace_gamma_above": ga,
        "trace_gamma_below": gb,
        "trace_charm_context": ch,
        "trace_oi_strength": oi,
        "flow_score_adjustment": 0,
        "flow_warning": None,
        "flow_rationale": None,
        "flow_blocks": [],
        "flow_provided": provided,
        "divergence": detect_hiro_price_divergence(t, c, r),
    }

    if not provided:
        fc["flow_rationale"] = MSG_NOT_PROVIDED
        return fc

    warnings, rationales = [], []

    hiro = evaluate_hiro_confirmation(direction, t, c, r)
    trace = evaluate_trace_gamma_context(direction, ga, gb, hiro_trend=t,
                                         near_call_wall=near_call_wall,
                                         near_put_wall=near_put_wall)
    charm = evaluate_charm_context(direction, ch, oi)
    fc["flow_score_adjustment"] = (hiro["adjustment_score"]
                                   + trace["adjustment_score"]
                                   + charm["adjustment_score"])
    for part in (hiro, trace):
        if part.get("warning"):
            warnings.append(part["warning"])
        if part.get("rationale"):
            rationales.append(part["rationale"])
    if charm.get("rationale"):
        rationales.append(charm["rationale"])

    # ---------- BLOQUEIOS (flow_gate = WATCH_ONLY; enum intocado) ----------
    div = fc["divergence"]
    if direction == "CALL":
        if div == "BEARISH_DIVERGENCE":
            fc["flow_blocks"].append({
                "applies_to": "CALL", "action": "WATCH_ONLY",
                "reason": "HIRO rising but price not responding (bearish divergence).",
            })
        if ga == "POSITIVE_GAMMA_ABOVE" and near_call_wall:
            fc["flow_blocks"].append({
                "applies_to": "CALL", "action": "WATCH_ONLY",
                "reason": "Positive gamma above near Call Wall.",
            })
        if not hiro["confirms"] and t in ("DOWN", "FLAT", "MIXED"):
            fc["flow_blocks"].append({
                "applies_to": "CALL", "action": "WATCH_ONLY",
                "reason": "Price action without HIRO confirmation for CALL.",
            })
    elif direction == "PUT":
        if div == "BULLISH_DIVERGENCE":
            fc["flow_blocks"].append({
                "applies_to": "PUT", "action": "WATCH_ONLY",
                "reason": "HIRO falling but price holding (bullish divergence).",
            })
        if gb == "POSITIVE_GAMMA_BELOW" and near_put_wall:
            fc["flow_blocks"].append({
                "applies_to": "PUT", "action": "WATCH_ONLY",
                "reason": "Positive gamma below near Put Wall.",
            })
        if not hiro["confirms"] and t in ("UP", "FLAT", "MIXED"):
            fc["flow_blocks"].append({
                "applies_to": "PUT", "action": "WATCH_ONLY",
                "reason": "Price action without HIRO confirmation for PUT.",
            })

    if oi == "LOW":
        warnings.append(MSG_OI_LOW)
        rationales.append("Low OI at the relevant strike reduces confidence "
                          "in pin plays and isolated levels.")

    fc["flow_warning"] = " | ".join(warnings) if warnings else None
    fc["flow_rationale"] = " ".join(rationales) if rationales else None
    return fc


# ============================================================
# APLICAÇÃO SOBRE A DECISÃO (portão — não altera o enum)
# ============================================================
def apply_flow_to_decision(decision, flow_context):
    """
    decision: string atual do Modo 2 (CALL REVERSAL, PUT REVERSAL,
              CALL BREAKOUT SMALL, PUT TREND, NO TRADE).
    Retorna: {"decision": <inalterada>, "flow_gate": "UNCHANGED"|"WATCH_ONLY",
              "gated": bool, "gate_reasons": [...]}
    WATCH_ONLY = rebaixamento/alerta visual; a decisão original é preservada
    para compatibilidade com Modo 3 e journal.
    """
    out = {"decision": decision, "flow_gate": "UNCHANGED",
           "gated": False, "gate_reasons": []}
    if not flow_context or not flow_context.get("flow_provided"):
        return out
    if not decision or decision == "NO TRADE":
        return out
    side = "CALL" if "CALL" in decision else "PUT" if "PUT" in decision else None
    if side is None:
        return out
    reasons = [b["reason"] for b in flow_context.get("flow_blocks", [])
               if b.get("applies_to") == side]
    if reasons:
        out.update(flow_gate="WATCH_ONLY", gated=True, gate_reasons=reasons)
    return out


# ============================================================
# DEMO — 4 casos da spec
# ============================================================
if __name__ == "__main__":
    import json

    casos = [
        ("Caso 1: rompe p/ cima sem HIRO", "CALL", dict(
            hiro_trend="FLAT", hiro_price_confirmation="NEUTRAL",
            price_response_to_flow="NOT_RESPONDING",
            trace_gamma_above="POSITIVE_GAMMA_ABOVE", near_call_wall=True)),
        ("Caso 2: reclaim VT + HIRO up + neg gamma above", "CALL", dict(
            hiro_trend="UP", hiro_price_confirmation="CONFIRMING_UP",
            price_response_to_flow="RESPONDING",
            trace_gamma_above="NEGATIVE_GAMMA_ABOVE")),
        ("Caso 3: perde nível + HIRO down + neg gamma below", "PUT", dict(
            hiro_trend="DOWN", hiro_price_confirmation="CONFIRMING_DOWN",
            price_response_to_flow="RESPONDING",
            trace_gamma_below="NEGATIVE_GAMMA_BELOW")),
        ("Caso 4: cai ate Put Wall sem HIRO down", "PUT", dict(
            hiro_trend="FLAT", hiro_price_confirmation="NEUTRAL",
            trace_gamma_below="POSITIVE_GAMMA_BELOW", near_put_wall=True)),
    ]
    for nome, direction, kw in casos:
        fc = build_flow_context(direction=direction, **kw)
        gate = apply_flow_to_decision(
            "CALL REVERSAL" if direction == "CALL" else "PUT TREND", fc)
        print(f"\n=== {nome} ===")
        print(f"  adjustment: {fc['flow_score_adjustment']:+d} | "
              f"gate: {gate['flow_gate']} | blocks: {len(fc['flow_blocks'])}")
        if fc["flow_warning"]:
            print(f"  warning : {fc['flow_warning']}")
        if fc["flow_rationale"]:
            print(f"  rationale: {fc['flow_rationale']}")
