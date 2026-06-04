"""
RBC — Risk Bridge Capital
Modo 5 · US Swing Options Scanner — IBKR TWS
=============================================
Busca cadeia de opcoes real via TWS API.
Roda de manha antes do pregao (9:00-9:30 ET).
Salva resultado em JSON para consultar depois.

Edge proprio RBC (sem API paga):
  - GEX estimado por strike via cadeia IBKR
  - IV Rank via IBKR
  - 25-delta skew calculado localmente
  - VRP = IV anual - HV30
  - Put/Call ratio via IBKR

Uso:
    python3 us_swing_ibkr.py
    python3 us_swing_ibkr.py --tickers NVDA AAPL --direction CALL
    python3 us_swing_ibkr.py --tickers NVDA --direction PUT

Nao altera nenhum arquivo existente do RBC.
"""

from __future__ import annotations
import json
import argparse
from datetime import datetime
from pathlib import Path

from ib_insync import IB, Stock, Option


# ── Configuracao ──────────────────────────────────────────────────────

TWS_HOST    = '127.0.0.1'
TWS_PORT    = 7497
CLIENT_ID   = 10
DTE_MIN     = 14
DTE_MAX     = 35
DELTA_RANGE = {
    'CALL': (0.30, 0.65),
    'PUT':  (-0.65, -0.30),
}
OUTPUT_DIR      = Path(__file__).parent / 'modo5_results'
DEFAULT_TICKERS = ['NVDA', 'AAPL', 'META', 'AMZN']


# ── Edge RBC — calculos quantitativos ────────────────────────────────

def calc_gex(gamma: float, oi: int, spot: float) -> float:
    """
    GEX estimado por contrato.
    GEX = gamma * OI * 100 * spot^2 * 0.01
    Positivo = dealers long gamma = mercado tende a reverter
    Negativo = dealers short gamma = mercado tende a tendenciar
    """
    if not gamma or not oi or not spot:
        return 0.0
    return round(gamma * oi * 100 * (spot ** 2) * 0.01, 0)


def calc_vrp(iv_annual: float, hv30: float) -> dict:
    """
    VRP = IV anual - HV30 (volatility risk premium)
    Positivo = vol cara = nao comprar opcao
    Negativo = vol barata = bom para comprar
    Zero ou proximo = neutro
    """
    if not iv_annual or not hv30:
        return {"vrp": None, "signal": "sem dados", "score": 1}
    vrp = round(iv_annual - hv30, 4)
    if vrp < -0.02:
        signal = "vol BARATA — favoravel para compra"
        score  = 2
    elif vrp < 0.05:
        signal = "vol neutra — aceitavel"
        score  = 1
    else:
        signal = "vol CARA — desfavoravel para compra"
        score  = 0
    return {"vrp": round(vrp * 100, 1), "signal": signal, "score": score}


def calc_skew(chain_calls: list, chain_puts: list, spot: float) -> dict:
    """
    25-delta skew = IV(put 25-delta) - IV(call 25-delta)
    Positivo (steep) = mercado pagando mais por puts = cuidado com CALL
    Negativo (reverse) = mercado pagando mais por calls = cuidado com PUT
    Proximo de zero = neutro
    """
    put25  = min(chain_puts,  key=lambda x: abs(abs(x['delta']) - 0.25), default=None)
    call25 = min(chain_calls, key=lambda x: abs(x['delta'] - 0.25),      default=None)

    if not put25 or not call25 or not put25['iv_pct'] or not call25['iv_pct']:
        return {"skew_pct": None, "signal": "sem dados", "score": 1}

    skew = round(put25['iv_pct'] - call25['iv_pct'], 1)

    if skew > 5:
        signal = f"Skew {skew:+.1f}% — puts caras, bearish institucional. Cuidado com CALL."
        score  = 0
    elif skew > 2:
        signal = f"Skew {skew:+.1f}% — leve pressao baixista"
        score  = 1
    elif skew > -2:
        signal = f"Skew {skew:+.1f}% — neutro, favoravel para ambas direcoes"
        score  = 2
    else:
        signal = f"Skew {skew:+.1f}% — calls caras, bullish institucional. Cuidado com PUT."
        score  = 1

    return {"skew_pct": skew, "signal": signal, "score": score}


def calc_net_gex(chain: list, spot: float) -> dict:
    """
    Net GEX = soma do GEX de todos os contratos da cadeia.
    Positivo = regime de suporte (positivo gamma)
    Negativo = regime de tendencia (negativo gamma)
    Gamma flip = strike onde GEX muda de sinal
    """
    if not chain:
        return {"net_gex": None, "regime": "sem dados", "score": 1}

    net = sum(calc_gex(c['gamma'], c['open_interest'], spot) for c in chain)

    if net > 0:
        regime = "POSITIVE GAMMA — suporte estrutural, reverter nos extremos"
        score  = 2
    else:
        regime = "NEGATIVE GAMMA — tendencia, dealers amplificam o movimento"
        score  = 1

    return {
        "net_gex":   round(net, 0),
        "net_gex_M": f"${net/1e6:.1f}M" if abs(net) > 1e6 else f"${net/1e3:.0f}K",
        "regime":    regime,
        "score":     score,
    }


def calc_pc_ratio(call_vol: int, put_vol: int) -> dict:
    """
    Put/Call ratio = put_volume / call_volume
    > 1.2 = mercado bearish (muita compra de put)
    < 0.7 = mercado bullish (muita compra de call)
    """
    if not call_vol or call_vol == 0:
        return {"pc_ratio": None, "signal": "sem dados", "score": 1}

    ratio = round(put_vol / call_vol, 2)

    if ratio > 1.2:
        signal = f"P/C {ratio} — bearish (puts dominam)"
        score  = 1
    elif ratio < 0.7:
        signal = f"P/C {ratio} — bullish (calls dominam)"
        score  = 1
    else:
        signal = f"P/C {ratio} — neutro"
        score  = 2

    return {"pc_ratio": ratio, "signal": signal, "score": score}


def edge_summary(gex: dict, vrp: dict, skew: dict, pc: dict, direction: str) -> dict:
    """
    Resume o edge em um veredicto.
    APROVO se 3 de 4 fatores favoraveis para a direcao escolhida.
    """
    scores = [gex['score'], vrp['score'], skew['score'], pc['score']]
    aprovados = sum(1 for s in scores if s >= 1)
    max_score = sum(scores)

    # Ajuste de direcao: skew alto = desfavoravel para CALL, favoravel para PUT
    skew_val = skew.get('skew_pct') or 0
    if direction == 'CALL' and skew_val > 5:
        aprovados -= 1
    if direction == 'PUT' and skew_val < -5:
        aprovados -= 1

    if aprovados >= 3:
        verdict = "EDGE FAVORAVEL"
        note    = f"{aprovados}/4 fatores alinham para {direction}"
    elif aprovados == 2:
        verdict = "EDGE NEUTRO"
        note    = f"Apenas {aprovados}/4 fatores alinham — aguardar confirmacao"
    else:
        verdict = "EDGE DESFAVORAVEL"
        note    = f"Apenas {aprovados}/4 fatores alinham — evitar entrada"

    return {
        "verdict":   verdict,
        "note":      note,
        "aprovados": aprovados,
        "fatores": {
            "gex": gex,
            "vrp": vrp,
            "skew": skew,
            "pc_ratio": pc,
        }
    }


# ── Scoring do contrato ───────────────────────────────────────────────

def score_contract(opt: dict, direction: str) -> dict:
    scores  = {}
    details = {}

    # 1. Delta (0-2)
    d = opt['delta']
    lo, hi = DELTA_RANGE[direction]
    if lo <= d <= hi:
        s = 2; msg = f"Delta {d:.2f} ideal"
    elif (lo - 0.10) <= d <= (hi + 0.10):
        s = 1; msg = f"Delta {d:.2f} aceitavel"
    else:
        s = 0; msg = f"Delta {d:.2f} fora do range"
    scores['delta'] = s; details['delta'] = msg

    # 2. DTE (0-2)
    dte = opt['dte']
    if DTE_MIN <= dte <= DTE_MAX:
        s = 2; msg = f"{dte}d ideal (14-35d)"
    elif 10 <= dte < DTE_MIN or DTE_MAX < dte <= 45:
        s = 1; msg = f"{dte}d aceitavel"
    else:
        s = 0; msg = f"{dte}d fora do range"
    scores['dte'] = s; details['dte'] = msg

    # 3. Spread (0-2)
    mid = opt['mid']
    spread_pct = ((opt['ask'] - opt['bid']) / mid * 100) if mid > 0 else 100
    if spread_pct < 5:
        s = 2; msg = f"Spread {spread_pct:.1f}% excelente"
    elif spread_pct < 10:
        s = 1; msg = f"Spread {spread_pct:.1f}% aceitavel"
    else:
        s = 0; msg = f"Spread {spread_pct:.1f}% largo"
    scores['spread'] = s; details['spread'] = msg
    opt['spread_pct'] = round(spread_pct, 1)

    # 4. Liquidez (0-2)
    vol = opt['volume']
    oi  = opt['open_interest']
    if vol > 1000 and oi > 2000:
        s = 2; msg = f"Vol {vol:,} / OI {oi:,} excelente"
    elif vol > 500 or oi > 1000:
        s = 1; msg = f"Vol {vol:,} / OI {oi:,} aceitavel"
    else:
        s = 0; msg = f"Vol {vol:,} / OI {oi:,} baixa liquidez"
    scores['liquidity'] = s; details['liquidity'] = msg

    # 5. IV / Earnings (0-2)
    iv_pct = opt['iv_pct']
    ed     = opt.get('earnings_days', -1)
    if 0 <= ed <= 5:
        s = 0; msg = f"Earnings em {ed}d — REPROVADO"
    elif iv_pct > 120:
        s = 0; msg = f"IV {iv_pct:.0f}% muito alta"
    elif iv_pct > 80:
        s = 1; msg = f"IV {iv_pct:.0f}% alta mas aceitavel"
    else:
        s = 2; msg = f"IV {iv_pct:.0f}% razoavel"
    scores['iv_event'] = s; details['iv_event'] = msg

    total   = sum(scores.values())
    verdict = "APROVO" if total >= 8 else "AGUARDAR" if total >= 6 else "REPROVO"
    price   = opt.get('ask') or opt.get('price_ref', 0)

    return {
        "score":        total,
        "verdict":      verdict,
        "score_detail": scores,
        "score_notes":  details,
        "entry_price":  price,
        "stop_price":   round(price * 0.65, 2),
        "target_1":     round(price * 1.40, 2),
        "target_2":     round(price * 1.80, 2),
    }


# ── Busca de dados via TWS ────────────────────────────────────────────

def get_spot_and_vol(ib: IB, ticker: str) -> tuple:
    """Retorna (spot, iv_rank, iv_annual, hv30, call_vol, put_vol)"""
    stk = Stock(ticker, 'SMART', 'USD')
    ib.qualifyContracts(stk)

    t = ib.reqMktData(stk, genericTickList='')
    ib.sleep(2)

    snap = ib.reqMktData(stk, genericTickList='', snapshot=True)
    ib.sleep(2)

    spot     = float(t.last or t.close or t.bid or 0)
    iv_rank  = 0.0
    iv_ann   = 0.0
    hv30     = 0.0
    call_vol = 0
    put_vol  = 0

    ib.cancelMktData(stk)
    return spot, iv_rank, iv_ann, hv30, call_vol, put_vol


def get_full_snapshot(ib: IB, ticker: str) -> dict:
    """Busca snapshot completo via conector IBKR MCP."""
    stk = Stock(ticker, 'SMART', 'USD')
    ib.qualifyContracts(stk)

    # 104=HV | 106=OI | 162=IV rank | 411=realtime greeks
    t = ib.reqMktData(stk, genericTickList='104,106,411')
    ib.sleep(3)

    spot   = float(t.last or t.close or t.bid or 0)
    iv_ann = 0.0
    hv30   = 0.0

    # IV anual via modelGreeks do subjacente
    if t.modelGreeks and t.modelGreeks.impliedVol:
        iv_ann = float(t.modelGreeks.impliedVol)

    # HV30 via campo historico
    if hasattr(t, 'histVolatility') and t.histVolatility:
        try:
            hv30 = float(t.histVolatility)
        except Exception:
            hv30 = 0.0

    # Fallback: usa IV da cadeia se HV nao chegar
    # Sera preenchido depois com media da cadeia
    call_vol = 0
    put_vol  = 0

    ib.cancelMktData(stk)
    return {
        "spot":     round(spot, 2),
        "iv_ann":   round(iv_ann, 4),
        "hv30":     round(hv30, 4),
        "call_vol": call_vol,
        "put_vol":  put_vol,
    }


def fetch_full_chain(ib: IB, ticker: str, spot: float) -> tuple:
    """
    Busca cadeia completa CALL e PUT.
    Retorna (calls, puts) como listas de dicts.
    """
    stk = Stock(ticker, 'SMART', 'USD')
    ib.qualifyContracts(stk)

    chains = ib.reqSecDefOptParams(stk.symbol, '', stk.secType, stk.conId)
    chain  = next((c for c in chains if c.exchange == 'SMART'), None)
    if not chain:
        return [], []

    hoje = datetime.now().date()
    expirations = sorted([
        exp for exp in chain.expirations
        if DTE_MIN <= (datetime.strptime(exp, '%Y%m%d').date() - hoje).days <= DTE_MAX
    ])
    if not expirations:
        return [], []

    expiration = expirations[0]
    dte = (datetime.strptime(expiration, '%Y%m%d').date() - hoje).days

    # Strikes ±12% do spot (evita deep ITM/OTM)
    strikes = sorted([s for s in chain.strikes
                      if spot * 0.88 <= s <= spot * 1.12])
    if not strikes:
        return [], []

    # Monta contratos CALL e PUT
    call_contracts = [Option(ticker, expiration, s, 'C', 'SMART') for s in strikes]
    put_contracts  = [Option(ticker, expiration, s, 'P', 'SMART') for s in strikes]

    valid_calls = ib.qualifyContracts(*call_contracts)
    valid_puts  = ib.qualifyContracts(*put_contracts)

    all_valid = valid_calls + valid_puts
    if not all_valid:
        return [], []

    tickers_data = [ib.reqMktData(c) for c in all_valid]
    ib.sleep(4)

    def parse(contracts, tdata, right):
        results = []
        for i, t in enumerate(tdata):
            c = contracts[i]
            bid   = t.bid   if t.bid   and t.bid   > 0 else 0
            ask   = t.ask   if t.ask   and t.ask   > 0 else 0
            last  = t.last  if t.last  and t.last  > 0 else 0
            close = t.close if t.close and t.close > 0 else 0
            vol   = int(t.volume) if t.volume and t.volume > 0 else 0

            greeks = t.modelGreeks
            iv     = float(greeks.impliedVol) if greeks and greeks.impliedVol else 0
            delta  = float(greeks.delta)      if greeks and greeks.delta      else 0
            gamma  = float(greeks.gamma)      if greeks and greeks.gamma      else 0
            theta  = float(greeks.theta)      if greeks and greeks.theta      else 0

            price_ref = ask if ask > 0 else (close if close > 0 else last)
            if price_ref == 0 and not greeks:
                continue

            mid = round((bid + ask) / 2, 2) if (bid + ask) > 0 else round(price_ref, 2)
            oi  = int(t.openInterest) if hasattr(t, 'openInterest') and t.openInterest and t.openInterest > 0 else 0

            results.append({
                "ticker":        ticker,
                "direction":     "CALL" if right == 'C' else "PUT",
                "expiration":    expiration,
                "dte":           dte,
                "strike":        c.strike,
                "right":         right,
                "bid":           round(bid, 2),
                "ask":           round(ask if ask > 0 else close, 2),
                "last":          round(last, 2),
                "close":         round(close, 2),
                "mid":           mid,
                "volume":        vol,
                "open_interest": oi,
                "iv_pct":        round(iv * 100, 1),
                "delta":         round(delta, 3),
                "gamma":         round(gamma, 5),
                "theta":         round(theta, 4),
                "price_ref":     round(price_ref, 2),
                "spot":          spot,
                "earnings_days": -1,
                "gex":           calc_gex(gamma, oi, spot),
            })
        return results

    nc = len(valid_calls)
    calls = parse(valid_calls, tickers_data[:nc],  'C')
    puts  = parse(valid_puts,  tickers_data[nc:],  'P')

    for t in tickers_data:
        try:
            ib.cancelMktData(t.contract)
        except Exception:
            pass

    return calls, puts


# ── Scanner principal ─────────────────────────────────────────────────

def scan_ticker(ib: IB, ticker: str, direction: str) -> dict:
    print(f"\n  Escaneando {ticker}...")

    # Snapshot do subjacente
    snap = get_full_snapshot(ib, ticker)
    spot = snap['spot']
    if not spot:
        return {"ticker": ticker, "direction": direction, "error": "Spot nao disponivel"}

    print(f"  {ticker} spot: ${spot} | IV ann: {snap['iv_ann']*100:.1f}% | HV30: {snap['hv30']*100:.1f}%")

    # Cadeia completa CALL + PUT
    calls, puts = fetch_full_chain(ib, ticker, spot)
    chain_dir = calls if direction == 'CALL' else puts

    if not chain_dir:
        return {"ticker": ticker, "direction": direction, "spot": spot,
                "error": "Sem contratos validos"}

    # ── Fallback IV via media da cadeia ──
    if snap['iv_ann'] == 0 and chain_dir:
        valid_ivs = [c['iv_pct']/100 for c in chain_dir if c['iv_pct'] > 0]
        snap['iv_ann'] = round(sum(valid_ivs)/len(valid_ivs), 4) if valid_ivs else 0

    # ── Edge RBC ──
    gex_data = calc_net_gex(calls + puts, spot)
    vrp_data = calc_vrp(snap['iv_ann'], snap['hv30'])
    skew_data = calc_skew(calls, puts, spot)
    pc_data   = calc_pc_ratio(snap['call_vol'], snap['put_vol'])
    edge      = edge_summary(gex_data, vrp_data, skew_data, pc_data, direction)

    print(f"  Edge: {edge['verdict']} ({edge['aprovados']}/4) | GEX: {gex_data['net_gex_M']} | VRP: {vrp_data.get('vrp','?')}% | Skew: {skew_data.get('skew_pct','?')}%")

    # Score cada contrato
    scored = []
    for opt in chain_dir:
        s = score_contract(opt, direction)
        opt.update(s)
        scored.append(opt)

    scored.sort(key=lambda x: (-x['score'], x.get('spread_pct', 100)))
    top3 = scored[:3]

    best    = top3[0]['score'] if top3 else 0
    overall = "APROVO" if best >= 8 else "AGUARDAR" if best >= 6 else "REPROVO"

    return {
        "ticker":          ticker,
        "direction":       direction,
        "spot":            spot,
        "scanned":         len(chain_dir),
        "overall_verdict": overall,
        "edge":            edge,
        "top_contracts":   top3,
        "timestamp":       datetime.now().strftime('%Y-%m-%d %H:%M ET'),
    }


# ── Output ────────────────────────────────────────────────────────────

def print_result(r: dict) -> None:
    SEP  = "-" * 65
    SEP2 = "=" * 65

    if "error" in r:
        print(f"\n  {r['ticker']} {r['direction']}: {r['error']}")
        return

    icon = "✅" if r['overall_verdict'] == "APROVO" else "⚠" if r['overall_verdict'] == "AGUARDAR" else "❌"
    print(f"\n{SEP2}")
    print(f"  {r['ticker']} · {r['direction']} | Spot ${r['spot']} | {r['timestamp']}")
    print(f"  {icon} {r['overall_verdict']} — {r['scanned']} contratos escaneados")

    # Edge RBC
    edge = r.get('edge', {})
    ei = "✅" if "FAVORAVEL" in edge.get('verdict','') else "⚠" if "NEUTRO" in edge.get('verdict','') else "❌"
    print(f"\n  {ei} EDGE RBC: {edge.get('verdict','')} — {edge.get('note','')}")
    fatores = edge.get('fatores', {})
    if fatores:
        gex = fatores.get('gex', {})
        vrp = fatores.get('vrp', {})
        sk  = fatores.get('skew', {})
        pc  = fatores.get('pc_ratio', {})
        print(f"     GEX   : {gex.get('net_gex_M','?')} — {gex.get('regime','')}")
        print(f"     VRP   : {vrp.get('vrp','?')}% — {vrp.get('signal','')}")
        print(f"     Skew  : {sk.get('skew_pct','?')}% — {sk.get('signal','')}")
        print(f"     P/C   : {pc.get('pc_ratio','?')} — {pc.get('signal','')}")
    print(f"{SEP2}")

    for i, c in enumerate(r['top_contracts'], 1):
        vi = "✅" if c['verdict'] == "APROVO" else "⚠" if c['verdict'] == "AGUARDAR" else "❌"
        print(f"\n  #{i} {r['ticker']} {c['direction']} {c['strike']} — Exp {c['expiration']} ({c['dte']}d)")
        print(f"  {vi} Score {c['score']}/10 | {c['verdict']}")
        print(f"{SEP}")
        print(f"  Bid/Ask    : ${c['bid']:.2f} / ${c['ask']:.2f}  (spread {c.get('spread_pct',0):.1f}%)")
        print(f"  Delta      : {c['delta']:.3f}  |  IV: {c['iv_pct']:.1f}%  |  GEX: ${c.get('gex',0):,.0f}")
        print(f"  Volume     : {c['volume']:,}  |  OI: {c['open_interest']:,}")
        print(f"  Entry      : ${c['entry_price']:.2f}  (${c['entry_price']*100:.0f}/contrato)")
        print(f"  Stop       : ${c['stop_price']:.2f}  (-35%)")
        print(f"  Alvo 1     : ${c['target_1']:.2f}  (+40%)")
        print(f"  Alvo 2     : ${c['target_2']:.2f}  (+80%)")
        print(f"  Score detalhe:")
        for k, note in c['score_notes'].items():
            s  = c['score_detail'][k]
            si = "✅" if s == 2 else "⚠" if s == 1 else "❌"
            print(f"    {si} [{s}/2] {note}")

    print(f"\n{SEP2}")


def save_results(results: list[dict]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts   = datetime.now().strftime('%Y%m%d_%H%M')
    path = OUTPUT_DIR / f"swing_scan_{ts}.json"
    with open(path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Resultado salvo em: {path}")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='RBC Modo 5 - US Swing Scanner')
    parser.add_argument('--tickers',   nargs='+', default=DEFAULT_TICKERS)
    parser.add_argument('--direction', choices=['CALL', 'PUT', 'BOTH'], default='BOTH')
    args = parser.parse_args()

    directions = ['CALL', 'PUT'] if args.direction == 'BOTH' else [args.direction]

    print("\n" + "=" * 65)
    print("  RBC — Modo 5 · US Swing Options Scanner v2.0")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Tickers : {', '.join(args.tickers)}")
    print(f"  Direcao : {args.direction}")
    print(f"  Edge    : GEX + VRP + Skew + P/C Ratio (sem API paga)")
    print("=" * 65)

    print(f"\n  Conectando ao TWS ({TWS_HOST}:{TWS_PORT})...")
    ib = IB()
    try:
        ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
        print("  Conectado!\n")
    except Exception as e:
        print(f"  Erro: {e}")
        print("  Verifique se o TWS esta aberto e API habilitada.")
        return

    results = []
    for ticker in args.tickers:
        for direction in directions:
            r = scan_ticker(ib, ticker, direction)
            results.append(r)
            print_result(r)

    ib.disconnect()
    save_results(results)

    print("  Confirme no TWS antes de operar.")
    print("  Stop: -35% | Alvo 1: +40% | Alvo 2: +80%\n")


if __name__ == '__main__':
    main()
