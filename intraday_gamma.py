"""
RBC — Modo 6: Intraday Gamma (sem SpotGamma)
=============================================
Calcula GEX (Gamma Exposure) por strike usando dados reais do IBKR.

Gera os niveis que o SpotGamma dava:
  - Call Wall  = strike com maior GEX positivo
  - Put Wall   = strike com maior GEX negativo
  - Zero Gamma = onde o GEX cumulativo cruza zero (proxy do Vol Trigger)

Duas versoes de GEX:
  - GEX por OI      = estrutura herdada de ontem (swing)
  - GEX por VOLUME  = fluxo real de hoje (intraday / 0DTE)

Requisitos:
  pip install ib_insync
  TWS ou IB Gateway aberto com API habilitada
  (TWS: File > Global Configuration > API > Settings > Enable ActiveX and Socket Clients)

Uso:
  python3 intraday_gamma.py            # expiracao 0DTE (hoje)
  python3 intraday_gamma.py 2026-07-17 # expiracao especifica
"""

import sys
import math
from datetime import datetime
from ib_insync import IB, Stock, Option

# ── CONFIG ────────────────────────────────────────────────────────────────
TWS_HOST = "127.0.0.1"
TWS_PORT = 7497        # TWS live = 7496 | TWS paper = 7497 | Gateway live = 4001
CLIENT_ID = 61          # qualquer numero nao usado por outro app
STRIKES_RANGE = 40      # quantos strikes acima/abaixo do spot (largo p/ pegar ZG em dias profundos)
# ──────────────────────────────────────────────────────────────────────────


def main():
    expiry_arg = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None

    ib = IB()
    print(f"Conectando ao TWS em {TWS_HOST}:{TWS_PORT} ...")
    try:
        ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID, timeout=10)
    except Exception as e:
        print(f"\nERRO: nao conectou ao TWS: {e}")
        print("Verifique: TWS aberto? API habilitada? Porta correta (7496 live / 7497 paper)?")
        return

    print("Conectado.\n")

    # ── SPY spot ──────────────────────────────────────────────────────────
    spy = Stock("SPY", "SMART", "USD")
    ib.qualifyContracts(spy)
    ticker = ib.reqMktData(spy, "", False, False)
    ib.sleep(2)
    spot = ticker.marketPrice()
    if not spot or math.isnan(spot):
        spot = ticker.close
    print(f"SPY spot: {spot:.2f}")

    # ── Expiracoes disponiveis ────────────────────────────────────────────
    chains = ib.reqSecDefOptParams(spy.symbol, "", spy.secType, spy.conId)
    chain = next(c for c in chains if c.tradingClass == "SPY" and c.exchange == "SMART")

    today = datetime.now().strftime("%Y%m%d")
    expirations = sorted(chain.expirations)

    now = datetime.now()
    market_closed = now.hour >= 16 or now.weekday() >= 5

    if expiry_arg:
        target_expiry = expiry_arg.replace("-", "")
    elif market_closed:
        # Apos 16h ET o 0DTE de hoje expirou — usa a proxima expiracao
        future = [e for e in expirations if e > today]
        target_expiry = future[0] if future else expirations[-1]
        print(f"Mercado fechado ({now:%H:%M}) — 0DTE de hoje expirou. Usando proxima expiracao.")
    else:
        target_expiry = today if today in expirations else expirations[0]

    dte = (datetime.strptime(target_expiry, "%Y%m%d") - datetime.now()).days
    print(f"Expiracao: {target_expiry} (DTE ~{max(dte,0)})\n")

    # ── Strikes ao redor do spot ──────────────────────────────────────────
    strikes = sorted(s for s in chain.strikes
                     if abs(s - spot) <= STRIKES_RANGE and s == int(s))

    contracts = []
    for strike in strikes:
        for right in ("C", "P"):
            contracts.append(Option("SPY", target_expiry, strike, right, "SMART", tradingClass="SPY"))

    contracts = ib.qualifyContracts(*contracts)
    print(f"{len(contracts)} contratos qualificados. Puxando greeks + OI + volume ...")

    # genericTickList "101" = OI de opcoes (tick 27 call OI / 28 put OI)
    # Coleta em LOTES p/ respeitar o limite de linhas de market data do TWS (~100)
    BATCH = 90
    tickers = []
    n_lotes = (len(contracts) + BATCH - 1) // BATCH
    for bi in range(0, len(contracts), BATCH):
        lote = contracts[bi:bi + BATCH]
        lote_tk = [ib.reqMktData(c, "101", False, False) for c in lote]
        ib.sleep(6)  # da tempo dos greeks chegarem
        for c in lote:
            ib.cancelMktData(c)
        tickers.extend(lote_tk)
        print(f"  lote {bi // BATCH + 1}/{n_lotes}: {len(lote)} contratos coletados")

    # ── Monta tabela por strike ───────────────────────────────────────────
    data = {}   # strike -> {call_gamma, call_oi, call_vol, put_gamma, put_oi, put_vol}
    def bs_gamma(spot_px, strike_px, iv, dte_days):
        """Black-Scholes gamma fallback quando TWS nao manda o greek."""
        t_yr = max(dte_days, 0.5) / 365.0
        if not iv or iv <= 0 or math.isnan(iv):
            return None
        d1 = (math.log(spot_px / strike_px) + (0.5 * iv * iv) * t_yr) / (iv * math.sqrt(t_yr))
        return math.exp(-0.5 * d1 * d1) / (spot_px * iv * math.sqrt(2 * math.pi * t_yr))

    for c, t in zip(contracts, tickers):
        g = None
        iv = None
        for src in (t.modelGreeks, t.lastGreeks, t.bidGreeks, t.askGreeks):
            if src:
                if src.gamma and not math.isnan(src.gamma) and g is None:
                    g = src.gamma
                if src.impliedVol and not math.isnan(src.impliedVol) and iv is None:
                    iv = src.impliedVol
        if g is None:
            # fallback Black-Scholes com a IV disponivel
            g = bs_gamma(spot, c.strike, iv, max(dte, 1))
        oi = None
        if c.right == "C":
            oi = t.callOpenInterest
        else:
            oi = t.putOpenInterest
        vol = t.volume if t.volume and not math.isnan(t.volume) else 0
        if oi is None or (isinstance(oi, float) and math.isnan(oi)):
            oi = 0

        row = data.setdefault(c.strike, {})
        prefix = "call" if c.right == "C" else "put"
        row[f"{prefix}_gamma"] = g or 0
        row[f"{prefix}_oi"] = oi
        row[f"{prefix}_vol"] = vol

    ib.disconnect()

    # ── GEX ───────────────────────────────────────────────────────────────
    # GEX = gamma * contratos * 100 shares * spot  (em "SPY-share-equivalents * $")
    # Convencao dealer: long calls (+), short puts => put GEX negativo
    rows = []
    for strike in sorted(data):
        d = data[strike]
        cg, pg = d.get("call_gamma", 0), d.get("put_gamma", 0)
        gex_oi = (cg * d.get("call_oi", 0) - pg * d.get("put_oi", 0)) * 100 * spot
        gex_vol = (cg * d.get("call_vol", 0) - pg * d.get("put_vol", 0)) * 100 * spot
        rows.append({
            "strike": strike,
            "gex_oi": gex_oi,
            "gex_vol": gex_vol,
            "call_oi": d.get("call_oi", 0), "put_oi": d.get("put_oi", 0),
            "call_vol": d.get("call_vol", 0), "put_vol": d.get("put_vol", 0),
        })

    if not rows:
        print("Nenhum dado retornado. Verifique subscricao OPRA no IBKR.")
        return

    # Trava de qualidade: sem gamma real, nao imprimir paredes falsas
    total_abs_gex = sum(abs(r["gex_oi"]) for r in rows)
    if total_abs_gex == 0:
        print("\nAVISO: greeks indisponiveis (gamma zerado em todos os strikes).")
        print("Causas comuns: mercado fechado, contratos expirados, ou dados atrasados.")
        print("Rode com o mercado aberto (9:30-16:00 ET) ou passe uma expiracao futura:")
        print("  python3 intraday_gamma.py 2026-07-07")
        print("\nOI bruto (ainda util para ver paredes de posicao):")
        top_calls = sorted(rows, key=lambda r: -r["call_oi"])[:3]
        top_puts  = sorted(rows, key=lambda r: -r["put_oi"])[:3]
        print("  Maiores Call OI:", ", ".join(f"{r['strike']:.0f} ({r['call_oi']:,.0f})" for r in top_calls))
        print("  Maiores Put OI: ", ", ".join(f"{r['strike']:.0f} ({r['put_oi']:,.0f})" for r in top_puts))
        return

    def levels(rows, key):
        """Call Wall, Put Wall e Zero Gamma REAL.
        Zero Gamma só é número quando o GEX acumulado cruza zero dentro do range coletado.
        Se não cruzar, retorna None + status ACIMA_DO_RANGE/ABAIXO_DO_RANGE.
        """
        call_wall = max(rows, key=lambda r: r[key])["strike"]
        put_wall = min(rows, key=lambda r: r[key])["strike"]

        # Piso de significancia: ignora ruido < 0.5% do maior |GEX| do perfil
        _piso = max((abs(r[key]) for r in rows), default=0) * 0.005
        _sig = [r for r in rows if abs(r[key]) > _piso]

        cum = 0
        zero_gamma = None
        zero_gamma_status = None
        prev_cum, prev_strike = None, None

        for r in _sig:
            cum += r[key]
            if prev_cum is not None and prev_cum < 0 <= cum:
                zero_gamma = prev_strike + (r["strike"] - prev_strike) * (-prev_cum) / (cum - prev_cum)
                zero_gamma = round(zero_gamma, 1)
                zero_gamma_status = "REAL"
                break
            prev_cum, prev_strike = cum, r["strike"]

        if zero_gamma is None:
            total = sum(r[key] for r in rows)
            zero_gamma_status = "ACIMA_DO_RANGE" if total < 0 else "ABAIXO_DO_RANGE"

        return call_wall, put_wall, zero_gamma, zero_gamma_status

    def find_vol_trigger(rows, key):
        """Vol Trigger RBC: flip LOCAL do GEX por strike.
        Retorna número só se o GEX local muda de negativo para positivo.
        Sem flip local = None + status SEM_FLIP_LOCAL.
        """
        # Ignora greeks nao coletados (0) e ruido < 0.5% do maior |GEX|
        _piso = max((abs(r[key]) for r in rows), default=0) * 0.005
        data = [r for r in rows if abs(r[key]) > _piso]
        for i in range(1, len(data)):
            prev_val = data[i - 1][key]
            curr_val = data[i][key]

            if prev_val < 0 <= curr_val:
                prev_strike = data[i - 1]["strike"]
                curr_strike = data[i]["strike"]

                if curr_val != prev_val:
                    vt = prev_strike + (curr_strike - prev_strike) * (-prev_val) / (curr_val - prev_val)
                else:
                    vt = curr_strike

                return round(vt, 1), "REAL"

        return None, "SEM_FLIP_LOCAL"

    # Cobertura de greeks: quantos strikes tem gamma real
    strikes_com_gamma = sum(1 for r in rows if r["gex_oi"] != 0)
    coverage = strikes_com_gamma / len(rows) * 100
    cw_oi, pw_oi, zg_oi, zg_oi_status = levels(rows, "gex_oi")
    cw_v, pw_v, zg_v, zg_v_status = levels(rows, "gex_vol")
    vt_oi, vt_oi_status = find_vol_trigger(rows, "gex_oi")
    vt_v, vt_v_status = find_vol_trigger(rows, "gex_vol")

    total_gex_oi = sum(r["gex_oi"] for r in rows)
    if zg_oi_status == "ACIMA_DO_RANGE":
        regime = "NEGATIVE GAMMA"
    elif zg_oi_status == "ABAIXO_DO_RANGE":
        regime = "POSITIVE GAMMA"
    else:
        regime = "POSITIVE GAMMA" if (zg_oi and spot > zg_oi) or (not zg_oi and total_gex_oi > 0) else "NEGATIVE GAMMA"

    # ── Output ────────────────────────────────────────────────────────────
    W = 62
    print("\n" + "=" * W)
    print(f"  RBC MODO 6 — INTRADAY GAMMA   SPY {spot:.2f}   {datetime.now():%H:%M ET}")
    print("=" * W)
    print(f"\n  {'Strike':>7} | {'GEX (OI)':>14} | {'GEX (Vol hoje)':>14} | {'C-OI':>7} {'P-OI':>7}")
    print("  " + "-" * (W - 4))
    for r in rows:
        mark = " <── spot" if abs(r["strike"] - spot) < 0.5 else ""
        print(f"  {r['strike']:>7.0f} | {r['gex_oi']:>14,.0f} | {r['gex_vol']:>14,.0f} | {r['call_oi']:>7,.0f} {r['put_oi']:>7,.0f}{mark}")

    conf = "OK" if coverage >= 70 else ("PARCIAL" if coverage >= 30 else "NAO CONFIAVEL")
    print(f"\n  COBERTURA DE GREEKS: {strikes_com_gamma}/{len(rows)} strikes ({coverage:.0f}%) — {conf}")
    if coverage < 70:
        print("  >> Niveis abaixo sao PROVISORIOS. Rode com mercado aberto para dados completos.")
    print("\n  NIVEIS — ESTRUTURA (OI, herdada de ontem — swing):")
    print(f"    Call Wall:  {cw_oi:.0f}")
    print(f"    Put Wall:   {pw_oi:.0f}")
    if isinstance(zg_oi, str):
        print(f"    Zero Gamma: {'acima do range — NEGATIVE GAMMA profundo' if zg_oi=='ACIMA_DO_RANGE' else 'abaixo do range — POSITIVE GAMMA profundo'}")
    else:
        print(f"    Zero Gamma: {zg_oi:.1f}" if zg_oi is not None else f"    Zero Gamma: fora do range ({zg_oi_status})")
        print(f"    Vol Trigger: {vt_oi:.1f}" if vt_oi is not None else f"    Vol Trigger: {vt_oi_status}")

    print("\n  NIVEIS — FLUXO (volume de HOJE — intraday/0DTE):")
    print(f"    Call Wall:  {cw_v:.0f}")
    print(f"    Put Wall:   {pw_v:.0f}")
    if isinstance(zg_v, str):
        print(f"    Zero Gamma: {'acima do range — NEGATIVE GAMMA profundo' if zg_v=='ACIMA_DO_RANGE' else 'abaixo do range — POSITIVE GAMMA profundo'}")
    else:
        print(f"    Zero Gamma: {zg_v:.1f}" if zg_v is not None else f"    Zero Gamma: fora do range ({zg_v_status})")
        print(f"    Vol Trigger: {vt_v:.1f}" if vt_v is not None else f"    Vol Trigger: {vt_v_status}")

    print(f"\n  REGIME: {regime} (spot {'acima' if 'POSITIVE' in regime else 'abaixo'} do zero gamma)")
    print("=" * W)

    # ── SNAPSHOT + COMPARACAO COM RUN ANTERIOR ───────────────────────────
    import json, os, glob
    snap_dir = os.path.expanduser("~/RBC/gamma_snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    now_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    today_str = datetime.now().strftime("%Y-%m-%d")

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "spot": round(spot, 2),
        "expiry": target_expiry,
        "oi":  {
            "call_wall": cw_oi,
            "put_wall": pw_oi,
            "zero_gamma": zg_oi,
            "zero_gamma_status": zg_oi_status,
            "vol_trigger": vt_oi,
            "vol_trigger_status": vt_oi_status,
        },
        "vol": {
            "call_wall": cw_v,
            "put_wall": pw_v,
            "zero_gamma": zg_v,
            "zero_gamma_status": zg_v_status,
            "vol_trigger": vt_v,
            "vol_trigger_status": vt_v_status,
        },
        "regime": regime,
        "abs_gamma_oi":  max(rows, key=lambda r: abs(r["gex_oi"]))["strike"] if rows else None,
        "abs_gamma_vol": max(rows, key=lambda r: abs(r["gex_vol"]))["strike"] if rows else None,
    }

    # compara com o snapshot anterior DO MESMO DIA
    _prev_info = {}
    prev_files = sorted(glob.glob(f"{snap_dir}/{today_str}_*.json"))
    if prev_files:
        with open(prev_files[-1]) as f:
            prev = json.load(f)
        prev_time = prev["timestamp"][11:16]
        print(f"\n  MIGRACAO DE PAREDES vs run das {prev_time}:")
        def delta(cur, old, name):
            if cur is None or old is None:
                return f"    {name}: sem dado para comparar"
            d = cur - old
            arrow = "→ subiu" if d > 0 else ("→ desceu" if d < 0 else "= estavel")
            return f"    {name}: {old} → {cur}  {arrow} {abs(d):.1f}pts" if d else f"    {name}: {cur}  = estavel"
        print(delta(snapshot["vol"]["put_wall"],  prev["vol"]["put_wall"],  "Put Wall (fluxo) "))
        print(delta(snapshot["vol"]["call_wall"], prev["vol"]["call_wall"], "Call Wall (fluxo)"))
        print(delta(snapshot["vol"]["zero_gamma"],prev["vol"]["zero_gamma"],"Zero Gamma (fluxo)"))
        _prev_info = {
            "prev_ts":        prev_time,
            "prev_spot":      prev["spot"],
            "prev_put_wall":  prev["vol"]["put_wall"],
            "prev_call_wall": prev["vol"]["call_wall"],
            "prev_zero_gamma":prev["vol"]["zero_gamma"],
            "prev_vol_trigger":prev["vol"].get("vol_trigger"),
        }
        spot_d = snapshot["spot"] - prev["spot"]
        print(f"    SPY: {prev['spot']} → {snapshot['spot']}  ({'+' if spot_d>=0 else ''}{spot_d:.2f})")
        print("\n  Leitura: Put Wall subindo = suporte subindo = vies call.")
        print("           Call Wall descendo = teto caindo = vies put.")
    else:
        print(f"\n  Primeiro run do dia — snapshot salvo. Proximos runs mostram migracao.")

    with open(f"{snap_dir}/{now_str}.json", "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"  Snapshot salvo: gamma_snapshots/{now_str}.json")

    # ── RITUAL: as 3 perguntas (computa ANTES do push, vai no payload) ──
    _ritual = None
    try:
        import json as _j, glob as _g, os as _os
        _flip = vt_v
        _btl = max(rows, key=lambda r: abs(r["gex_vol"]))
        _btl_s, _btl_g = _btl["strike"], _btl["gex_vol"]
        _files = sorted(_g.glob(_os.path.join("gamma_snapshots", "*.json")))
        _mig = "SEM BASE"
        if len(_files) >= 2:
            try:
                _prev_r = _j.load(open(_files[-2]))
                _pw_prev = (_prev_r.get("vol") or {}).get("put_wall")
                if _pw_prev and pw_v:
                    _mig = ("DESCENDO" if pw_v < _pw_prev else
                            "SUBINDO" if pw_v > _pw_prev else "ESTAVEL")
            except Exception:
                pass
        ZONA_VT = 0.30  # pts — dentro da faixa, toque nao e aceitacao: LADO nao vota
        _lado = ("PUT" if _flip and spot < _flip - ZONA_VT else
                 "CALL" if _flip and spot > _flip + ZONA_VT else
                 "NA LINHA" if _flip else "INDEFINIDO")
        _vp = sum([_lado == "PUT",  _btl_g < 0, _mig == "DESCENDO"])
        _vc = sum([_lado == "CALL", _btl_g > 0, _mig == "SUBINDO"])
        if _vp >= 2 and _vp > _vc:
            _verd = f"{_vp}/3 alinhados -> PUT"
        elif _vc >= 2 and _vc > _vp:
            _verd = f"{_vc}/3 alinhados -> CALL"
        else:
            _verd = "dividido -> SEM EDGE, aguardar"
        _os.makedirs("gamma_snapshots", exist_ok=True)
        _vf = _os.path.join("gamma_snapshots", "last_verdict.txt")
        _last = open(_vf).read().strip() if _os.path.exists(_vf) else None
        _mudou = bool(_last and _last != _verd)
        open(_vf, "w").write(_verd)
        _ritual = {
            "lado": _lado,
            "vt_fluxo": _flip,
            "batalha_strike": _btl_s,
            "batalha_gex_m": round(_btl_g / 1e6, 1),
            "batalha_dist": round(abs(spot - _btl_s), 2),
            "migracao": _mig,
            "votos_put": _vp,
            "votos_call": _vc,
            "veredito": _verd,
            "veredito_anterior": _last,
            "veredito_mudou": _mudou,
        }
        print("\n  " + "-"*12 + f" RITUAL {datetime.now():%H:%M} ET " + "-"*12)
        _ld = ('ABAIXO' if _lado=='PUT' else 'ACIMA' if _lado=='CALL' else
               f'NA LINHA (dentro de +-{ZONA_VT})' if _lado=='NA LINHA' else 'sem flip')
        print(f"  1. LADO:     SPY {spot:.2f} {_ld} do VT fluxo {_flip if _flip else '-'} -> {_lado}")
        print(f"  2. BATALHA:  maior |GEX| = {_btl_s:.0f} ({_btl_g/1e6:+.0f}M) a {abs(spot-_btl_s):.1f} pts")
        print(f"  3. MIGRACAO: Put Wall fluxo {_mig}")
        print(f"  VEREDITO: {_verd}")
        if _mudou:
            print(f"  !! VEREDITO MUDOU: '{_last}' -> '{_verd}' — reavaliar posicao!")
    except Exception as _re:
        print(f"  Ritual indisponivel: {_re}")

    # ── PUSH PARA O RAILWAY (grava niveis no journal de hoje) ──────────
    if "--no-push" in sys.argv:
        pass
    elif coverage < 30 and "--force-push" not in sys.argv:
        print("  Push PULADO — cobertura de greeks < 30% (niveis provisorios).")
        print("  Com mercado aberto a cobertura sobe e o push acontece sozinho.")
    else:
        try:
            import urllib.request
            payload = {
                "source": "modo6",
                "date": today_str,
                "spot": snapshot["spot"],
                "call_wall": snapshot["oi"]["call_wall"],
                "put_wall": snapshot["oi"]["put_wall"],
                "zero_gamma": snapshot["oi"]["zero_gamma"],
                "vol_trigger": snapshot["oi"]["vol_trigger"],
                "vol_trigger_status": snapshot["oi"]["vol_trigger_status"],
                "zero_gamma_status": snapshot["oi"]["zero_gamma_status"],
                "gamma_combos": sorted(
                    r["strike"] for r in
                    sorted(rows, key=lambda r: -abs(r["gex_oi"]))[:6]),
                "flow_call_wall":   snapshot["vol"]["call_wall"],
                "flow_put_wall":    snapshot["vol"]["put_wall"],
                "flow_zero_gamma":  snapshot["vol"]["zero_gamma"],
                "flow_vol_trigger": snapshot["vol"]["vol_trigger"],
                **_prev_info,
                "ritual": _ritual,
                "regime": snapshot["regime"],
                "coverage_pct": round(coverage, 0),
                "gex_profile": [
                    {"strike": r["strike"],
                     "gex_oi":  round(r["gex_oi"]  / 1e6, 1),
                     "gex_vol": round(r["gex_vol"] / 1e6, 1)}
                    for r in rows
                    if abs(r["strike"] - snapshot["spot"]) <= 10
                ],
            }
            req = urllib.request.Request(
                "https://web-production-00b33.up.railway.app/api/gamma-levels",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                print(f"  Push para Railway: {resp.status} — niveis no journal de hoje")
        except Exception as e:
            print(f"  Push falhou: {e}")


    print("\n  Interpretacao rapida:")
    print("  - Acima do Zero Gamma: dealers estabilizam (range).")
    print("  - Abaixo do Zero Gamma: dealers amplificam (trend).")
    print("  - Walls por VOLUME mostram onde o mercado de HOJE esta se posicionando.")


if __name__ == "__main__":
    if "--auto" in sys.argv or "--watch" in sys.argv:
        import time
        print("MODO AUTO: roda a cada 5 min durante o pregao (9:30-16:00 ET). Ctrl+C para parar.")
        while True:
            now = datetime.now()
            if now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) <= (16, 0):
                try:
                    main()
                except Exception as e:
                    print(f"Run falhou: {e} — tento de novo em 15 min")
                time.sleep(5 * 60)
            else:
                print(f"{now:%H:%M} — fora do pregao, aguardando...", end="\r")
                time.sleep(60)
    else:
        main()
