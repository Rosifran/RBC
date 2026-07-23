"""
RBC — Camada 2: Confirmação Técnica (elo Flow Scanner → APROVO_ONDINHA)
========================================================================
Recebe a direção do fluxo incomum (CALL/PUT) e pontua o gráfico DIÁRIO
do subjacente em 4 critérios (0-10). A aposta detectada no fluxo só vira
candidata a entrada se o gráfico sustentar a direção.

Score:
  Tendência (0-3): preço vs SMA20/SMA50 alinhadas com a direção
  Momentum  (0-3): RSI14 a favor sem estar esticado (entrada atrasada = 0)
  Estrutura (0-3): espaço até resistência (CALL) / suporte (PUT) de 20d
  Volume    (0-1): subjacente confirmando acima da média de 20d

Veredito (mesma régua do us_swing):
  >= 8  -> APROVO_ONDINHA
  6-7   -> AGUARDAR
  <  6  -> REPROVO_TECNICA
"""

def _sma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None

def _rsi14(closes):
    if len(closes) < 15:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:14]) / 14
    avg_l = sum(losses[:14]) / 14
    for i in range(14, len(gains)):
        avg_g = (avg_g * 13 + gains[i]) / 14
        avg_l = (avg_l * 13 + losses[i]) / 14
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - 100 / (1 + rs), 1)

def analyze_technical(ib, ticker, direction, _bars=None):
    """direction: 'CALL' ou 'PUT' (do flow_summary.dominant_direction)."""
    if _bars is None:
        from ib_insync import Stock
        contract = Stock(ticker, "SMART", "USD")
        ib.qualifyContracts(contract)
        _bars = ib.reqHistoricalData(
            contract, endDateTime="", durationStr="6 M",
            barSizeSetting="1 day", whatToShow="TRADES",
            useRTH=True, formatDate=1)
    closes  = [b.close for b in _bars]
    highs   = [b.high for b in _bars]
    lows    = [b.low for b in _bars]
    volumes = [b.volume for b in _bars]

    if len(closes) < 60:
        return {"verdict": "SEM_DADOS", "score": None,
                "note": f"Historico insuficiente ({len(closes)} candles)."}

    close  = closes[-1]
    sma20  = _sma(closes, 20)
    sma50  = _sma(closes, 50)
    rsi    = _rsi14(closes)
    res20  = max(highs[-21:-1])   # resistencia: maxima dos 20d anteriores
    sup20  = min(lows[-21:-1])    # suporte: minima dos 20d anteriores
    vol_avg = _sma(volumes, 20)
    is_call = direction == "CALL"

    # ── Tendencia (0-3) ──
    t = 0
    if is_call:
        t += close > sma20
        t += sma20 > sma50
        t += close > sma50
    else:
        t += close < sma20
        t += sma20 < sma50
        t += close < sma50
    trend_pts = int(t)

    # ── Momentum (0-3): RSI espelhado p/ PUT ──
    r = rsi if is_call else (100 - rsi)
    if 50 <= r <= 68:      mom_pts = 3   # a favor, saudavel
    elif 45 <= r < 50 or 68 < r <= 72: mom_pts = 2
    elif 40 <= r < 45 or 72 < r <= 78: mom_pts = 1   # fraco ou esticando
    else:                  mom_pts = 0   # contra, ou esticado (entrada atrasada)

    # ── Estrutura (0-3): espaco para andar ──
    if is_call:
        if close > res20:
            est_pts, est_note = 3, "rompimento da resistencia 20d"
        else:
            dist = (res20 - close) / close * 100
            est_pts = 3 if dist >= 5 else 2 if dist >= 3 else 1 if dist >= 1.5 else 0
            est_note = f"{dist:.1f}% ate resistencia {res20:.2f}"
    else:
        if close < sup20:
            est_pts, est_note = 3, "perda do suporte 20d"
        else:
            dist = (close - sup20) / close * 100
            est_pts = 3 if dist >= 5 else 2 if dist >= 3 else 1 if dist >= 1.5 else 0
            est_note = f"{dist:.1f}% ate suporte {sup20:.2f}"

    # ── Volume (0-1) ──
    vol_pts = 1 if vol_avg and volumes[-1] > 1.2 * vol_avg else 0

    score = trend_pts + mom_pts + est_pts + vol_pts
    if r > 78:
        # RSI esticado na direcao da aposta = entrada atrasada. Veto duro.
        verdict = "REPROVO_TECNICA"
        est_note += " | RSI esticado (entrada atrasada)"
    elif score >= 8:
        verdict = "APROVO_ONDINHA"
    elif score >= 6:
        verdict = "AGUARDAR"
    else:
        verdict = "REPROVO_TECNICA"

    return {
        "verdict":   verdict,
        "score":     score,
        "direction": direction,
        "close":     round(close, 2),
        "sma20":     round(sma20, 2),
        "sma50":     round(sma50, 2),
        "rsi14":     rsi,
        "trend_pts": trend_pts,
        "mom_pts":   mom_pts,
        "est_pts":   est_pts,
        "est_note":  est_note,
        "vol_pts":   vol_pts,
        "note": (f"Tendencia {trend_pts}/3 · Momentum {mom_pts}/3 (RSI {rsi}) · "
                 f"Estrutura {est_pts}/3 ({est_note}) · Volume {vol_pts}/1"),
    }

def print_tecnica(ticker, tec):
    v = tec.get("verdict")
    icon = {"APROVO_ONDINHA": "🟢", "AGUARDAR": "🟡",
            "REPROVO_TECNICA": "🔴"}.get(v, "⚪")
    print(f"  {icon} CAMADA 2 TECNICA — {v}"
          + (f" · Score {tec['score']}/10" if tec.get("score") is not None else ""))
    if tec.get("note"):
        print(f"    {tec['note']}")
    if v == "APROVO_ONDINHA":
        print(f"    Fluxo + tecnica alinhados. Candidato a 1 contrato "
              f"{tec.get('direction','')} — validar preco do contrato antes.")
    elif v == "AGUARDAR":
        print(f"    Tecnica parcial. Monitorar — nao e entrada ainda.")
    elif v == "REPROVO_TECNICA":
        print(f"    Grafico nao sustenta a direcao do fluxo. Descartar.")
    print()
