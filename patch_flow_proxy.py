"""
RBC EUA — Patch 2 adaptado: Flow Proxy Engine (SPY x VIX intraday)
===================================================================
Proxy honesto do HIRO usando infra existente (webhooks TradingView 1min):

  SPY ↑ + VIX ↓ = CONFIRMING_UP    (fluxo confirmando alta)
  SPY ↑ + VIX ↑ = FRAGILE_UP       (hedge demand subindo — rally desconfiado)
  SPY ↓ + VIX ↑ = CONFIRMING_DOWN  (fluxo defensivo real)
  SPY ↓ + VIX ↓ = SQUEEZE_RISK     (queda sem medo — V-bottom risk)

1. journal.py — tabela quote_history (INSERT, retencao 3 dias) + get
2. app.py    — POST /api/tv/quote tambem grava historico (defensivo);
               analyze_flow_proxy() janela 30min;
               integracao Modo 2: fluxo CONTRADIZENDO a direcao →
               reasons + GOOD→CAUTION (padrao aprovado, nunca bloqueia)
3. index.html — linha no box Linha Operacional, apos Vol Premium

Honestidade: o sistema chama de "Flow Proxy", nunca HIRO.
Confirma fluxo; nao antecipa. Precisa de ~15min de webhooks no dia
para ativar (senao fica invisivel — zero poluicao).

NAO altera: motor, decision, entry/stop/targets, next_setup,
evaluate_hard_blocks, calendar, vol_premium, Modo 3, Journal.

Uso: python3 patch_flow_proxy.py ~/RBC/app.py ~/RBC/templates/index.html ~/RBC/journal.py
"""
import sys, shutil, ast
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# JOURNAL.PY — 1 substituição
# ══════════════════════════════════════════════════════════════════════

J1_OLD = '''def get_calendar_events(from_date=None):
    init_calendar()
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if from_date:
            cur.execute("SELECT * FROM calendar_events WHERE event_date >= %s ORDER BY event_date",
                        (from_date,))
        else:
            cur.execute("SELECT * FROM calendar_events ORDER BY event_date")
        return cur.fetchall()'''

J1_NEW = '''def get_calendar_events(from_date=None):
    init_calendar()
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if from_date:
            cur.execute("SELECT * FROM calendar_events WHERE event_date >= %s ORDER BY event_date",
                        (from_date,))
        else:
            cur.execute("SELECT * FROM calendar_events ORDER BY event_date")
        return cur.fetchall()


# ── Quote History (Flow Proxy — SPY x VIX intraday) ─────────────────

def init_quote_history():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS quote_history (
                id          SERIAL PRIMARY KEY,
                symbol      VARCHAR(10) NOT NULL,
                price       NUMERIC(10,4) NOT NULL,
                received_at TIMESTAMP DEFAULT NOW()
            )""")
        conn.commit()

def save_quote_history(symbol, price, tv_time=None):
    """INSERT no historico intraday + retencao de 3 dias."""
    init_quote_history()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO quote_history (symbol, price) VALUES (%s, %s)",
            (symbol, price))
        cur.execute(
            "DELETE FROM quote_history WHERE received_at < NOW() - INTERVAL '3 days'")
        conn.commit()

def get_quote_history(symbol, minutes=30):
    """Quotes do simbolo na janela, em ordem cronologica."""
    init_quote_history()
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT price, received_at FROM quote_history
               WHERE symbol = %s
                 AND received_at >= NOW() - INTERVAL '1 minute' * %s
               ORDER BY received_at ASC""",
            (symbol, minutes))
        return cur.fetchall()'''

# ══════════════════════════════════════════════════════════════════════
# APP.PY — 4 substituições
# ══════════════════════════════════════════════════════════════════════

# 1. POST /api/tv/quote também grava o histórico (defensivo)
A1_OLD = '''    save_market_quote(symbol, price, tv_time)
    return jsonify({"ok": True, "symbol": symbol, "price": price})'''

A1_NEW = '''    save_market_quote(symbol, price, tv_time)
    try:
        from journal import save_quote_history
        save_quote_history(symbol, price, tv_time)
    except Exception:
        pass  # historico nunca derruba o webhook
    return jsonify({"ok": True, "symbol": symbol, "price": price})'''

# 2. analyze_flow_proxy (módulo-level, antes do vol premium)
A2_OLD = '''def analyze_vol_premium(vix_now, rv_1m, rv_5d, spread=3.5):'''

A2_NEW = '''def analyze_flow_proxy(window_min=30):
    """Flow Proxy — SPY x VIX intraday (curso SpotGamma, Patch 2 adaptado).
    Proxy honesto do HIRO: confirma ou contradiz a direcao pela demanda
    por hedge. NAO antecipa fluxo — confirma."""
    try:
        from journal import get_quote_history
        spy_rows = get_quote_history("SPY", window_min)
        vix_rows = get_quote_history("VIX", window_min)
    except Exception:
        return None
    if len(spy_rows) < 3 or len(vix_rows) < 3:
        return None  # historico insuficiente — fica invisivel

    def _chg_pct(rows):
        first, last = float(rows[0]["price"]), float(rows[-1]["price"])
        if not first:
            return 0.0
        return round((last - first) / first * 100, 3)

    spy_pct = _chg_pct(spy_rows)
    vix_pct = _chg_pct(vix_rows)

    spy_dir = "UP" if spy_pct > 0.10 else ("DOWN" if spy_pct < -0.10 else "FLAT")
    vix_dir = "UP" if vix_pct > 1.5 else ("DOWN" if vix_pct < -1.5 else "FLAT")

    if spy_dir == "UP" and vix_dir == "DOWN":
        state = "CONFIRMING_UP"
        note  = "Flow proxy: SPY sobe com medo caindo — fluxo confirmando alta."
    elif spy_dir == "UP" and vix_dir == "UP":
        state = "FRAGILE_UP"
        note  = ("Flow proxy: SPY sobe com demanda por hedge subindo — "
                 "rally desconfiado, alta fragil.")
    elif spy_dir == "DOWN" and vix_dir == "UP":
        state = "CONFIRMING_DOWN"
        note  = "Flow proxy: queda com VIX subindo — fluxo defensivo real."
    elif spy_dir == "DOWN" and vix_dir == "DOWN":
        state = "SQUEEZE_RISK"
        note  = ("Flow proxy: queda SEM medo (VIX caindo na queda) — "
                 "risco de squeeze/V-bottom. Cuidado com PUT atrasado.")
    else:
        state, note = "NEUTRAL", None

    return {
        "flow_state":  state,
        "note":        note,
        "spy_chg_pct": spy_pct,
        "vix_chg_pct": vix_pct,
        "spy_dir":     spy_dir,
        "vix_dir":     vix_dir,
        "window_min":  window_min,
        "samples":     min(len(spy_rows), len(vix_rows)),
    }


def analyze_vol_premium(vix_now, rv_1m, rv_5d, spread=3.5):'''

# 3. Integração no Modo 2 (após o bloco vol_premium)
A3_OLD = '''    # ── Volatility Premium (VIX vs RV — curso SpotGamma) ──────────────
    vol_premium = analyze_vol_premium(
        vix_now, data.get("rv_1m"), data.get("rv_5d"))
    if vol_premium and vol_premium.get("premium_state") == "EXPENSIVE":
        if vol_premium.get("note"):
            intelligence_block["reasons"].append(vol_premium["note"])
        if intelligence_block.get("entry_quality") == "GOOD":
            intelligence_block["entry_quality"] = "CAUTION"'''

A3_NEW = '''    # ── Volatility Premium (VIX vs RV — curso SpotGamma) ──────────────
    vol_premium = analyze_vol_premium(
        vix_now, data.get("rv_1m"), data.get("rv_5d"))
    if vol_premium and vol_premium.get("premium_state") == "EXPENSIVE":
        if vol_premium.get("note"):
            intelligence_block["reasons"].append(vol_premium["note"])
        if intelligence_block.get("entry_quality") == "GOOD":
            intelligence_block["entry_quality"] = "CAUTION"

    # ── Flow Proxy (SPY x VIX — Patch 2 adaptado) ─────────────────────
    try:
        flow_proxy = analyze_flow_proxy()
    except Exception:
        flow_proxy = None
    if flow_proxy and decision:
        _fs = flow_proxy.get("flow_state")
        _contradicts = (
            ("CALL" in decision and _fs in ("CONFIRMING_DOWN", "FRAGILE_UP")) or
            ("PUT"  in decision and _fs in ("CONFIRMING_UP", "SQUEEZE_RISK")))
        if _contradicts:
            if flow_proxy.get("note"):
                intelligence_block["reasons"].append(flow_proxy["note"])
            if intelligence_block.get("entry_quality") == "GOOD":
                intelligence_block["entry_quality"] = "CAUTION"'''

# 4. Output
A4_OLD = '''        "vol_premium":      vol_premium,'''

A4_NEW = '''        "vol_premium":      vol_premium,
        "flow_proxy":       flow_proxy,'''

# ══════════════════════════════════════════════════════════════════════
# INDEX.HTML — 1 substituição: linha após Vol Premium no box operacional
# ══════════════════════════════════════════════════════════════════════

H1_OLD = '''      ${d.vol_premium ? `<div style="font-size:11px;color:#475569;margin-top:4px;padding-top:4px;border-top:0.5px solid #e0e7ff;">Vol Premium: VIX <b>${d.vol_premium.vix}</b> → RV esperada ~${d.vol_premium.implied_rv}% · RV1M ${d.vol_premium.rv_1m}% <span style="font-weight:600;color:${d.vol_premium.premium_state === 'EXPENSIVE' ? '#dc2626' : d.vol_premium.premium_state === 'CHEAP' ? '#16a34a' : '#64748b'};">${d.vol_premium.premium_state === 'EXPENSIVE' ? 'CARO' : d.vol_premium.premium_state === 'CHEAP' ? 'BARATO' : 'JUSTO'}</span>${(d.vol_premium.rv_5d !== null && d.vol_premium.rv_5d !== undefined) ? ` · RV5D ${d.vol_premium.rv_5d}%${d.vol_premium.rv_trend === 'ACCELERATING' ? ` <span style="color:#d97706;font-weight:600;">acelerando</span>` : d.vol_premium.rv_trend === 'COOLING' ? ' esfriando' : ' estável'}` : ''}</div>` : ''}'''

H1_NEW = '''      ${d.vol_premium ? `<div style="font-size:11px;color:#475569;margin-top:4px;padding-top:4px;border-top:0.5px solid #e0e7ff;">Vol Premium: VIX <b>${d.vol_premium.vix}</b> → RV esperada ~${d.vol_premium.implied_rv}% · RV1M ${d.vol_premium.rv_1m}% <span style="font-weight:600;color:${d.vol_premium.premium_state === 'EXPENSIVE' ? '#dc2626' : d.vol_premium.premium_state === 'CHEAP' ? '#16a34a' : '#64748b'};">${d.vol_premium.premium_state === 'EXPENSIVE' ? 'CARO' : d.vol_premium.premium_state === 'CHEAP' ? 'BARATO' : 'JUSTO'}</span>${(d.vol_premium.rv_5d !== null && d.vol_premium.rv_5d !== undefined) ? ` · RV5D ${d.vol_premium.rv_5d}%${d.vol_premium.rv_trend === 'ACCELERATING' ? ` <span style="color:#d97706;font-weight:600;">acelerando</span>` : d.vol_premium.rv_trend === 'COOLING' ? ' esfriando' : ' estável'}` : ''}</div>` : ''}
      ${d.flow_proxy ? `<div style="font-size:11px;color:#475569;margin-top:4px;padding-top:4px;border-top:0.5px solid #e0e7ff;">Flow Proxy ${d.flow_proxy.window_min}min: SPY ${d.flow_proxy.spy_chg_pct > 0 ? '+' : ''}${d.flow_proxy.spy_chg_pct}% · VIX ${d.flow_proxy.vix_chg_pct > 0 ? '+' : ''}${d.flow_proxy.vix_chg_pct}% → <span style="font-weight:600;color:${d.flow_proxy.flow_state === 'CONFIRMING_UP' ? '#16a34a' : d.flow_proxy.flow_state === 'CONFIRMING_DOWN' ? '#dc2626' : d.flow_proxy.flow_state === 'FRAGILE_UP' ? '#d97706' : d.flow_proxy.flow_state === 'SQUEEZE_RISK' ? '#7c3aed' : '#64748b'};">${d.flow_proxy.flow_state === 'CONFIRMING_UP' ? 'CONFIRMANDO ALTA' : d.flow_proxy.flow_state === 'CONFIRMING_DOWN' ? 'CONFIRMANDO QUEDA' : d.flow_proxy.flow_state === 'FRAGILE_UP' ? 'ALTA FRÁGIL' : d.flow_proxy.flow_state === 'SQUEEZE_RISK' ? 'RISCO DE SQUEEZE' : 'NEUTRO'}</span></div>` : ''}'''

# ══════════════════════════════════════════════════════════════════════
# Aplicar
# ══════════════════════════════════════════════════════════════════════

if len(sys.argv) < 4:
    print("Uso: python3 patch_flow_proxy.py ~/RBC/app.py ~/RBC/templates/index.html ~/RBC/journal.py")
    sys.exit(1)

app_path, html_path, journal_path = sys.argv[1], sys.argv[2], sys.argv[3]
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

groups = [
    (journal_path, [(J1_OLD, J1_NEW, "journal: quote_history + helpers")]),
    (app_path,     [(A1_OLD, A1_NEW, "app: webhook grava historico"),
                    (A2_OLD, A2_NEW, "app: funcao analyze_flow_proxy"),
                    (A3_OLD, A3_NEW, "app: integracao Modo 2 (contradicao → CAUTION)"),
                    (A4_OLD, A4_NEW, "app: flow_proxy no output")]),
    (html_path,    [(H1_OLD, H1_NEW, "html: linha Flow Proxy no card Regime")]),
]

contents = {}
for path, patches in groups:
    c = open(path).read()
    for old, _, label in patches:
        n = c.count(old)
        if n != 1:
            print(f"ERRO — '{label}': ancora encontrada {n}x em {path}")
            sys.exit(1)
    contents[path] = c

for path, _ in groups:
    ext = path.rsplit(".", 1)[1]
    shutil.copy2(path, path.replace(f".{ext}", f"_backup_{ts}.{ext}"))
print(f"Backups criados ({ts})")

for path, patches in groups:
    c = contents[path]
    for old, new, label in patches:
        c = c.replace(old, new, 1)
        print(f"✅ {label}")
    if path.endswith(".py"):
        ast.parse(c)
    open(path, 'w').write(c)

print()
print("Apos o deploy: o historico comeca a acumular com os webhooks.")
print("Amanha, apos ~15 min de pregao, o Flow Proxy aparece no Modo 2.")
print()
print("Proximo passo:")
print("  git add app.py templates/index.html journal.py")
print('  git commit -m "APROVADO: Flow Proxy Engine — SPY x VIX intraday (Patch 2 adaptado)"')
print("  git push")
