"""
RBC — Risk Bridge Capital
Brasil Options Scanner v1.0
============================
Scanner de opções brasileiras via OpLab API.
Estratégia adaptada para 1-3 semanas (não 0DTE).

Ativos monitorados: PETR4, VALE3, BOVA11

Lógica de estratégia:
  IV Rank > 50%  → PUT SPREAD  (vender vol cara)
  IV Rank 30-50% → CALL/PUT SPREAD (direcional)
  IV Rank < 30%  → COMPRA DIRETA (vol barata)

Uso:
    python rbc_br_scanner.py
"""

import os
import math
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

EMAIL    = os.getenv("OPLAB_EMAIL")
SENHA    = os.getenv("OPLAB_SENHA")
BASE_URL = "https://api.oplab.com.br/v3"

CAPITAL  = 1000.0   # R$ capital total
ATIVOS   = ["PETR4", "VALE3", "BOVA11"]

# ── Autenticação ──────────────────────────────────────────────────────

def autenticar():
    r = requests.post(
        f"{BASE_URL}/domain/users/authenticate",
        data={"email": EMAIL, "password": SENHA}
    )
    if r.status_code == 200:
        return r.json().get("access-token")
    raise Exception(f"Erro de autenticação: {r.status_code}")


# ── Black-Scholes (reaproveitado do scanner EUA) ──────────────────────

def norm_cdf(x):
    a = [0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429]
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    t = 1.0 / (1.0 + p * abs(x))
    y = 1.0 - (((((a[4]*t + a[3])*t + a[2])*t + a[1])*t + a[0])*t * math.exp(-x*x/2))
    return 0.5 * (1.0 + sign * y)

def bs_greeks(option_type, S, K, T, r, sigma):
    if T <= 0:
        intrinsic = max(0, S-K) if option_type == 'call' else max(0, K-S)
        return dict(price=intrinsic, delta=1.0 if intrinsic > 0 else 0.0,
                    gamma=0, theta=0, vega=0)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    phi = math.exp(-0.5*d1**2) / math.sqrt(2*math.pi)
    if option_type == 'call':
        price = S*norm_cdf(d1) - K*math.exp(-r*T)*norm_cdf(d2)
        delta = norm_cdf(d1)
    else:
        price = K*math.exp(-r*T)*norm_cdf(-d2) - S*norm_cdf(-d1)
        delta = norm_cdf(d1) - 1
    gamma = phi / (S*sigma*math.sqrt(T))
    theta = (-S*phi*sigma/(2*math.sqrt(T))
             - r*K*math.exp(-r*T)*(norm_cdf(d2) if option_type=='call' else norm_cdf(-d2))) / 365
    vega  = S*phi*math.sqrt(T)/100
    return dict(price=round(price,4), delta=round(delta,4),
                gamma=round(gamma,6), theta=round(theta,4), vega=round(vega,4))


# ── Kelly Sizing (reaproveitado do scanner EUA) ───────────────────────

def kelly_sizing(capital, win_rate=0.55, rr=1.5, max_pct=0.10):
    """
    Kelly 1/4 fração.
    max_pct: máximo do capital por operação (padrão 10% = R$100 de R$1.000)
    """
    kelly     = (win_rate * rr - (1 - win_rate)) / rr
    kelly_q   = kelly * 0.25
    sizing    = min(kelly_q * capital, capital * max_pct)
    return {
        'kelly_full':    round(kelly * 100, 2),
        'kelly_quarter': round(kelly_q * 100, 2),
        'recommended':   round(sizing, 2),
        'max_loss':      round(sizing, 2),   # no spread = risco = prêmio pago ou diferença
    }


# ── Busca de dados OpLab ──────────────────────────────────────────────

def buscar_spot(token, ativo):
    """Busca o preço atual do ativo."""
    headers = {"Access-Token": token}
    r = requests.get(f"{BASE_URL}/market/stocks/{ativo}", headers=headers)
    if r.status_code == 200:
        d = r.json()
        return d.get("close") or d.get("last") or d.get("price")
    return None

def buscar_opcoes_vencimento(token, ativo, dias_min=14, dias_max=35):
    """
    Busca opções do ativo filtrando por vencimento ideal (1-4 semanas).
    Retorna lista de opções no vencimento mais próximo dentro do range.
    """
    headers  = {"Access-Token": token}
    r = requests.get(f"{BASE_URL}/market/options/{ativo}", headers=headers)
    if r.status_code != 200:
        return [], None

    hoje     = datetime.now().date()
    data_min = hoje + timedelta(days=dias_min)
    data_max = hoje + timedelta(days=dias_max)

    opcoes = r.json()

    # Filtra por vencimento no range ideal
    candidatos = {}
    for op in opcoes:
        venc_str = op.get("due_date", "")
        try:
            venc = datetime.strptime(str(venc_str)[:10], "%Y-%m-%d").date()
        except:
            continue
        if data_min <= venc <= data_max:
            if venc not in candidatos:
                candidatos[venc] = []
            candidatos[venc].append(op)

    if not candidatos:
        return [], None

    # Usa o vencimento mais próximo dentro do range
    venc_ideal = sorted(candidatos.keys())[0]
    return candidatos[venc_ideal], venc_ideal


def buscar_iv_rank(token, ativo):
    """
    Busca IV Rank e dados de volatilidade do ativo.
    Retorna dict com iv_atual, iv_rank, iv_percentil, hv, tendencia_curta, tendencia_media
    """
    headers = {"Access-Token": token}
    r = requests.get(f"{BASE_URL}/market/stocks/{ativo}", headers=headers)
    if r.status_code == 200:
        d = r.json()
        # Converte trend: 1 = altista, -1 = baixista, 0 = neutro
        def parse_trend(val):
            if val == 1:  return 'up'
            if val == -1: return 'down'
            return 'neutral'
        score = d.get('oplab_score', {})
        score_val = score.get('value') if isinstance(score, dict) else score
        return {
            'iv_atual':        d.get('iv_current'),
            'iv_rank':         d.get('iv_1y_rank'),
            'iv_percentil':    d.get('iv_1y_percentile'),
            'hv':              d.get('ewma_current'),
            'tendencia_curta': parse_trend(d.get('short_term_trend')),
            'tendencia_media': parse_trend(d.get('middle_term_trend')),
            'spot':            d.get('close'),
            'oplab_score':     score_val,
        }
    return {}


# ── Estratégia por IV Rank ────────────────────────────────────────────

def definir_estrategia(iv_rank, tendencia_curta, tendencia_media):
    """
    Define a estratégia baseada no IV Rank e tendência.
    """
    if iv_rank is None:
        return 'AGUARDAR', 'IV Rank não disponível.'

    if iv_rank > 50:
        # IV alta — vender vol
        return 'PUT_SPREAD', (
            f'IV Rank {iv_rank:.1f}% — vol CARA. '
            'Vende put ATM + compra put OTM. '
            'Theta e queda de IV trabalham a seu favor.'
        )
    elif iv_rank > 30:
        # IV moderada — spread direcional
        if tendencia_curta == 'down' or tendencia_media == 'down':
            return 'PUT_SPREAD', (
                f'IV Rank {iv_rank:.1f}% — vol moderada + tendência baixista. '
                'Put spread direcional.'
            )
        else:
            return 'CALL_SPREAD', (
                f'IV Rank {iv_rank:.1f}% — vol moderada + tendência altista. '
                'Call spread direcional.'
            )
    else:
        # IV baixa — comprar vol
        if tendencia_curta == 'down' or tendencia_media == 'down':
            return 'COMPRA_PUT', (
                f'IV Rank {iv_rank:.1f}% — vol BARATA + tendência baixista. '
                'Compra put direta — melhor custo-benefício.'
            )
        else:
            return 'COMPRA_CALL', (
                f'IV Rank {iv_rank:.1f}% — vol BARATA + tendência altista. '
                'Compra call direta — melhor custo-benefício.'
            )


# ── Seleção de strikes para spread ───────────────────────────────────

def spread_width(spot):
    """Largura ideal do spread baseado no spot."""
    if spot < 60:
        return 2.0
    elif spot < 120:
        return 3.0
    else:
        return 5.0


def selecionar_put_spread(opcoes, spot, rf=0.1450, iv=0.34, dias=14):
    """
    Seleciona o melhor put spread (venda levemente OTM + compra 2-3 pts abaixo).
    Spread fixo calibrado ao spot do ativo.
    """
    T = dias / 365
    puts = [op for op in opcoes if op.get('symbol', '')[4:5].upper() in 'MNOPQRSTUVWX']
    puts.sort(key=lambda x: x.get('strike', 0))

    # Strike venda = ~1% abaixo do spot (levemente OTM)
    alvo_venda = spot * 0.98
    atm = min(puts, key=lambda x: abs(x.get('strike', 0) - alvo_venda), default=None)
    if not atm:
        return None

    strike_venda = atm.get('strike', spot)

    # Strike compra = largura fixa abaixo do strike de venda
    largura      = spread_width(spot)
    alvo_compra  = strike_venda - largura
    otm = min(puts, key=lambda x: abs(x.get('strike', 0) - alvo_compra), default=None)
    if not otm:
        return None

    strike_compra = otm.get('strike', alvo_compra)

    # Black-Scholes para ambos
    g_venda  = bs_greeks('put', spot, strike_venda,  T, rf, iv)
    g_compra = bs_greeks('put', spot, strike_compra, T, rf, iv)

    # Prêmio líquido recebido
    premio_recebido = round(g_venda['price'] - g_compra['price'], 4)
    risco_maximo    = round(strike_venda - strike_compra - premio_recebido, 4)
    break_even      = round(strike_venda - premio_recebido, 2)
    lucro_maximo    = premio_recebido
    rr              = round(lucro_maximo / risco_maximo, 2) if risco_maximo > 0 else 0

    return {
        'tipo':             'PUT SPREAD',
        'acao':             f'Vende PUT {strike_venda} + Compra PUT {strike_compra}',
        'strike_venda':     strike_venda,
        'strike_compra':    strike_compra,
        'premio_recebido':  premio_recebido,
        'risco_maximo':     risco_maximo,
        'lucro_maximo':     lucro_maximo,
        'break_even':       break_even,
        'rr':               rr,
        'delta_venda':      g_venda['delta'],
        'delta_compra':     g_compra['delta'],
        'theta_liquido':    round(abs(g_venda['theta']) - abs(g_compra['theta']), 4),
        'vega_liquido':     round(g_venda['vega']  - g_compra['vega'],  4),
    }


def selecionar_call_spread(opcoes, spot, rf=0.1450, iv=0.34, dias=14):
    """
    Seleciona o melhor call spread (compra ATM + vende OTM).
    """
    T = dias / 365
    calls = [op for op in opcoes if op.get('symbol', '')[4:5].upper() in 'ABCDEFGHIJKL']
    calls.sort(key=lambda x: x.get('strike', 0))

    atm = min(calls, key=lambda x: abs(x.get('strike', 0) - spot), default=None)
    if not atm:
        return None

    strike_compra = atm.get('strike', spot)
    otm_alvo      = spot * 1.03
    otm = min(calls, key=lambda x: abs(x.get('strike', 0) - otm_alvo), default=None)
    if not otm:
        return None

    strike_venda = otm.get('strike', otm_alvo)

    g_compra = bs_greeks('call', spot, strike_compra, T, rf, iv)
    g_venda  = bs_greeks('call', spot, strike_venda,  T, rf, iv)

    premio_pago  = round(g_compra['price'] - g_venda['price'], 4)
    lucro_maximo = round(strike_venda - strike_compra - premio_pago, 4)
    break_even   = round(strike_compra + premio_pago, 2)
    rr           = round(lucro_maximo / premio_pago, 2) if premio_pago > 0 else 0

    return {
        'tipo':          'CALL SPREAD',
        'acao':          f'Compra CALL {strike_compra} + Vende CALL {strike_venda}',
        'strike_compra': strike_compra,
        'strike_venda':  strike_venda,
        'premio_pago':   premio_pago,
        'lucro_maximo':  lucro_maximo,
        'break_even':    break_even,
        'rr':            rr,
        'delta_compra':  g_compra['delta'],
        'theta_liquido': round(g_compra['theta'] - g_venda['theta'], 4),
        'vega_liquido':  round(g_compra['vega']  - g_venda['vega'],  4),
    }


def selecionar_compra_direta(opcoes, spot, tipo, rf=0.1450, iv=0.34, dias=14):
    """Compra direta de call ou put ATM."""
    T = dias / 365
    if tipo == 'call':
        filtradas = [op for op in opcoes if op.get('symbol', '')[4:5].upper() in 'ABCDEFGHIJKL']
    else:
        filtradas = [op for op in opcoes if op.get('symbol', '')[4:5].upper() in 'MNOPQRSTUVWX']
    atm = min(filtradas, key=lambda x: abs(x.get('strike', 0) - spot), default=None)
    if not atm:
        return None

    strike = atm.get('strike', spot)
    g = bs_greeks(tipo, spot, strike, T, rf, iv)

    return {
        'tipo':       f'COMPRA {tipo.upper()}',
        'acao':       f'Compra {tipo.upper()} {strike}',
        'strike':     strike,
        'premio':     g['price'],
        'delta':      g['delta'],
        'gamma':      g['gamma'],
        'theta':      g['theta'],
        'vega':       g['vega'],
        'break_even': round(strike + g['price'], 2) if tipo == 'call' else round(strike - g['price'], 2),
    }


# ── Saídas (adaptado para 1-3 semanas) ───────────────────────────────

def regras_saida(estrategia, premio, dias_vencimento):
    """
    Regras de saída simples e claras — igual à filosofia do scanner EUA.
    PUT SPREAD vendido  : alvo 50% do prêmio recebido | stop 2x | tempo 7 dias antes
    CALL SPREAD comprado: alvo +100% prêmio pago      | stop -50% | tempo 7 dias antes
    COMPRA DIRETA       : alvo +100% prêmio pago      | stop -50% | tempo 7 dias antes
    """
    dias_corte = max(1, dias_vencimento - 7)  # fecha 7 dias antes obrigatório

    if 'PUT SPREAD' in estrategia.get('tipo', ''):
        premio_rec = estrategia.get('premio_recebido', 0)
        return {
            'tipo':            'PUT SPREAD (vendido)',
            'alvo_recompra':   round(premio_rec * 0.50, 4),  # spread vale 50% do recebido → 50% lucro
            'stop_recompra':   round(premio_rec * 2.0,  4),  # spread vale 2x o recebido → stop
            'lucro_alvo_pct':  50,
            'stop_pct':        100,   # perde valor equivalente ao prêmio recebido
            'regra_tempo':     f'Fechar obrigatório em {dias_corte} dias (7 dias antes do vencimento)',
            'filosofia':       (
                'Não segurar até o vencimento. '
                'Alvo: recomprar o spread por 50% do recebido. '
                'Stop: spread vale 2x o que você recebeu. '
                'Primeiro gatilho vence.'
            ),
        }

    elif 'CALL SPREAD' in estrategia.get('tipo', ''):
        premio_pago = estrategia.get('premio_pago', 0)
        return {
            'tipo':           'CALL SPREAD (comprado)',
            'alvo_venda':     round(premio_pago * 2.0, 4),   # dobrar o prêmio pago
            'stop_venda':     round(premio_pago * 0.5, 4),   # perder 50% do pago
            'lucro_alvo_pct': 100,
            'stop_pct':       50,
            'regra_tempo':    f'Fechar obrigatório em {dias_corte} dias (7 dias antes do vencimento)',
            'filosofia':      (
                'Alvo +100% do prêmio pago. '
                'Stop -50%. '
                'Theta é inimigo — não segurar perto do vencimento.'
            ),
        }

    else:
        # Compra direta
        premio_pago = estrategia.get('premio', 0)
        return {
            'tipo':           'COMPRA DIRETA',
            'alvo_venda':     round(premio_pago * 2.0, 4),
            'stop_venda':     round(premio_pago * 0.5, 4),
            'lucro_alvo_pct': 100,
            'stop_pct':       50,
            'regra_tempo':    f'Fechar obrigatório em {dias_corte} dias (7 dias antes do vencimento)',
            'filosofia':      (
                'Alvo +100% do prêmio. '
                'Stop -50%. '
                'Theta corrói rápido perto do vencimento.'
            ),
        }


# ── Risk Gate Brasil ──────────────────────────────────────────────────

def risk_gate_br(iv_rank, tendencia_curta, tendencia_media, estrategia_tipo, spot, opcoes_count):
    """
    Risk Gate adaptado para Brasil — sem restrição de horário ET.
    Janela BR: 10:15–16:30
    """
    checks = []

    try:
        from zoneinfo import ZoneInfo
        now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
    except:
        now_br = datetime.now()

    hora = now_br.time()
    from datetime import time as dtime

    # 1. Janela de entrada
    ok1 = dtime(10, 15) <= hora <= dtime(16, 30)
    checks.append({
        'item':   'Janela de entrada (10:15–16:30 BRT)',
        'pass':   ok1,
        'detail': f"Hora BRT: {hora.strftime('%H:%M')} — {'✅ dentro da janela' if ok1 else '🚫 fora da janela'}"
    })

    # 2. IV Rank
    if 'PUT_SPREAD' in estrategia_tipo or 'SPREAD' in estrategia_tipo:
        ok2 = iv_rank is not None and iv_rank > 30
        iv_str = f"{iv_rank:.1f}%" if iv_rank is not None else "N/A"
        checks.append({
            'item':   'IV Rank adequado para spread',
            'pass':   ok2,
            'detail': f"IV Rank {iv_str} — {'✅ adequado' if ok2 else '⚠ muito baixo para spread'}"
        })
    else:
        ok2 = iv_rank is not None and iv_rank < 50
        iv_str = f"{iv_rank:.1f}%" if iv_rank is not None else "N/A"
        checks.append({
            'item':   'IV Rank adequado para compra',
            'pass':   ok2,
            'detail': f"IV Rank {iv_str} — {'✅ adequado para compra' if ok2 else '⚠ IV muito alta para comprar'}"
        })

    # 3. Liquidez
    ok3 = opcoes_count > 50
    checks.append({
        'item':   'Liquidez (opções disponíveis)',
        'pass':   ok3,
        'detail': f"{opcoes_count} contratos encontrados — {'✅ líquido' if ok3 else '⚠ baixa liquidez'}"
    })

    # 4. Filtro de tendência obrigatório
    # PUT SPREAD não operar em tendência fortemente altista
    # COMPRA CALL não operar em tendência fortemente baixista
    if 'PUT_SPREAD' in estrategia_tipo:
        contra = (tendencia_curta == 'up' and tendencia_media == 'up')
        ok4 = not contra
        detalhe_tend = (
            '✅ Tendência neutra/baixista — put spread adequado'
            if ok4 else
            '🚫 Tendência ALTISTA dupla — put spread perigoso. Aguardar reversão.'
        )
    elif 'COMPRA_CALL' in estrategia_tipo:
        contra = (tendencia_curta == 'down' and tendencia_media == 'down')
        ok4 = not contra
        detalhe_tend = (
            '✅ Tendência favorável para call'
            if ok4 else
            '🚫 Tendência BAIXISTA dupla — não comprar call.'
        )
    else:
        ok4 = True
        detalhe_tend = f'✅ Curta: {tendencia_curta or "-"}  |  Média: {tendencia_media or "-"}'

    checks.append({
        'item':   'Filtro de tendência',
        'pass':   ok4,
        'detail': detalhe_tend
    })

    gate_open = all(c['pass'] for c in checks)
    return {'gate_open': gate_open, 'checks': checks, 'hora_br': hora.strftime('%H:%M BRT')}


# ── Análise completa por ativo ────────────────────────────────────────

def analisar_ativo(token, ativo):
    """Análise completa de um ativo."""

    # 1. Dados de volatilidade
    vol_data = buscar_iv_rank(token, ativo)
    spot     = vol_data.get('spot')
    iv_rank  = vol_data.get('iv_rank')
    iv_atual = vol_data.get('iv_atual')
    hv       = vol_data.get('hv')
    t_curta  = vol_data.get('tendencia_curta', '')
    t_media  = vol_data.get('tendencia_media', '')

    if not spot:
        return {'ativo': ativo, 'erro': 'Spot não disponível'}

    # IV como decimal para Black-Scholes
    iv_bs = (iv_atual / 100) if iv_atual and iv_atual > 1 else (iv_atual or 0.30)
    rf    = 0.1450  # SELIC 14.50%

    # 2. Opções no vencimento ideal (1-4 semanas)
    opcoes, venc = buscar_opcoes_vencimento(token, ativo, dias_min=14, dias_max=35)
    if not opcoes or not venc:
        return {'ativo': ativo, 'erro': 'Sem opções no vencimento ideal (7-28 dias)'}

    hoje      = datetime.now().date()
    dias_venc = (venc - hoje).days

    # 3. Estratégia
    estrategia_tipo, estrategia_desc = definir_estrategia(iv_rank, t_curta, t_media)

    # 4. Monta o trade
    trade = None
    if estrategia_tipo == 'PUT_SPREAD':
        trade = selecionar_put_spread(opcoes, spot, rf, iv_bs, dias_venc)
    elif estrategia_tipo == 'CALL_SPREAD':
        trade = selecionar_call_spread(opcoes, spot, rf, iv_bs, dias_venc)
    elif estrategia_tipo == 'COMPRA_PUT':
        trade = selecionar_compra_direta(opcoes, spot, 'put', rf, iv_bs, dias_venc)
    elif estrategia_tipo == 'COMPRA_CALL':
        trade = selecionar_compra_direta(opcoes, spot, 'call', rf, iv_bs, dias_venc)

    # 5. Saídas
    saidas = regras_saida(trade, 0, dias_venc) if trade else None

    # 6. Sizing
    sizing = kelly_sizing(CAPITAL)

    # 7. Risk Gate
    gate = risk_gate_br(iv_rank, t_curta, t_media, estrategia_tipo, spot, len(opcoes))

    return {
        'ativo':            ativo,
        'spot':             spot,
        'iv_atual':         iv_atual,
        'iv_rank':          iv_rank,
        'hv':               hv,
        'tendencia_curta':  t_curta,
        'tendencia_media':  t_media,
        'vencimento':       str(venc),
        'dias_vencimento':  dias_venc,
        'estrategia_tipo':  estrategia_tipo,
        'estrategia_desc':  estrategia_desc,
        'trade':            trade,
        'saidas':           saidas,
        'sizing':           sizing,
        'gate':             gate,
        'opcoes_count':     len(opcoes),
    }


# ── Relatório ─────────────────────────────────────────────────────────

def print_relatorio(resultado):
    SEP  = '─' * 65
    SEP2 = '═' * 65

    ativo = resultado['ativo']

    if 'erro' in resultado:
        print(f"\n  ⚠  {ativo}: {resultado['erro']}")
        return

    spot     = resultado['spot']
    iv_rank  = resultado.get('iv_rank')
    iv_atual = resultado.get('iv_atual')
    hv       = resultado.get('hv')
    t_curta  = resultado.get('tendencia_curta', '-')
    t_media  = resultado.get('tendencia_media', '-')

    # Ícone de tendência
    def trend_icon(t):
        if t == 'up':   return '↑ Alta'
        if t == 'down': return '↓ Baixa'
        return '→ Neutra'

    print(f"\n{SEP2}")
    print(f"  RBC Brasil | {ativo}  —  R$ {spot:.2f}")
    print(f"  Vencimento alvo: {resultado['vencimento']}  ({resultado['dias_vencimento']} dias)")
    print(f"{SEP2}")

    # Volatilidade
    print(f"\n📊 Volatilidade")
    print(f"{SEP}")
    iv_str   = f"{iv_atual:.2f}%" if iv_atual else '-'
    hv_str   = f"{hv:.2f}%"      if hv       else '-'
    rank_str = f"{iv_rank:.1f}%" if iv_rank  else '-'
    iv_vs_hv = ''
    if iv_atual and hv:
        diff = iv_atual - hv
        iv_vs_hv = f"  ({'IV cara +' if diff > 0 else 'IV barata '}{abs(diff):.1f}%)"
    print(f"  IV Atual    : {iv_str}{iv_vs_hv}")
    print(f"  HV (EWMA)   : {hv_str}")
    print(f"  IV Rank     : {rank_str}  {'🔴 vender vol' if iv_rank and iv_rank > 50 else '🟡 neutro' if iv_rank and iv_rank > 30 else '🟢 comprar vol'}")
    print(f"  Tendência   : Curta {trend_icon(t_curta)}  |  Média {trend_icon(t_media)}")
    print(f"  Opções disp.: {resultado['opcoes_count']} contratos")

    # Estratégia
    est = resultado['estrategia_tipo']
    print(f"\n🎯 Estratégia recomendada: {est.replace('_', ' ')}")
    print(f"{SEP}")
    print(f"  {resultado['estrategia_desc']}")

    # Trade
    trade = resultado.get('trade')
    if trade:
        print(f"\n📋 Trade")
        print(f"{SEP}")
        print(f"  {trade['acao']}")

        if 'PUT SPREAD' in trade.get('tipo', ''):
            print(f"  Prêmio recebido : R$ {trade['premio_recebido']:.4f} por ação")
            print(f"  Risco máximo    : R$ {trade['risco_maximo']:.4f} por ação")
            print(f"  Lucro máximo    : R$ {trade['lucro_maximo']:.4f} por ação")
            print(f"  Break-even      : R$ {trade['break_even']:.2f}")
            print(f"  Risk/Reward     : {trade['rr']}x")
            print(f"  Theta líquido   : R$ {trade['theta_liquido']:.4f}/dia  ← a seu favor ✅")
            print(f"  Vega líquido    : {trade['vega_liquido']:.4f}  ← queda de IV beneficia ✅")

        elif 'CALL SPREAD' in trade.get('tipo', ''):
            print(f"  Prêmio pago     : R$ {trade['premio_pago']:.4f} por ação")
            print(f"  Lucro máximo    : R$ {trade['lucro_maximo']:.4f} por ação")
            print(f"  Break-even      : R$ {trade['break_even']:.2f}")
            print(f"  Risk/Reward     : {trade['rr']}x")

        else:
            print(f"  Prêmio          : R$ {trade['premio']:.4f} por ação")
            print(f"  Delta           : {trade['delta']:.4f}")
            print(f"  Gamma           : {trade['gamma']:.6f}")
            print(f"  Theta/dia       : R$ {trade['theta']:.4f}")
            print(f"  Break-even      : R$ {trade['break_even']:.2f}")

        # ⚠️ Lembrete Black-Scholes
        print(f"\n  ⚠  Preços calculados pelo modelo Black-Scholes.")
        print(f"     Confirme bid/ask real no Profit antes de entrar.")

    # Saídas
    saidas = resultado.get('saidas')
    if saidas:
        print(f"\n🚪 Regras de saída")
        print(f"{SEP}")
        if 'alvo_recompra' in saidas:
            print(f"  Alvo (recompra spread) : R$ {saidas['alvo_recompra']:.4f}  (+{saidas['lucro_alvo_pct']}% do lucro máximo)")
            print(f"  Stop (recompra spread) : R$ {saidas['stop_recompra']:.4f}  (-{saidas['stop_pct']}% — spread dobrou)")
        else:
            print(f"  Alvo (venda)  : R$ {saidas['alvo_venda']:.4f}  (+{saidas['lucro_alvo_pct']}%)")
            print(f"  Stop (venda)  : R$ {saidas['stop_venda']:.4f}  (-{saidas['stop_pct']}%)")
        print(f"  Regra de tempo: {saidas['regra_tempo']}")
        print(f"  Filosofia     : {saidas['filosofia']}")

    # Sizing
    sz = resultado.get('sizing', {})
    gate = resultado.get('gate', {})
    if gate.get('gate_open'):
        print(f"\n💰 Sizing — Kelly 1/4  (capital R$ {CAPITAL:.0f})")
        print(f"{SEP}")
        print(f"  Kelly full        : {sz.get('kelly_full')}%")
        print(f"  Kelly 1/4         : {sz.get('kelly_quarter')}%")
        print(f"  Sizing recomendado: R$ {sz.get('recommended'):.2f}")
        print(f"  Risco máximo op   : R$ {sz.get('max_loss'):.2f}")

    # Risk Gate
    status = '✅ GATE ABERTO' if gate.get('gate_open') else '🚫 GATE FECHADO'
    print(f"\n🛡  Risk Gate — {status}  ({gate.get('hora_br', '')})")
    print(f"{SEP}")
    for c in gate.get('checks', []):
        icon = '  ✓' if c['pass'] else '  ✗'
        print(f"{icon} {c['item']}")
        print(f"      {c['detail']}")

    print(f"\n{SEP2}")


def print_resumo(resultados):
    """Resumo comparativo dos três ativos."""
    SEP2 = '═' * 65
    print(f"\n{SEP2}")
    print(f"  RBC Brasil | RESUMO COMPARATIVO")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{SEP2}")
    print(f"\n  {'Ativo':<8} {'Spot':>8} {'IV':>7} {'IV Rank':>8} {'Estratégia':<20} {'Gate'}")
    print(f"  {'-'*60}")

    melhor = None
    melhor_score = -1

    for r in resultados:
        if 'erro' in r:
            print(f"  {r['ativo']:<8} {'—':>8} {'—':>7} {'—':>8} {r['erro']:<20}")
            continue

        spot     = f"R${r['spot']:.2f}"
        iv       = f"{r['iv_atual']:.1f}%" if r.get('iv_atual') else '-'
        iv_rank  = f"{r['iv_rank']:.1f}%"  if r.get('iv_rank')  else '-'
        est      = r['estrategia_tipo'].replace('_', ' ')
        gate_ok  = '✅' if r['gate']['gate_open'] else '🚫'

        print(f"  {r['ativo']:<8} {spot:>8} {iv:>7} {iv_rank:>8} {est:<20} {gate_ok}")

        # Pontuação para sugerir o melhor
        score = 0
        if r['gate']['gate_open']:
            score += 3
        if r.get('iv_rank') and r['iv_rank'] > 50:
            score += 2   # IV alta = put spread mais gordo
        if r.get('trade') and r['trade']:
            score += 1

        if score > melhor_score:
            melhor_score = score
            melhor = r

    if melhor and not 'erro' in melhor:
        print(f"\n  ★ Melhor setup hoje: {melhor['ativo']}")
        print(f"    {melhor['estrategia_desc']}")
        if melhor.get('trade'):
            print(f"    Trade: {melhor['trade']['acao']}")

    print(f"\n{SEP2}\n")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    SEP2 = '═' * 65

    try:
        from zoneinfo import ZoneInfo
        now_br = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime('%Y-%m-%d %H:%M BRT')
    except:
        now_br = datetime.now().strftime('%Y-%m-%d %H:%M')

    print(f"\n{SEP2}")
    print(f"  RBC — Risk Bridge Capital | Brasil Scanner v1.0")
    print(f"  {now_br}")
    print(f"  Ativos: {', '.join(ATIVOS)}  |  Capital: R$ {CAPITAL:.0f}")
    print(f"{SEP2}")

    print("\n  Autenticando na OpLab...")
    try:
        token = autenticar()
        print("  ✅ Autenticado!\n")
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return

    resultados = []
    for ativo in ATIVOS:
        print(f"  Analisando {ativo}...")
        r = analisar_ativo(token, ativo)
        resultados.append(r)

    # Resumo primeiro
    print_resumo(resultados)

    # Relatório detalhado de cada ativo
    detalhe = input("  Ver relatório detalhado? [s/n]: ").strip().lower()
    if detalhe == 's':
        for r in resultados:
            print_relatorio(r)
            input("\n  [Enter para próximo ativo]")

    print(f"\n  ⚠  Dados educacionais — não são recomendações de investimento.")
    print(f"  ⚠  Confirme todos os preços no Profit antes de operar.\n")


if __name__ == '__main__':
    main()
