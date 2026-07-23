"""
RBC EUA — patch cirúrgico Modo 1 plano 0DTE
Substitui APENAS o bloco de geração do plano (call_trigger, put_trigger, avoid, best_setup).
Lógica nova:
  - Lê reference_price para determinar regime
  - NEGATIVE GAMMA (ref < vol_trigger): CALL só em reclaim de VT/ZG, não breakout acima da Call Wall
  - POSITIVE GAMMA (ref >= vol_trigger): lógica anterior mantida
  - PUT: não perseguir se já distante do nível
  - Combos acima da Call Wall = resistências/alvos, não entradas
Não toca em nada fora deste bloco.
Uso: python3 patch_modo1_plan.py ~/RBC/app.py
"""
import sys, shutil, ast
from datetime import datetime

OLD = '''    put_line  = vol_trig or zero_g
    above_put = [c for c in combos_f if put_line and c > put_line]

    # no_trade_hi = segundo combo acima do put_line
    if len(above_put) >= 2:
        no_trade_hi = above_put[1]
    elif above_put:
        no_trade_hi = above_put[0]
    else:
        no_trade_hi = call_wall

    # CALL escalonado — começa acima de no_trade_hi
    if len(above_put) >= 3 and call_wall:
        parsed["plan"]["call_trigger"] = f"SPY above {above_put[1]}, better above {above_put[2]}, strongest above {call_wall}."
    elif len(above_put) >= 2 and call_wall:
        parsed["plan"]["call_trigger"] = f"SPY above {above_put[1]}, strongest above {call_wall}."
    elif call_wall:
        parsed["plan"]["call_trigger"] = f"SPY above {call_wall}."

    # PUT linha dura
    if put_line:
        parsed["plan"]["put_trigger"] = f"SPY below {put_line}."

    # NO TRADE zona de compressão
    if put_line and no_trade_hi:
        parsed["plan"]["avoid"] = f"SPY between {put_line} and {no_trade_hi}."

    # BEST operacional
    if put_line and no_trade_hi:
        parsed["plan"]["best_setup"] = f"Wait for breakout; do not trade inside {put_line}–{no_trade_hi} compression zone."

    # SCORE baseado em sinais de risco
    if froth and vol_spasm:
        parsed["score"]["value"] = 2
        cor_str = f" and COR1M {cor1m}" if cor1m else ""
        parsed["score"]["justification"] = f"Positive gamma supports stocks, but extreme call froth{cor_str} create volatility-spasm risk."'''

NEW = '''    ref_price = spy.get("reference_price")
    put_line  = vol_trig or zero_g

    # ── Regime: RBC decide com base em reference_price vs vol_trigger ──
    # NEGATIVE GAMMA: ref abaixo do Vol Trigger → mercado frágil
    # POSITIVE GAMMA: ref igual ou acima do Vol Trigger → mercado sustentado
    if ref_price and vol_trig:
        negative_gamma = ref_price < vol_trig
    else:
        negative_gamma = False  # sem dados suficientes, assume positivo

    # Combos abaixo e acima da Call Wall (para separar entradas de alvos)
    combos_below_cw = [c for c in combos_f if call_wall and c < call_wall]
    combos_above_cw = [c for c in combos_f if call_wall and c >= call_wall]

    if negative_gamma:
        # ── NEGATIVE GAMMA ────────────────────────────────────────────
        # CALL: só em reclaim do Vol Trigger / Zero Gamma
        # Não usar combos acima da Call Wall como entrada
        vt_str = vol_trig or zero_g
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
            )

        # PUT: rejeição ou aceitação abaixo do Vol Trigger
        if put_line:
            parsed["plan"]["put_trigger"] = (
                f"SPY rejection of {put_line} or acceptance below. "
                f"Targets: {ref_price or 'Reference Price'}, then {spy.get('put_wall') or 'Put Wall'}. "
                f"Do not chase if already extended from {put_line}."
            )

        # NO TRADE
        if put_line and call_wall:
            parsed["plan"]["avoid"] = (
                f"SPY between {put_line} and {call_wall} without clear direction. "
                f"Wait for rejection or reclaim of {put_line}."
            )

        # BEST operacional
        parsed["plan"]["best_setup"] = (
            f"NEGATIVE GAMMA regime — fragile market. "
            f"Best: PUT on rejection of {put_line or 'Vol Trigger'}, "
            f"or CALL only on clean reclaim of {put_line or 'Vol Trigger'}. "
            f"No trade in middle of range."
        )

        # SCORE em Negative Gamma
        parsed["score"]["value"] = 2
        cor_str = f" COR1M {cor1m}." if cor1m else ""
        parsed["score"]["justification"] = (
            f"Negative Gamma regime — SPY below Vol Trigger. "
            f"Fragile, headline-sensitive.{cor_str} Reduce size, wait for level."
        )

    else:
        # ── POSITIVE GAMMA ────────────────────────────────────────────
        # Lógica original mantida: combos acima do put_line como escada
        above_put = [c for c in combos_f if put_line and c > put_line]

        if len(above_put) >= 2:
            no_trade_hi = above_put[1]
        elif above_put:
            no_trade_hi = above_put[0]
        else:
            no_trade_hi = call_wall

        if len(above_put) >= 3 and call_wall:
            parsed["plan"]["call_trigger"] = f"SPY above {above_put[1]}, better above {above_put[2]}, strongest above {call_wall}."
        elif len(above_put) >= 2 and call_wall:
            parsed["plan"]["call_trigger"] = f"SPY above {above_put[1]}, strongest above {call_wall}."
        elif call_wall:
            parsed["plan"]["call_trigger"] = f"SPY above {call_wall}."

        if put_line:
            parsed["plan"]["put_trigger"] = f"SPY below {put_line}."

        if put_line and no_trade_hi:
            parsed["plan"]["avoid"] = f"SPY between {put_line} and {no_trade_hi}."

        if put_line and no_trade_hi:
            parsed["plan"]["best_setup"] = f"Wait for breakout; do not trade inside {put_line}–{no_trade_hi} compression zone."

        # SCORE em Positive Gamma
        if froth and vol_spasm:
            parsed["score"]["value"] = 2
            cor_str = f" and COR1M {cor1m}" if cor1m else ""
            parsed["score"]["justification"] = f"Positive gamma supports stocks, but extreme call froth{cor_str} create volatility-spasm risk."'''

if len(sys.argv) < 2:
    print("Uso: python3 patch_modo1_plan.py ~/RBC/app.py")
    sys.exit(1)

path = sys.argv[1]
content = open(path).read()

if OLD not in content:
    print("ERRO — bloco original não encontrado. Verifique se o arquivo está correto.")
    sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = path.replace(".py", f"_backup_{ts}.py")
shutil.copy2(path, backup)
print(f"Backup criado: {backup}")

content = content.replace(OLD, NEW, 1)
ast.parse(content)
open(path, 'w').write(content)
print("✅ Plano 0DTE atualizado")
print("   + Regime NEGATIVE_GAMMA detectado por reference_price < vol_trigger")
print("   + CALL em Negative Gamma = reclaim VT/ZG, não breakout acima da Call Wall")
print("   + PUT = rejeição com regra de não perseguir")
print("   + POSITIVE GAMMA = lógica anterior mantida")
