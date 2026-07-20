"""
RBC — Risk Bridge Capital
Modo 8 · Equity Research v0.1-beta
===================================
Motor de análise fundamentalista sell-side para mid caps industriais.

Pipeline:
  1. SCREENER  — filtra o universo candidato (market cap, cobertura, liquidez de opções)
  2. COLETA    — SEC EDGAR (companyfacts) + yfinance (preço, múltiplos, opções)
  3. SCORING   — 4 pilares (Qualidade, Crescimento, Balanço, Valuation) vs. pares
  4. GATE      — red flags que travam BUY independente do score
  5. RATING    — BUY / HOLD / SELL + preço-alvo por EV/EBITDA justo
  6. TESE      — Claude escreve a tese sell-side em PT-BR (opcional, usa ANTHROPIC_API_KEY)

Uso local:
  python3 rbc_research.py            → roda pipeline completo no universo
  python3 rbc_research.py AIT GGG    → roda só nos tickers informados

OBS: Ferramenta educacional de organização de análise. Não é recomendação
de compra ou venda. Decisão final é sempre sua, com preço real do IBKR.
"""

import os
import sys
import json
import time
import math
import statistics
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    requests = None

try:
    import yfinance as yf
except ImportError:
    yf = None

# ── Configuração ──────────────────────────────────────────────────────

# Universo candidato: mid caps industriais americanas com opções listadas.
# O screener revalida em runtime (market cap, nº de analistas, liquidez de
# opções) — esta lista é só o ponto de partida, edite à vontade.
UNIVERSE = [
    "AIT",   # Applied Industrial Technologies — distribuição industrial
    "GGG",   # Graco — equipamentos de fluidos
    "NDSN",  # Nordson — sistemas de dispensação
    "MIDD",  # Middleby — equipamentos foodservice
    "RRX",   # Regal Rexnord — motores e transmissão
    "FLS",   # Flowserve — bombas e válvulas
    "CSL",   # Carlisle — materiais de construção
    "AOS",   # A.O. Smith — aquecedores de água
    "CW",    # Curtiss-Wright — industrial/defesa
    "TTC",   # Toro — equipamentos de paisagismo
    "DCI",   # Donaldson — filtração
    "IEX",   # IDEX — bombas e medição
    "CR",    # Crane — industrial diversificado
    "MAS",   # Masco — produtos de construção
    "ALLE",  # Allegion — segurança/fechaduras
    "GNRC",  # Generac — geradores
    "OSK",   # Oshkosh — veículos especiais
    "TKR",   # Timken — rolamentos
    "KMT",   # Kennametal — ferramentas de corte
    "PNR",   # Pentair — água
    "SSD",   # Simpson Manufacturing — conectores estruturais
    "MLI",   # Mueller Industries — produtos de cobre
    "ATKR",  # Atkore — infraestrutura elétrica
    "FELE",  # Franklin Electric — bombas d'água
    "JBTM",   # JBT Marel — equipamentos alimentícios
    "ESAB",  # ESAB — soldagem
    "WTS",   # Watts Water — controle de água
    "EXP",   # Eagle Materials — cimento e gesso
]

SCREEN = {
    "mcap_min": 2e9,           # US$ 2 bi
    "mcap_max": 25e9,          # US$ 25 bi
    "max_analysts": 20,        # mid caps podem ter mais cobertura que small caps
    "min_option_oi": 150,      # calibrado para liquidez real de mid caps
    "max_option_spread": 0.25, # research aceita spread maior; trade ainda exige IBKR
}

WEIGHTS = {"quality": 0.30, "growth": 0.25, "balance": 0.20, "valuation": 0.25}

RATING_BUY = 65    # composto ≥ 65 e gate limpo
RATING_SELL = 40   # composto ≤ 40 ou 2+ red flags

CACHE_PATH = os.path.expanduser("~/RBC/research_cache.json")
SEC_UA = os.environ.get(
    "SEC_USER_AGENT",
    "RBC Research (Risk Bridge Capital) contato@riskbridge.example",
)

# ── Utilidades ────────────────────────────────────────────────────────

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _pct_rank(values, x, higher_is_better=True):
    """Percentil (0-100) de x dentro de values. Ignora None."""
    vals = [v for v in values if v is not None and not math.isnan(v)]
    if x is None or (isinstance(x, float) and math.isnan(x)) or len(vals) < 3:
        return None
    below = sum(1 for v in vals if v < x)
    equal = sum(1 for v in vals if v == x)
    pct = (below + 0.5 * equal) / len(vals) * 100
    return pct if higher_is_better else 100 - pct


# ── SEC EDGAR ─────────────────────────────────────────────────────────

_TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "op_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "dep_amort": ["DepreciationDepletionAndAmortization",
                  "DepreciationAndAmortization",
                  "DepreciationAmortizationAndAccretionNet"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "lt_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "st_debt": ["LongTermDebtCurrent", "DebtCurrent",
                "ShortTermBorrowings"],
    "assets_cur": ["AssetsCurrent"],
    "liab_cur": ["LiabilitiesCurrent"],
    "interest_exp": ["InterestExpense", "InterestExpenseDebt",
                     "InterestIncomeExpenseNet"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}

_INSTANT = {"equity", "cash", "lt_debt", "st_debt", "assets_cur", "liab_cur"}


def edgar_cik_map():
    """ticker → CIK (10 dígitos). Cacheado em memória."""
    if getattr(edgar_cik_map, "_cache", None):
        return edgar_cik_map._cache
    r = requests.get("https://www.sec.gov/files/company_tickers.json",
                     headers={"User-Agent": SEC_UA}, timeout=30)
    r.raise_for_status()
    data = r.json()
    out = {row["ticker"].upper(): str(row["cik_str"]).zfill(10)
           for row in data.values()}
    edgar_cik_map._cache = out
    return out


def edgar_companyfacts(ticker):
    cik = edgar_cik_map().get(ticker.upper())
    if not cik:
        return None
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    r = requests.get(url, headers={"User-Agent": SEC_UA}, timeout=60)
    if r.status_code != 200:
        return None
    time.sleep(0.15)  # cortesia com o rate limit do SEC (10 req/s máx)
    return r.json()


def _extract_series(facts, keys, instant=False):
    """
    Extrai série {end_date: value} de um conceito us-gaap, testando fallbacks.
    Para fluxos (não-instant), mantém apenas períodos de ~1 trimestre (60-120d)
    e também registra períodos anuais para derivar Q4 = FY − (Q1+Q2+Q3).
    """
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for key in keys:
        node = gaap.get(key)
        if not node:
            continue
        units = node.get("units", {})
        pts = units.get("USD") or next(iter(units.values()), [])
        if not pts:
            continue
        q, fy = {}, {}
        for p in pts:
            if p.get("form") not in ("10-Q", "10-K"):
                continue
            end = p.get("end")
            val = p.get("val")
            if end is None or val is None:
                continue
            if instant:
                q[end] = val
                continue
            start = p.get("start")
            if not start:
                continue
            days = _safe(lambda: (datetime.fromisoformat(end)
                                  - datetime.fromisoformat(start)).days)
            if days is None:
                continue
            if 60 <= days <= 120:
                q[end] = val
            elif 330 <= days <= 400:
                fy[end] = val
        if q or fy:
            return {"quarterly": q, "annual": fy}
    return {"quarterly": {}, "annual": {}}


def _fill_q4(series):
    """Deriva Q4 ausente: FY − soma dos 3 trimestres anteriores no mesmo ano fiscal."""
    q, fy = series["quarterly"], series["annual"]
    for end, fy_val in fy.items():
        if end in q:
            continue
        end_dt = _safe(lambda: datetime.fromisoformat(end))
        if not end_dt:
            continue
        prior = [v for d, v in q.items()
                 if (dd := _safe(lambda: datetime.fromisoformat(d)))
                 and timedelta(days=0) < end_dt - dd <= timedelta(days=290)]
        if len(prior) == 3:
            q[end] = fy_val - sum(prior)
    return q


def collect_fundamentals(ticker):
    """
    Baixa e organiza os fundamentos trimestrais de um ticker via EDGAR.
    Retorna dict com séries trimestrais ordenadas (mais recente por último).
    """
    facts = edgar_companyfacts(ticker)
    if not facts:
        return None
    out = {"ticker": ticker, "entity": facts.get("entityName", ticker)}
    for name, keys in _TAGS.items():
        s = _extract_series(facts, keys, instant=(name in _INSTANT))
        data = s["quarterly"] if name in _INSTANT else _fill_q4(s)
        out[name] = dict(sorted(data.items())[-24:])  # ~6 anos
    return out


# ── Métricas derivadas ────────────────────────────────────────────────

def _last(d, n=1):
    vals = list(d.values())
    return vals[-n:] if vals else []


def _ttm(d, offset=0):
    vals = list(d.values())
    if len(vals) < 4 + offset:
        return None
    sl = vals[-(4 + offset):len(vals) - offset or None]
    return sum(sl[:4]) if len(sl) >= 4 else None


def compute_metrics(f, market):
    """
    f      : saída de collect_fundamentals
    market : dict com price, mcap, shares (yfinance)
    """
    m = {}
    rev_ttm = _ttm(f["revenue"]);          m["rev_ttm"] = rev_ttm
    rev_prev = _ttm(f["revenue"], 4)
    ni_ttm = _ttm(f["net_income"]);        m["ni_ttm"] = ni_ttm
    ni_prev = _ttm(f["net_income"], 4)
    op_ttm = _ttm(f["op_income"])
    da_ttm = _ttm(f["dep_amort"]) or 0
    ocf_ttm = _ttm(f["ocf"])
    capex_ttm = _ttm(f["capex"]) or 0
    int_ttm = _ttm(f["interest_exp"])

    ebitda = (op_ttm + da_ttm) if op_ttm is not None else None
    m["ebitda_ttm"] = ebitda
    fcf = (ocf_ttm - abs(capex_ttm)) if ocf_ttm is not None else None
    m["fcf_ttm"] = fcf

    eq = (_last(f["equity"]) or [None])[0]
    cash = (_last(f["cash"]) or [0])[0] or 0
    lt = (_last(f["lt_debt"]) or [0])[0] or 0
    st = (_last(f["st_debt"]) or [0])[0] or 0
    ac = (_last(f["assets_cur"]) or [None])[0]
    lc = (_last(f["liab_cur"]) or [None])[0]
    net_debt = lt + st - cash
    m["net_debt"] = net_debt

    # Qualidade
    m["roe"] = ni_ttm / eq if ni_ttm and eq else None
    m["op_margin"] = op_ttm / rev_ttm if op_ttm and rev_ttm else None
    m["fcf_conv"] = fcf / ni_ttm if fcf is not None and ni_ttm else None
    cap_emp = (eq or 0) + lt + st
    m["roic"] = (op_ttm * 0.78) / cap_emp if op_ttm and cap_emp > 0 else None

    # Crescimento
    m["rev_yoy"] = rev_ttm / rev_prev - 1 if rev_ttm and rev_prev else None
    m["ni_yoy"] = ni_ttm / ni_prev - 1 if ni_ttm and ni_prev and ni_prev > 0 else None
    ops = _last(f["op_income"], 6)
    revs = _last(f["revenue"], 6)
    if len(ops) >= 6 and len(revs) >= 6 and all(revs):
        margins = [o / r for o, r in zip(ops, revs)]
        m["margin_trend"] = margins[-1] - statistics.mean(margins[:3])
        m["_margins_seq"] = margins
    else:
        m["margin_trend"] = None
        m["_margins_seq"] = []

    # Balanço
    m["nd_ebitda"] = net_debt / ebitda if ebitda and ebitda > 0 else None
    m["int_cover"] = op_ttm / abs(int_ttm) if op_ttm and int_ttm else None
    m["current_ratio"] = ac / lc if ac and lc else None

    # Valuation (precisa de mercado)
    price = market.get("price")
    mcap = market.get("mcap")
    shares = market.get("shares")
    m["price"] = price
    m["shares"] = shares
    if mcap and ebitda and ebitda > 0:
        m["ev_ebitda"] = (mcap + net_debt) / ebitda
    else:
        m["ev_ebitda"] = None
    m["pe"] = mcap / ni_ttm if mcap and ni_ttm and ni_ttm > 0 else None
    m["fcf_yield"] = fcf / mcap if fcf is not None and mcap else None
    return m


# ── Gate de red flags ─────────────────────────────────────────────────

def red_flags(m, f):
    flags = []
    if m.get("nd_ebitda") is not None and m["nd_ebitda"] > 4:
        flags.append(f"Dívida líquida/EBITDA {m['nd_ebitda']:.1f}x > 4x")
    if m.get("int_cover") is not None and m["int_cover"] < 2:
        flags.append(f"Cobertura de juros {m['int_cover']:.1f}x < 2x")
    if m.get("current_ratio") is not None and m["current_ratio"] < 1:
        flags.append(f"Current ratio {m['current_ratio']:.2f} < 1")
    fcfs = []
    ocf, capex = list(f["ocf"].values()), list(f["capex"].values())
    for i in range(1, min(len(ocf), len(capex), 4) + 1):
        fcfs.append(ocf[-i] - abs(capex[-i]))
    if len(fcfs) == 4 and all(x < 0 for x in fcfs):
        flags.append("FCF negativo nos últimos 4 trimestres")
    seq = m.get("_margins_seq", [])
    if len(seq) >= 4 and seq[-1] < seq[-2] < seq[-3] < seq[-4]:
        flags.append("Margem operacional caindo há 3 trimestres seguidos")
    return flags


# ── Scoring vs. pares ─────────────────────────────────────────────────

PILLARS = {
    "quality":   [("roe", True), ("roic", True), ("op_margin", True), ("fcf_conv", True)],
    "growth":    [("rev_yoy", True), ("ni_yoy", True), ("margin_trend", True)],
    "balance":   [("nd_ebitda", False), ("int_cover", True), ("current_ratio", True)],
    "valuation": [("ev_ebitda", False), ("pe", False), ("fcf_yield", True)],
}


def score_universe(metrics_by_ticker):
    """
    metrics_by_ticker: {ticker: metrics}
    Retorna {ticker: {pillar_scores, composite}}
    """
    tickers = list(metrics_by_ticker)
    scores = {}
    for t in tickers:
        m = metrics_by_ticker[t]
        pillar_scores = {}
        for pillar, metric_list in PILLARS.items():
            pcts = []
            for name, hib in metric_list:
                peer_vals = [metrics_by_ticker[o].get(name) for o in tickers]
                pct = _pct_rank(peer_vals, m.get(name), higher_is_better=hib)
                if pct is not None:
                    pcts.append(pct)
            pillar_scores[pillar] = round(statistics.mean(pcts), 1) if pcts else None
        valid = {k: v for k, v in pillar_scores.items() if v is not None}
        if valid:
            wsum = sum(WEIGHTS[k] for k in valid)
            composite = sum(WEIGHTS[k] * v for k, v in valid.items()) / wsum
        else:
            composite = None
        scores[t] = {"pillars": pillar_scores,
                     "composite": round(composite, 1) if composite else None}
    return scores


def target_price(m, peer_ev_ebitda_median, quality_pct):
    """
    EV/EBITDA justo = mediana dos pares × ajuste de qualidade (0.90x a 1.10x).
    Alvo = (mult_justo × EBITDA − dívida líquida) / ações.
    """
    if not all([m.get("ebitda_ttm"), m.get("shares"), peer_ev_ebitda_median]):
        return None, None
    adj = 0.90 + 0.20 * ((quality_pct or 50) / 100)
    fair_mult = peer_ev_ebitda_median * adj
    tgt = (fair_mult * m["ebitda_ttm"] - m["net_debt"]) / m["shares"]
    upside = tgt / m["price"] - 1 if m.get("price") else None
    return round(tgt, 2), (round(upside * 100, 1) if upside is not None else None)


def assign_rating(composite, flags, upside_pct=None):
    """
    Rating fundamentalista calibrado:
    - BUY exige score alto + upside relevante.
    - SELL com upside alto vira REVIEW, não SELL automático.
    - Red flags fortes bloqueiam BUY.
    """
    if len(flags) >= 2:
        if upside_pct is not None and upside_pct >= 15:
            return "REVIEW"
        return "SELL"

    if composite >= RATING_BUY:
        if upside_pct is not None and upside_pct >= 15 and not flags:
            return "BUY"
        return "HOLD"

    if composite <= RATING_SELL:
        if upside_pct is not None and upside_pct >= 15:
            return "REVIEW"
        return "SELL"

    return "HOLD"
def market_snapshot(ticker):
    tk = yf.Ticker(ticker)
    info = _safe(lambda: tk.info, {}) or {}
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not price:
        h = _safe(lambda: tk.history(period="5d"))
        price = float(h["Close"].iloc[-1]) if h is not None and len(h) else None
    return {
        "price": price,
        "mcap": info.get("marketCap"),
        "shares": info.get("sharesOutstanding"),
        "analysts": info.get("numberOfAnalystOpinions"),
        "name": info.get("shortName", ticker),
        "industry": info.get("industry", ""),
        "iv_hint": info.get("impliedVolatility"),
    }


def option_liquidity(ticker, spot):
    """OI somado e spread médio no ATM (±3 strikes) do vencimento ~30-45d."""
    tk = yf.Ticker(ticker)
    exps = _safe(lambda: tk.options, []) or []
    if not exps or not spot:
        return {"oi": 0, "spread": None}
    today = datetime.now()
    best = min(exps, key=lambda e: abs((_safe(lambda: datetime.fromisoformat(e))
                                        or today) - today - timedelta(days=37)))
    chain = _safe(lambda: tk.option_chain(best))
    if chain is None:
        return {"oi": 0, "spread": None}
    oi_total, spreads = 0, []
    for df in (chain.calls, chain.puts):
        df = df.copy()
        df["dist"] = (df["strike"] - spot).abs()
        near = df.nsmallest(3, "dist")
        oi_total += int(near["openInterest"].fillna(0).sum())
        for _, row in near.iterrows():
            bid, ask = row.get("bid") or 0, row.get("ask") or 0
            mid = (bid + ask) / 2
            if mid > 0.05:
                spreads.append((ask - bid) / mid)
    return {"oi": oi_total,
            "spread": round(statistics.mean(spreads), 3) if spreads else None,
            "expiry": best}


def run_screener(tickers=None, check_options=True):
    """Aplica os filtros SCREEN e retorna [{ticker, pass, motivo, dados}]."""
    results = []
    for t in tickers or UNIVERSE:
        mkt = _safe(lambda: market_snapshot(t), {}) or {}
        row = {"ticker": t, "name": mkt.get("name", t),
               "mcap": mkt.get("mcap"), "analysts": mkt.get("analysts"),
               "price": mkt.get("price"), "pass": True, "reasons": []}
        mc = mkt.get("mcap")
        if mc and not (SCREEN["mcap_min"] <= mc <= SCREEN["mcap_max"]):
            row["pass"] = False
            row["reasons"].append(f"mcap ${mc/1e9:.1f}B fora de "
                                  f"{SCREEN['mcap_min']/1e9:.0f}-{SCREEN['mcap_max']/1e9:.0f}B")
        an = mkt.get("analysts")
        if an and an > SCREEN["max_analysts"]:
            row["pass"] = False
            row["reasons"].append(f"{an} analistas > {SCREEN['max_analysts']} (muito coberta)")
        if check_options and row["pass"]:
            liq = _safe(lambda: option_liquidity(t, mkt.get("price")),
                        {"oi": 0, "spread": None})
            row["option_oi"] = liq["oi"]
            row["option_spread"] = liq["spread"]
            sem_dados = (liq["oi"] == 0 and liq["spread"] is None)
            if sem_dados:
                # Falha do Yahoo, nao iliquidez comprovada: aprova com aviso.
                row["reasons"].append("opcoes: Yahoo sem dados - conferir liquidez no IBKR")
            else:
                if liq["oi"] < SCREEN["min_option_oi"]:
                    row["pass"] = False
                    row["reasons"].append(f"OI opcoes {liq['oi']} < {SCREEN['min_option_oi']}")
                if liq["spread"] and liq["spread"] > SCREEN["max_option_spread"]:
                    # Spread do Yahoo fora do pregao e obsoleto: aviso, nao veto.
                    # Checagem real de spread e no IBKR, no strike da operacao.
                    row["reasons"].append(f"aviso: spread Yahoo {liq['spread']*100:.0f}% - conferir no IBKR")
        results.append(row)
    return results


# ── Tese via Claude (opcional) ────────────────────────────────────────

def write_thesis(ticker, name, m, scores, rating, tgt, upside, flags):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        payload = {
            "empresa": name, "ticker": ticker, "rating": rating,
            "preco": m.get("price"), "alvo": tgt, "upside_pct": upside,
            "scores": scores, "red_flags": flags,
            "metricas": {k: v for k, v in m.items()
                         if not k.startswith("_") and v is not None},
        }
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content":
                f"Você é analista sell-side sênior. Com base nestes dados, escreva "
                f"uma tese de investimento em português, 5-6 linhas, direta, no estilo "
                f"de sumário executivo de research de banco: rating, alvo, os 2-3 "
                f"argumentos centrais e o principal risco. Sem disclaimers, sem "
                f"markdown.\n\n{json.dumps(payload, default=str)}"}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"(tese indisponível: {e})"


# ── Pipeline completo ─────────────────────────────────────────────────

def run_research(tickers=None, with_thesis=True, verbose=True):
    tickers = tickers or [r["ticker"] for r in run_screener() if r["pass"]]
    if verbose:
        print(f"\n  Universo pós-screener: {len(tickers)} tickers → {', '.join(tickers)}")

    fundamentals, markets, metrics = {}, {}, {}
    for t in tickers:
        if verbose:
            print(f"  Coletando {t} (EDGAR + mercado)...")
        f = _safe(lambda: collect_fundamentals(t))
        mkt = _safe(lambda: market_snapshot(t), {}) or {}
        if not f or not mkt.get("mcap"):
            if verbose:
                print(f"    ⚠ {t}: dados incompletos, pulando.")
            continue
        fundamentals[t], markets[t] = f, mkt
        metrics[t] = compute_metrics(f, mkt)

    if len(metrics) < 3:
        raise RuntimeError("Menos de 3 tickers com dados — grupo de pares insuficiente.")

    scores = score_universe(metrics)
    ev_meds = [m["ev_ebitda"] for m in metrics.values() if m.get("ev_ebitda")]
    ev_median = statistics.median(ev_meds) if ev_meds else None

    report = []
    for t in metrics:
        m, sc = metrics[t], scores[t]
        flags = red_flags(m, fundamentals[t])
        tgt, upside = target_price(m, ev_median, sc["pillars"].get("quality"))
        rating = assign_rating(sc["composite"], flags, upside)
        row = {
            "ticker": t, "name": markets[t].get("name", t),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "rating": rating, "composite": sc["composite"],
            "pillars": sc["pillars"], "red_flags": flags,
            "price": m.get("price"), "target": tgt, "upside_pct": upside,
            "ev_ebitda": m.get("ev_ebitda"), "pe": m.get("pe"),
            "fcf_yield": m.get("fcf_yield"), "nd_ebitda": m.get("nd_ebitda"),
            "rev_yoy": m.get("rev_yoy"), "op_margin": m.get("op_margin"),
            "roe": m.get("roe"),
        }
        if with_thesis:
            row["thesis"] = write_thesis(t, row["name"], m, sc["pillars"],
                                         rating, tgt, upside, flags)
        report.append(row)

    report.sort(key=lambda r: r["composite"] or 0, reverse=True)
    _save_cache(report)
    return report


def _save_cache(report):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w") as fh:
            json.dump({"updated": datetime.now().isoformat(),
                       "report": report}, fh, indent=2, default=str)
    except Exception:
        pass


def load_cache():
    try:
        with open(CACHE_PATH) as fh:
            return json.load(fh)
    except Exception:
        return None


# ── Relatório em texto (estilo RBC) ───────────────────────────────────

def print_report(report):
    SEP, SEP2 = "─" * 68, "═" * 68
    print(f"\n{SEP2}")
    print(f"  RBC — Risk Bridge Capital | Equity Research v0.1-beta")
    print(f"  Mid caps industriais · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{SEP2}\n")
    print(f"  {'TICKER':<7}{'RATING':<7}{'SCORE':>6}{'PREÇO':>9}{'ALVO':>9}"
          f"{'UPSIDE':>8}{'EV/EBITDA':>10}{'ND/EBITDA':>10}")
    print(f"  {SEP[:66]}")
    for r in report:
        up = f"{r['upside_pct']:+.1f}%" if r["upside_pct"] is not None else "—"
        ev = f"{r['ev_ebitda']:.1f}x" if r["ev_ebitda"] else "—"
        nd = f"{r['nd_ebitda']:.1f}x" if r["nd_ebitda"] is not None else "—"
        px = f"${r['price']:.2f}" if r["price"] else "—"
        tg = f"${r['target']:.2f}" if r["target"] else "—"
        icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "REVIEW": "🔎"}.get(r["rating"], "⚪")
        print(f"  {r['ticker']:<7}{icon} {r['rating']:<5}"
              f"{r['composite'] or 0:>5.0f}{px:>9}{tg:>9}{up:>8}{ev:>10}{nd:>10}")
    print(f"\n{SEP}")
    for r in report:
        p = r["pillars"]
        print(f"\n  ▪ {r['ticker']} — {r['name']}")
        print(f"    Qualidade {p.get('quality') or 0:.0f} | "
              f"Crescimento {p.get('growth') or 0:.0f} | "
              f"Balanço {p.get('balance') or 0:.0f} | "
              f"Valuation {p.get('valuation') or 0:.0f}")
        for fl in r["red_flags"]:
            print(f"    🚩 {fl}")
        if r.get("thesis"):
            print(f"    {r['thesis']}")
    print(f"\n{SEP2}")
    print(f"  Ferramenta educacional. Não é recomendação de compra/venda.")
    print(f"  Confirme preços e prêmios reais no IBKR antes de qualquer decisão.")
    print(f"{SEP2}\n")


# ── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if requests is None or yf is None:
        print("Instale as dependências: pip3 install requests yfinance")
        sys.exit(1)
    args = [a.upper() for a in sys.argv[1:]]
    rep = run_research(tickers=args or None,
                       with_thesis=bool(os.environ.get("ANTHROPIC_API_KEY")))
    print_report(rep)
