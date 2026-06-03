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
