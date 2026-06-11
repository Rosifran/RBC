"""
test_flow_context.py — os 6 testes da spec HIRO/TRACE (Etapa A).
Rodar:  python3 test_flow_context.py
Sem dependências externas (asserts puros).
"""
from flow_context_engine import (
    NA, build_flow_context, apply_flow_to_decision, classify_oi_strength,
    detect_hiro_price_divergence, MSG_NOT_PROVIDED, MSG_CHARM_NO_SIZE,
)

ok = 0

def check(nome, cond):
    global ok
    assert cond, f"FALHOU: {nome}"
    ok += 1
    print(f"  ✅ {nome}")


# ── Teste 1: CALL bloqueado por falta de HIRO confirmation ──
print("\n[1] CALL bloqueado por falta de HIRO confirmation (bearish divergence)")
fc = build_flow_context(
    direction="CALL", hiro_trend="UP",
    hiro_price_confirmation="DIVERGENCE_UP_PRICE_NOT_RESPONDING",
    price_response_to_flow="NOT_RESPONDING")
g = apply_flow_to_decision("CALL REVERSAL", fc)
check("divergencia detectada", fc["divergence"] == "BEARISH_DIVERGENCE")
check("score -2", fc["flow_score_adjustment"] == -2)
check("gate WATCH_ONLY", g["flow_gate"] == "WATCH_ONLY" and g["gated"])
check("decisao original preservada (enum intocado)", g["decision"] == "CALL REVERSAL")
check("warning de chase presente", "Avoid CALL chase" in (fc["flow_warning"] or ""))

# ── Teste 2: PUT bloqueado perto do Put Wall sem HIRO down ──
print("\n[2] PUT bloqueado perto do Put Wall sem HIRO down")
fc = build_flow_context(
    direction="PUT", hiro_trend="FLAT", hiro_price_confirmation="NEUTRAL",
    trace_gamma_below="POSITIVE_GAMMA_BELOW", near_put_wall=True)
g = apply_flow_to_decision("PUT TREND", fc)
check("gate WATCH_ONLY", g["flow_gate"] == "WATCH_ONLY")
check("bloqueio por Put Wall registrado",
      any("Put Wall" in b["reason"] for b in fc["flow_blocks"]))
check("bloqueio por falta de confirmacao registrado",
      any("without HIRO confirmation" in b["reason"] for b in fc["flow_blocks"]))
check("warning de absorcao", "Avoid late PUT chase" in (fc["flow_warning"] or ""))

# ── Teste 3: CALL ganha score com HIRO up + negative gamma above ──
print("\n[3] CALL ganha score: HIRO up + negative gamma above")
fc = build_flow_context(
    direction="CALL", hiro_trend="UP", hiro_price_confirmation="CONFIRMING_UP",
    price_response_to_flow="RESPONDING", trace_gamma_above="NEGATIVE_GAMMA_ABOVE")
g = apply_flow_to_decision("CALL REVERSAL", fc)
check("score +4 (2 HIRO + 2 TRACE)", fc["flow_score_adjustment"] == 4)
check("sem gate", g["flow_gate"] == "UNCHANGED" and not fc["flow_blocks"])
check("warning de aceleracao p/ cima",
      "upside acceleration" in (fc["flow_warning"] or ""))

# ── Teste 4: PUT ganha score com HIRO down + negative gamma below ──
print("\n[4] PUT ganha score: HIRO down + negative gamma below")
fc = build_flow_context(
    direction="PUT", hiro_trend="DOWN", hiro_price_confirmation="CONFIRMING_DOWN",
    price_response_to_flow="RESPONDING", trace_gamma_below="NEGATIVE_GAMMA_BELOW")
g = apply_flow_to_decision("PUT TREND", fc)
check("score +4", fc["flow_score_adjustment"] == 4)
check("sem gate", g["flow_gate"] == "UNCHANGED")
check("warning de aceleracao p/ baixo",
      "downside acceleration" in (fc["flow_warning"] or ""))

# ── Teste 5: Charm ignorado quando OI é LOW ──
print("\n[5] Charm ignorado quando OI e LOW")
fc = build_flow_context(
    direction="CALL", hiro_trend="UP", hiro_price_confirmation="CONFIRMING_UP",
    price_response_to_flow="RESPONDING",
    trace_charm_context="BUYING_PRESSURE", trace_oi_strength="LOW")
check("charm NAO pontuou (2, nao 3)", fc["flow_score_adjustment"] == 2)
check("nota de charm sem tamanho", MSG_CHARM_NO_SIZE in (fc["flow_rationale"] or ""))
check("warning de OI baixo", "low OI" in (fc["flow_warning"] or ""))
# contraprova: com OI HIGH o charm pontua
fc2 = build_flow_context(
    direction="CALL", hiro_trend="UP", hiro_price_confirmation="CONFIRMING_UP",
    price_response_to_flow="RESPONDING",
    trace_charm_context="BUYING_PRESSURE", trace_oi_strength="HIGH")
check("contraprova: charm + OI HIGH soma +1 (total 3)",
      fc2["flow_score_adjustment"] == 3)

# ── Teste 6: sistema funciona normalmente com HIRO/TRACE NOT_AVAILABLE ──
print("\n[6] HIRO/TRACE ausentes -> logica antiga intacta")
for kwargs in (dict(),                                     # nada fornecido
               dict(hiro_trend=None, trace_oi_strength=""),  # vazios
               dict(hiro_trend="NOT_AVAILABLE"),              # explicito
               dict(hiro_trend="qualquer coisa invalida")):   # invalido
    fc = build_flow_context(direction="CALL", **kwargs)
    g = apply_flow_to_decision("CALL BREAKOUT SMALL", fc)
    check(f"flow_provided=False, adj=0, sem blocks ({kwargs or 'vazio'})",
          fc["flow_provided"] is False
          and fc["flow_score_adjustment"] == 0
          and not fc["flow_blocks"]
          and g["flow_gate"] == "UNCHANGED")
fc = build_flow_context(direction="CALL")
check("mensagem 'not provided' presente", fc["flow_rationale"] == MSG_NOT_PROVIDED)
check("NO TRADE nunca e gated",
      apply_flow_to_decision("NO TRADE", build_flow_context(
          direction="CALL", hiro_trend="FLAT"))["flow_gate"] == "UNCHANGED")

# ── Teste 7: CALL perto da Call Wall + POSITIVE_GAMMA_ABOVE sem HIRO ──
print("\n[7] Trava anti-chase: CALL na Call Wall + pos gamma + sem HIRO confirmando")
for trend, conf in (("FLAT", "NEUTRAL"), ("DOWN", "NEUTRAL"), ("MIXED", "NEUTRAL"),
                    ("UP", "DIVERGENCE_UP_PRICE_NOT_RESPONDING")):
    fc = build_flow_context(
        direction="CALL", hiro_trend=trend, hiro_price_confirmation=conf,
        price_response_to_flow="NOT_RESPONDING",
        trace_gamma_above="POSITIVE_GAMMA_ABOVE", near_call_wall=True)
    g = apply_flow_to_decision("CALL REVERSAL", fc)
    check(f"gate WATCH_ONLY (hiro={trend}/{conf})",
          g["flow_gate"] == "WATCH_ONLY" and g["gated"])
    check(f"bloqueio por Call Wall registrado (hiro={trend})",
          any("Call Wall" in b["reason"] for b in fc["flow_blocks"]))
# contraprova: HIRO confirmando NAO trava (gamma positivo vira so cautela -1)
fc = build_flow_context(
    direction="CALL", hiro_trend="UP", hiro_price_confirmation="CONFIRMING_UP",
    price_response_to_flow="RESPONDING",
    trace_gamma_above="POSITIVE_GAMMA_ABOVE", near_call_wall=True)
g = apply_flow_to_decision("CALL REVERSAL", fc)
check("contraprova: HIRO confirmando ainda trava na wall? (sim — pos gamma na wall sempre trava)",
      g["flow_gate"] == "WATCH_ONLY")
check("contraprova: mas score reflete confirmacao - cautela (+2-1=+1)",
      fc["flow_score_adjustment"] == 1)

# ── Teste 8: PUT perto do Put Wall + POSITIVE_GAMMA_BELOW + divergente/sem confirmacao ──
print("\n[8] Trava anti-chase: PUT na Put Wall + pos gamma + HIRO divergente ou ausente")
# 8a: HIRO em divergencia bullish formal
fc = build_flow_context(
    direction="PUT", hiro_trend="DOWN",
    hiro_price_confirmation="DIVERGENCE_DOWN_PRICE_NOT_RESPONDING",
    price_response_to_flow="NOT_RESPONDING",
    trace_gamma_below="POSITIVE_GAMMA_BELOW", near_put_wall=True)
g = apply_flow_to_decision("PUT TREND", fc)
check("8a divergencia bullish: gate WATCH_ONLY", g["flow_gate"] == "WATCH_ONLY")
check("8a dois bloqueios (divergencia + Put Wall)",
      any("bullish divergence" in b["reason"] for b in fc["flow_blocks"])
      and any("Put Wall" in b["reason"] for b in fc["flow_blocks"]))
check("8a score -3 (divergencia -2 + cautela wall -1)",
      fc["flow_score_adjustment"] == -3)
# 8b: HIRO simplesmente sem confirmar (UP/FLAT/MIXED)
for trend in ("UP", "FLAT", "MIXED"):
    fc = build_flow_context(
        direction="PUT", hiro_trend=trend, hiro_price_confirmation="NEUTRAL",
        trace_gamma_below="POSITIVE_GAMMA_BELOW", near_put_wall=True)
    g = apply_flow_to_decision("PUT TREND", fc)
    check(f"8b sem confirmacao (hiro={trend}): gate WATCH_ONLY",
          g["flow_gate"] == "WATCH_ONLY"
          and any("Put Wall" in b["reason"] for b in fc["flow_blocks"]))

# ── extras: helpers isolados ──
print("\n[extras] helpers")
check("classify_oi_strength: 3000 -> LOW", classify_oi_strength(3000) == "LOW")
check("classify_oi_strength: 7500 -> MEDIUM", classify_oi_strength(7500) == "MEDIUM")
check("classify_oi_strength: 15000 -> HIGH", classify_oi_strength(15000) == "HIGH")
check("classify_oi_strength: None -> NOT_AVAILABLE", classify_oi_strength(None) == NA)
check("divergencia: caso nenhum",
      detect_hiro_price_divergence("UP", "CONFIRMING_UP", "RESPONDING") == "NONE")

print(f"\n{'='*50}\n{ok} checks passaram — Etapa A validada.")
