import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import date

DATABASE_URL = os.environ.get("DATABASE_URL")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS trade_journal (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMP DEFAULT NOW(),
    date            DATE NOT NULL UNIQUE,
    weekday         VARCHAR(10),
    pdf_score       INTEGER,
    call_wall       NUMERIC(8,2),
    put_wall        NUMERIC(8,2),
    vol_trigger     NUMERIC(8,2),
    zero_gamma      NUMERIC(8,2),
    c3              NUMERIC(8,2),
    c4              NUMERIC(8,2),
    c1              NUMERIC(8,2),
    open_spy        NUMERIC(8,2),
    vix_open        NUMERIC(6,2),
    spy_10am        NUMERIC(8,2),
    spy_1030        NUMERIC(8,2),
    spy_12pm        NUMERIC(8,2),
    close_spy       NUMERIC(8,2),
    modo2_decision  VARCHAR(50),
    entry_level     NUMERIC(8,2),
    target_1        NUMERIC(8,2),
    target_2        NUMERIC(8,2),
    stop_level      NUMERIC(8,2),
    hit_target_1    BOOLEAN,
    hit_target_2    BOOLEAN,
    hit_stop        BOOLEAN,
    max_favorable_move  NUMERIC(6,2),
    max_adverse_move    NUMERIC(6,2),
    best_trade_window   VARCHAR(20),
    notes               TEXT,
    c4_reclaimed        BOOLEAN,
    c4_reclaimed_time   VARCHAR(10),
    c1_hit              BOOLEAN,
    c1_hit_time         VARCHAR(10),
    call_wall_hit       BOOLEAN,
    call_wall_hit_time  VARCHAR(10),
    near_call_wall      BOOLEAN,
    max_spy             NUMERIC(8,2),
    min_spy             NUMERIC(8,2),
    trade_path          VARCHAR(100),
    trade_quality       VARCHAR(50),
    vol_trigger_lost      BOOLEAN,
    vol_trigger_lost_time VARCHAR(10),
    pm_note_summary       TEXT,
    pm_hiro               VARCHAR(50),
    pm_vix_close          NUMERIC(6,2),
    pm_cor1m_close        NUMERIC(6,2),
    pm_market_comment     TEXT,
    pm_flow_comment       TEXT,
    pm_vol_comment        TEXT,
    next_events           TEXT,
    pm_levels_raw         TEXT
);
"""

def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE)
            new_cols = [
                ("c4_reclaimed",          "BOOLEAN"),
                ("c4_reclaimed_time",     "VARCHAR(10)"),
                ("c1_hit",                "BOOLEAN"),
                ("c1_hit_time",           "VARCHAR(10)"),
                ("call_wall_hit",         "BOOLEAN"),
                ("call_wall_hit_time",    "VARCHAR(10)"),
                ("near_call_wall",        "BOOLEAN"),
                ("max_spy",               "NUMERIC(8,2)"),
                ("min_spy",               "NUMERIC(8,2)"),
                ("trade_path",            "VARCHAR(100)"),
                ("trade_quality",         "VARCHAR(50)"),
                ("vol_trigger_lost",      "BOOLEAN"),
                ("vol_trigger_lost_time", "VARCHAR(10)"),
                ("pm_note_summary",       "TEXT"),
                ("pm_hiro",               "VARCHAR(50)"),
                ("pm_vix_close",          "NUMERIC(6,2)"),
                ("pm_cor1m_close",        "NUMERIC(6,2)"),
                ("pm_market_comment",     "TEXT"),
                ("pm_flow_comment",       "TEXT"),
                ("pm_vol_comment",        "TEXT"),
                ("next_events",           "TEXT"),
                ("pm_levels_raw",         "TEXT"),
            ]
            for col, typ in new_cols:
                cur.execute("ALTER TABLE trade_journal ADD COLUMN IF NOT EXISTS %s %s;" % (col, typ))
        conn.commit()

def save_snapshot(data):
    init_db()
    fields = [
        "date","weekday","pdf_score",
        "call_wall","put_wall","vol_trigger","zero_gamma","c3","c4","c1",
        "open_spy","vix_open","spy_10am","spy_1030","spy_12pm","close_spy",
        "modo2_decision","entry_level","target_1","target_2","stop_level",
        "hit_target_1","hit_target_2","hit_stop",
        "max_favorable_move","max_adverse_move","best_trade_window","notes",
        "c4_reclaimed","c4_reclaimed_time","c1_hit","c1_hit_time",
        "call_wall_hit","call_wall_hit_time","near_call_wall",
        "max_spy","min_spy","trade_path","trade_quality",
        "vol_trigger_lost","vol_trigger_lost_time",
        "pm_note_summary","pm_hiro","pm_vix_close","pm_cor1m_close",
        "pm_market_comment","pm_flow_comment","pm_vol_comment","next_events","pm_levels_raw"
    ]
    vals = {f: data.get(f) for f in fields if data.get(f) is not None}
    if "date" not in vals:
        vals["date"] = date.today().isoformat()
    vals["weekday"] = vals.get("weekday") or date.fromisoformat(str(vals["date"])).strftime("%A")

    cols   = ", ".join(vals.keys())
    params = ", ".join(["%("+k+")s" for k in vals.keys()])
    update = ", ".join([k+"=EXCLUDED."+k for k in vals.keys() if k != "date"])

    sql = "INSERT INTO trade_journal ("+cols+") VALUES ("+params+") ON CONFLICT (date) DO UPDATE SET "+update+" RETURNING id, date;"

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, vals)
            row = cur.fetchone()
        conn.commit()
    return dict(row)

def get_journal(limit=30):
    init_db()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM trade_journal ORDER BY date DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_snapshot_by_date(date_str):
    init_db()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM trade_journal WHERE date = %s LIMIT 1", (date_str,))
            row = cur.fetchone()
    return dict(row) if row else {}


# ── Market Quotes (TradingView intraday) ─────────────────────────────

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


# ── Swing Scans (Modo 5) ──────────────────────────────────────────────
# ── Calendar events (Calendar Risk Engine) ──────────────────────────

def init_calendar():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                event_date DATE NOT NULL,
                event_name VARCHAR(120) NOT NULL,
                event_time VARCHAR(24),
                importance INT DEFAULT 1,
                PRIMARY KEY (event_date, event_name)
            )""")
        conn.commit()

def save_calendar_events(events):
    """Upsert de eventos: [{date, name, time, importance}]. Sem duplicar."""
    if not events:
        return 0
    init_calendar()
    n = 0
    with get_conn() as conn, conn.cursor() as cur:
        for ev in events:
            cur.execute("""
                INSERT INTO calendar_events (event_date, event_name, event_time, importance)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (event_date, event_name)
                DO UPDATE SET event_time = EXCLUDED.event_time,
                              importance = EXCLUDED.importance
            """, (ev["date"], ev["name"][:120], ev.get("time"), ev.get("importance", 1)))
            n += 1
        conn.commit()
    return n

def get_calendar_events(from_date=None):
    init_calendar()
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if from_date:
            cur.execute("SELECT * FROM calendar_events WHERE event_date >= %s ORDER BY event_date",
                        (from_date,))
        else:
            cur.execute("SELECT * FROM calendar_events ORDER BY event_date")
        return cur.fetchall()


from datetime import datetime as _dt_swing

CREATE_SWING = """
CREATE TABLE IF NOT EXISTS swing_scans (
    id          SERIAL PRIMARY KEY,
    created_at  TIMESTAMP DEFAULT NOW(),
    scan_date   DATE NOT NULL,
    scan_time   VARCHAR(20),
    ticker      VARCHAR(10) NOT NULL,
    direction   VARCHAR(5) NOT NULL,
    spot        NUMERIC(10,2),
    scanned     INTEGER,
    verdict     VARCHAR(20),
    edge_verdict VARCHAR(30),
    edge_aprovados INTEGER,
    edge_gex    TEXT,
    edge_vrp    TEXT,
    edge_skew   TEXT,
    edge_pc     TEXT,
    contracts   JSONB,
    raw         JSONB
);
"""

def init_swing_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_SWING)
        conn.commit()

def save_swing_scan(scan: dict):
    """Salva um resultado do scanner Modo 5 no PostgreSQL."""
    import json as _json
    init_swing_db()
    edge = scan.get("edge") or {}
    fatores = edge.get("fatores") or {}

    vals = {
        "scan_date":      _dt_swing.now().date().isoformat(),
        "scan_time":      scan.get("timestamp", ""),
        "ticker":         scan.get("ticker", ""),
        "direction":      scan.get("direction", ""),
        "spot":           scan.get("spot"),
        "scanned":        scan.get("scanned", 0),
        "verdict":        scan.get("overall_verdict", ""),
        "edge_verdict":   edge.get("verdict", ""),
        "edge_aprovados": edge.get("aprovados", 0),
        "edge_gex":       _json.dumps(fatores.get("gex")) if fatores.get("gex") else None,
        "edge_vrp":       _json.dumps(fatores.get("vrp")) if fatores.get("vrp") else None,
        "edge_skew":      _json.dumps(fatores.get("skew")) if fatores.get("skew") else None,
        "edge_pc":        _json.dumps(fatores.get("pc_ratio")) if fatores.get("pc_ratio") else None,
        "contracts":      _json.dumps(scan.get("top_contracts", [])),
        "raw":            _json.dumps(scan),
    }

    cols   = ", ".join(vals.keys())
    params = ", ".join(["%("+k+")s" for k in vals.keys()])
    sql = f"INSERT INTO swing_scans ({cols}) VALUES ({params}) RETURNING id;"

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, vals)
            row = cur.fetchone()
        conn.commit()
    return dict(row)

def get_swing_latest(limit=20):
    """Retorna os scans mais recentes agrupados por data/hora."""
    import json as _json
    init_swing_db()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM swing_scans
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for f in ['contracts', 'raw', 'edge_gex', 'edge_vrp', 'edge_skew', 'edge_pc']:
            if d.get(f) and isinstance(d[f], str):
                try: d[f] = _json.loads(d[f])
                except: pass
        result.append(d)
    return result

def get_swing_latest_scan():
    """Retorna o scan mais recente completo (todos os tickers do ultimo run)."""
    import json as _json
    init_swing_db()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Pega o timestamp do scan mais recente
            cur.execute("SELECT scan_time FROM swing_scans ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return []
            latest_time = row['scan_time']
            # Busca todos os registros desse scan
            cur.execute("""
                SELECT * FROM swing_scans
                WHERE scan_date = (SELECT scan_date FROM swing_scans ORDER BY created_at DESC LIMIT 1)
                ORDER BY ticker, direction
            """)
            rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for f in ['contracts', 'raw', 'edge_gex', 'edge_vrp', 'edge_skew', 'edge_pc']:
            if d.get(f) and isinstance(d[f], str):
                try: d[f] = _json.loads(d[f])
                except: pass
        result.append(d)
    return result

    init_db()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM trade_journal WHERE date = %s LIMIT 1", (date_str,))
            row = cur.fetchone()
    return dict(row) if row else {}
