"""
RBC — Patch 1: market_quotes no PostgreSQL
- journal.py: tabela market_quotes + save_market_quote + get_market_quotes
- app.py: POST /api/tv/quote salva no PG, GET /api/tv/quote lê do PG
Não toca em trade_journal, motor, Modo 1, 2, 3.
Uso: python3 patch_market_quotes_pg.py ~/RBC/journal.py ~/RBC/app.py
"""
import sys, shutil, ast
from datetime import datetime

# ════════════════════════════════════════════════════════════════════
# PATCH journal.py — adiciona tabela + funções após get_snapshot_by_date
# ════════════════════════════════════════════════════════════════════

JOURNAL_ANCHOR = '''# ── Swing Scans (Modo 5) ──────────────────────────────────────────────'''

JOURNAL_NEW = '''# ── Market Quotes (TradingView intraday) ─────────────────────────────

CREATE_MARKET_QUOTES = """
CREATE TABLE IF NOT EXISTS market_quotes (
    symbol      VARCHAR(10) PRIMARY KEY,
    price       NUMERIC(10,4),
    tv_time     TIMESTAMP,
    received_at TIMESTAMP DEFAULT NOW()
);
"""

def init_market_quotes():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_MARKET_QUOTES)
        conn.commit()

def save_market_quote(symbol, price, tv_time=None):
    """Salva ou atualiza quote de SPY ou VIX."""
    init_market_quotes()
    sql = """
        INSERT INTO market_quotes (symbol, price, tv_time, received_at)
        VALUES (%(symbol)s, %(price)s, %(tv_time)s, NOW())
        ON CONFLICT (symbol) DO UPDATE SET
            price       = EXCLUDED.price,
            tv_time     = EXCLUDED.tv_time,
            received_at = NOW();
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"symbol": symbol, "price": price, "tv_time": tv_time})
        conn.commit()

def get_market_quotes():
    """Retorna SPY e VIX do banco. Retorna {} se tabela vazia."""
    try:
        init_market_quotes()
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT symbol, price, tv_time, received_at FROM market_quotes")
                rows = cur.fetchall()
        return {r["symbol"]: dict(r) for r in rows}
    except Exception:
        return {}


# ── Swing Scans (Modo 5) ──────────────────────────────────────────────'''

# ════════════════════════════════════════════════════════════════════
# PATCH app.py — substitui rotas /api/tv/quote (memória → PostgreSQL)
# ════════════════════════════════════════════════════════════════════

APP_OLD = '''# ── TradingView market quote (SPY + VIX) ─────────────────────────────
_tv_quote = {}  # {"spy": float, "vix": float, "ts": str}

@app.route("/api/tv/quote", methods=["POST"])
def tv_quote_post():
    """
    Recebe quote de mercado do TradingView.
    Payload esperado: {"symbol": "SPY"|"VIX", "price": 756.10, "time": "2026-06-08T10:05:00"}
    """
    data   = request.get_json(silent=True) or {}
    symbol = str(data.get("symbol", "")).upper().replace("$", "")
    price  = data.get("price")
    ts     = data.get("time") or datetime.utcnow().isoformat()

    if not symbol or price is None:
        return jsonify({"error": "symbol and price required"}), 400

    try:
        price = float(price)
    except (ValueError, TypeError):
        return jsonify({"error": "price must be numeric"}), 400

    if symbol in ("SPY", "SPDR"):
        _tv_quote["spy"] = price
    elif symbol in ("VIX", "CBOE:VIX", "VIX1D"):
        _tv_quote["vix"] = price
    else:
        return jsonify({"error": f"unknown symbol: {symbol}"}), 400

    _tv_quote["ts"] = ts
    return jsonify({"ok": True, "symbol": symbol, "price": price, "ts": ts})


@app.route("/api/tv/quote", methods=["GET"])
def tv_quote_get():
    """Retorna o último quote recebido do TradingView."""
    if not _tv_quote:
        return jsonify({"ok": False, "message": "Sem dados recentes — preencher manualmente."}), 200
    age_ok = True
    if _tv_quote.get("ts"):
        try:
            from datetime import timezone
            ts = datetime.fromisoformat(_tv_quote["ts"].replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            age_ok = age_min < 30  # considera stale após 30 min
        except Exception:
            pass
    return jsonify({
        "ok":     True,
        "spy":    _tv_quote.get("spy"),
        "vix":    _tv_quote.get("vix"),
        "ts":     _tv_quote.get("ts"),
        "fresh":  age_ok,
        "message": None if age_ok else "Dado com mais de 30 min — confirmar manualmente.",
    })'''

APP_NEW = '''# ── TradingView market quote (SPY + VIX) → PostgreSQL ────────────────

@app.route("/api/tv/quote", methods=["POST"])
def tv_quote_post():
    """
    Recebe quote de mercado do TradingView e salva no PostgreSQL.
    Payload: {"symbol": "SPY"|"VIX", "price": 756.10, "time": "2026-06-08T10:05:00"}
    """
    from journal import save_market_quote
    data   = request.get_json(silent=True) or {}
    symbol = str(data.get("symbol", "")).upper().replace("$", "").replace("CBOE:", "")
    price  = data.get("price")
    tv_ts  = data.get("time")

    if not symbol or price is None:
        return jsonify({"error": "symbol and price required"}), 400

    try:
        price = float(price)
    except (ValueError, TypeError):
        return jsonify({"error": "price must be numeric"}), 400

    # Normaliza símbolo
    if symbol in ("SPDR", "SPY500"):
        symbol = "SPY"
    elif symbol in ("VIX1D", "VIX"):
        symbol = "VIX"

    if symbol not in ("SPY", "VIX"):
        return jsonify({"error": f"unknown symbol: {symbol}"}), 400

    # Converte tv_ts para datetime
    tv_time = None
    if tv_ts:
        try:
            # TradingView pode mandar Unix ms ou ISO string
            if str(tv_ts).isdigit():
                ts_int = int(tv_ts)
                # se for segundos (< 1e12) converte; se for ms divide
                if ts_int > 1e12:
                    ts_int = ts_int // 1000
                from datetime import timezone
                tv_time = datetime.fromtimestamp(ts_int, tz=timezone.utc)
            else:
                tv_time = datetime.fromisoformat(str(tv_ts).replace("Z", "+00:00"))
        except Exception:
            tv_time = None

    save_market_quote(symbol, price, tv_time)
    return jsonify({"ok": True, "symbol": symbol, "price": price})


@app.route("/api/tv/quote", methods=["GET"])
def tv_quote_get():
    """Retorna último quote do PostgreSQL com flag fresh (<30 min)."""
    from journal import get_market_quotes
    from datetime import timezone

    quotes = get_market_quotes()
    if not quotes:
        return jsonify({"ok": False, "message": "Sem dados recentes — preencher manualmente."})

    spy_row = quotes.get("SPY") or {}
    vix_row = quotes.get("VIX") or {}

    spy   = float(spy_row.get("price") or 0) or None
    vix   = float(vix_row.get("price") or 0) or None

    # fresh = received_at de SPY menos de 30 min atrás
    fresh = False
    ts_str = None
    if spy_row.get("received_at"):
        try:
            rec = spy_row["received_at"]
            if hasattr(rec, "tzinfo") and rec.tzinfo is None:
                rec = rec.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - rec).total_seconds() / 60
            fresh   = age_min < 30
            ts_str  = rec.strftime("%H:%M ET")
        except Exception:
            pass

    return jsonify({
        "ok":     bool(spy and vix),
        "spy":    spy,
        "vix":    vix,
        "ts":     ts_str,
        "fresh":  fresh,
        "message": None if fresh else "Dado com mais de 30 min — confirmar manualmente.",
    })'''

# ════════════════════════════════════════════════════════════════════
# Aplicar patches
# ════════════════════════════════════════════════════════════════════

if len(sys.argv) < 3:
    print("Uso: python3 patch_market_quotes_pg.py ~/RBC/journal.py ~/RBC/app.py")
    sys.exit(1)

journal_path = sys.argv[1]
app_path     = sys.argv[2]
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

# --- journal.py ---
jcontent = open(journal_path).read()
if JOURNAL_ANCHOR not in jcontent:
    print("ERRO — âncora journal.py não encontrada.")
    sys.exit(1)
if "market_quotes" in jcontent:
    print("AVISO — market_quotes já existe em journal.py. Pulando.")
else:
    shutil.copy2(journal_path, journal_path.replace(".py", f"_backup_{ts}.py"))
    jcontent = jcontent.replace(JOURNAL_ANCHOR, JOURNAL_NEW, 1)
    ast.parse(jcontent)
    open(journal_path, 'w').write(jcontent)
    print("✅ journal.py — tabela market_quotes + save/get funções")

# --- app.py ---
acontent = open(app_path).read()
if APP_OLD not in acontent:
    print("ERRO — bloco antigo /api/tv/quote não encontrado em app.py.")
    sys.exit(1)
shutil.copy2(app_path, app_path.replace(".py", f"_backup_{ts}.py"))
acontent = acontent.replace(APP_OLD, APP_NEW, 1)
ast.parse(acontent)
open(app_path, 'w').write(acontent)
print("✅ app.py — /api/tv/quote lê/escreve no PostgreSQL")
print()
print("Próximo passo:")
print("  git add journal.py app.py")
print('  git commit -m "APROVADO: market_quotes PostgreSQL — TradingView → PG → Modo 2"')
print("  git push")
