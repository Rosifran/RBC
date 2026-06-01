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
    notes               TEXT
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
        conn.commit()

def save_snapshot(data):
    init_db()
    fields = [
        "date","weekday","pdf_score",
        "call_wall","put_wall","vol_trigger","zero_gamma","c3","c4","c1",
        "open_spy","vix_open","spy_10am","spy_1030","spy_12pm","close_spy",
        "modo2_decision","entry_level","target_1","target_2","stop_level",
        "hit_target_1","hit_target_2","hit_stop",
        "max_favorable_move","max_adverse_move","best_trade_window","notes"
    ]
    vals = {f: data.get(f) for f in fields}
    if not vals["date"]:
        vals["date"] = date.today().isoformat()
    vals["weekday"] = vals["weekday"] or date.fromisoformat(str(vals["date"])).strftime("%A")

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
