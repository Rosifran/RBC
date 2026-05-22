"""
RBC — Risk Bridge Capital
0DTE Strike Scanner v1.5-beta
========================
Cole os dados do SpotGamma no formato padrão e o scanner
recomenda o melhor strike para 0DTE no SPY.

Fluxo diário:
  1. Antes da abertura  → cole dados SpotGamma, rode em modo PRE_MARKET
  2. 9:30–10:00 ET      → observe, cole VIX + HIRO, rode em modo OPEN_WATCH
  3. Após 10:00 ET      → scanner libera análise de strike se gate abrir

Uso:
    python rbc_0dte_scanner.py

Ou importe e use as funções individualmente no seu código.
"""

import math
from datetime import datetime, time as dtime

# ── Black-Scholes ────────────────────────────────────────────────────

def norm_cdf(x):
    """Approximação de Abramowitz & Stegun — erro < 1.5e-7."""
    a = [0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429]
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    t = 1.0 / (1.0 + p * abs(x))
    y = 1.0 - (((((a[4]*t + a[3])*t + a[2])*t + a[1])*t + a[0])*t * math.exp(-x*x/2))
    return 0.5 * (1.0 + sign * y)

def bs_greeks(option_type, S, K, T, r, sigma):
    """
    Calcula preço teórico e Greeks pelo modelo Black-Scholes.
    option_type : 'call' ou 'put'
    S           : preço do spot
    K           : strike
    T           : tempo até expiração em anos
    r           : taxa risk-free (decimal)
    sigma       : volatilidade implícita anualizada (decimal)
    Retorna dict com price, delta, gamma, theta, vega, rho
    """
    if T <= 0:
        intrinsic = max(0, S - K) if option_type == 'call' else max(0, K - S)
        return dict(price=intrinsic, delta=1.0 if intrinsic > 0 else 0.0,
                    gamma=0, theta=0, vega=0, rho=0)

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    phi = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)

    if option_type == 'call':
        price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
        delta = norm_cdf(d1)
        rho   = K * T * math.exp(-r * T) * norm_cdf(d2) / 100
    else:
        price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
        delta = norm_cdf(d1) - 1
        rho   = -K * T * math.exp(-r * T) * norm_cdf(-d2) / 100

    gamma = phi / (S * sigma * math.sqrt(T))
    theta = (-S * phi * sigma / (2 * math.sqrt(T))
             - r * K * math.exp(-r * T) * (norm_cdf(d2) if option_type == 'call' else norm_cdf(-d2))) / 365
    vega  = S * phi * math.sqrt(T) / 100

    return dict(price=price, delta=delta, gamma=gamma,
                theta=theta, vega=vega, rho=rho)


# ── Parser SpotGamma ──────────────────────────────────────────────────

def parse_sg_data(raw_string):
    """
    Parseia a string de dados no formato SpotGamma que você cola.
    Formato de cada ativo:
      $TICKER, ticker, call_wall, put_wall, vol_trigger, abs_gamma,
      support1, support2, support3, combo1, combo2, combo3, combo4,
      implied_1d_move, implied_5d_move, zero_gamma
    Retorna dict keyed pelo ticker limpo (ex: 'SPY').
    """
    result = {}
    tokens = [t.strip() for t in raw_string.split(',')]
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith('$'):
            try:
                symbol   = tok.lstrip('$')          # ex: SPX
                ticker   = tokens[i+1]               # ex: SPX
                call_wall    = float(tokens[i+2])
                put_wall     = float(tokens[i+3])
                vol_trigger  = float(tokens[i+4])
                abs_gamma    = float(tokens[i+5])
                support1     = float(tokens[i+6])
                support2     = float(tokens[i+7])
                support3     = float(tokens[i+8])
                combo1       = float(tokens[i+9])
                combo2       = float(tokens[i+10])
                combo3       = float(tokens[i+11])
                combo4       = float(tokens[i+12])
                imp_1d       = float(tokens[i+13])
                imp_5d       = float(tokens[i+14])
                zero_gamma   = float(tokens[i+15])
                result[symbol] = {
                    'symbol':      symbol,
                    'ticker':      ticker,
                    'call_wall':   call_wall,
                    'put_wall':    put_wall,
                    'vol_trigger': vol_trigger,
                    'abs_gamma':   abs_gamma,
                    'supports':    [support1, support2, support3],
                    'combos':      [combo1, combo2, combo3, combo4],
                    'imp_1d':      imp_1d,
                    'imp_5d':      imp_5d,
                    'zero_gamma':  zero_gamma,
                }
                i += 16
            except (IndexError, ValueError):
                i += 1
        else:
            i += 1
    return result


# ── Parser Menthor Q ─────────────────────────────────────────────────

def parse_mq_data(raw_string):
    """
    Parseia a string de dados do Menthor Q.
    Usa matching exato de label para evitar confusão entre
    'Call Resistance' e 'Call Resistance 0DTE'.
    """
    result = {}
    import re
    blocks = re.split(r'\$(\w+):', raw_string)
    i = 1
    while i < len(blocks) - 1:
        ticker   = blocks[i].strip()
        data_str = blocks[i + 1]
        tokens   = [t.strip() for t in data_str.split(',')]

        def get_val_exact(label):
            """Matching exato — evita 'Call Resistance' capturar 'Call Resistance 0DTE'."""
            label_norm = label.strip().lower()
            for j, t in enumerate(tokens):
                if t.strip().lower() == label_norm:
                    try:
                        return float(tokens[j + 1])
                    except (IndexError, ValueError):
                        pass
            return None

        def get_val_gex(n):
            """GEX strikes por número exato."""
            return get_val_exact(f'GEX {n}')

        gex_strikes = []
        for n in range(1, 11):
            v = get_val_gex(n)
            if v is not None:
                gex_strikes.append(v)

        result[ticker] = {
            'ticker':           ticker,
            'call_res':         get_val_exact('Call Resistance'),
            'put_sup':          get_val_exact('Put Support'),
            'hvl':              get_val_exact('HVL'),
            'range_min':        get_val_exact('1D Min'),
            'range_max':        get_val_exact('1D Max'),
            'call_res_0dte':    get_val_exact('Call Resistance 0DTE'),
            'put_sup_0dte':     get_val_exact('Put Support 0DTE'),
            'hvl_0dte':         get_val_exact('HVL 0DTE'),
            'gamma_wall_0dte':  get_val_exact('Gamma Wall 0DTE'),
            'gex_strikes':      gex_strikes,
        }
        i += 2
    return result


# ── Sinal combinado SpotGamma + Menthor Q ────────────────────────────

def combined_signal(sg, mq, spot):
    """
    Cruza os dados do SpotGamma (sg) e Menthor Q (mq) para o mesmo ticker.
    Retorna um sinal combinado com confirmações e divergências.

    sg  : dict de um ticker do parse_sg_data()
    mq  : dict de um ticker do parse_mq_data()
    spot: preço atual do ativo
    """
    signals   = []
    confirms  = 0
    conflicts = 0

    # ── 1. Range do dia (Menthor Q) ───────────────────────────────────
    if mq.get('range_min') and mq.get('range_max'):
        rng = mq['range_max'] - mq['range_min']
        pct_in_range = (spot - mq['range_min']) / rng * 100 if rng else 50
        signals.append({
            'fonte': 'MQ Range',
            'label': f"Range 1D: {mq['range_min']} – {mq['range_max']}",
            'detail': f"Spot em {pct_in_range:.0f}% do range. "
                      f"{'Próximo do topo — call risk.' if pct_in_range > 75 else 'Próximo da base — put risk.' if pct_in_range < 25 else 'Spot no meio do range — neutro.'}",
            'ok': 25 <= pct_in_range <= 75
        })

    # ── 2. HVL 0DTE — ponto de controle do volume ────────────────────
    if mq.get('hvl_0dte'):
        above_hvl = spot > mq['hvl_0dte']
        signals.append({
            'fonte': 'MQ HVL 0DTE',
            'label': f"HVL 0DTE: {mq['hvl_0dte']}",
            'detail': f"Spot {'acima' if above_hvl else 'abaixo'} do High Volume Level 0DTE. "
                      f"{'Favorece calls — compradores controlam.' if above_hvl else 'Favorece puts — vendedores controlam.'}",
            'ok': above_hvl
        })
        if above_hvl:
            confirms += 1
        else:
            conflicts += 1

    # ── 3. Gamma Wall 0DTE vs Call Wall SpotGamma ─────────────────────
    sg_cw = sg.get('call_wall')
    mq_gw = mq.get('gamma_wall_0dte')
    if sg_cw and mq_gw:
        diff = abs(sg_cw - mq_gw)
        aligned = diff <= 2.0
        signals.append({
            'fonte': 'SG+MQ Gamma Wall',
            'label': f"SG Call Wall {sg_cw} | MQ Gamma Wall 0DTE {mq_gw}",
            'detail': f"{'✅ Confirmação — ambas as fontes apontam para o mesmo nível de resistência.' if aligned else f'⚠ Divergência de {diff:.1f} pts — usar o mais conservador ({min(sg_cw, mq_gw)}).'}",
            'ok': aligned
        })
        if aligned:
            confirms += 1
        else:
            conflicts += 1

    # ── 4. Put support — confirmação de piso ─────────────────────────
    sg_pw = sg.get('put_wall')
    mq_ps = mq.get('put_sup_0dte')
    if sg_pw and mq_ps:
        diff = abs(sg_pw - mq_ps)
        aligned = diff <= 3.0
        signals.append({
            'fonte': 'SG+MQ Put Support',
            'label': f"SG Put Wall {sg_pw} | MQ Put Support 0DTE {mq_ps}",
            'detail': f"{'✅ Piso confirmado pelas duas fontes.' if aligned else f'⚠ Divergência de {diff:.1f} pts — zona de suporte ampla.'}",
            'ok': aligned
        })
        if aligned:
            confirms += 1
        else:
            conflicts += 1

    # ── 5. GEX strikes MQ — clusters de gamma ────────────────────────
    gex = mq.get('gex_strikes', [])
    if gex:
        nearest_gex = min(gex, key=lambda x: abs(x - spot))
        dist_gex = abs(nearest_gex - spot)
        signals.append({
            'fonte': 'MQ GEX Cluster',
            'label': f"GEX mais próximo: {nearest_gex} (dist {dist_gex:.2f} pts)",
            'detail': f"Top 3 GEX strikes: {gex[:3]}. "
                      f"{'⚠ Spot colado em GEX strike — movimento brusco possível ao romper.' if dist_gex < 1.5 else 'Distância segura do cluster de gamma.'}",
            'ok': dist_gex >= 1.5
        })

    # ── Veredicto combinado ───────────────────────────────────────────
    if confirms >= 2 and conflicts == 0:
        combined = 'FORTE'
        combined_desc = 'SpotGamma e Menthor Q confirmam o mesmo viés. Sinal de alta confiança.'
    elif confirms >= 1 and conflicts <= 1:
        combined = 'MODERADO'
        combined_desc = 'Confirmação parcial entre as fontes. Usar como leitura — entrada depende do Risk Gate no Modo 3.'
    else:
        combined = 'FRACO'
        combined_desc = 'Fontes divergentes. Aguardar convergência antes de entrar.'

    # Strike de referência combinado (mais conservador)
    call_ref = min(filter(None, [sg_cw, mq_gw, mq.get('call_res_0dte')]))   if any([sg_cw, mq_gw, mq.get('call_res_0dte')]) else None
    put_ref  = max(filter(None, [sg_pw, mq_ps, mq.get('put_sup')])) if any([sg_pw, mq_ps, mq.get('put_sup')]) else None

    return {
        'signals':        signals,
        'confirms':       confirms,
        'conflicts':      conflicts,
        'combined':       combined,
        'combined_desc':  combined_desc,
        'call_ref':       call_ref,   # resistência combinada mais conservadora
        'put_ref':        put_ref,    # suporte combinado mais conservador
        'hvl_0dte':       mq.get('hvl_0dte'),
        'gamma_wall':     mq_gw,
        'range_min':      mq.get('range_min'),
        'range_max':      mq.get('range_max'),
        'gex_top3':       gex[:3] if gex else [],
    }


def print_combined(cs, spot):
    """Imprime o relatório do sinal combinado SG + MQ."""
    SEP = '─' * 60
    print(f"\n🔀 Sinal Combinado — SpotGamma + Menthor Q")
    print(f"{SEP}")
    print(f"  Força do sinal : {cs['combined']}")
    print(f"  {cs['combined_desc']}")
    if cs['range_min'] and cs['range_max']:
        print(f"  Range do dia   : {cs['range_min']} – {cs['range_max']}  "
              f"(amplitude {cs['range_max']-cs['range_min']:.2f} pts)")
    if cs['call_ref']:
        print(f"  Resistência ref: {cs['call_ref']}  (mais conservadora das fontes)")
    if cs['put_ref']:
        print(f"  Suporte ref    : {cs['put_ref']}  (mais conservador das fontes)")
    if cs['hvl_0dte']:
        above = spot > cs['hvl_0dte']
        print(f"  HVL 0DTE       : {cs['hvl_0dte']}  → Spot {'ACIMA ✅' if above else 'ABAIXO ⚠'}")
    if cs['gex_top3']:
        print(f"  GEX top 3      : {cs['gex_top3']}")
    print(f"\n  Confirmações: {cs['confirms']}  |  Conflitos: {cs['conflicts']}")
    print(f"{SEP}")
    for s in cs['signals']:
        icon = '  ✅' if s['ok'] else '  ⚠️ '
        print(f"{icon} [{s['fonte']}] {s['label']}")
        print(f"      {s['detail']}")


# ── Lógica de ambiente e viés ─────────────────────────────────────────

def market_environment(data, spot):
    """
    Avalia o ambiente de mercado com base nos níveis SpotGamma.
    Retorna dict com bias, regime, e flags de risco.
    """
    above_zero_gamma = spot > data['zero_gamma']
    above_vol_trigger = spot > data['vol_trigger']
    above_abs_gamma  = spot > data['abs_gamma']
    dist_call = (data['call_wall'] - spot) / spot * 100
    dist_put  = (spot - data['put_wall'])  / spot * 100
    range_compressed = dist_call < 1.5 and dist_put < 3.0

    # Regime
    if above_zero_gamma and above_abs_gamma:
        regime = 'POSITIVE_GAMMA'
        regime_desc = 'GEX positivo — dealers compram baixa e vendem alta. Range comprimido favorável.'
    elif above_zero_gamma and not above_abs_gamma:
        regime = 'TRANSITION'
        regime_desc = 'Zona de transição — acima do ZG mas abaixo do Gamma Absoluto. Aguardar confirmação.'
    else:
        regime = 'NEGATIVE_GAMMA'
        regime_desc = 'Abaixo do Zero Gamma — dealers amplificam moves. Alta vol realizada esperada.'

    # Viés direcional
    if above_zero_gamma and dist_call < dist_put:
        bias = 'CALL'
        bias_desc = 'Spot mais próximo da Call Wall — pressão de alta. Favorece calls ou call spreads.'
    elif not above_zero_gamma:
        bias = 'PUT'
        bias_desc = 'Spot abaixo do Zero Gamma — pressão vendedora. Favorece puts ou put spreads.'
    else:
        bias = 'NEUTRAL'
        bias_desc = 'Spot centralizado entre suporte e resistência. Aguardar rompimento de nível.'

    return {
        'regime':           regime,
        'regime_desc':      regime_desc,
        'bias':             bias,
        'bias_desc':        bias_desc,
        'above_zero_gamma': above_zero_gamma,
        'above_vol_trigger': above_vol_trigger,
        'range_compressed': range_compressed,
        'dist_to_call_wall': dist_call,
        'dist_to_put_wall':  dist_put,
    }


# ── Scanner de strike 0DTE (LEGADO) ──────────────────────────────────
# Mantida para testes e referência. O fluxo principal usa score_side().
def best_0dte_strike(spot, data, env, iv=0.15, rf=0.053, hours_to_exp=4.0):
    """
    Dado o spot atual e o ambiente SpotGamma, calcula os melhores
    candidatos de strike para 0DTE (call ou put) com base em:
      - Gamma máximo (sensibilidade ao movimento)
      - Distância ao nível de suporte/resistência SpotGamma
      - Moneyness (OTM preferido para melhor assimetria)
      - Score composto

    Retorna lista de candidatos ordenada pelo score.
    """
    T = hours_to_exp / (365 * 24)
    option_type = 'call' if env['bias'] in ('CALL', 'NEUTRAL') else 'put'

    # Gera strikes candidatos em torno do spot (cada $0.50 ou $1)
    step = 0.5
    strikes = [round(spot + step * i, 2) for i in range(-20, 21)]

    # Níveis chave do SpotGamma para calcular proximidade
    key_levels = (data['combos'] + data['supports'] +
                  [data['call_wall'], data['put_wall'],
                   data['abs_gamma'], data['zero_gamma']])

    candidates = []
    for K in strikes:
        g = bs_greeks(option_type, spot, K, T, rf, iv)
        if g['price'] < 0.05:
            continue  # prêmio mínimo

        # Distância percentual do strike ao spot
        dist_pct = abs(K - spot) / spot * 100

        # OTM score — preferimos levemente OTM (0.1% a 0.8%)
        if option_type == 'call':
            otm = (K - spot) / spot * 100
        else:
            otm = (spot - K) / spot * 100

        if otm < 0:
            otm_score = 0.0          # ITM — penalizar
        elif otm < 0.1:
            otm_score = 0.7          # ATM — ok mas caro
        elif otm <= 0.6:
            otm_score = 1.0          # OTM ideal
        elif otm <= 1.2:
            otm_score = 0.6          # OTM moderado
        else:
            otm_score = 0.2          # muito OTM

        # Proximidade a um nível chave SpotGamma (quanto mais próximo, melhor)
        min_dist_to_level = min(abs(K - lvl) for lvl in key_levels)
        level_score = max(0, 1 - min_dist_to_level / 5)

        # Gamma score — normalizado pelo maior gamma da lista
        gamma_raw = g['gamma']

        # Score composto
        composite = (gamma_raw * 1000 * 0.40 +
                     otm_score           * 0.35 +
                     level_score         * 0.25)

        candidates.append({
            'strike':       K,
            'type':         option_type,
            'price':        round(g['price'], 2),
            'delta':        round(g['delta'], 4),
            'gamma':        round(g['gamma'], 6),
            'theta':        round(g['theta'] * 100, 3),   # por contrato
            'vega':         round(g['vega'] * 100, 3),    # por contrato
            'otm_pct':      round(otm, 3),
            'level_score':  round(level_score, 3),
            'otm_score':    round(otm_score, 3),
            'composite':    round(composite, 4),
            'nearest_level': min(key_levels, key=lambda l: abs(K - l)),
        })

    candidates.sort(key=lambda x: x['composite'], reverse=True)
    return candidates[:5]   # top 5


def exit_levels(premium_paid, contracts=1, target_pct=0.75, stop_pct=0.50):
    """
    Calcula os níveis exatos de saída baseados no prêmio pago.
    target_pct : percentual de ganho para saída (padrão 75%)
    stop_pct   : percentual de perda para stop (padrão 50%)
    Retorna dict com preços e valores em dólares.
    """
    cost_basis   = premium_paid * 100 * contracts   # custo total em USD
    target_price = round(premium_paid * (1 + target_pct), 2)
    stop_price   = round(premium_paid * (1 - stop_pct), 2)
    target_usd   = round(cost_basis * target_pct, 2)
    stop_usd     = round(cost_basis * stop_pct, 2)
    return {
        'premium_paid':  premium_paid,
        'contracts':     contracts,
        'cost_basis':    cost_basis,
        'target_price':  target_price,   # preço da opção para sair com lucro
        'stop_price':    stop_price,     # preço da opção para sair com stop
        'target_usd':    target_usd,     # lucro em USD
        'stop_usd':      stop_usd,       # perda em USD
        'target_pct':    target_pct * 100,
        'stop_pct':      stop_pct * 100,
        'time_cutoff':   '12:00 ET',     # saída obrigatória por tempo
    }


def score_side(spot, data, env, iv, rf, hours_to_exp, option_type, key_levels):
    """
    Calcula o melhor strike e score para um lado (call ou put).
    Lógica 0DTE: ATM tem Gamma máximo — é exatamente o que queremos.
    Retorna (candidates[:5], side_score) ou (None, 0) se inviável.
    """
    T = hours_to_exp / (365 * 24)
    step = 0.5
    strikes = [round(spot + step * i, 2) for i in range(-20, 21)]
    candidates = []

    for K in strikes:
        g = bs_greeks(option_type, spot, K, T, rf, iv)
        if g['price'] < 0.05:
            continue

        # Distância ao spot em pontos absolutos
        dist_pts = abs(K - spot)

        # Moneyness para o lado correto
        if option_type == 'call':
            otm = (K - spot) / spot * 100   # positivo = OTM
        else:
            otm = (spot - K) / spot * 100   # positivo = OTM

        # ── OTM score para 0DTE ───────────────────────────────────────
        # ATM (dist ≤ 0.5 pts)  → score máximo  — Gamma explode aqui
        # Levemente OTM (0.5–1) → bom           — ainda alta aceleração
        # OTM (1–2 pts)         → moderado       — Gamma cai rapidamente
        # OTM (> 2 pts)         → penalizar      — Gamma quase zero em 0DTE
        if dist_pts <= 0.5:
            otm_score = 1.0    # ATM — máxima aceleração de Gamma
        elif dist_pts <= 1.0:
            otm_score = 0.85   # quase ATM — ainda excelente
        elif dist_pts <= 2.0:
            otm_score = 0.55   # OTM leve — Gamma caindo
        elif dist_pts <= 3.5:
            otm_score = 0.25   # OTM moderado — baixa aceleração
        else:
            otm_score = 0.05   # muito OTM — evitar em 0DTE

        # Penalidade extra para ITM — prêmio caro, menos alavancagem
        if otm < 0:
            otm_score *= 0.6

        # Proximidade a nível chave SpotGamma
        min_dist = min(abs(K - lvl) for lvl in key_levels)
        level_score = max(0, 1 - min_dist / 5)

        # ── Score composto ─────────────────────────────────────────────
        # Gamma tem peso dominante em 0DTE — é a razão de existir
        # OTM score (ATM bias) é o segundo fator mais importante
        # Nível SpotGamma confirma o setup
        composite = (g['gamma'] * 1000 * 0.50 +   # Gamma: peso 50%
                     otm_score           * 0.35 +   # ATM bias: peso 35%
                     level_score         * 0.15)    # Nível SG: peso 15%

        candidates.append({
            'strike':        K,
            'type':          option_type,
            'price':         round(g['price'], 2),
            'delta':         round(g['delta'], 4),
            'gamma':         round(g['gamma'], 6),
            'theta':         round(g['theta'] * 100, 3),
            'vega':          round(g['vega'] * 100, 3),
            'otm_pct':       round(otm, 3),
            'dist_pts':      round(dist_pts, 2),
            'level_score':   round(level_score, 3),
            'otm_score':     round(otm_score, 3),
            'composite':     round(composite, 4),
            'nearest_level': min(key_levels, key=lambda l: abs(K - l)),
        })

    candidates.sort(key=lambda x: x['composite'], reverse=True)
    if not candidates:
        return None, 0.0

    best = candidates[0]
    side_score = best['composite']

    # Bônus/penalidade contextual por ambiente
    if option_type == 'call' and env['above_zero_gamma'] and env['dist_to_call_wall'] > 0.5:
        side_score *= 1.2    # ambiente favorável para call
    if option_type == 'put' and not env['above_zero_gamma']:
        side_score *= 1.2    # ambiente favorável para put
    if option_type == 'call' and env['dist_to_call_wall'] < 0.3:
        side_score *= 0.4    # muito próximo da resistência — risco alto
    if option_type == 'put' and env['dist_to_put_wall'] < 0.5:
        side_score *= 0.4    # muito próximo do suporte — risco alto

    return candidates[:5], round(side_score, 4)




# ── Risk Gate 0DTE ────────────────────────────────────────────────────

def risk_gate_check(spot, data, env, capital=50000, best_side='CALL'):
    """
    Risk gate com timezone ET real e critério de distância
    dependente do lado escolhido (CALL ou PUT).
    """
    checks = []

    # Timezone ET real — funciona em qualquer máquina
    try:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now_et = datetime.now()
    now = now_et.time()

    # 1. Regime
    ok = env['regime'] != 'NEGATIVE_GAMMA'
    checks.append({'item': 'Regime de mercado', 'pass': ok,
                   'detail': env['regime_desc']})

    # 2. Spot vs Zero Gamma
    ok2 = env['above_zero_gamma']
    checks.append({'item': 'Spot acima do Zero Gamma', 'pass': ok2,
                   'detail': f"Spot {spot} vs ZG {data['zero_gamma']} — {'OK' if ok2 else 'Alta vol esperada'}"})

    # 3. Distância ao nível de risco — depende do lado escolhido
    if best_side == 'PUT':
        ok3 = env['dist_to_put_wall'] > 0.5
        checks.append({
            'item': 'Distância da Put Wall > 0.5% (lado PUT)',
            'pass': ok3,
            'detail': f"Distância atual: {env['dist_to_put_wall']:.2f}% — não entrar colado no suporte"
        })
    else:
        ok3 = env['dist_to_call_wall'] > 0.3
        checks.append({
            'item': 'Distância da Call Wall > 0.3% (lado CALL)',
            'pass': ok3,
            'detail': f"Distância atual: {env['dist_to_call_wall']:.2f}% — não entrar colado na resistência"
        })

    # 4. Janela de entrada 9:45–12:00 ET
    ok4 = dtime(9, 45) <= now <= dtime(12, 0)
    after_cut = now > dtime(12, 0)
    checks.append({'item': 'Janela de entrada (9:45–12:00 ET)', 'pass': ok4,
                   'detail': (f"Hora ET: {now.strftime('%H:%M')} — "
                               f"{'✅ Dentro da janela' if ok4 else '🚫 APÓS 12:00 — não abrir novas posições' if after_cut else '⏳ Aguardando abertura'}")})

    # 5. Move implícito
    ok5 = data['imp_1d'] <= 0.01
    checks.append({'item': 'Move implícito 1D ≤ 1%', 'pass': ok5,
                   'detail': f"Move implícito: {data['imp_1d']*100:.2f}%"})

    gate_open = all(c['pass'] for c in checks)
    return {'gate_open': gate_open, 'checks': checks, 'after_cutoff': after_cut,
            'now_et': now.strftime('%H:%M ET')}


# ── Análise principal SPY 0DTE ────────────────────────────────────────

def analyze_spy_0dte(sg_data, spot_spy, iv=0.15, rf=0.053,
                     hours_to_exp=4.0, capital=50000,
                     premium_paid=None, contracts=1):
    """
    Análise completa para 0DTE no SPY.
    Avalia CALL e PUT — recomenda o melhor lado.
    premium_paid : prêmio pago em USD (opcional) — calcula saídas exatas.
    """
    data = sg_data.get('SPY') or sg_data.get('$SPY')
    if not data:
        return {'error': 'SPY não encontrado nos dados SpotGamma.'}

    env  = market_environment(data, spot_spy)

    key_levels = (data['combos'] + data['supports'] +
                  [data['call_wall'], data['put_wall'],
                   data['abs_gamma'], data['zero_gamma']])

    # Avalia os dois lados primeiro
    call_cands, call_score = score_side(spot_spy, data, env, iv, rf,
                                        hours_to_exp, 'call', key_levels)
    put_cands,  put_score  = score_side(spot_spy, data, env, iv, rf,
                                        hours_to_exp, 'put',  key_levels)

    # Escolhe o melhor lado
    if call_score >= put_score:
        best_side   = 'CALL'
        candidates  = call_cands or []
        other_side  = 'PUT'
        other_score = put_score
    else:
        best_side   = 'PUT'
        candidates  = put_cands or []
        other_side  = 'CALL'
        other_score = call_score

    # Risk gate calculado APÓS conhecer o melhor lado
    gate = risk_gate_check(spot_spy, data, env, capital, best_side)

    # Kelly sizing — premissa fixa, deixa explícito
    win_rate  = 0.55   # premissa: 55% win rate histórico
    rr        = 1.5    # premissa: payoff médio 1.5R
    kelly     = (win_rate * rr - (1 - win_rate)) / rr
    kelly_q   = kelly * 0.25
    layer_cap = capital * 0.03
    sizing    = min(kelly_q * capital, layer_cap)
    max_loss  = sizing * 0.50

    # Níveis de saída
    exits = exit_levels(premium_paid, contracts) if premium_paid else None

    # Data/hora ET
    try:
        from zoneinfo import ZoneInfo as _ZI
        import datetime as _dtm
        _now = _dtm.datetime.now(_ZI("America/New_York")).strftime('%Y-%m-%d %H:%M ET')
    except Exception:
        _now = datetime.now().strftime('%Y-%m-%d %H:%M')

    return {
        'date':        _now,
        'spot':        spot_spy,
        'data':        data,
        'env':         env,
        'gate':        gate,
        'best_side':   best_side,
        'call_score':  call_score,
        'put_score':   put_score,
        'other_side':  other_side,
        'candidates':  candidates,
        'call_cands':  call_cands or [],
        'put_cands':   put_cands  or [],
        'exits':       exits,
        'sizing': {
            'kelly_full':    round(kelly * 100, 2),
            'kelly_quarter': round(kelly_q * 100, 2),
            'layer_cap':     round(layer_cap, 2),
            'recommended':   round(sizing, 2),
            'max_loss':      round(max_loss, 2),
            'max_loss_pct':  round(max_loss / capital * 100, 3),
        }
    }


# ── Módulo: Primeiros 30 minutos ─────────────────────────────────────

def opening_watch(vix_open, vix_now, hiro_direction, spot_open,
                  spot_now, sg_data, capital=50000, mq_data=None):
    """
    Monitora os primeiros 30 minutos (9:30–10:00 ET).
    Você alimenta os dados que vê no TradingView e SpotGamma.

    vix_open       : VIX no momento da abertura (9:30)
    vix_now        : VIX atual (atualiza a cada 5 min)
    hiro_direction : 'positive', 'negative' ou 'neutral'
                     (veja no HIRO do SpotGamma — sobe = positive)
    spot_open      : preço SPY na abertura
    spot_now       : preço SPY atual
    sg_data        : dict do parse_sg_data()
    capital        : capital total

    Retorna dict com avaliação do ambiente de abertura.
    """
    spy = sg_data.get('SPY') or sg_data.get('$SPY', {})

    vix_change      = vix_now - vix_open
    vix_change_pct  = vix_change / vix_open * 100 if vix_open else 0
    spot_change_pct = (spot_now - spot_open) / spot_open * 100 if spot_open else 0

    signals = []
    score   = 0  # positivo = favorável para operar, negativo = esperar

    # ── VIX ──────────────────────────────────────────────────────────
    if vix_now < 15:
        signals.append(('✅', 'VIX < 15', 'Vol muito baixa — ambiente calmo. 0DTE pode ser caro para comprar.'))
        score += 1
    elif vix_now < 20:
        signals.append(('✅', 'VIX 15–20', 'Zona ideal para 0DTE — vol suficiente para movimento, não excessiva.'))
        score += 2
    elif vix_now < 25:
        signals.append(('⚠️ ', 'VIX 20–25', 'Vol elevada — prêmios caros. Sizing menor. Prefira spreads.'))
        score += 0
    else:
        signals.append(('🚫', 'VIX > 25', 'Vol muito alta — risco de gap. Não operar 0DTE naked.'))
        score -= 2

    # ── Direção do VIX nos primeiros 30 min ──────────────────────────
    if vix_change_pct <= -3:
        signals.append(('✅', 'VIX caindo forte (>{:.1f}%)'.format(abs(vix_change_pct)),
                         'Medo saindo do mercado — favorável para posições compradas.'))
        score += 2
    elif vix_change_pct <= -1:
        signals.append(('✅', 'VIX caindo ({:.1f}%)'.format(vix_change_pct),
                         'Vol recuando — ambiente se estabilizando.'))
        score += 1
    elif vix_change_pct <= 1:
        signals.append(('⚠️ ', 'VIX estável ({:.1f}%)'.format(vix_change_pct),
                         'Sem direção clara de volatilidade. Aguardar.'))
        score += 0
    elif vix_change_pct <= 3:
        signals.append(('⚠️ ', 'VIX subindo ({:.1f}%)'.format(vix_change_pct),
                         'Vol aumentando — dealers vendendo. Cuidado com calls longas.'))
        score -= 1
    else:
        signals.append(('🚫', 'VIX subindo forte ({:.1f}%)'.format(vix_change_pct),
                         'Spike de vol — não operar. Aguardar estabilização.'))
        score -= 3

    # ── HIRO ─────────────────────────────────────────────────────────
    if hiro_direction == 'positive':
        signals.append(('✅', 'HIRO positivo',
                         'Fluxo de delta acumulado comprador — dealers compram mercado. Favorece calls.'))
        score += 2
    elif hiro_direction == 'neutral':
        signals.append(('⚠️ ', 'HIRO neutro',
                         'Fluxo sem direção clara. Aguardar pelo menos até 10:15 ET.'))
        score += 0
    else:
        signals.append(('🚫', 'HIRO negativo',
                         'Fluxo de delta vendedor — dealers vendendo. Favorece puts ou aguardar.'))
        score -= 2

    # ── Movimento do spot na abertura ────────────────────────────────
    if abs(spot_change_pct) < 0.2:
        signals.append(('✅', f'Abertura tranquila ({spot_change_pct:+.2f}%)',
                         'Sem gap relevante. Bom sinal para range comprimido.'))
        score += 1
    elif abs(spot_change_pct) < 0.5:
        signals.append(('⚠️ ', f'Abertura com movimento ({spot_change_pct:+.2f}%)',
                         'Movimento moderado. Aguardar formação de direção.'))
        score += 0
    else:
        signals.append(('🚫', f'Gap de abertura ({spot_change_pct:+.2f}%)',
                         'Gap relevante — mercado pode reverter ou continuar. Não operar nos primeiros 30 min.'))
        score -= 1

    # ── Spot vs níveis SpotGamma ──────────────────────────────────────
    if spy:
        above_zg = spot_now > spy.get('zero_gamma', 0)
        above_vt = spot_now > spy.get('vol_trigger', 0)
        if above_zg and above_vt:
            signals.append(('✅', 'Spot acima do ZG e Vol Trigger',
                             'Zona de gamma positivo confirmada. Dealers compram baixa.'))
            score += 2
        elif above_zg:
            signals.append(('⚠️ ', 'Spot acima do ZG, abaixo do Vol Trigger',
                             'Zona de transição. Aguardar spot superar o Vol Trigger para confirmar.'))
            score += 1
        else:
            signals.append(('🚫', 'Spot abaixo do Zero Gamma',
                             'Ambiente de gamma negativo. Alta volatilidade esperada. Não operar calls.'))
            score -= 2

    # ── Veredicto base (SG + VIX + HIRO) ────────────────────────────────
    base_score = score

    # ── Sinal Menthor Q integrado ao score ───────────────────────────────
    # Filosofia RBC: MQ só ajuda quando fontes convergem sem conflito.
    # MODERADO com conflito = neutro — não operar em dúvida.
    mq_boost = 0
    mq_note  = None
    if mq_data:
        mq_spy = mq_data.get('SPY', {}) if isinstance(mq_data, dict) else {}
        if mq_spy:
            cs = combined_signal(spy, mq_spy, spot_now) if spy else None
            if cs:
                if cs['combined'] == 'FORTE':
                    mq_boost = 2
                    mq_note = ('✅', 'MQ + SG — sinal FORTE',
                               f"Confirmações: {cs['confirms']} | Conflitos: {cs['conflicts']} — +2 pts.")
                elif cs['combined'] == 'MODERADO' and cs['conflicts'] == 0:
                    mq_boost = 1
                    mq_note = ('✅', 'MQ + SG — MODERADO sem conflito',
                               f"Confirmações: {cs['confirms']} | Conflitos: 0 — +1 pt.")
                elif cs['combined'] == 'MODERADO' and cs['conflicts'] > 0:
                    mq_boost = 0
                    mq_note = ('⚠️ ', 'MQ + SG — MODERADO com conflito',
                               f"Confirmações: {cs['confirms']} | Conflitos: {cs['conflicts']} — neutro (0 pts). Fontes divergentes.")
                else:
                    mq_boost = -2
                    mq_note = ('🚫', 'MQ + SG — sinal FRACO',
                               f"Confirmações: {cs['confirms']} | Conflitos: {cs['conflicts']} — -2 pts. Não operar.")
                score += mq_boost
                if mq_note:
                    signals.append(mq_note)

    # ── Veredicto final combinado ─────────────────────────────────────────
    if score >= 5:
        verdict = 'OPERAR'
        verdict_desc = 'Ambiente favorável para continuar monitorando. Rode o Modo 3 após 10:00 ET para liberar ou bloquear a entrada.'
        verdict_icon = '✅'
    elif score >= 2:
        verdict = 'AGUARDAR'
        verdict_desc = 'Sinais mistos. Aguardar até 10:00–10:15 ET para confirmar direção. Modo 3 decidirá.'
        verdict_icon = '⚠️ '
    else:
        verdict = 'NÃO OPERAR'
        verdict_desc = 'Ambiente desfavorável. Hoje não é dia de 0DTE. Preserve o capital.'
        verdict_icon = '🚫'

    return {
        'vix_open':        vix_open,
        'vix_now':         vix_now,
        'vix_change_pct':  round(vix_change_pct, 2),
        'hiro':            hiro_direction,
        'spot_open':       spot_open,
        'spot_now':        spot_now,
        'spot_change_pct': round(spot_change_pct, 2),
        'signals':         signals,
        'score':           score,
        'base_score':      base_score,
        'mq_boost':        mq_boost,
        'verdict':         verdict,
        'verdict_desc':    verdict_desc,
        'verdict_icon':    verdict_icon,
    }


def print_opening_watch(ow):
    """Imprime o relatório dos primeiros 30 minutos."""
    SEP  = '─' * 60
    SEP2 = '═' * 60

    # Timezone ET real
    try:
        from zoneinfo import ZoneInfo
        import datetime as dtm
        now_str = dtm.datetime.now(ZoneInfo("America/New_York")).strftime('%Y-%m-%d %H:%M ET')
    except Exception:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    print(f"\n{SEP2}")
    print(f"  RBC | Monitoramento de Abertura — Primeiros 30 min")
    print(f"  {now_str}")
    print(f"{SEP2}")

    print(f"\n  VIX abertura : {ow['vix_open']:.2f}")
    print(f"  VIX atual    : {ow['vix_now']:.2f}  ({ow['vix_change_pct']:+.2f}%)")
    print(f"  HIRO         : {ow['hiro'].upper()}")
    print(f"  SPY abertura : {ow['spot_open']:.2f}")
    print(f"  SPY atual    : {ow['spot_now']:.2f}  ({ow['spot_change_pct']:+.2f}%)")

    print(f"\n{SEP}")
    print(f"  Sinais de abertura  (SG + MQ + VIX + HIRO)")
    print(f"{SEP}")
    for icon, label, desc in ow['signals']:
        print(f"  {icon} {label}")
        print(f"      {desc}")

    print(f"\n{SEP}")
    bar_filled = min(10, max(0, ow['score'] + 5))
    score_bar  = '█' * bar_filled + '░' * (10 - bar_filled)
    base = ow.get('base_score', ow['score'])
    boost = ow.get('mq_boost', 0)
    score_detail = f"base SG/VIX/HIRO: {base:+d}  |  MQ: {boost:+d}  |  total: {ow['score']:+d}"
    print(f"  Score combinado : [{score_bar}]  {score_detail}")
    print(f"\n  {ow['verdict_icon']} VEREDICTO: {ow['verdict']}")
    print(f"  {ow['verdict_desc']}")
    print(f"\n{SEP2}\n")


# ── Relatório em texto ────────────────────────────────────────────────

def print_report(result):
    SEP  = '─' * 60
    SEP2 = '═' * 60

    print(f"\n{SEP2}")
    print(f"  RBC — Risk Bridge Capital | 0DTE Scanner v1.5-beta")
    print(f"  {result['date']}")
    print(f"{SEP2}")

    d = result['data']
    s = result['spot']
    print(f"\n📊 SPY — Níveis SpotGamma")
    print(f"{SEP}")
    print(f"  Spot atual       : {s}")
    print(f"  Call Wall        : {d['call_wall']}  (+{(d['call_wall']-s)/s*100:.2f}%)")
    print(f"  Put Wall         : {d['put_wall']}  (-{(s-d['put_wall'])/s*100:.2f}%)")
    print(f"  Abs Gamma Strike : {d['abs_gamma']}")
    print(f"  Vol Trigger      : {d['vol_trigger']}")
    print(f"  Zero Gamma       : {d['zero_gamma']}")
    print(f"  Move implícito 1D: {d['imp_1d']*100:.2f}%")
    print(f"  Combos           : {d['combos']}")

    env = result['env']
    print(f"\n🌐 Ambiente")
    print(f"{SEP}")
    print(f"  Regime : {env['regime']}  |  Viés: {env['bias']}")
    print(f"  {env['bias_desc']}")
    print(f"  Dist. Call Wall: {env['dist_to_call_wall']:.2f}%  |  Dist. Put Wall: {env['dist_to_put_wall']:.2f}%")

    # Risk Gate
    gate = result['gate']
    status = '✅ GATE ABERTO' if gate['gate_open'] else '🚫 GATE FECHADO'
    print(f"\n🛡  Risk Gate — {status}  ({result['gate'].get('now_et','')})")
    print(f"{SEP}")
    for c in gate['checks']:
        icon = '  ✓' if c['pass'] else '  ✗'
        print(f"{icon} {c['item']}")
        print(f"      {c['detail']}")

    # Nota sobre filosofia conservadora
    if not gate['gate_open']:
        print(f"\n  Filosofia RBC: abaixo do Zero Gamma = não operar 0DTE naked.")
        print(f"  Ambiente de gamma negativo amplifica moves — risco assimétrico contra você.")
        print(f"  Preserve capital. Haverá outro setup amanhã.")

    if gate.get('after_cutoff'):
        print(f"\n  ⏰ Após 12:00 ET — janela de entrada encerrada.")
        print(f"     Se você já tem posição aberta, mantenha os níveis de saída.")

    # ── CALL vs PUT — sempre mostrar, gate aberto ou fechado ──────────
    print(f"\n⚖  CALL vs PUT — avaliação dos dois lados")
    print(f"{SEP}")
    print(f"  {'CALL':<6} score: {result['call_score']:.4f}  {'★ MELHOR LADO' if result['best_side']=='CALL' else ''}")
    print(f"  {'PUT':<6} score: {result['put_score']:.4f}  {'★ MELHOR LADO' if result['best_side']=='PUT' else ''}")
    print(f"\n  Lado com maior Gamma ATM: {result['best_side']}")
    if not gate['gate_open']:
        print(f"  🚫 Gate fechado — use esta informação para aprendizado, não para entrar.")

    # ── Top 5 strikes — sempre mostrar ───────────────────────────────
    print(f"\n🎯 Top strikes — score RBC 0DTE ({result['best_side']})")
    print(f"{SEP}")
    print(f"  {'#':<3} {'Strike':<8} {'Dist':<7} {'Preço':<8} {'Delta':<8} {'Gamma':<10} {'Theta/d':<10} Score")
    print(f"  {'-'*65}")
    for i, c in enumerate(result['candidates'][:5], 1):
        atm_flag = ' ← ATM' if c['dist_pts'] <= 0.5 else (' ← quase ATM' if c['dist_pts'] <= 1.0 else '')
        marker = ' ★' if i == 1 else ''
        print(f"  {i:<3} {c['strike']:<8} {c['dist_pts']:<7.2f} ${c['price']:<7.2f} "
              f"{c['delta']:<8.4f} {c['gamma']:<10.6f} "
              f"-${abs(c['theta']):<8.3f} {c['composite']:.4f}{marker}{atm_flag}")
        print(f"      → Nível SG mais próximo: {c['nearest_level']}")

    if result['candidates']:
        best = result['candidates'][0]
        gopen = gate['gate_open']
        print(f"\n  {'★ ENTRADA RECOMENDADA' if gopen else '○ Strike de referência (gate fechado)'}")
        print(f"  {best['type'].upper()} SPY  strike {best['strike']}")
        print(f"  Prêmio teórico : US$ {best['price']:.2f}")
        print(f"  ⚠  Este é o preço BLACK-SCHOLES — confirme o prêmio real no IBKR antes de entrar.")
        print(f"  Delta          : {best['delta']:.4f}  |  Gamma: {best['gamma']:.6f}")
        print(f"  Theta/dia      : -US$ {abs(best['theta']):.3f}")

    # ── Sizing — só se gate aberto ────────────────────────────────────
    if gate['gate_open']:
        sz = result['sizing']
        print(f"\n💰 Sizing — Kelly 1/4  (premissa: WR 55%, payoff 1.5R)")
        print(f"{SEP}")
        print(f"  Kelly full        : {sz['kelly_full']}%")
        print(f"  Kelly 1/4 frac    : {sz['kelly_quarter']}%")
        print(f"  Teto camada 0DTE  : US$ {sz['layer_cap']:.2f}  (3% do capital)")
        print(f"  Sizing recomendado: US$ {sz['recommended']:.2f}")
        print(f"  Stop automático   : US$ {sz['max_loss']:.2f}  ({sz['max_loss_pct']:.3f}% do capital)")
        print(f"  ⚠  Ajuste win rate e payoff quando tiver histórico real.")

    # ── Saídas — sempre mostrar se prêmio foi informado ──────────────
    print(f"\n🚪 Regras de saída — máximo até 12:00 ET")
    print(f"{SEP}")
    if result.get('exits'):
        ex = result['exits']
        print(f"  Prêmio pago      : US$ {ex['premium_paid']:.2f}  "
              f"(custo total: US$ {ex['cost_basis']:.2f})")
        print(f"  ✅ ALVO (+75%)   : US$ {ex['target_price']:.2f} por contrato  "
              f"→  lucro US$ {ex['target_usd']:.2f}")
        print(f"  🚫 STOP (-50%)   : US$ {ex['stop_price']:.2f} por contrato  "
              f"→  perda US$ {ex['stop_usd']:.2f}")
        print(f"  ⏰ TEMPO (12:00) : saída obrigatória — primeiro gatilho vence")
        print(f"\n  Nunca segure após 12:00 ET. Nunca mova o stop para baixo.")
    else:
        print(f"  Alvo   : +75% do prêmio pago")
        print(f"  Stop   : -50% do prêmio pago")
        print(f"  Tempo  : 12:00 ET — obrigatório")
        print(f"\n  → Informe o prêmio pago no modo 3 para ver os valores exatos em USD.")

    print(f"\n  ⚠  1 contrato SPY = multiplicador 100. Confirme o prêmio real no IBKR.")


    print(f"\n{SEP2}")
    print(f"  RBC | Dados educacionais — não são recomendações de investimento.")
    print(f"{SEP2}\n")


# ── Modo 4: Monitor de Trajetória ────────────────────────────────────

def trajectory_analysis(spot_now, spot_prev, vix_now, vix_prev,
                        sg_data, mq_data=None, minutes_between=15,
                        spot_prev2=None, vix_prev2=None):
    """
    Monitor de Trajetória — acompanhamento ao vivo.
    Não libera entrada. Serve para responder:
      - O spot está se aproximando de uma parede?
      - Está acelerando ou perdendo força?
      - O VIX confirma ou contradiz o movimento?
      - Devo ficar mais defensiva?

    spot_prev2 : leitura anterior a spot_prev (opcional, detecta desaceleração)
    vix_prev2  : leitura anterior a vix_prev  (opcional)
    """
    spy = sg_data.get('SPY', {})
    mq  = (mq_data or {}).get('SPY', {})
    if not spy:
        return {'error': 'SPY não encontrado.'}

    # ── Velocidade e direção ──────────────────────────────────────────
    spot_delta     = spot_now - spot_prev
    spot_vel       = spot_delta / minutes_between        # pts/min
    spot_dir       = 'SUBINDO' if spot_delta > 0.10 else 'CAINDO' if spot_delta < -0.10 else 'LATERAL'
    spot_delta_pct = spot_delta / spot_prev * 100 if spot_prev else 0

    vix_delta = vix_now - vix_prev
    vix_dir   = 'SUBINDO' if vix_delta > 0.15 else 'CAINDO' if vix_delta < -0.15 else 'ESTÁVEL'

    # ── Detecção de desaceleração (se tiver leitura anterior) ────────
    decelerating = False
    decel_note   = None
    if spot_prev2 is not None:
        vel_prev = (spot_prev - spot_prev2) / minutes_between
        if abs(spot_vel) < abs(vel_prev) * 0.6:   # velocidade caiu >40%
            decelerating = True
            decel_note = f"velocidade caiu de {vel_prev:+.3f} para {spot_vel:+.3f} pts/min"

    # ── Distâncias ────────────────────────────────────────────────────
    call_wall   = spy.get('call_wall', 0)
    put_wall    = spy.get('put_wall', 0)
    zero_gamma  = spy.get('zero_gamma', 0)
    vol_trigger = spy.get('vol_trigger', 0)
    abs_gamma   = spy.get('abs_gamma', 0)

    dist_cw = call_wall - spot_now
    dist_pw = spot_now - put_wall
    dist_zg = spot_now - zero_gamma
    dist_vt = spot_now - vol_trigger
    dist_ag = abs_gamma - spot_now

    gex_near  = None
    if mq.get('gex_strikes'):
        gex_near = min(mq['gex_strikes'], key=lambda x: abs(x - spot_now))

    hvl_0dte   = mq.get('hvl_0dte')
    range_max  = mq.get('range_max')
    range_min  = mq.get('range_min')
    gamma_wall = mq.get('gamma_wall_0dte')

    # ── Projeção linear (só referência, não previsão) ─────────────────
    proj_15 = round(spot_now + spot_vel * 15, 2)
    proj_30 = round(spot_now + spot_vel * 30, 2)

    # ── Alertas de aproximação — com linguagem prudente ───────────────
    alerts = []

    # 1. Aproximando da Call Wall
    if spot_dir == 'SUBINDO' and 0 < dist_cw <= 3.0:
        eta_min = dist_cw / spot_vel if spot_vel > 0 else None
        eta_str = f"~{eta_min:.0f} min (se velocidade mantiver)" if eta_min and eta_min < 60 else "—"
        urgency = '🔴' if dist_cw <= 1.0 else '🟡'

        if decelerating and vix_dir in ('SUBINDO', 'ESTÁVEL'):
            # Condição mais completa para reversão
            cond = ("Spot subiu, está desacelerando perto da resistência com VIX não caindo "
                    "— possível setup de PUT de reversão começa a se formar. "
                    "Aguardar perda de momentum antes de qualquer entrada.")
        elif decelerating:
            cond = ("Spot desacelerando perto da Call Wall — monitor. "
                    "Ainda não é sinal de reversão, só de cautela com calls.")
        elif vix_dir == 'SUBINDO' and vix_now > 19:
            cond = ("Spot subindo em direção à Call Wall mas VIX também sobe — "
                    "movimento sem convicção. Cuidado com compra de call perto da resistência.")
        else:
            cond = ("Spot se aproximando da Call Wall com momentum. "
                    "Não antecipar PUT — aguardar sinal de rejeição real.")

        alerts.append({
            'icon':  urgency,
            'nivel': f'Call Wall {call_wall}',
            'dist':  f'+{dist_cw:.2f} pts',
            'eta':   eta_str,
            'cond':  cond,
        })

    # 2. Rompimento da Call Wall
    if spot_now > call_wall and spot_dir == 'SUBINDO' and not (vix_dir == 'SUBINDO' and vix_now > 20):
        alerts.append({
            'icon':  '🟡',
            'nivel': f'Rompimento da Call Wall {call_wall}',
            'dist':  f'+{spot_now - call_wall:.2f} pts acima',
            'eta':   '—',
            'cond':  ('Spot rompeu a Call Wall com VIX controlado. '
                      'Não antecipar PUT de reversão cedo demais — rompimento pode ter continuidade. '
                      'Aguardar rejeição confirmada antes de considerar qualquer put.'),
        })

    # 3. Aproximando do Put Wall
    if spot_dir == 'CAINDO' and 0 < dist_pw <= 3.0:
        urgency = '🔴' if dist_pw <= 1.0 else '🟡'
        if vix_dir == 'SUBINDO' and vix_now > 19:
            cond = ("Spot caindo em direção ao suporte com VIX subindo — "
                    "suporte em teste com pressão real. "
                    "Não comprar call contra esse fluxo.")
        elif decelerating:
            cond = ("Spot desacelerando perto do Put Wall — "
                    "possível bounce começa a se formar. Aguardar confirmação.")
        else:
            cond = ("Spot se aproximando do suporte. Pode haver bounce ou colapso. "
                    "Sem sinal de reversão confirmado ainda.")

        alerts.append({
            'icon':  urgency,
            'nivel': f'Put Wall {put_wall}',
            'dist':  f'-{dist_pw:.2f} pts',
            'eta':   f"~{dist_pw/abs(spot_vel):.0f} min" if spot_vel < 0 else '—',
            'cond':  cond,
        })

    # 4. Spot caindo em direção ao Zero Gamma
    if spot_dir == 'CAINDO' and 0 < dist_zg <= 3.0:
        alerts.append({
            'icon':  '🔴',
            'nivel': f'Zero Gamma {zero_gamma}',
            'dist':  f'{dist_zg:.2f} pts acima',
            'eta':   f"~{dist_zg/abs(spot_vel):.0f} min" if spot_vel < 0 else '—',
            'cond':  ('Se spot perder o Zero Gamma, ambiente vira gamma negativo — '
                      'vol pode explodir. Gate fecha automaticamente no Modo 3.'),
        })

    # 5. VIX cruzando 20
    if 18.5 <= vix_now <= 21.5:
        alerts.append({
            'icon':  '🟡',
            'nivel': f'VIX zona de transição ({vix_now:.2f})',
            'dist':  f'{vix_delta:+.2f} vs {minutes_between} min atrás',
            'eta':   '—',
            'cond':  (f"VIX {'subindo em direção a 20 — regime de vol pode mudar. Aguardar ou reduzir risco.' if vix_now >= 19.5 and vix_dir == 'SUBINDO' else 'caindo abaixo de 20 — ambiente melhorando para 0DTE.'}"),
        })

    # 6. Spot fora do range MQ
    if range_max and spot_now > range_max + 0.50:
        alerts.append({
            'icon':  '🔴',
            'nivel': f'Acima do Range MQ (max {range_max})',
            'dist':  f'+{spot_now-range_max:.2f} pts fora',
            'eta':   '—',
            'cond':  ('Spot além do range máximo previsto pelo Menthor Q. '
                      'Probabilidade de reversão ou compressão aumenta. '
                      'Não comprar calls aqui — aguardar.'),
        })
    elif range_min and spot_now < range_min - 0.50:
        alerts.append({
            'icon':  '🔴',
            'nivel': f'Abaixo do Range MQ (min {range_min})',
            'dist':  f'-{range_min-spot_now:.2f} pts fora',
            'eta':   '—',
            'cond':  ('Spot abaixo do range mínimo previsto. '
                      'Risco de aceleração vendedora ou bounce técnico. '
                      'Não comprar puts aqui — aguardar confirmação.'),
        })

    # ── Leitura geral ─────────────────────────────────────────────────
    if spot_dir == 'SUBINDO' and vix_dir == 'CAINDO' and vix_now < 20:
        traj_bias = 'CALL'
        traj_desc = ('Spot subindo + VIX caindo abaixo de 20 — '
                     'ambiente favorável para calls. Monitorar resistências.')
        traj_icon = '✅'
    elif spot_dir == 'SUBINDO' and vix_dir == 'SUBINDO' and vix_now > 18.5:
        traj_bias = 'NEUTRO'
        traj_desc = ('Spot subindo mas VIX também sobe — movimento sem convicção. '
                     'Aguardar. Risco de reversão.')
        traj_icon = '⚠️ '
    elif spot_dir == 'CAINDO' and vix_dir == 'SUBINDO':
        traj_bias = 'PUT'
        traj_desc = ('Spot caindo + VIX subindo — pressão vendedora com vol crescente. '
                     'PUT pode ser o lado, mas entrada depende do Modo 3.')
        traj_icon = '⚠️ '
    elif spot_dir == 'CAINDO' and vix_dir == 'CAINDO':
        traj_bias = 'NEUTRO'
        traj_desc = ('Spot caindo mas VIX também cai — venda sem pânico. '
                     'Pode ser correção. Aguardar direção clara.')
        traj_icon = '⚠️ '
    else:
        traj_bias = 'LATERAL'
        traj_desc = 'Spot e VIX sem direção relevante. Não operar até ter sinal claro.'
        traj_icon = '⚠️ '

    return {
        'spot_now':      spot_now,
        'spot_prev':     spot_prev,
        'spot_delta':    round(spot_delta, 2),
        'spot_delta_pct': round(spot_delta_pct, 3),
        'spot_vel':      round(spot_vel, 3),
        'spot_dir':      spot_dir,
        'decelerating':  decelerating,
        'decel_note':    decel_note,
        'proj_15':       proj_15,
        'proj_30':       proj_30,
        'vix_now':       vix_now,
        'vix_prev':      vix_prev,
        'vix_delta':     round(vix_delta, 2),
        'vix_dir':       vix_dir,
        'dist_cw':       round(dist_cw, 2),
        'dist_pw':       round(dist_pw, 2),
        'dist_zg':       round(dist_zg, 2),
        'dist_vt':       round(dist_vt, 2),
        'gex_near':      gex_near,
        'hvl_0dte':      hvl_0dte,
        'traj_bias':     traj_bias,
        'traj_desc':     traj_desc,
        'traj_icon':     traj_icon,
        'alerts':        alerts,
        'minutes':       minutes_between,
    }


def print_trajectory(tr):
    SEP  = '─' * 60
    SEP2 = '═' * 60

    try:
        from zoneinfo import ZoneInfo
        import datetime as dtm
        now_str = dtm.datetime.now(ZoneInfo("America/New_York")).strftime('%H:%M ET')
    except Exception:
        now_str = datetime.now().strftime('%H:%M')

    print(f"\n{SEP2}")
    print(f"  RBC | Modo 4 — Trajetória e Sinalizações Preditivas")
    print(f"  {now_str}  |  Intervalo: {tr['minutes']} min")
    print(f"{SEP2}")

    print(f"\n📍 Trajetória do spot")
    print(f"{SEP}")
    dir_arrow = '↑' if tr['spot_dir']=='SUBINDO' else '↓' if tr['spot_dir']=='CAINDO' else '→'
    print(f"  SPY  : {tr['spot_prev']} → {tr['spot_now']}  {dir_arrow} {tr['spot_delta']:+.2f} pts  ({tr['spot_delta_pct']:+.3f}%)")
    print(f"  Vel  : {tr['spot_vel']:+.3f} pts/min")
    print(f"  VIX  : {tr['vix_prev']:.2f} → {tr['vix_now']:.2f}  ({tr['vix_delta']:+.2f})  {tr['vix_dir']}")
    print(f"\n  Projeção se trajetória continuar:")
    print(f"  +15 min → SPY {tr['proj_15']}  |  +30 min → SPY {tr['proj_30']}")
    print(f"  ⚠  Projeção linear — o mercado não é linear. Use como referência, não como certeza.")

    print(f"\n📐 Distâncias aos níveis")
    print(f"{SEP}")
    print(f"  Call Wall   : {tr['dist_cw']:+.2f} pts  {'→ PRÓXIMO ⚠' if 0 < tr['dist_cw'] <= 2 else ''}")
    print(f"  Put Wall    : -{tr['dist_pw']:.2f} pts  {'→ PRÓXIMO ⚠' if 0 < tr['dist_pw'] <= 2 else ''}")
    print(f"  Zero Gamma  : {tr['dist_zg']:+.2f} pts  {'→ PRÓXIMO ⚠' if abs(tr['dist_zg']) <= 2 else ''}")
    print(f"  Vol Trigger : {tr['dist_vt']:+.2f} pts")
    if tr['gex_near']:
        print(f"  GEX MQ near : {tr['gex_near']}  (dist {abs(tr['spot_now']-tr['gex_near']):.2f} pts)")
    if tr['hvl_0dte']:
        print(f"  HVL 0DTE MQ : {tr['hvl_0dte']}  (dist {abs(tr['spot_now']-tr['hvl_0dte']):.2f} pts)")

    print(f"\n{tr['traj_icon']} Leitura da trajetória — viés: {tr['traj_bias']}")
    print(f"{SEP}")
    print(f"  {tr['traj_desc']}")

    if tr['alerts']:
        print(f"\n🔔 Alertas de aproximação ({len(tr['alerts'])} ativo(s))")
        print(f"{SEP}")
        for a in tr['alerts']:
            print(f"\n  {a['icon']} {a['nivel']}  |  Dist: {a['dist']}  |  ETA: {a['eta']}")
            print(f"     {a['cond']}")
    else:
        print(f"\n  Nenhuma sinalização ativa. Spot longe dos níveis críticos.")

    print(f"\n{SEP2}")
    print(f"  Sinalizações são condicionais — 'SE acontecer X, ENTÃO considerar Y'.")
    print(f"  Nunca entrar antes do Risk Gate do Modo 3 abrir.")
    print(f"{SEP2}\n")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    try:
        from zoneinfo import ZoneInfo
        import datetime as dtm
        now_et = dtm.datetime.now(ZoneInfo("America/New_York")).strftime('%Y-%m-%d %H:%M ET')
    except Exception:
        now_et = datetime.now().strftime('%Y-%m-%d %H:%M')

    print("\n" + "═" * 60)
    print("  RBC — Risk Bridge Capital | 0DTE Scanner v1.5-beta")
    print(f"  {now_et}")
    print("═" * 60)
    print("""
  MODOS DE USO:
    1 → Pré-mercado  (antes 9:30)  — carrega níveis SpotGamma
    2 → Abertura     (9:30–10:00)  — monitora VIX + HIRO
    3 → Operacional  (após 10:00)  — recomenda strike 0DTE
    4 → Trajetória   (qualquer hora) — onde o spot está indo
    """)

    modo = input("  Escolha o modo [1/2/3/4]: ").strip()

    # ── Dados SpotGamma — auto-load ou prompt ───────────────────────
    import os
    dados_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dados_hoje.txt')
    if os.path.exists(dados_path):
        with open(dados_path, 'r') as _f:
            raw_input = _f.read().strip()
        print(f"  (dados carregados de dados_hoje.txt)")
    else:
        print("\n  Cole os dados do SpotGamma (Enter para usar exemplo):")
        raw_input = input("  > ").strip()
        if not raw_input:
            raw_input = (
                "$SPX, SPX, 7500, 6500, 7295, 7500, 7000, 7400, 7450, 7501, 7524, 7599, 7554, 0.0063, 0.0155, 7236, "
                "$SPY, SPY, 750, 730, 744, 750, 745, 740, 755, 747.5, 743.05, 750.47, 749.73, 0.0063, 0.0155, 741, "
                "$NDX, NDX, 30000, 27500, 28990, 29500, 30000, 29000, 27000, 29994, 29787, 30201, 30409, 0.01, 0, 26754, "
                "$QQQ, QQQ, 725, 700, 718, 700, 720, 710, 715, 730.2, 725.2, 720.2, 718.05, 0.01, 0, 712"
            )
            print("  (usando dados SpotGamma de exemplo)")

    sg_data = parse_sg_data(raw_input)
    spy_ref = sg_data.get('SPY', {})

    # MQ removido em v1.5-beta — sem prompts
    mq_data = {}
    mq_spy  = {}

    # ── MODO 1: Pré-mercado ─────────────────────────────────────────
    if modo == '1':
        print("\n" + "─" * 60)
        print("  PRÉ-MERCADO — Níveis SpotGamma")
        print("─" * 60)
        if spy_ref:
            d = spy_ref
            print(f"\n  Call Wall        : {d['call_wall']}")
            print(f"  Put Wall         : {d['put_wall']}")
            print(f"  Zero Gamma       : {d['zero_gamma']}")
            print(f"  Vol Trigger      : {d['vol_trigger']}")
            print(f"  Abs Gamma Strike : {d['abs_gamma']}")
            print(f"  Combos           : {d['combos']}")
            print(f"  Supports         : {d['supports']}")
            print(f"  Move implícito 1D: {d['imp_1d']*100:.2f}%")
            print(f"  Move implícito 5D: {d['imp_5d']*100:.2f}%")
        else:
            print("\n  SPY não encontrado nos dados SpotGamma.")
        print(f"\n  Ação: Rode o modo 2 às 9:35 com VIX e HIRO.")
        print()
        run_m2 = input("  Rodar Modo 2 agora? [s/n]: ").strip().lower()
        if run_m2 != 's':
            return
        modo = '2'

    # ── MODO 2: Abertura (primeiros 30 min) ─────────────────────────
    if modo == '2':
        print("\n  Dados de abertura (TradingView):")
        try:
            vix_open  = float(input("  VIX abertura (9:30): "))
            vix_now   = float(input("  VIX agora          : "))
            spot_open = float(input("  SPY abertura (9:30): "))
            spot_now  = float(input("  SPY agora          : "))
        except ValueError:
            print("  Erro de input. Use valores numéricos.")
            return

        hiro = 'neutral'

        ow = opening_watch(vix_open, vix_now, hiro, spot_open, spot_now,
                           sg_data, mq_data=mq_data)
        print_opening_watch(ow)

        if ow['verdict'] == 'OPERAR':
            print("  → Rode o modo 3 após 10:00 ET para o strike recomendado.\n")

        return

    # ── MODO 4: Monitor de Trajetória ────────────────────────────────
    if modo == '4':
        print("\n  Monitor de Trajetória — duas leituras de spot e VIX:")
        print("  (Dica: para detectar desaceleração, informe também a leitura de 30 min atrás)")
        try:
            spot_now  = float(input("  SPY agora                  : "))
            spot_prev = float(input("  SPY há 15 min              : "))
            vix_now   = float(input("  VIX agora                  : "))
            vix_prev  = float(input("  VIX há 15 min              : "))
            min_input = input("  Intervalo em min [15]      : ").strip()
            mins      = int(min_input) if min_input else 15
            print("  Leitura anterior (Enter para pular — detecta desaceleração):")
            p2 = input("  SPY há 30 min (opcional)   : ").strip()
            v2 = input("  VIX há 30 min (opcional)   : ").strip()
            spot_prev2 = float(p2) if p2 else None
            vix_prev2  = float(v2) if v2 else None
        except ValueError:
            print("  Erro de input. Use valores numéricos.")
            return

        tr = trajectory_analysis(spot_now, spot_prev, vix_now, vix_prev,
                                  sg_data, mq_data, minutes_between=mins,
                                  spot_prev2=spot_prev2, vix_prev2=vix_prev2)
        if 'error' in tr:
            print(f"  Erro: {tr['error']}")
        else:
            print_trajectory(tr)

        return

    # ── MODO 3: Strike scanner (após 10:00 ET) ──────────────────────
    print("\n  Parâmetros do momento (TradingView):")
    try:
        SPOT_SPY     = float(input("  SPY spot atual           : "))
        vix_val      = float(input("  VIX atual                : "))
        IV           = round(vix_val / 100, 4)
        hours_input  = input("  Horas até expiração [4.0]: ").strip()
        HOURS_TO_EXP = float(hours_input) if hours_input else 4.0
        cap_input    = input("  Capital total [50000]    : ").strip()
        CAPITAL      = float(cap_input) if cap_input else 50000.0
        prem_input   = input("  Prêmio pago (Enter=pular) : ").strip()
        PREMIUM      = float(prem_input) if prem_input else None
        contr_input  = input("  Contratos [1]            : ").strip()
        CONTRACTS    = int(contr_input) if contr_input else 1
        RF           = 0.0527
    except ValueError:
        print("  Erro de input. Use valores numéricos.")
        return

    print(f"\n  IV proxy (VIX/100)       : {IV*100:.2f}%")
    print(f"  Risk-free (T-Bill 3m)    : {RF*100:.2f}%")

    if spy_ref and mq_spy:
        cs = combined_signal(spy_ref, mq_spy, SPOT_SPY)
        print_combined(cs, SPOT_SPY)
        print()

    result = analyze_spy_0dte(sg_data, SPOT_SPY, IV, RF, HOURS_TO_EXP,
                               CAPITAL, PREMIUM, CONTRACTS)

    if 'error' in result:
        print(f"\n  Erro: {result['error']}")
    else:
        print_report(result)

        if mq_spy and result.get('candidates'):
            best = result['candidates'][0]
            print(f"\n  ── Contexto Menthor Q para o strike recomendado ──")
            print(f"  Strike recomendado : {best['strike']} {best['type'].upper()}")
            gw      = mq_spy.get('gamma_wall_0dte')
            hvl     = mq_spy.get('hvl_0dte')
            rng_max = mq_spy.get('range_max')
            rng_min = mq_spy.get('range_min')
            if gw:
                print(f"  Gamma Wall 0DTE MQ : {gw}  {'✅ strike abaixo da resistência' if best['strike'] < gw else '⚠ strike NA ou ACIMA — cuidado'}")
            if hvl:
                print(f"  HVL 0DTE MQ        : {hvl}  → Spot {'acima ✅' if SPOT_SPY > hvl else 'abaixo ⚠'}")
            if rng_min and rng_max:
                print(f"  Range do dia       : {rng_min} – {rng_max}")
                if best['type'] == 'call' and SPOT_SPY > rng_max * 0.995:
                    print(f"  ⚠ Spot próximo do topo do range — risco de reversão para call")
                elif best['type'] == 'put' and SPOT_SPY < rng_min * 1.005:
                    print(f"  ⚠ Spot próximo do piso do range — risco de reversão para put")
            print(f"  GEX top 3 MQ       : {mq_spy.get('gex_strikes', [])[:3]}\n")


if __name__ == '__main__':
    main()
