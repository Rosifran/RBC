"""
RBC — Módulo de Logging v2
==========================
Grava sinais e trades no Postgres (Railway) quando DATABASE_URL existe,
ou em CSV local (Mac) quando não existe. Mesma API nos dois casos.

Uso no scanner:
    from rbc_log import log_signal
    sid = log_signal(modulo="0DTE", ticker="SPY", gate_status="ABERTO", ...)

Uso manual:
    python3 rbc_trade.py            # registra entrada
    python3 rbc_trade.py --saida    # registra saída
    python3 rbc_trade.py --resumo   # estatísticas
"""

import os
import csv
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# CONFIG
# ============================================================
LOG_DIR      = os.path.expanduser("~/RBC/logs")
SIGNALS_CSV  = os.path.join(LOG_DIR, "signals.csv")
TRADES_CSV   = os.path.join(LOG_DIR, "trades.csv")
ET           = ZoneInfo("America/New_York")

USE_PG = bool(os.environ.get("DATABASE_URL"))

SIGNAL_COLS = [
    "signal_id", "timestamp_et", "modulo", "ticker", "gate_status",
    "estrategia", "strike", "vencimento", "bid", "ask", "mid",
    "iv_rank", "delta", "contratos_sugeridos", "custo_estimado", "motivo_gate",
]

TRADE_COLS = [
    "trade_id", "signal_id", "modulo", "ticker", "tipo", "strike", "vencimento",
    "data_entrada", "hora_et_entrada", "qty",
    "fill_entrada", "bid_entrada", "ask_entrada",
    "data_saida", "hora_et_saida", "fill_saida", "bid_saida", "ask_saida",
    "resultado_usd", "resultado_pct", "motivo_saida", "nota",
]


# ============================================================
# POSTGRES
# ============================================================
def _conn():
    from journal import get_conn
    return get_conn()


def _pg_init():
    """Cria as tabelas se não existirem. Idempotente."""
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rbc_signals (
                    signal_id           TEXT PRIMARY KEY,
                    timestamp_et        TEXT,
                    modulo              TEXT,
                    ticker              TEXT,
                    gate_status         TEXT,
                    estrategia          TEXT,
                    strike              TEXT,
                    vencimento          TEXT,
                    bid                 TEXT,
                    ask                 TEXT,
                    mid                 TEXT,
                    iv_rank             TEXT,
                    delta               TEXT,
                    contratos_sugeridos TEXT,
                    custo_estimado      TEXT,
                    motivo_gate         TEXT,
                    created_at          TIMESTAMPTZ DEFAULT NOW()
                )""")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rbc_trades (
                    trade_id        TEXT PRIMARY KEY,
                    signal_id       TEXT,
                    modulo          TEXT,
                    ticker          TEXT,
                    tipo            TEXT,
                    strike          TEXT,
                    vencimento      TEXT,
                    data_entrada    TEXT,
                    hora_et_entrada TEXT,
                    qty             TEXT,
                    fill_entrada    TEXT,
                    bid_entrada     TEXT,
                    ask_entrada     TEXT,
                    data_saida      TEXT,
                    hora_et_saida   TEXT,
                    fill_saida      TEXT,
                    bid_saida       TEXT,
                    ask_saida       TEXT,
                    resultado_usd   TEXT,
                    resultado_pct   TEXT,
                    motivo_saida    TEXT,
                    nota            TEXT,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )""")
        c.commit()


# ============================================================
# HELPERS
# ============================================================
def _ensure(path, cols):
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=cols).writeheader()


def _now_et():
    return datetime.now(ET)


def _next_id(table, path, cols, prefix):
    """ID único por timestamp + aleatório — seguro para processos concorrentes.
    Formato: S260722133812345678a3f (prefixo + AAMMDDHHMMSSffffff + 3 hex)."""
    import random
    return (f"{prefix}{_now_et().strftime('%y%m%d%H%M%S%f')}"
            f"{random.randint(0, 4095):03x}")


def _insert(table, cols, row, path):
    if USE_PG:
        _pg_init()
        with _conn() as c:
            with c.cursor() as cur:
                ph = ", ".join(["%s"] * len(cols))
                cur.execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph}) "
                    f"ON CONFLICT DO NOTHING",
                    [str(row.get(k, "")) for k in cols])
            c.commit()
        return
    _ensure(path, cols)
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=cols).writerow(row)
        f.flush()
        os.fsync(f.fileno())


def read_rows(path, cols):
    """Lê de Postgres ou CSV conforme o ambiente."""
    table = "rbc_signals" if cols is SIGNAL_COLS else "rbc_trades"
    if USE_PG:
        try:
            _pg_init()
            with _conn() as c:
                with c.cursor() as cur:
                    cur.execute(
                        f"SELECT {', '.join(cols)} FROM {table} ORDER BY created_at")
                    return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            pass
    _ensure(path, cols)
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ============================================================
# LOG DE SINAL
# ============================================================
def log_signal(modulo, ticker, gate_status, estrategia="", strike="",
               vencimento="", bid="", ask="", iv_rank="", delta="",
               contratos_sugeridos="", custo_estimado="", motivo_gate=""):
    """Grava um sinal e devolve o signal_id. Nunca derruba o chamador."""
    try:
        sid = _next_id("rbc_signals", SIGNALS_CSV, SIGNAL_COLS, "S")
        try:
            mid = round((float(bid) + float(ask)) / 2, 4)
        except (TypeError, ValueError):
            mid = ""

        row = {
            "signal_id":           sid,
            "timestamp_et":        _now_et().strftime("%Y-%m-%d %H:%M:%S"),
            "modulo":              modulo,
            "ticker":              ticker,
            "gate_status":         gate_status,
            "estrategia":          estrategia,
            "strike":              strike,
            "vencimento":          vencimento,
            "bid":                 bid,
            "ask":                 ask,
            "mid":                 mid,
            "iv_rank":             iv_rank,
            "delta":               delta,
            "contratos_sugeridos": contratos_sugeridos,
            "custo_estimado":      custo_estimado,
            "motivo_gate":         motivo_gate,
        }
        _insert("rbc_signals", SIGNAL_COLS, row, SIGNALS_CSV)
        return sid
    except Exception as e:
        print(f"  [log] aviso: falha ao gravar sinal — {e}")
        return None


# ============================================================
# TRADE — ENTRADA
# ============================================================
def log_trade_entry(signal_id, modulo, ticker, tipo, strike, vencimento,
                    qty, fill_entrada, bid_entrada="", ask_entrada="", nota=""):
    tid = _next_id("rbc_trades", TRADES_CSV, TRADE_COLS, "T")
    now = _now_et()

    row = {c: "" for c in TRADE_COLS}
    row.update({
        "trade_id":        tid,
        "signal_id":       signal_id,
        "modulo":          modulo,
        "ticker":          ticker,
        "tipo":            tipo,
        "strike":          strike,
        "vencimento":      vencimento,
        "data_entrada":    now.strftime("%Y-%m-%d"),
        "hora_et_entrada": now.strftime("%H:%M:%S"),
        "qty":             qty,
        "fill_entrada":    fill_entrada,
        "bid_entrada":     bid_entrada,
        "ask_entrada":     ask_entrada,
        "nota":            nota,
    })
    _insert("rbc_trades", TRADE_COLS, row, TRADES_CSV)
    return tid


# ============================================================
# TRADE — SAÍDA
# ============================================================
def log_trade_exit(trade_id, fill_saida, bid_saida="", ask_saida="",
                   motivo_saida="", nota=""):
    now = _now_et()

    if USE_PG:
        try:
            _pg_init()
            with _conn() as c:
                with c.cursor() as cur:
                    cur.execute(
                        "SELECT fill_entrada, qty, nota FROM rbc_trades "
                        "WHERE trade_id = %s", (trade_id,))
                    r = cur.fetchone()
                    if not r:
                        return None
                    entrada, qty = float(r[0]), int(float(r[1]))
                    saida   = float(fill_saida)
                    res_usd = round((saida - entrada) * 100 * qty, 2)
                    res_pct = round((saida - entrada) / entrada * 100, 2) if entrada else ""
                    nova    = ((r[2] or "") + " | " + nota).strip(" |") if nota else (r[2] or "")

                    cur.execute("""
                        UPDATE rbc_trades SET
                            data_saida=%s, hora_et_saida=%s, fill_saida=%s,
                            bid_saida=%s, ask_saida=%s, resultado_usd=%s,
                            resultado_pct=%s, motivo_saida=%s, nota=%s
                        WHERE trade_id=%s""",
                        (now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
                         str(fill_saida), str(bid_saida), str(ask_saida),
                         str(res_usd), str(res_pct), motivo_saida, nova, trade_id))
                c.commit()
            return trade_id
        except Exception as e:
            print(f"  [log] aviso: {e}")
            return None

    rows  = read_rows(TRADES_CSV, TRADE_COLS)
    found = False
    for r in rows:
        if r["trade_id"] == trade_id:
            found = True
            entrada = float(r["fill_entrada"])
            saida   = float(fill_saida)
            qty     = int(float(r["qty"]))
            res_usd = round((saida - entrada) * 100 * qty, 2)
            res_pct = round((saida - entrada) / entrada * 100, 2) if entrada else ""
            r.update({
                "data_saida":    now.strftime("%Y-%m-%d"),
                "hora_et_saida": now.strftime("%H:%M:%S"),
                "fill_saida":    fill_saida,
                "bid_saida":     bid_saida,
                "ask_saida":     ask_saida,
                "resultado_usd": res_usd,
                "resultado_pct": res_pct,
                "motivo_saida":  motivo_saida,
            })
            if nota:
                r["nota"] = (r.get("nota", "") + " | " + nota).strip(" |")

    if not found:
        return None

    with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_COLS)
        w.writeheader()
        w.writerows(rows)
    return trade_id


# ============================================================
def open_trades():
    return [r for r in read_rows(TRADES_CSV, TRADE_COLS) if not r.get("fill_saida")]


def storage_info():
    return "Postgres (Railway)" if USE_PG else f"CSV local ({LOG_DIR})"
