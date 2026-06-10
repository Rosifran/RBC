"""
RBC EUA — Modo 5 Swing | Capital Fit Engine v1.0
=================================================
Camada de adequação de capital para contratos de opções (swing 14-35 DTE).

Objetivo: classificar cada contrato não só pelo score técnico, mas pela
adequação ao perfil operacional (1 contrato, custo controlado, risco em
dólar administrável, liquidez, movimento suficiente).

Interface principal:
    capital_fit_engine(contract, spot, ticker_profile) -> dict

Não mexe em: conexão IBKR, universo de tickers, score técnico antigo,
regras existentes de delta/DTE/spread. Apenas ADICIONA o campo
`capital_fit` ao resultado de cada contrato.

Integração (no scanner swing, após montar cada contrato):
    from capital_fit_engine import capital_fit_engine, get_ticker_profile
    profile = get_ticker_profile(ticker)
    contract["ticker_profile"] = profile
    contract["capital_fit"] = capital_fit_engine(contract, spot, profile)
"""

# ============================================================
# CONFIG — ajustar aqui sem tocar na lógica
# ============================================================
CONFIG = {
    "stop_pct": 0.35,              # stop padrão swing: -35% do prêmio
    "max_risk_at_stop": 250.0,     # risco máximo em dólar no stop (1 contrato)
    "max_spread_pct": 0.05,        # spread bid/ask máximo aceitável (5%)
    "min_volume": 100,             # volume mínimo no contrato
    "min_open_interest": 200,      # OI mínimo (se disponível; None = ignora)
    "oi_zero_means_missing": True, # feed IBKR atual retorna OI=0 sempre → tratar como ausente
    "min_delta": 0.30,             # abaixo disso = delta baixo demais
    "ideal_delta": (0.35, 0.55),   # faixa ideal de delta
    "dte_range": (14, 35),         # janela swing
    "iv_max_reasonable": 0.85,     # IV acima disso = prêmio inflado (85%)
    # Faixas de custo (contract_cost = ask * 100)
    "cost_cheap": 100.0,           # < 100 → CHEAP_SLOW
    "cost_ideal": (150.0, 350.0),  # faixa ideal para 1 contrato
    "cost_acceptable_max": 500.0,  # 350-500 → ACCEPTABLE
    "cost_expensive_max": 700.0,   # 500-700 → EXPENSIVE | >700 → BETTER_AS_SPREAD
}

# ============================================================
# TICKER PROFILES — classificação estática inicial
# movement_profile: SLOW | BALANCED | FAST
# premium_profile:  CHEAP | NORMAL | EXPENSIVE
# Pode ser refinado depois com ATR% real vindo do IBKR.
# ============================================================
TICKER_PROFILES = {
    # lentos / baratos
    "BAC":  {"movement_profile": "SLOW",     "premium_profile": "CHEAP"},
    "WFC":  {"movement_profile": "SLOW",     "premium_profile": "CHEAP"},
    "XLF":  {"movement_profile": "SLOW",     "premium_profile": "CHEAP"},
    "INTC": {"movement_profile": "BALANCED", "premium_profile": "CHEAP"},
    "SOFI": {"movement_profile": "BALANCED", "premium_profile": "CHEAP"},
    # meio termo — candidatos BALANCED/ACCESSIBLE
    "UBER": {"movement_profile": "BALANCED", "premium_profile": "NORMAL"},
    "PLTR": {"movement_profile": "FAST",     "premium_profile": "NORMAL"},
    "AMD":  {"movement_profile": "FAST",     "premium_profile": "NORMAL"},
    # rápidos / caros
    "AAPL": {"movement_profile": "BALANCED", "premium_profile": "EXPENSIVE"},
    "NVDA": {"movement_profile": "FAST",     "premium_profile": "EXPENSIVE"},
    "META": {"movement_profile": "FAST",     "premium_profile": "EXPENSIVE"},
    "AMZN": {"movement_profile": "BALANCED", "premium_profile": "EXPENSIVE"},
    "MSFT": {"movement_profile": "BALANCED", "premium_profile": "EXPENSIVE"},
    "TSLA": {"movement_profile": "FAST",     "premium_profile": "EXPENSIVE"},
    "SPY":  {"movement_profile": "BALANCED", "premium_profile": "NORMAL"},
    "QQQ":  {"movement_profile": "BALANCED", "premium_profile": "NORMAL"},
}

DEFAULT_PROFILE = {"movement_profile": "BALANCED", "premium_profile": "NORMAL"}


def get_ticker_profile(ticker, atr_pct=None):
    """
    Retorna o perfil do ticker. Se atr_pct (ATR diário / spot) for passado,
    refina movement_profile dinamicamente:
        < 1.2%  → SLOW | 1.2-2.5% → BALANCED | > 2.5% → FAST
    """
    profile = dict(TICKER_PROFILES.get(ticker.upper(), DEFAULT_PROFILE))
    if atr_pct is not None:
        if atr_pct < 0.012:
            profile["movement_profile"] = "SLOW"
        elif atr_pct <= 0.025:
            profile["movement_profile"] = "BALANCED"
        else:
            profile["movement_profile"] = "FAST"
    return profile


# ============================================================
# HELPERS
# ============================================================
def _spread_pct(bid, ask):
    """Spread relativo ao mid. Retorna None se dados insuficientes."""
    if not bid or not ask or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid


def _get(contract, *keys, default=None):
    """Busca tolerante a nomes de campo diferentes (ask/Ask/ask_price...)."""
    for k in keys:
        if k in contract and contract[k] is not None:
            return contract[k]
    return default


# ============================================================
# ENGINE PRINCIPAL
# ============================================================
def capital_fit_engine(contract, spot=None, ticker_profile=None):
    """
    Avalia adequação de capital de um contrato para o perfil swing
    (1 contrato, 14-35 DTE, custo ideal $150-$350).

    contract: dict com (nomes alternativos aceitos):
        ask / ask_price, bid / bid_price, delta, dte / days_to_exp,
        volume, open_interest / oi, iv / implied_vol
    spot: preço atual do subjacente (opcional, usado em notas)
    ticker_profile: dict {movement_profile, premium_profile}
                    (usar get_ticker_profile(); se None, assume BALANCED/NORMAL)

    Retorna dict capital_fit conforme spec.
    """
    cfg = CONFIG
    profile = ticker_profile or DEFAULT_PROFILE

    ask_raw = _get(contract, "ask", "ask_price")
    bid_raw = _get(contract, "bid", "bid_price")
    ask = float(ask_raw) if ask_raw is not None else None
    bid = float(bid_raw) if bid_raw is not None else None
    delta = _get(contract, "delta")
    delta = abs(float(delta)) if delta is not None else None
    dte = _get(contract, "dte", "days_to_exp", "days_to_expiration")
    dte = int(dte) if dte is not None else None
    volume = _get(contract, "volume", "vol")          # None = ausente; 0 = real
    volume = int(volume) if volume is not None else None
    oi = _get(contract, "open_interest", "oi")
    oi = int(oi) if oi is not None else None
    if oi == 0 and cfg["oi_zero_means_missing"]:
        oi = None  # feed atual não entrega OI — 0 é ausência, não OI real
    iv = _get(contract, "iv", "iv_pct", "implied_vol", "implied_volatility")
    iv = float(iv) if iv is not None else None
    if iv is not None and iv > 3:  # veio em % (ex: 45.0) em vez de decimal
        iv = iv / 100.0

    # ---------- DADOS_INSUFICIENTES (feed incompleto != contrato ruim) ----------
    # Dado AUSENTE (None) ou preço <= 0 vindo do IBKR é problema de feed.
    # Não classificar nem reprovar — sinalizar para revalidação.
    missing = []
    if ask is None or ask <= 0:
        missing.append("ask")
    if bid is None or bid < 0:
        missing.append("bid")
    if volume is None and oi is None:
        missing.append("volume/OI")
    if missing:
        cost = round(ask * 100, 2) if ask and ask > 0 else None
        return {
            "contract_cost": cost,
            "risk_at_stop": round(cost * cfg["stop_pct"], 2) if cost else None,
            "cost_bucket": "DADOS_INSUFICIENTES",
            "capital_status": "DADOS_INSUFICIENTES",
            "reason": f"feed IBKR incompleto: faltando {', '.join(missing)}",
            "preferred_structure": "WAIT",  # WAIT = revalidar quando feed completo; SKIP = reprovação real
            "rosi_note": (
                "Dados incompletos do feed IBKR. Ausência de dado não significa "
                "contrato ruim — revalidar antes de decidir."
            ),
        }

    contract_cost = round(ask * 100, 2)
    risk_at_stop = round(contract_cost * cfg["stop_pct"], 2)
    spread = _spread_pct(bid, ask)

    # ---------- gates duros (só com dado PRESENTE e comprovadamente ruim) ----------
    # Liquidez em 3 estados:
    #   OK          → volume ou OI acima do mínimo
    #   BAD         → dados presentes confirmam liquidez ruim → REPROVO
    #   UNCONFIRMED → volume baixo mas OI ausente no feed → NÃO reprova (regra GPT #2)
    vol_bad = volume is not None and volume < cfg["min_volume"]
    oi_bad = oi is not None and oi < cfg["min_open_interest"]
    if (volume or 0) >= cfg["min_volume"] or (oi or 0) >= cfg["min_open_interest"]:
        liquidity = "OK"
    elif (vol_bad and oi_bad) or (volume is None and oi_bad):
        liquidity = "BAD"
    else:
        liquidity = "UNCONFIRMED"
    liquidity_bad = liquidity == "BAD"
    spread_terrible = spread is not None and spread > cfg["max_spread_pct"] * 2  # >10%

    fails = []
    if spread_terrible:
        fails.append(f"spread muito ruim ({spread:.1%})")
    if liquidity_bad:
        fails.append(f"liquidez ruim (vol {volume}, OI {oi})")
    if risk_at_stop > cfg["max_risk_at_stop"]:
        fails.append(
            f"risco no stop ${risk_at_stop:.0f} > limite ${cfg['max_risk_at_stop']:.0f}"
        )

    hard_fail = spread_terrible or liquidity_bad
    if hard_fail:
        return {
            "contract_cost": contract_cost,
            "risk_at_stop": risk_at_stop,
            "cost_bucket": "REPROVO",
            "capital_status": "REPROVO_CAPITAL",
            "reason": "; ".join(fails),
            "preferred_structure": "SKIP",
            "rosi_note": "Contrato não adequado para o capital/perfil atual.",
        }

    # ---------- checks de qualidade (soft) ----------
    spread_ok = spread is not None and spread <= cfg["max_spread_pct"]
    volume_ok = liquidity != "BAD"  # UNCONFIRMED passa, mas rebaixa status depois
    dte_ok = dte is not None and cfg["dte_range"][0] <= dte <= cfg["dte_range"][1]
    delta_ideal = (
        delta is not None
        and cfg["ideal_delta"][0] <= delta <= cfg["ideal_delta"][1]
    )
    delta_too_low = delta is not None and delta < cfg["min_delta"]
    iv_ok = iv is None or iv <= cfg["iv_max_reasonable"]
    ticker_slow = profile.get("movement_profile") == "SLOW"
    quality_ok = spread_ok and volume_ok and dte_ok and iv_ok

    lo_ideal, hi_ideal = cfg["cost_ideal"]

    # ---------- classificação por custo + perfil ----------
    if contract_cost > cfg["cost_expensive_max"]:
        bucket = "BETTER_AS_SPREAD"
        status = "MONITORAR"
        structure = "DEBIT_SPREAD"
        reason = f"custo ${contract_cost:.0f} acima de ${cfg['cost_expensive_max']:.0f}"
        note = (
            "Contrato caro para compra direta. Se a tese for boa, preferir "
            "debit spread, call spread, put spread ou fly."
        )
        if iv is not None and iv > cfg["iv_max_reasonable"]:
            structure = "FLY"
            note += " IV elevada favorece fly para reduzir custo de vega."

    elif contract_cost > cfg["cost_acceptable_max"]:
        bucket = "EXPENSIVE"
        status = "MONITORAR"
        structure = "DEBIT_SPREAD"
        reason = (
            f"custo ${contract_cost:.0f} na faixa "
            f"${cfg['cost_acceptable_max']:.0f}-${cfg['cost_expensive_max']:.0f}"
        )
        note = "Contrato bom tecnicamente, mas caro para compra direta com 1 contrato."

    elif contract_cost < cfg["cost_cheap"] or delta_too_low or ticker_slow:
        bucket = "CHEAP_SLOW"
        status = "MONITORAR"
        structure = "LONG_OPTION"
        motivos = []
        if contract_cost < cfg["cost_cheap"]:
            motivos.append(f"custo baixo (${contract_cost:.0f})")
        if delta_too_low:
            motivos.append(f"delta baixo ({delta:.2f})")
        if ticker_slow:
            motivos.append("ticker historicamente lento")
        reason = "; ".join(motivos)
        note = "Contrato barato, mas pode ser lento. Só usar se a tese for muito clara."

    elif lo_ideal <= contract_cost <= hi_ideal and delta_ideal and quality_ok:
        bucket = "IDEAL_FOR_ONE_CONTRACT"
        status = "APROVO_CAPITAL"
        structure = "LONG_OPTION"
        reason = (
            f"custo ${contract_cost:.0f}, delta {delta:.2f}, DTE {dte}, "
            f"spread {spread:.1%}, liquidez ok"
        )
        note = (
            "Contrato ideal para 1 contrato: custo controlado, delta útil "
            "e risco administrável."
        )

    elif contract_cost <= cfg["cost_acceptable_max"] and quality_ok:
        # cobre 100-150 (entre cheap e ideal) e 350-500
        bucket = "ACCEPTABLE"
        status = "APROVO_CAPITAL"
        structure = "LONG_OPTION"
        if contract_cost < lo_ideal:
            reason = f"custo ${contract_cost:.0f} abaixo da faixa ideal, mas filtros ok"
            note = (
                "Contrato acessível e líquido, porém abaixo da faixa ideal — "
                "confirmar se o movimento esperado paga o trade."
            )
        else:
            reason = f"custo ${contract_cost:.0f} acima da faixa ideal, filtros ok"
            note = "Contrato aceitável, mas risco em dólar já exige convicção maior."
        if not delta_ideal and delta is not None:
            reason += f"; delta {delta:.2f} fora da faixa 0.35-0.55"

    else:
        # custo na faixa, mas qualidade falhou (spread/volume/DTE/IV)
        problemas = []
        if not spread_ok and spread is not None:
            problemas.append(f"spread {spread:.1%} > 5%")
        if not volume_ok:
            problemas.append(f"volume {volume} baixo")
        if not dte_ok:
            problemas.append(f"DTE {dte} fora de 14-35")
        if not iv_ok:
            problemas.append(f"IV {iv:.0%} inflada")
        if fails:
            problemas.extend(fails)
        bucket = "REPROVO"
        status = "REPROVO_CAPITAL"
        structure = "SKIP"
        reason = "; ".join(problemas) or "filtros de qualidade reprovados"
        note = "Contrato não adequado para o capital/perfil atual."

    # liquidez não confirmada (OI ausente + volume baixo) rebaixa status, não reprova
    if status == "APROVO_CAPITAL" and liquidity == "UNCONFIRMED":
        status = "MONITORAR"
        reason += f"; liquidez nao confirmada (vol {volume}, OI ausente no feed)"
        note += (
            " Liquidez não confirmada — OI ausente no feed; "
            "checar volume na abertura antes de entrar."
        )

    # risco no stop acima do limite rebaixa status (mesmo com bucket ok)
    if status == "APROVO_CAPITAL" and risk_at_stop > cfg["max_risk_at_stop"]:
        status = "MONITORAR"
        reason += f"; risco no stop ${risk_at_stop:.0f} acima do limite"
        note += " Atenção: risco em dólar no stop acima do limite desejado."

    return {
        "contract_cost": contract_cost,
        "risk_at_stop": risk_at_stop,
        "cost_bucket": bucket,
        "capital_status": status,
        "reason": reason,
        "preferred_structure": structure,
        "rosi_note": note,
    }


# ============================================================
# OUTPUT VISUAL — bloco CAPITAL FIT (texto, para o Modo 5)
# ============================================================
STATUS_ICON = {
    "APROVO_CAPITAL": "🟢",
    "MONITORAR": "🟡",
    "REPROVO_CAPITAL": "🔴",
    "DADOS_INSUFICIENTES": "⚪",
}

def format_capital_fit_block(capital_fit):
    """Bloco visual padrão CAPITAL FIT para exibir junto do score técnico."""
    icon = STATUS_ICON.get(capital_fit["capital_status"], "")
    cost = capital_fit.get("contract_cost")
    risk = capital_fit.get("risk_at_stop")
    cost_str = f"${cost:.0f}" if cost is not None else "N/A"
    risk_str = f"${risk:.0f}" if risk is not None else "N/A"
    return (
        "CAPITAL FIT\n"
        f"* Custo do contrato: {cost_str}\n"
        f"* Risco no stop (35%): {risk_str}\n"
        f"* Bucket: {capital_fit['cost_bucket']}\n"
        f"* Status capital: {icon} {capital_fit['capital_status']}\n"
        f"* Estrutura preferida: {capital_fit['preferred_structure']}\n"
        f"* Nota Rosi: \"{capital_fit['rosi_note']}\""
    )


# ============================================================
# ORDENAÇÃO — filtro opcional "IDEAL primeiro"
# ============================================================
BUCKET_PRIORITY = {
    "IDEAL_FOR_ONE_CONTRACT": 0,
    "ACCEPTABLE": 1,
    "CHEAP_SLOW": 2,
    "EXPENSIVE": 3,
    "BETTER_AS_SPREAD": 4,
    "DADOS_INSUFICIENTES": 5,
    "REPROVO": 6,
}

def sort_by_capital_fit(results, ideal_first=True):
    """
    Ordena lista de contratos (cada um com result['capital_fit']).
    ideal_first=True → IDEAL_FOR_ONE_CONTRACT primeiro; dentro do mesmo
    bucket, mantém ordem original (score técnico decide).
    """
    if not ideal_first:
        return results
    return sorted(
        results,
        key=lambda r: BUCKET_PRIORITY.get(
            (r.get("capital_fit") or {}).get("cost_bucket", "REPROVO"), 9
        ),
    )


# ============================================================
# INTEGRAÇÃO MODO 5 — enriquecimento do payload de swing_scans
# ============================================================
def enrich_scan_results(results, ideal_first=False):
    """
    Enriquecimento in-place do payload do Modo 5 (formato real confirmado
    em /api/modo5/latest):

        results = [
          {"ticker": "AAPL", "spot": 289.91, "direction": "CALL",
           "top_contracts": [{"ask":..., "bid":..., "delta":..., "dte":...,
                              "volume":..., "open_interest":..., "iv_pct":...}, ...],
           ...},
          ...
        ]

    Adiciona:
        bloco["ticker_profile"]          → perfil do ticker
        contrato["capital_fit"]          → output do engine
    Se ideal_first=True, reordena top_contracts (IDEAL primeiro).

    Uso no scanner (1 linha, antes de salvar em swing_scans):
        from capital_fit_engine import enrich_scan_results
        results = enrich_scan_results(results)
    """
    for block in results or []:
        ticker = block.get("ticker", "")
        block_spot = block.get("spot")
        profile = get_ticker_profile(ticker)
        block["ticker_profile"] = profile
        contracts = block.get("top_contracts") or []
        for c in contracts:
            c["capital_fit"] = capital_fit_engine(
                c, spot=c.get("spot", block_spot), ticker_profile=profile
            )
        if ideal_first:
            block["top_contracts"] = sort_by_capital_fit(contracts)
    return results


# ============================================================
# DEMO — exemplos da spec
# ============================================================
if __name__ == "__main__":
    # NVDA CALL 210 — caro
    nvda = {"ask": 6.85, "bid": 6.70, "delta": 0.48, "dte": 21, "volume": 5400, "iv": 0.42}
    fit = capital_fit_engine(nvda, spot=205.0, ticker_profile=get_ticker_profile("NVDA"))
    print("NVDA CALL 210 | Score técnico: 9/10")
    print(format_capital_fit_block(fit), "\n")

    # BAC CALL — barato e lento
    bac = {"ask": 1.00, "bid": 0.95, "delta": 0.40, "dte": 28, "volume": 800, "iv": 0.25}
    fit = capital_fit_engine(bac, spot=42.0, ticker_profile=get_ticker_profile("BAC"))
    print("BAC CALL")
    print(format_capital_fit_block(fit), "\n")

    # UBER CALL — candidato ideal
    uber = {"ask": 2.40, "bid": 2.32, "delta": 0.45, "dte": 24, "volume": 1200, "iv": 0.38}
    fit = capital_fit_engine(uber, spot=78.0, ticker_profile=get_ticker_profile("UBER"))
    print("UBER CALL")
    print(format_capital_fit_block(fit), "\n")

    # PLTR CALL — feed IBKR incompleto (sem bid, sem volume/OI)
    pltr = {"ask": 3.10, "bid": None, "delta": 0.42, "dte": 20}
    fit = capital_fit_engine(pltr, spot=65.0, ticker_profile=get_ticker_profile("PLTR"))
    print("PLTR CALL (feed incompleto)")
    print(format_capital_fit_block(fit))
