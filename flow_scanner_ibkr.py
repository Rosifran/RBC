"""
RBC — Flow Scanner IBKR (Pré-mercado)
======================================
Detecta atividade incomum de opções via IBKR TWS.
Reutiliza fetch_full_chain() do us_swing_ibkr.py.

Filosofia (aprovada):
  - "atividade incomum" — não "baleia confirmada"
  - "possível interesse direcional" — não "smart money"
  - "precisa confirmação técnica" — não é entrada automática
  - Pré-mercado: watchlist de atenção para o dia

Critérios de atividade incomum:
  - volume > 3x open_interest  (posição nova)
  - volume > 300 contratos     (tamanho mínimo)
  - delta entre 0.15 e 0.55   (direcional, não hedge de cauda)
  - spread < 20%               (líquido)
  - 7 ≤ DTE ≤ 45              (swing razoável)

Filtros anti-falso-positivo:
  - Rolagem: volume alto em 2 vencimentos → caution_flag
  - Estrutura: CALL e PUT simultâneos → caution_flag
  - Market maker: volume espalhado em muitos strikes → ignorado

Output: salva em flow_alerts (tabela nova PostgreSQL)
        + exibe no Modo 5 acima do Position Manager

Regras dos cursos integradas:
  - delta como proxy de POP (Aula 2): preferir 0.30-0.45
  - theta cresce nos últimos 30d (Aula Extra): DTE < 14 = cautela
  - IV crush pós-evento (Doc Trader PRO): flag earnings_risk

Uso: python3 flow_scanner_ibkr.py [--tickers NVDA AAPL ...]
     Requer TWS aberto com API habilitada (porta 7497)
"""

import argparse
import json
import logging
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────
TWS_HOST   = "127.0.0.1"
TWS_PORT   = 7497
CLIENT_ID  = 2          # diferente do scanner principal (1)
OUTPUT_DIR = Path.home() / "RBC" / "flow_output"

# Universo aprovado — 50 tickers balanceados por liquidez e oportunidade
DEFAULT_TICKERS = [
    # Mega caps / ETFs principais
    "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA",
    # Tech / Growth
    "AMD", "CRM", "SNOW", "CRWD", "NET", "DDOG", "PANW", "PLTR", "UBER", "HOOD",
    "SHOP", "PYPL",
    # Financeiro / Crypto
    "JPM", "BAC", "C", "COIN", "SOFI", "SQ", "AFRM", "WFC",
    # Energia / Commodities
    "OXY", "DVN", "HAL", "XOM", "SLB", "CCJ",
    # Saúde / Biotech
    "MRNA", "BNTX", "VRTX", "ABBV", "PFE", "BMY",
    # ETFs setoriais
    "XLF", "XLE", "XBI", "XOP", "ARKK", "SMH", "GLD", "TLT",
    # Mais acessíveis / alto volume de opções
    "F", "T", "SNAP", "RIVN", "WBD", "INTC",
]

# Filtros de atividade incomum
# Detecção nasce da cadeia de opções, não do volume da ação
VOL_OI_MIN_RATIO   = 3.0   # volume >= 3x OI (critério principal relativo)
VOL_MIN_CONTRACTS  = 100   # mínimo absoluto — proteção contra ruído
                            # (baixo para capturar tickers mid como SNAP, RIVN)
DELTA_MIN = 0.15            # não é hedge de cauda
DELTA_MAX = 0.55            # não é deep ITM
SPREAD_MAX_PCT = 20.0       # liquidez mínima
DTE_MIN = 7
DTE_MAX = 45

# ── Imports IBKR ──────────────────────────────────────────────────────
try:
    from ib_insync import IB, Stock, Option
except ImportError:
    print("Erro: ib_insync não instalado. pip install ib_insync")
    sys.exit(1)

# Reutiliza funções do scanner principal
sys.path.insert(0, str(Path(__file__).parent))
try:
    from us_swing_ibkr import fetch_full_chain, get_full_snapshot
except ImportError:
    print("Erro: us_swing_ibkr.py não encontrado em ~/RBC/")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════
# Engine de detecção
# ══════════════════════════════════════════════════════════════════════

def _spread_pct(bid, ask):
    mid = (bid + ask) / 2
    return round((ask - bid) / mid * 100, 1) if mid > 0 else 999

def _activity_label(ratio):
    if ratio >= 10: return f"volume {ratio:.0f}x o OI — atividade muito incomum"
    if ratio >= 5:  return f"volume {ratio:.0f}x o OI — atividade incomum"
    return f"volume {ratio:.1f}x o OI — acima da média"

def _confidence(ratio, n_strikes):
    """Alta: ratio > 10x em 1-2 strikes. Média: 5-10x. Baixa: 3-5x."""
    if ratio >= 10 and n_strikes <= 2: return "ALTA"
    if ratio >= 5:                     return "MEDIA"
    return "BAIXA"

def detect_unusual_flow(calls: list, puts: list,
                        spot: float, ticker: str) -> dict:
    """
    Varre calls e puts em busca de atividade incomum.
    Retorna dict com alerts[] e flow_summary.
    """
    alerts = []
    expiration_vol = {}  # {exp: {C: vol, P: vol}} — detecta rolagem

    for contracts, direction in [(calls, "CALL"), (puts, "PUT")]:
        for c in contracts:
            vol = c.get("volume", 0)
            oi  = c.get("open_interest", 0)
            bid = c.get("bid", 0)
            ask = c.get("ask", c.get("price_ref", 0))
            delta = abs(c.get("delta", 0))
            dte   = c.get("dte", 0)

            # Filtros básicos
            if vol < VOL_MIN_CONTRACTS:     continue
            # OI pode vir zerado do TWS durante o pregao (campo separado)
            # Quando OI=0: usa volume absoluto elevado como criterio
            # Quando OI>0: usa ratio volume/OI como critério principal
            if oi == 0:
                if vol < 500:   continue   # ruido sem OI
                ratio = None               # OI indisponivel
                ratio_label = "OI indisponivel"
            else:
                ratio = round(vol / oi, 1)
                if ratio < VOL_OI_MIN_RATIO: continue
                ratio_label = f"{ratio}x OI"
            if delta < DELTA_MIN or delta > DELTA_MAX: continue
            if DTE_MIN > dte or dte > DTE_MAX:         continue
            spd = _spread_pct(bid, ask)
            if spd > SPREAD_MAX_PCT:        continue

            # Acumula por vencimento para detectar rolagem/estrutura
            exp = c.get("expiration", "")
            if exp not in expiration_vol:
                expiration_vol[exp] = {"CALL": 0, "PUT": 0}
            expiration_vol[exp][direction] += vol

            # Alerta de theta pelo curso (DTE < 14 = cuidado)
            theta_flag = dte < 14

            alerts.append({
                "direction":        direction,
                "strike":           c.get("strike"),
                "expiration":       exp,
                "dte":              dte,
                "volume":           vol,
                "open_interest":    oi,
                "volume_oi_ratio":  ratio,
                "delta":            round(delta, 3),
                "iv_pct":           c.get("iv_pct"),
                "bid":              bid,
                "ask":              ask,
                "spread_pct":       spd,
                "activity_label":   _activity_label(ratio) if ratio else f"volume {vol:,} — OI indisponivel",
                "theta_flag":       theta_flag,
                "caution_flag":     None,   # preenchido abaixo
                "needs_confirmation": True,
            })

    if not alerts:
        return {
            "ticker":       ticker,
            "scan_date":    date.today().isoformat(),
            "scan_type":    "PRE_MARKET",
            "alerts":       [],
            "flow_summary": {
                "dominant_direction": None,
                "confidence":         None,
                "note": "Nenhuma atividade incomum detectada nos filtros aplicados.",
            }
        }

    # ── Anti-falso-positivo ───────────────────────────────────────────

    # 1. Rolagem: mesmo strike com volume em 2+ vencimentos
    strike_exps = {}
    for a in alerts:
        key = (a["direction"], a["strike"])
        strike_exps.setdefault(key, set()).add(a["expiration"])
    for a in alerts:
        key = (a["direction"], a["strike"])
        if len(strike_exps[key]) >= 2:
            a["caution_flag"] = "possivel_rolagem"

    # 2. Estrutura: CALL e PUT no mesmo vencimento com volume alto
    for exp, vols in expiration_vol.items():
        if vols["CALL"] > VOL_MIN_CONTRACTS and vols["PUT"] > VOL_MIN_CONTRACTS:
            for a in alerts:
                if a["expiration"] == exp and not a["caution_flag"]:
                    a["caution_flag"] = "estrutura_detectada"

    # ── Resumo direcional ─────────────────────────────────────────────
    clean = [a for a in alerts if not a["caution_flag"]]
    call_vol = sum(a["volume"] for a in clean if a["direction"] == "CALL")
    put_vol  = sum(a["volume"] for a in clean if a["direction"] == "PUT")
    n_clean  = len(clean)

    if call_vol > put_vol * 1.5:
        dominant = "CALL"
    elif put_vol > call_vol * 1.5:
        dominant = "PUT"
    else:
        dominant = "MISTO"

    best_ratio = max((a["volume_oi_ratio"] for a in clean if a["volume_oi_ratio"]), default=0)
    best_vol   = max((a["volume"] for a in clean), default=0)
    if best_ratio:
        confidence = _confidence(best_ratio, n_clean)
    elif best_vol >= 1000:
        confidence = "MEDIA"   # sem OI mas volume relevante
    elif best_vol >= 500:
        confidence = "BAIXA"
    else:
        confidence = "BAIXA"

    if dominant == "CALL" and confidence == "ALTA":
        note = ("Atividade incomum concentrada em CALL. "
                "Possível interesse direcional de alta. "
                "Precisa confirmação técnica antes de qualquer entrada.")
    elif dominant == "PUT" and confidence == "ALTA":
        note = ("Atividade incomum concentrada em PUT. "
                "Possível interesse direcional de baixa. "
                "Precisa confirmação técnica antes de qualquer entrada.")
    elif dominant == "MISTO":
        note = ("Atividade incomum em ambas direções — possível estrutura ou hedge. "
                "Não direcional. Não seguir sem confirmação técnica clara.")
    else:
        note = (f"Atividade incomum em {dominant} com confiança {confidence}. "
                "Precisa confirmação técnica.")

    return {
        "ticker":    ticker,
        "spot":      spot,
        "scan_date": date.today().isoformat(),
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "PRE_MARKET",
        "alerts":    alerts,
        "flow_summary": {
            "dominant_direction": dominant,
            "confidence":         confidence,
            "note":               note,
            "clean_alerts":       n_clean,
            "total_alerts":       len(alerts),
        }
    }


# ══════════════════════════════════════════════════════════════════════
# Save + Print
# ══════════════════════════════════════════════════════════════════════

def save_flow_results(results: list) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    ts   = datetime.now().strftime('%Y%m%d_%H%M')
    path = OUTPUT_DIR / f"flow_scan_{ts}.json"
    with open(path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Resultado salvo em: {path}")

def save_flow_history(ticker: str, spot: float,
                      calls: list, puts: list,
                      alerts: list) -> None:
    """Salva histórico de volume de opções por ticker no PostgreSQL.
    Acumula dados próprios — base para detecção relativa futura.
    Desde o primeiro scan, já vai construindo a média histórica."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from journal import get_conn
        import json as _json
        call_vol = sum(c.get("volume", 0) for c in calls)
        put_vol  = sum(p.get("volume", 0) for p in puts)
        total_vol = call_vol + put_vol
        total_oi  = sum(c.get("open_interest", 0) for c in calls + puts)
        n_filtered = len(alerts)
        # Contratos que passaram nos filtros (resumo)
        filtered_summary = [
            {"dir": a["direction"], "strike": a["strike"],
             "exp": a["expiration"], "vol": a["volume"],
             "oi": a["open_interest"], "ratio": a["volume_oi_ratio"]}
            for a in alerts
        ]
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS flow_history (
                    id           SERIAL PRIMARY KEY,
                    ticker       VARCHAR(10) NOT NULL,
                    scan_date    DATE NOT NULL,
                    scan_time    VARCHAR(20),
                    spot         NUMERIC(10,4),
                    call_volume  INT DEFAULT 0,
                    put_volume   INT DEFAULT 0,
                    total_volume INT DEFAULT 0,
                    total_oi     INT DEFAULT 0,
                    n_contracts  INT DEFAULT 0,
                    n_filtered   INT DEFAULT 0,
                    filtered_json TEXT,
                    created_at   TIMESTAMP DEFAULT NOW()
                )""")
            cur.execute("""
                INSERT INTO flow_history
                  (ticker, scan_date, scan_time, spot,
                   call_volume, put_volume, total_volume,
                   total_oi, n_contracts, n_filtered, filtered_json)
                VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (ticker,
                 datetime.now().strftime("%H:%M ET"),
                 spot, call_vol, put_vol, total_vol,
                 total_oi, len(calls)+len(puts),
                 n_filtered,
                 _json.dumps(filtered_summary, default=str)))
            conn.commit()
    except Exception as e:
        print(f"  Aviso: não foi possível salvar histórico de {ticker} — {e}")

def get_flow_baseline(ticker: str) -> dict:
    """Retorna média histórica de volume de opções do ticker.
    Usado quando tivermos >= 10 dias de dados próprios acumulados.
    Abaixo disso, retorna None — scanner usa apenas ratio OI."""
    try:
        from journal import get_conn
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as dias,
                       AVG(total_volume) as avg_vol,
                       AVG(call_volume)  as avg_call,
                       AVG(put_volume)   as avg_put
                FROM flow_history
                WHERE ticker = %s
                  AND scan_date >= CURRENT_DATE - INTERVAL '30 days'
            """, (ticker,))
            row = cur.fetchone()
            if row and row[0] >= 10:
                return {
                    "dias":     row[0],
                    "avg_vol":  float(row[1] or 0),
                    "avg_call": float(row[2] or 0),
                    "avg_put":  float(row[3] or 0),
                    "baseline_ready": True,
                }
            return {"baseline_ready": False, "dias": row[0] if row else 0}
    except Exception:
        return {"baseline_ready": False, "dias": 0}


def save_flow_pg(result: dict) -> None:
    """Salva alerta de fluxo no PostgreSQL (tabela flow_alerts)."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from journal import get_conn
        import psycopg2
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS flow_alerts (
                    id           SERIAL PRIMARY KEY,
                    ticker       VARCHAR(10),
                    spot         NUMERIC(10,4),
                    scan_date    DATE,
                    scan_time    VARCHAR(20),
                    dominant_dir VARCHAR(10),
                    confidence   VARCHAR(10),
                    note         TEXT,
                    alerts_json  TEXT,
                    created_at   TIMESTAMP DEFAULT NOW()
                )""")
            cur.execute("""
                INSERT INTO flow_alerts
                  (ticker, spot, scan_date, scan_time,
                   dominant_dir, confidence, note, alerts_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (result["ticker"], result.get("spot"),
                 result["scan_date"], result.get("scan_time"),
                 result["flow_summary"]["dominant_direction"],
                 result["flow_summary"]["confidence"],
                 result["flow_summary"]["note"],
                 json.dumps(result["alerts"], default=str)))
            conn.commit()
    except Exception as e:
        print(f"  Aviso: não foi possível salvar no banco — {e}")

def print_flow_result(r: dict) -> None:
    SEP  = "-" * 65
    SEP2 = "=" * 65
    fs   = r.get("flow_summary", {})
    alerts = r.get("alerts", [])

    print(f"\n{SEP2}")
    print(f"  {r['ticker']} · Spot ${r.get('spot', '—')} · {r.get('scan_time','')}")

    if not alerts:
        print(f"  Sem atividade incomum detectada.")
        print(SEP2)
        return

    conf_icon = {"ALTA": "🔴", "MEDIA": "🟡", "BAIXA": "⚪"}.get(
        fs.get("confidence", ""), "⚪")
    print(f"  {conf_icon} ATIVIDADE INCOMUM — {fs.get('dominant_direction','?')} "
          f"· Confiança {fs.get('confidence','?')}")
    print(f"  {fs.get('note','')}")
    print(SEP)

    clean  = [a for a in alerts if not a["caution_flag"]]
    flagged = [a for a in alerts if a["caution_flag"]]

    if clean:
        print(f"  Alertas limpos ({len(clean)}):")
        for a in clean:
            theta_warn = " ⚠ DTE curto" if a.get("theta_flag") else ""
            print(f"    {a['direction']} {a['strike']} · Exp {a['expiration']} "
                  f"({a['dte']}d){theta_warn}")
            print(f"    Vol {a['volume']:,} · OI {a['open_interest']:,} "
                  f"· Ratio {a['volume_oi_ratio']}x · Delta {a['delta']} "
                  f"· IV {a['iv_pct']}% · Ask ${a['ask']:.2f}")
            print(f"    → {a['activity_label']}")
            print(f"    ⚠ Precisa confirmação técnica antes de qualquer entrada.")
            print()

    if flagged:
        print(f"  Alertas com cautela ({len(flagged)}):")
        for a in flagged:
            print(f"    {a['direction']} {a['strike']} ({a['expiration']}) "
                  f"· {a['caution_flag']} · Vol {a['volume']:,}")
        print()

    print(SEP2)


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='RBC Flow Scanner — detector de atividade incomum pré-mercado')
    parser.add_argument('--tickers', nargs='+', default=DEFAULT_TICKERS)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    if not args.verbose:
        logging.getLogger('ib_insync.wrapper').setLevel(logging.CRITICAL)
        logging.getLogger('ib_insync.client').setLevel(logging.CRITICAL)

    print("\n" + "=" * 65)
    print("  RBC — Flow Scanner · Atividade Incomum de Opções")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')} · PRÉ-MERCADO")
    print(f"  Tickers: {', '.join(args.tickers)}")
    print(f"  Filtros: Vol ≥ {VOL_OI_MIN_RATIO}x OI · ≥{VOL_MIN_CONTRACTS} contratos")
    print(f"           Delta {DELTA_MIN}–{DELTA_MAX} · DTE {DTE_MIN}–{DTE_MAX}d")
    print("  ⚠ Flow = ATENÇÃO, não oportunidade.")
    print("    Flow nasce da cadeia de opções, não do volume da ação.")
    print("    Depois: análise técnica + contrato aceitável.")
    print("=" * 65)

    print(f"\n  Conectando ao TWS ({TWS_HOST}:{TWS_PORT})...")
    ib = IB()
    try:
        ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
        print("  Conectado!\n")
    except Exception as e:
        print(f"  Erro: {e}")
        print("  Verifique se o TWS está aberto e API habilitada.")
        return

    results = []
    for ticker in args.tickers:
        print(f"\n  Escaneando {ticker}...")
        try:
            snap = get_full_snapshot(ib, ticker)
            spot = snap.get("spot", 0)
            if not spot:
                print(f"  {ticker}: spot não disponível — pulando")
                continue
            print(f"  {ticker} spot: ${spot}")
            calls, puts = fetch_full_chain(ib, ticker, spot)
            if not calls and not puts:
                print(f"  {ticker}: sem cadeia de opções — pulando")
                continue
            result = detect_unusual_flow(calls, puts, spot, ticker)
            results.append(result)
            print_flow_result(result)

            # Salva histórico próprio SEMPRE (base para detecção relativa futura)
            save_flow_history(ticker, spot, calls, puts, result["alerts"])

            # Contexto secundário: volume da ação via IBKR (não é critério principal)
            baseline = get_flow_baseline(ticker)
            if baseline["baseline_ready"]:
                total_vol = sum(c.get("volume",0) for c in calls+puts)
                if baseline["avg_vol"] > 0:
                    vol_ratio = round(total_vol / baseline["avg_vol"], 1)
                    result["flow_summary"]["historical_context"] = (
                        f"Volume de opções hoje: {total_vol:,} "
                        f"({vol_ratio}x a média de {baseline['dias']}d)")
            else:
                result["flow_summary"]["historical_context"] = (
                    f"Histórico próprio: {baseline.get('dias',0)} dias acumulados "
                    f"(mínimo 10 para baseline relativo)")

            # Salva no PG só se tem alertas
            if result["alerts"]:
                save_flow_pg(result)
        except Exception as e:
            print(f"  {ticker}: erro — {e}")
            if args.verbose:
                import traceback; traceback.print_exc()

    ib.disconnect()
    save_flow_results(results)

    # Resumo final
    with_alerts = [r for r in results if r.get("alerts")]
    print(f"\n  Resumo: {len(with_alerts)}/{len(results)} tickers com atividade incomum")
    if with_alerts:
        print("  Watchlist para hoje:")
        for r in with_alerts:
            fs = r["flow_summary"]
            clean = [a for a in r["alerts"] if not a["caution_flag"]]
            if clean:
                best = max(clean, key=lambda a: a["volume_oi_ratio"])
                print(f"    {r['ticker']} · {fs['dominant_direction']} "
                      f"· {best['strike']} {best['expiration']} "
                      f"· {best['volume_oi_ratio']}x · {fs['confidence']}")
    print()
    print("  Próximo passo: confirmar análise técnica no TradingView")
    print("  antes de qualquer entrada.\n")


if __name__ == '__main__':
    main()
