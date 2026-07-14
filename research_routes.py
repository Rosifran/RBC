"""
RBC — Modo 8 · Equity Research — rotas Flask
=============================================
Integração no app.py (2 linhas):

    from research_routes import research_bp
    app.register_blueprint(research_bp)

Rotas:
  GET  /research                   → página do Modo 8
  GET  /api/research/ratings       → última rodada (cache JSON / PostgreSQL)
  POST /api/research/screener      → roda o screener no universo
  POST /api/research/update        → pipeline completo (coleta + score + tese)
                                     body opcional: {"tickers": ["AIT","GGG"]}
  GET  /api/research/ticker/<t>    → card detalhado de um ticker
"""

import os
import json
import threading
from datetime import datetime
from flask import Blueprint, jsonify, request, render_template

import rbc_research as R

research_bp = Blueprint("research", __name__)

# Estado da atualização em background (coleta EDGAR demora ~1-2 min)
_job = {"running": False, "started": None, "error": None, "done": None}


# ── PostgreSQL opcional (usa DATABASE_URL do Railway) ─────────────────

def _pg_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2
        return psycopg2.connect(url)
    except Exception:
        return None


def _pg_save(report):
    conn = _pg_conn()
    if not conn:
        return
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS research_ratings (
                    id SERIAL PRIMARY KEY,
                    run_date DATE NOT NULL,
                    ticker TEXT NOT NULL,
                    rating TEXT, composite REAL,
                    q_quality REAL, q_growth REAL, q_balance REAL, q_valuation REAL,
                    price REAL, target REAL, upside_pct REAL,
                    ev_ebitda REAL, nd_ebitda REAL,
                    red_flags TEXT, thesis TEXT,
                    UNIQUE (run_date, ticker)
                )""")
            for r in report:
                p = r.get("pillars", {})
                cur.execute("""
                    INSERT INTO research_ratings
                    (run_date, ticker, rating, composite, q_quality, q_growth,
                     q_balance, q_valuation, price, target, upside_pct,
                     ev_ebitda, nd_ebitda, red_flags, thesis)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_date, ticker) DO UPDATE SET
                      rating=EXCLUDED.rating, composite=EXCLUDED.composite,
                      price=EXCLUDED.price, target=EXCLUDED.target,
                      upside_pct=EXCLUDED.upside_pct, thesis=EXCLUDED.thesis
                """, (r["date"], r["ticker"], r["rating"], r["composite"],
                      p.get("quality"), p.get("growth"), p.get("balance"),
                      p.get("valuation"), r["price"], r["target"],
                      r["upside_pct"], r["ev_ebitda"], r["nd_ebitda"],
                      json.dumps(r["red_flags"]), r.get("thesis")))
    except Exception:
        pass
    finally:
        conn.close()


# ── Página ────────────────────────────────────────────────────────────

@research_bp.route("/research")
def research_page():
    return render_template("research.html")


# ── API ───────────────────────────────────────────────────────────────

@research_bp.route("/api/research/ratings")
def api_ratings():
    cache = R.load_cache()
    return jsonify({
        "ok": bool(cache),
        "updated": cache.get("updated") if cache else None,
        "report": cache.get("report", []) if cache else [],
        "job": _job,
        "disclaimer": "Ferramenta educacional. Não é recomendação de compra ou venda.",
    })


@research_bp.route("/api/research/screener", methods=["POST"])
def api_screener():
    try:
        body = request.get_json(silent=True) or {}
        rows = R.run_screener(tickers=body.get("tickers"),
                              check_options=body.get("check_options", True))
        return jsonify({"ok": True, "universe": rows,
                        "passed": [r["ticker"] for r in rows if r["pass"]]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@research_bp.route("/api/research/lookup", methods=["POST"])
def api_lookup():
    """
    Lookup de ticker avulso fora do universo.
    Ex: TSLA, AAPL, NVDA.
    Não gera BUY/HOLD/SELL porque não compara contra pares corretos.
    """
    try:
        body = request.get_json(silent=True) or {}
        ticker = (body.get("ticker") or "").upper().strip()

        if not ticker:
            return jsonify({"ok": False, "error": "Ticker obrigatório."}), 400

        market = R.market_snapshot(ticker)
        fundamentals = R.collect_fundamentals(ticker)

        if not fundamentals:
            return jsonify({
                "ok": False,
                "ticker": ticker,
                "error": "Fundamentos não encontrados no EDGAR para este ticker."
            }), 404

        metrics = R.compute_metrics(fundamentals, market)
        flags = R.red_flags(metrics, fundamentals)

        return jsonify({
            "ok": True,
            "ticker": ticker,
            "name": fundamentals.get("entity") or market.get("name") or ticker,
            "outside_research_universe": ticker not in R.UNIVERSE,
            "note": "Ticker lookup avulso. Sem BUY/HOLD/SELL porque não há comparação com pares setoriais.",
            "market": {
                "price": market.get("price"),
                "mcap": market.get("mcap"),
                "analysts": market.get("analysts"),
            },
            "metrics": {
                "revenue_ttm": metrics.get("rev_ttm"),
                "ebitda_ttm": metrics.get("ebitda_ttm"),
                "fcf_ttm": metrics.get("fcf_ttm"),
                "roe": metrics.get("roe"),
                "roic": metrics.get("roic"),
                "op_margin": metrics.get("op_margin"),
                "rev_yoy": metrics.get("rev_yoy"),
                "ni_yoy": metrics.get("ni_yoy"),
                "nd_ebitda": metrics.get("nd_ebitda"),
                "int_cover": metrics.get("int_cover"),
                "current_ratio": metrics.get("current_ratio"),
                "ev_ebitda": metrics.get("ev_ebitda"),
                "pe": metrics.get("pe"),
                "fcf_yield": metrics.get("fcf_yield"),
            },
            "red_flags": flags,
            "options_note": "Liquidez de opções deve ser confirmada no IBKR, especialmente fora do horário de mercado."
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _run_update(tickers, with_thesis):
    try:
        report = R.run_research(tickers=tickers, with_thesis=with_thesis,
                                verbose=False)
        _pg_save(report)
        _job.update(running=False, done=datetime.now().isoformat(), error=None)
    except Exception as e:
        _job.update(running=False, error=str(e))


@research_bp.route("/api/research/update", methods=["POST"])
def api_update():
    if _job["running"]:
        return jsonify({"ok": False, "error": "Atualização já em andamento.",
                        "job": _job}), 409
    body = request.get_json(silent=True) or {}
    tickers = [t.upper() for t in body.get("tickers", [])] or None
    with_thesis = bool(os.environ.get("ANTHROPIC_API_KEY")) and \
        body.get("thesis", True)
    _job.update(running=True, started=datetime.now().isoformat(),
                error=None, done=None)
    threading.Thread(target=_run_update, args=(tickers, with_thesis),
                     daemon=True).start()
    return jsonify({"ok": True, "message":
                    "Atualização iniciada — coleta EDGAR leva 1-2 min. "
                    "Recarregue os ratings em instantes.", "job": _job})


@research_bp.route("/api/research/ticker/<ticker>")
def api_ticker(ticker):
    cache = R.load_cache()
    if not cache:
        return jsonify({"ok": False, "error": "Nenhuma rodada em cache. "
                        "Rode a atualização primeiro."}), 404
    for r in cache.get("report", []):
        if r["ticker"] == ticker.upper():
            return jsonify({"ok": True, "data": r,
                            "updated": cache.get("updated")})
    return jsonify({"ok": False,
                    "error": f"{ticker.upper()} não está na última rodada."}), 404
