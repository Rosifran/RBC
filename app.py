"""
RBC — Risk Bridge Capital | Flask API
"""

import io
import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

import anthropic

load_dotenv()
import pdfplumber
from flask import Flask, jsonify, render_template, request

_anthropic = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

_PDF_PROMPT = """You are a quantitative trading assistant. Extract structured data from this SpotGamma PDF report.

Return ONLY a valid JSON object with exactly these fields. No markdown, no explanation.

{{
  "spy": {{
    "reference_price": null,
    "risk_pivot": null,
    "call_wall": null,
    "put_wall": null,
    "vol_trigger": null,
    "zero_gamma": null,
    "absolute_gamma": null,
    "move_1d": null,
    "move_5d": null,
    "move_1d_high": null,
    "move_1d_low": null,
    "spy_levels": [],
    "combos": []
  }},
  "spx": {{
    "reference_price": null,
    "call_wall": null,
    "put_wall": null,
    "vol_trigger": null,
    "zero_gamma": null,
    "pivot": null,
    "resistance": [],
    "support": []
  }},
  "macro": {{
    "cor1m": null,
    "risk_pivot_spx": null,
    "positive_gamma_support": null,
    "extreme_call_froth": null,
    "volatility_spasm_risk": null,
    "key_events": []
  }},
  "regime": {{
    "gamma": null,
    "bias": null,
    "vix_posture": null,
    "summary": null
  }},
  "founder_alerts": [],
  "plan": {{
    "call_trigger": null,
    "put_trigger": null,
    "avoid": null,
    "best_setup": null
  }},
  "score": {{
    "value": null,
    "justification": null
  }},
  "sg_string": "$SPY, SPY, <call_wall>, <put_wall>, <vol_trigger>, <absolute_gamma>, <put_wall>, <spy_level_1>, <spy_level_2>, <combo1>, <combo2>, <combo3>, <combo4>, <move_1d>, <move_5d>, <zero_gamma>"
}}

Rules:
- move_1d and move_5d as decimals (0.61% = 0.0061)
- move_1d_high and move_1d_low: absolute SPY price levels
- cor1m: extract the COR1M indicator value if mentioned
- risk_pivot_spx: extract the Risk Pivot SPX level if mentioned
- spy.risk_pivot: SPY Risk Pivot level if mentioned; if only SPX Risk Pivot is given, divide by 10 (e.g. SPX 7400 -> SPY 740.0)
- positive_gamma_support: true/false
- extreme_call_froth: true/false
- volatility_spasm_risk: true/false
- key_events: list of key dates/events mentioned
- plan.call_trigger: SPY level to enter call (start with SPY)
- plan.put_trigger: SPY level to enter put (start with SPY)
- score.value: 1-5 integer (5=ideal, 1=avoid)
- score.justification: one sentence, trading-desk style
- founder_alerts: max 6 items, most important first
- If field not found use null
- Return raw JSON only, no markdown

PDF TEXT:
{text}
"""

from rbc_0dte_scanner import (
    analyze_spy_0dte,
    market_environment,
    opening_watch,
    parse_sg_data,
)

app = Flask(__name__, template_folder="templates")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "1.6-railway-test"})


@app.route("/")
def index():
    return render_template("index.html")



def normalize_claude_output(parsed):
    """Normalize and sanitize Claude JSON output."""

    def limit_sentences(text, max_sentences):
        if not text or not isinstance(text, str):
            return text
        sentences = text.replace('!', '.').replace('?', '.').split('.')
        sentences = [s.strip() for s in sentences if s.strip()]
        return '. '.join(sentences[:max_sentences]) + ('.' if sentences[:max_sentences] else '')

    # 1. score always exists
    if not parsed.get("score") or not isinstance(parsed.get("score"), dict):
        parsed["score"] = {"value": None, "justification": None}
    else:
        parsed["score"].setdefault("value", None)
        parsed["score"].setdefault("justification", None)

    # 2. plan always exists with required keys
    if not parsed.get("plan") or not isinstance(parsed.get("plan"), dict):
        parsed["plan"] = {}
    for key in ["call_trigger", "put_trigger", "avoid", "best_setup"]:
        parsed["plan"].setdefault(key, None)

    # 3. founder_alerts always a list
    fa = parsed.get("founder_alerts")
    if fa is None:
        parsed["founder_alerts"] = []
    elif isinstance(fa, str):
        parsed["founder_alerts"] = [fa]
    elif not isinstance(fa, list):
        parsed["founder_alerts"] = []

    # 4 & 5. RBC decide — regra fixa, Claude só extrai dados
    spy = parsed.get("spy") or {}
    spx = parsed.get("spx") or {}
    macro = parsed.get("macro") or {}

    combos   = spy.get("combos") or []
    combos_f = sorted([c for c in combos if isinstance(c, (int, float))])
    vol_trig  = spy.get("vol_trigger")
    zero_g    = spy.get("zero_gamma")
    call_wall = spy.get("call_wall")
    cor1m     = macro.get("cor1m")
    froth     = macro.get("extreme_call_froth")
    vol_spasm = macro.get("volatility_spasm_risk")

    ref_price = spy.get("reference_price")
    put_line  = vol_trig or zero_g

    # ── Regime: RBC decide com base em reference_price vs vol_trigger ──
    # NEGATIVE GAMMA: ref abaixo do Vol Trigger → mercado frágil
    # POSITIVE GAMMA: ref igual ou acima do Vol Trigger → mercado sustentado
    if ref_price and vol_trig:
        negative_gamma = ref_price < vol_trig
    else:
        negative_gamma = False  # sem dados suficientes, assume positivo

    # Combos abaixo e acima da Call Wall (para separar entradas de alvos)
    combos_below_cw = [c for c in combos_f if call_wall and c < call_wall]
    combos_above_cw = [c for c in combos_f if call_wall and c >= call_wall]

    if negative_gamma:
        # ── NEGATIVE GAMMA ────────────────────────────────────────────
        # CALL: só em reclaim do Vol Trigger / Zero Gamma
        # Não usar combos acima da Call Wall como entrada
        vt_str = vol_trig or zero_g
        zg_str = zero_g or vol_trig
        if vt_str and zg_str and vt_str != zg_str:
            parsed["plan"]["call_trigger"] = (
                f"SPY reclaim {vt_str} with acceptance. "
                f"Confirm above {zg_str}. "
                f"Targets: {call_wall or 'Call Wall'}."
            )
        elif vt_str:
            parsed["plan"]["call_trigger"] = (
                f"SPY reclaim {vt_str} with acceptance. "
                f"Target: {call_wall or 'Call Wall'}. "
                f"Do not chase call above Call Wall."
            )

        # PUT: rejeição ou aceitação abaixo do Vol Trigger
        if put_line:
            parsed["plan"]["put_trigger"] = (
                f"SPY rejection of {put_line} or acceptance below. "
                f"Targets: {ref_price or 'Reference Price'}, then {spy.get('put_wall') or 'Put Wall'}. "
                f"Do not chase if already extended from {put_line}."
            )

        # NO TRADE
        if put_line and call_wall:
            parsed["plan"]["avoid"] = (
                f"SPY between {put_line} and {call_wall} without clear direction. "
                f"Wait for rejection or reclaim of {put_line}."
            )

        # BEST operacional
        parsed["plan"]["best_setup"] = (
            f"NEGATIVE GAMMA regime — fragile market. "
            f"Best: PUT on rejection of {put_line or 'Vol Trigger'}, "
            f"or CALL only on clean reclaim of {put_line or 'Vol Trigger'}. "
            f"No trade in middle of range."
        )

        # SCORE em Negative Gamma
        parsed["score"]["value"] = 2
        cor_str = f" COR1M {cor1m}." if cor1m else ""
        parsed["score"]["justification"] = (
            f"Negative Gamma regime — SPY below Vol Trigger. "
            f"Fragile, headline-sensitive.{cor_str} Reduce size, wait for level."
        )

    else:
        # ── POSITIVE GAMMA ────────────────────────────────────────────
        # Lógica original mantida: combos acima do put_line como escada
        above_put = [c for c in combos_f if put_line and c > put_line]

        if len(above_put) >= 2:
            no_trade_hi = above_put[1]
        elif above_put:
            no_trade_hi = above_put[0]
        else:
            no_trade_hi = call_wall

        if len(above_put) >= 3 and call_wall:
            parsed["plan"]["call_trigger"] = f"SPY above {above_put[1]}, better above {above_put[2]}, strongest above {call_wall}."
        elif len(above_put) >= 2 and call_wall:
            parsed["plan"]["call_trigger"] = f"SPY above {above_put[1]}, strongest above {call_wall}."
        elif call_wall:
            parsed["plan"]["call_trigger"] = f"SPY above {call_wall}."

        if put_line:
            parsed["plan"]["put_trigger"] = f"SPY below {put_line}."

        if put_line and no_trade_hi:
            parsed["plan"]["avoid"] = f"SPY between {put_line} and {no_trade_hi}."

        if put_line and no_trade_hi:
            parsed["plan"]["best_setup"] = f"Wait for breakout; do not trade inside {put_line}–{no_trade_hi} compression zone."

        # SCORE em Positive Gamma
        if froth and vol_spasm:
            parsed["score"]["value"] = 2
            cor_str = f" and COR1M {cor1m}" if cor1m else ""
            parsed["score"]["justification"] = f"Positive gamma supports stocks, but extreme call froth{cor_str} create volatility-spasm risk."

    # 6. Normalize bias to single word
    regime = parsed.get("regime") or {}
    if regime.get("bias"):
        regime["bias"] = regime["bias"].strip().split()[0].lower()
    parsed["regime"] = regime
    regime = parsed.get("regime") or {}
    if isinstance(regime, dict):
        regime["summary"] = limit_sentences(regime.get("summary"), 2)
        parsed["regime"] = regime

    parsed["gamma_interpretation"] = limit_sentences(parsed.get("gamma_interpretation"), 2)

    return parsed

@app.route("/api/parse-pdf", methods=["POST"])
def parse_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "File must be a PDF"}), 400

    try:
        with pdfplumber.open(io.BytesIO(f.read())) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(pages).strip()
    except Exception as e:
        return jsonify({"error": f"PDF extraction failed: {e}"}), 500

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        print(f"=== ANTHROPIC_API_KEY present: {bool(api_key)}, starts with: {api_key[:8] + '...' if api_key else 'NOT SET'} ===")

        prompt_text = _PDF_PROMPT.format(text=text[:12000])
        print("=== EXACT PROMPT SENT TO CLAUDE ===")
        print(prompt_text)
        print("=== END PROMPT ===")

        try:
            msg = _anthropic.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                timeout=30,
                messages=[{
                    "role": "user",
                    "content": prompt_text,
                }],
            )
        except Exception as api_exc:
            import traceback
            print("=== ANTHROPIC API EXCEPTION ===")
            traceback.print_exc()
            print(f"=== EXCEPTION TYPE: {type(api_exc).__name__} ===")
            print(f"=== EXCEPTION ARGS: {api_exc.args} ===")
            print("=== END ANTHROPIC API EXCEPTION ===")
            return jsonify({"error": f"Claude API call failed: {api_exc}", "raw": None}), 200
        print(f"=== RESPONSE METADATA: model={msg.model}, stop_reason={msg.stop_reason}, usage={msg.usage} ===")
        raw = msg.content[0].text
        print("=== FULL RAW CLAUDE RESPONSE (before any processing) ===")
        print(repr(raw))
        print("=== END RAW CLAUDE RESPONSE ===")
        raw = raw.strip()
        cleaned = raw
        if "```" in cleaned:
            parts = cleaned.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    cleaned = part
                    break
        cleaned = cleaned.strip()
        try:
            parsed = json.loads(cleaned)
            parsed = normalize_claude_output(parsed)
        except json.JSONDecodeError as e:
            return jsonify({"error": f"Claude returned invalid JSON: {e}", "raw": raw}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Claude API error: {e}", "raw": locals().get("raw")}), 200

    # ── Auto-save journal snapshot pré-market ──
    try:
        from journal import save_snapshot
        spy_data  = parsed.get("spy") or {}
        plan_data = parsed.get("plan") or {}
        score_data = parsed.get("score") or {}
        combos = sorted([c for c in (spy_data.get("combos") or []) if isinstance(c, (int, float))])
        vol_trig = spy_data.get("vol_trigger") or spy_data.get("zero_gamma")
        above = [c for c in combos if vol_trig and c > vol_trig]

        import re
        def extract_spy_level(txt):
            if not txt: return None
            m = re.search(r"SPY\s*([\d.]+)", txt or "")
            return float(m.group(1)) if m else None

        save_snapshot({
            "pdf_score":    score_data.get("value"),
            "call_wall":    spy_data.get("call_wall"),
            "put_wall":     spy_data.get("put_wall"),
            "vol_trigger":  spy_data.get("vol_trigger"),
            "zero_gamma":   spy_data.get("zero_gamma"),
            "c3":           above[0] if len(above) >= 1 else None,
            "c4":           above[1] if len(above) >= 2 else None,
            "c1":           above[2] if len(above) >= 3 else None,
            "target_1":     plan_data.get("call_trigger") and extract_spy_level(plan_data.get("call_trigger")),
            "stop_level":   plan_data.get("put_trigger") and extract_spy_level(plan_data.get("put_trigger")),
        })
    except Exception as je:
        print(f"Journal auto-save warning: {je}")

    return jsonify({
        "ok": True,
        "spy": parsed.get("spy"),
        "spx": parsed.get("spx"),
        "regime": parsed.get("regime"),
        "founder_alerts": parsed.get("founder_alerts", []),
        "gamma_interpretation": parsed.get("gamma_interpretation"),
        "plan": parsed.get("plan"),
        "score": parsed.get("score"),
        "sg_string": parsed.get("sg_string"),
        "briefing": parsed.get("briefing"),
        "eventos": parsed.get("eventos", []),
    })


_PM_PDF_PROMPT = """You are a quantitative trading assistant. Extract structured pre-market data from this PDF report.

Return ONLY a valid JSON object with exactly these fields. No markdown, no explanation.

{{
  "pm_hiro": null,
  "pm_vix_close": null,
  "pm_cor1m_close": null,
  "pm_market_comment": null,
  "pm_flow_comment": null,
  "pm_vol_comment": null,
  "next_events": null,
  "pm_levels_raw": null
}}

Rules:
- pm_hiro: HIRO indicator direction as a short string ("bullish", "bearish", "neutral", or the raw value found)
- pm_vix_close: yesterday's or most recent VIX close as a decimal number (e.g. 18.5)
- pm_cor1m_close: COR1M indicator close value as a decimal number
- pm_market_comment: 1-2 sentence summary of overall market tone/context from the report
- pm_flow_comment: 1-2 sentence summary of options flow or dealer positioning commentary
- pm_vol_comment: 1-2 sentence summary of volatility commentary
- next_events: comma-separated list of upcoming key events/dates mentioned (e.g. "FOMC 2026-06-12, CPI 2026-06-11")
- pm_levels_raw: raw text block with key price levels mentioned (paste verbatim if present, else summarize)
- Use null for any field not found in the text
- Return raw JSON only, no markdown

PDF TEXT:
{text}
"""


@app.route("/api/parse-pm-pdf", methods=["POST"])
def parse_pm_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "File must be a PDF"}), 400

    try:
        with pdfplumber.open(io.BytesIO(f.read())) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(pages).strip()
    except Exception as e:
        return jsonify({"error": f"PDF extraction failed: {e}"}), 500

    try:
        msg = _anthropic.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            timeout=30,
            messages=[{"role": "user", "content": _PM_PDF_PROMPT.format(text=text[:12000])}],
        )
        raw = msg.content[0].text.strip()
        cleaned = raw
        if "```" in cleaned:
            for part in cleaned.split("```"):
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    cleaned = part
                    break
        parsed = json.loads(cleaned.strip())
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Claude returned invalid JSON: {e}", "raw": raw}), 200
    except Exception as e:
        return jsonify({"error": f"Claude API error: {e}"}), 500

    import datetime
    try:
        from journal import save_snapshot
        save_snapshot({
            "date":               str(datetime.date.today()),
            "pm_hiro":            parsed.get("pm_hiro"),
            "pm_vix_close":       parsed.get("pm_vix_close"),
            "pm_cor1m_close":     parsed.get("pm_cor1m_close"),
            "pm_market_comment":  parsed.get("pm_market_comment"),
            "pm_flow_comment":    parsed.get("pm_flow_comment"),
            "pm_vol_comment":     parsed.get("pm_vol_comment"),
            "next_events":        parsed.get("next_events"),
            "pm_levels_raw":      parsed.get("pm_levels_raw"),
        })
    except Exception as je:
        print(f"Journal auto-save warning (parse-pm-pdf): {je}")

    return jsonify({"ok": True, **parsed})


# ── TradingView market quote (SPY + VIX) → PostgreSQL ────────────────

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
    })


@app.route("/api/modo1", methods=["POST"])
def modo1():
    """Pre-market: parse SpotGamma data and return SPY key levels."""
    data = request.get_json(silent=True) or {}
    raw = data.get("sg_raw") or data.get("sg_string", "")
    if not raw:
        return jsonify({"error": "sg_raw is required"}), 400

    sg = parse_sg_data(raw)
    spy = sg.get("SPY") or sg.get("$SPY")
    if not spy:
        return jsonify({"error": "SPY not found in SpotGamma data"}), 422

    return jsonify({
        "ticker":       spy["symbol"],
        "call_wall":    spy["call_wall"],
        "put_wall":     spy["put_wall"],
        "zero_gamma":   spy["zero_gamma"],
        "vol_trigger":  spy["vol_trigger"],
        "abs_gamma":    spy["abs_gamma"],
        "combos":       spy["combos"],
        "supports":     spy["supports"],
        "imp_1d_pct":   round(spy["imp_1d"] * 100, 3),
        "imp_5d_pct":   round(spy["imp_5d"] * 100, 3),
    })


@app.route("/api/modo2", methods=["POST"])
def modo2():
    """Opening watch (9:30–10:00 ET): VIX + HIRO + spot movement analysis."""
    data = request.get_json(silent=True) or {}

    # Accept both old and new field names
    vix_open  = data.get("vix_open")  or data.get("vix_close_yesterday")
    vix_now   = data.get("vix_now")   or data.get("vix_open_today")
    spot_open = data.get("spot_open") or data.get("spy_open_today") or data.get("spy_close_yesterday")
    spot_now  = data.get("spot_now")  or data.get("spy_open_today") or data.get("spy_close_yesterday")
    sg_raw    = data.get("sg_raw")    or data.get("sg_string") or ""

    # só vix_now e spot_now são obrigatórios
    required = []
    if not vix_now:  required.append("vix_now")
    if not spot_now: required.append("spot_now")
    if required:
        return jsonify({"error": f"Missing fields: {', '.join(required)}"}), 400
    # opcionais com fallback
    if not vix_open:  vix_open  = vix_now
    if not spot_open: spot_open = spot_now

    try:
        vix_open  = float(vix_open)
        vix_now   = float(vix_now)
        spot_open = float(spot_open)
        spot_now  = float(spot_now)
        hiro      = data.get("hiro_direction", "neutral")
        capital   = float(data.get("capital", 50000))
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid numeric value: {e}"}), 400

    data["sg_raw"] = sg_raw

    sg = parse_sg_data(data["sg_raw"])

    ow = opening_watch(
        vix_open, vix_now, hiro, spot_open, spot_now,
        sg_data=sg, capital=capital,
    )

    # ── Regime de Gamma + Lógica RBC 0DTE v2.0 ──────────────────────────
    # Compra simples CALL ou PUT / 1 contrato / sem spread / sem overnight
    # Vol Trigger = interruptor de regime
    # Compatível com Modo 3: decision, entry, stop, target_1, target_2, risk, levels

    def _all_levels(s):
        raw = []
        for k in ['spy_levels', 'combos', 'combo_strikes']:
            raw += [v for v in (s.get(k) or []) if isinstance(v, (int, float))]
        for k in ['call_wall', 'put_wall', 'vol_trigger', 'zero_gamma',
                  'move_1d_high', 'move_1d_low']:
            v = s.get(k)
            if v and isinstance(v, (int, float)):
                raw.append(v)
        return sorted(set(raw))

    def _above(levels, ref, n=2):
        return [l for l in levels if l > float(ref)][:n]

    def _below(levels, ref, n=2):
        return sorted([l for l in levels if l < float(ref)], reverse=True)[:n]

    def _safe_t2_call(t1, candidates):
        # t2 CALL: next level above t1. Fallback: t1 + 2
        opts = [l for l in candidates if float(l) > float(t1)]
        return opts[0] if opts else round(float(t1) + 2, 2)

    def _safe_t2_put(t1, candidates):
        # t2 PUT: next level below t1. Fallback: t1 - 2
        opts = sorted([l for l in candidates if float(l) < float(t1)], reverse=True)
        return opts[0] if opts else round(float(t1) - 2, 2)

    def _level_type(v, s, rp, m1h, m1l):
        """Classifica o tipo de um nivel para o Location Engine."""
        if v is None:
            return None
        vf = float(v)
        if s.get('call_wall')   and vf == float(s['call_wall']):   return 'CALL_WALL'
        if s.get('put_wall')    and vf == float(s['put_wall']):    return 'PUT_WALL'
        if s.get('vol_trigger') and vf == float(s['vol_trigger']): return 'VOL_TRIGGER'
        if s.get('zero_gamma')  and vf == float(s['zero_gamma']):  return 'ZERO_GAMMA'
        if rp  and vf == float(rp):  return 'RISK_PIVOT'
        if m1h and vf == float(m1h): return '1D_MOVE_HIGH'
        if m1l and vf == float(m1l): return '1D_MOVE_LOW'
        return 'COMBO/LEVEL'

    def analyze_trade_location(spot, levels, near, s, rp=None, m1h=None, m1l=None):
        """Location Engine — curso SpotGamma.
        Posicao do spot no micro-range entre os niveis reais do dia.
        Informativo: nao decide, nao altera o motor."""
        if not spot or not levels:
            return None
        spot_f = float(spot)
        sups = [float(l) for l in levels if float(l) < spot_f]
        ress = [float(l) for l in levels if float(l) > spot_f]
        n_sup = max(sups) if sups else None
        n_res = min(ress) if ress else None

        loc = {
            "nearest_support":         n_sup,
            "nearest_support_type":    _level_type(n_sup, s, rp, m1h, m1l),
            "nearest_resistance":      n_res,
            "nearest_resistance_type": _level_type(n_res, s, rp, m1h, m1l),
            "distance_to_support":     round(spot_f - n_sup, 2) if n_sup is not None else None,
            "distance_to_resistance":  round(n_res - spot_f, 2) if n_res is not None else None,
            "range_position":          None,
            "location_zone":           None,
            "location_quality":        None,
            "location_warning":        None,
            "location_report":         None,
            "is_near_call_wall":   bool(s.get('call_wall')   and abs(spot_f - float(s['call_wall']))   <= near),
            "is_near_put_wall":    bool(s.get('put_wall')    and abs(spot_f - float(s['put_wall']))    <= near),
            "is_near_vol_trigger": bool(s.get('vol_trigger') and abs(spot_f - float(s['vol_trigger'])) <= near),
            "is_near_risk_pivot":  bool(rp                   and abs(spot_f - float(rp))               <= near),
            "is_near_zero_gamma":  bool(s.get('zero_gamma')  and abs(spot_f - float(s['zero_gamma']))  <= near),
        }

        if n_sup is not None and n_res is not None and n_res > n_sup:
            rpos = (spot_f - n_sup) / (n_res - n_sup)
            loc["range_position"] = round(rpos, 2)
            if rpos <= 0.25:
                loc["location_zone"] = "NEAR_SUPPORT"
            elif rpos <= 0.40:
                loc["location_zone"] = "LOWER_RANGE"
            elif rpos <= 0.60:
                loc["location_zone"] = "MIDDLE_OF_RANGE"
            elif rpos <= 0.75:
                loc["location_zone"] = "UPPER_RANGE"
            else:
                loc["location_zone"] = "NEAR_RESISTANCE"

        # Qualidade da localizacao
        # DANGEROUS sobrepoe tudo: colado em wall = zona de armadilha,
        # nao de entrada (CALL atrasado na CW / PUT atrasado na PW).
        _z = loc["location_zone"]
        if loc["is_near_call_wall"] or loc["is_near_put_wall"]:
            loc["location_quality"] = "DANGEROUS"
        elif _z in ("NEAR_SUPPORT", "NEAR_RESISTANCE"):
            loc["location_quality"] = "STRONG"   # perto de nivel decisivo comum
        elif _z in ("LOWER_RANGE", "UPPER_RANGE"):
            loc["location_quality"] = "MEDIUM"
        elif _z == "MIDDLE_OF_RANGE":
            loc["location_quality"] = "WEAK"

        # Warning contextual (prioridade: walls > meio do range)
        if loc["is_near_call_wall"]:
            loc["location_warning"] = ("Preco perto do Call Wall — evitar CALL atrasado.")
        elif loc["is_near_put_wall"]:
            loc["location_warning"] = ("Preco perto do Put Wall — evitar PUT atrasado; "
                                       "risco de bounce/V-bottom.")
        elif _z == "MIDDLE_OF_RANGE":
            loc["location_warning"] = ("Preco entre suporte e resistencia, sem edge "
                                       "estrutural claro. Aguardar aproximacao de nivel "
                                       "ou confirmacao.")

        # Relatorio descritivo
        if n_sup is not None and n_res is not None and loc["range_position"] is not None:
            loc["location_report"] = (
                f"SPY {spot_f} entre {n_sup} ({loc['nearest_support_type']}) e "
                f"{n_res} ({loc['nearest_resistance_type']}) — posicao "
                f"{loc['range_position']} ({_z}). Qualidade: {loc['location_quality']}.")

        return loc

    spy        = sg.get('SPY') or sg.get('$SPY') or {}
    combos_raw = spy.get('combos') or spy.get('combo_strikes') or []
    combos     = sorted([c for c in combos_raw if isinstance(c, (int, float))])
    vol_trig   = spy.get('vol_trigger') or spy.get('zero_gamma')
    call_wall  = spy.get('call_wall')
    put_wall   = spy.get('put_wall')
    all_lvls   = _all_levels(spy)

    # 1D Expected Move
    move_1d_high = spy.get('move_1d_high')
    move_1d_low  = spy.get('move_1d_low')
    if not move_1d_high and spy.get('imp_1d') and spot_now:
        try:
            move_1d_high = round(float(spot_now) * (1 + float(spy['imp_1d'])), 2)
            move_1d_low  = round(float(spot_now) * (1 - float(spy['imp_1d'])), 2)
        except Exception:
            pass

    # C4 = segundo combo acima do Vol Trigger
    above_vt = [c for c in combos if vol_trig and c > float(vol_trig)]
    c4_level = above_vt[1] if len(above_vt) >= 2 else (above_vt[0] if above_vt else call_wall)

    # m1_score e risk
    m1_score = int(data.get("m1_score") or 2)
    risk_str = "High" if m1_score <= 2 else "Medium" if m1_score <= 3 else "Normal"

    # Proximidade de nível: min(1.50 pts, 0.2% do spot)
    near_level = min(1.50, float(spot_now) * 0.002) if spot_now else 1.50

    # ── Regime ──
    gamma_regime = (
        "POSITIVE_GAMMA"
        if (vol_trig and float(spot_now) >= float(vol_trig))
        else "NEGATIVE_GAMMA"
    )

    # ── Camada OPERACIONAL — Risk Pivot (curso SpotGamma) ─────────────
    # Vol Trigger = regime ESTRUTURAL (gamma_regime acima, motor intacto).
    # Risk Pivot  = linha OPERACIONAL intraday — incorpora posicoes 0DTE.
    # Camadas separadas: o motor decide pelo estrutural; o operacional
    # informa zona de transicao, chase risk e divergencia entre linhas.
    risk_pivot = None
    try:
        _rp = data.get("risk_pivot")
        if _rp:
            risk_pivot = float(_rp)
            if risk_pivot > 2000:  # veio em escala SPX → converte p/ SPY
                risk_pivot = round(risk_pivot / 10, 2)
    except (ValueError, TypeError):
        risk_pivot = None

    operational_regime_line   = risk_pivot or (float(vol_trig) if vol_trig else None)
    operational_regime_source = "RISK_PIVOT" if risk_pivot else ("VOL_TRIGGER" if vol_trig else None)

    distance_to_operational_pct = None
    operational_regime          = None
    regime_zone                 = None
    regime_strength             = None
    if operational_regime_line and spot_now:
        distance_to_operational_pct = round(
            (float(spot_now) - operational_regime_line) / operational_regime_line * 100, 3)
        operational_regime = "ABOVE_LINE" if distance_to_operational_pct >= 0 else "BELOW_LINE"
        _abs_d = abs(distance_to_operational_pct)
        if _abs_d <= 0.15:
            regime_zone     = "TRANSITION"
            regime_strength = "transition"
        elif _abs_d <= 0.35:
            regime_strength = "moderate"
        elif _abs_d <= 0.80:
            regime_strength = "clear"
        else:
            regime_strength = "extended"  # esticado = chase risk

    # Divergencia entre camadas: SPY entre Risk Pivot e Vol Trigger
    operational_note = None
    if risk_pivot and vol_trig and spot_now:
        _s, _vt_v = float(spot_now), float(vol_trig)
        _above_rp = _s >= risk_pivot
        _above_vt = _s >= _vt_v
        if _above_rp != _above_vt:
            if _above_rp:
                operational_note = (
                    f"SPY entre Risk Pivot {risk_pivot} e Vol Trigger {_vt_v} — "
                    f"zona intermediaria: risco operacional controlado, mas regime "
                    f"estrutural ainda negativo. Exigir confirmacao extra.")
            else:
                operational_note = (
                    f"SPY entre Vol Trigger {_vt_v} e Risk Pivot {risk_pivot} — "
                    f"zona intermediaria: regime estrutural positivo, mas linha "
                    f"operacional perdida. Exigir confirmacao extra.")

    # ── Alertas 1D Move ──
    at_move_high = bool(move_1d_high and abs(float(spot_now) - float(move_1d_high)) <= near_level)
    at_move_low  = bool(move_1d_low  and abs(float(spot_now) - float(move_1d_low))  <= near_level)

    # ── Location Engine (curso SpotGamma) ─────────────────────────────
    # Risk Pivot e 1D Moves incluidos nos niveis SO aqui —
    # all_lvls original intacto (alvos nao mudam).
    _loc_levels = all_lvls[:]
    if risk_pivot:
        _loc_levels.append(risk_pivot)
    if move_1d_high:
        _loc_levels.append(float(move_1d_high))
    if move_1d_low:
        _loc_levels.append(float(move_1d_low))
    location = analyze_trade_location(
        spot_now, _loc_levels, near_level, spy,
        rp=risk_pivot, m1h=move_1d_high, m1l=move_1d_low)

    # HIRO: não disponível — não bloqueia decisão
    hiro_state = "not_available"

    decision = "NO TRADE"
    reason   = ""
    entry    = ""
    stop     = ""
    t1 = t2  = None
    op_score = 2
    hard_rules = []

    if gamma_regime == "POSITIVE_GAMMA" and vol_trig and call_wall:
        near_vt  = abs(float(spot_now) - float(vol_trig))  <= near_level
        near_cw  = abs(float(spot_now) - float(call_wall)) <= near_level
        above_c4 = bool(
            c4_level
            and float(spot_now) > float(c4_level)
            and float(spot_now) < float(call_wall)
        )

        if near_vt or at_move_low:
            # Extremo inferior → CALL REVERSAL
            decision = "CALL REVERSAL"
            reason   = (f"SPY near Vol Trigger {vol_trig}"
                        f"{' / at 1D Move Low' if at_move_low else ''}."
                        " Dealers provide support here.")
            entry    = f"Buy call ATM/OTM near {vol_trig}. Enter 9:45 ET."
            stop     = f"SPY closes below {vol_trig} — regime flips negative."
            ups      = _above(all_lvls, spot_now, 2)
            t1       = ups[0] if ups else round(float(vol_trig) + 2, 2)
            t2       = _safe_t2_call(t1, all_lvls)
            op_score = min(4, m1_score + 2)
            hard_rules.append(f"EXIT CALL immediately if SPY closes below {vol_trig}.")

        elif near_cw or at_move_high:
            # Extremo superior → PUT REVERSAL
            decision = "PUT REVERSAL"
            reason   = (f"SPY near Call Wall {call_wall}"
                        f"{' / at 1D Move High' if at_move_high else ''}."
                        " Dealer selling pressure here.")
            entry    = f"Buy put ATM/OTM near {call_wall}. Enter 9:45 ET."
            stop     = f"SPY closes above {call_wall} — call wall flips to support."
            dns      = _below(all_lvls, spot_now, 2)
            t1       = dns[0] if dns else round(float(call_wall) - 2, 2)
            t2       = _safe_t2_put(t1, all_lvls)
            op_score = min(4, m1_score + 2)
            hard_rules.append(f"EXIT PUT immediately if SPY closes above {call_wall}.")

        elif above_c4:
            # Acima do C4, abaixo da Call Wall → CALL BREAKOUT SMALL
            decision = "CALL BREAKOUT SMALL"
            reason   = (f"SPY above {c4_level}, below Call Wall {call_wall}."
                        " Breakout in progress — small size only.")
            entry    = f"Small call above {c4_level}. Target Call Wall {call_wall}."
            stop     = f"Back below {c4_level}."
            t1       = float(call_wall)
            t2       = _safe_t2_call(t1, all_lvls)
            op_score = min(3, m1_score + 1)
            hard_rules.append("SMALL size only — breakout can fail at Call Wall.")

        else:
            # Meio da faixa → NO TRADE
            decision = "NO TRADE"
            reason   = (f"SPY in middle of range {vol_trig}–{call_wall}."
                        " Not near any extreme. No structural edge.")
            entry    = "Wait for SPY to approach Vol Trigger or Call Wall."
            t1       = c4_level
            t2       = call_wall

    elif gamma_regime == "NEGATIVE_GAMMA" and vol_trig:
        # Abaixo do Vol Trigger → PUT TREND
        decision = "PUT TREND"
        reason   = (f"SPY below Vol Trigger {vol_trig}."
                    " Negative gamma — dealers amplify the move downward.")
        stop     = f"SPY closes back above {vol_trig}."

        # Alvos PUT TREND: só combos e spy_levels ABAIXO do spot_now
        # Put Wall nunca é alvo automático — é suporte extremo estrutural
        _put_candidates = sorted(
            [l for l in (spy.get('combos') or []) + (spy.get('spy_levels') or [])
             if isinstance(l, (int, float)) and float(l) < float(spot_now)],
            reverse=True
        )
        # Filtra só níveis próximos (dentro de 8 pts)
        _put_nearby = [l for l in _put_candidates
                       if float(spot_now) - float(l) <= 8.0]

        t1 = _put_nearby[0] if _put_nearby else None
        t2 = _put_nearby[1] if len(_put_nearby) >= 2 else None

        # Validação final: nunca alvo acima ou igual ao spot
        if t1 and float(t1) >= float(spot_now): t1 = None
        if t2 and float(t2) >= float(spot_now): t2 = None

        # Put Wall como nota de suporte extremo
        pw_note = f" Put Wall {put_wall} = suporte extremo." if put_wall else ""
        entry   = f"Buy put OTM. SPY accepted below {vol_trig}.{pw_note}"

        op_score = min(3, m1_score + 1)
        hard_rules.append(f"EXIT PUT immediately if SPY recovers {vol_trig}.")
        if at_move_low:
            hard_rules.append(
                f"⚠ SPY at 1D Move Low {move_1d_low} — bounce possible. Monitor closely.")

    else:
        decision = "NO TRADE"
        reason   = "Insufficient level data to determine setup."
        entry    = "No entry."

    # Hard rules obrigatórias
    hard_rules.append("Saida obrigatoria 12:30 ET se nao houver follow-through.")
    if regime_zone == "TRANSITION":
        hard_rules.append(
            f"⚠ SPY a {abs(distance_to_operational_pct):.2f}% da linha operacional "
            f"({operational_regime_source} {operational_regime_line}) — zona de TRANSICAO. "
            f"Toque nao e aceitacao: aguardar 2+ velas fechadas do lado escolhido.")
    elif regime_strength == "extended":
        hard_rules.append(
            f"⚠ SPY esticado {abs(distance_to_operational_pct):.2f}% da linha operacional "
            f"({operational_regime_source} {operational_regime_line}) — chase risk elevado. Nao perseguir.")
    if operational_note:
        hard_rules.append(f"⚠ {operational_note}")
    # ── Warnings do Location Engine (apos camada operacional) ─────────
    if location:
        if location.get("location_warning"):
            hard_rules.append(f"⚠ LOCATION: {location['location_warning']}")
        if decision and "CALL" in decision and location.get("location_zone") == "NEAR_RESISTANCE" \
                and not location.get("is_near_call_wall"):
            hard_rules.append(
                f"⚠ LOCATION: CALL colado na resistencia "
                f"{location['nearest_resistance']} ({location['nearest_resistance_type']}) "
                f"— exigir rompimento com aceitacao (2+ velas fechadas acima).")
        if decision and "PUT" in decision and location.get("location_zone") == "NEAR_SUPPORT" \
                and not location.get("is_near_put_wall"):
            hard_rules.append(
                f"⚠ LOCATION: PUT colado no suporte "
                f"{location['nearest_support']} ({location['nearest_support_type']}) "
                f"— aguardar perda do nivel com aceitacao abaixo.")
    if at_move_high:
        hard_rules.append(
            f"⚠ SPY at 1D Move High {move_1d_high} — PUT reversal possible.")
    if at_move_low and decision not in ("PUT TREND",):
        hard_rules.append(
            f"⚠ SPY at 1D Move Low {move_1d_low} — CALL reversal possible.")

    # Garantia final: targets nunca invertidos
    if t1 and t2:
        is_call = decision in ("CALL REVERSAL", "CALL BREAKOUT SMALL")
        is_put  = decision in ("PUT REVERSAL", "PUT TREND")
        if is_call and float(t2) <= float(t1):
            t2 = round(float(t1) + 2, 2)
        if is_put and float(t2) >= float(t1):
            t2 = round(float(t1) - 2, 2)

    # ── Context bias: cruza PM Note da noite com PDF da manhã ────────────
    context_bias        = "neutral_context"
    context_warning     = ""
    pm_context_date     = None
    pm_hiro_ctx         = None
    pm_vix_ctx          = None
    pm_cor1m_ctx        = None

    try:
        from journal import get_journal
        rows = get_journal(limit=5)
        pm_row = None
        for row in rows:
            if row.get("pm_hiro") or row.get("pm_vix_close") or row.get("pm_cor1m_close"):
                pm_row = row
                break

        if pm_row:
            pm_hiro_ctx   = (pm_row.get("pm_hiro") or "").lower()
            pm_vix_ctx    = pm_row.get("pm_vix_close")
            pm_cor1m_ctx  = pm_row.get("pm_cor1m_close")
            pm_context_date = str(pm_row.get("date", ""))

            bearish_signals = 0
            bullish_signals = 0

            if any(w in pm_hiro_ctx for w in ["bearish", "negative", "bear", "selling"]):
                bearish_signals += 2
            elif any(w in pm_hiro_ctx for w in ["bullish", "positive", "bull", "buying"]):
                bullish_signals += 2

            if pm_vix_ctx and float(pm_vix_ctx) > 18:
                bearish_signals += 1
            elif pm_vix_ctx and float(pm_vix_ctx) < 15:
                bullish_signals += 1

            if pm_cor1m_ctx and float(pm_cor1m_ctx) >= 6.0:
                bearish_signals += 2
            elif pm_cor1m_ctx and float(pm_cor1m_ctx) < 4.0:
                bullish_signals += 1

            if bearish_signals >= 3:
                context_bias = "bearish_context"
            elif bullish_signals >= 3:
                context_bias = "bullish_context"
            elif bearish_signals > 0 and bullish_signals > 0:
                context_bias = "mixed_context"
            else:
                context_bias = "neutral_context"

            warnings = []
            if context_bias == "bearish_context":
                if decision in ("CALL REVERSAL", "CALL BREAKOUT SMALL"):
                    warnings.append(
                        f"PM Note bearish (HIRO {pm_hiro_ctx}) + COR1M {pm_cor1m_ctx} "
                        f"— CALL requer confirmacao adicional. Tamanho reduzido.")
                elif decision in ("PUT TREND", "PUT REVERSAL"):
                    warnings.append(f"PM Note bearish confirma PUT. Contexto alinhado.")
                if pm_cor1m_ctx and float(pm_cor1m_ctx) >= 6.0:
                    warnings.append(
                        f"⚠ COR1M {pm_cor1m_ctx} acima do risk barrier 6.0 "
                        f"— risco de volatility spasm.")
                if pm_vix_ctx and float(pm_vix_ctx) > 16:
                    warnings.append(
                        f"⚠ VIX ontem {pm_vix_ctx} elevado — opcoes mais caras hoje.")
            elif context_bias == "bullish_context":
                if decision in ("PUT TREND", "PUT REVERSAL"):
                    warnings.append(
                        f"PM Note bullish (HIRO {pm_hiro_ctx}) — "
                        f"PUT requer confirmacao. Contexto diverge.")
                elif decision in ("CALL REVERSAL", "CALL BREAKOUT SMALL"):
                    warnings.append(f"PM Note bullish confirma CALL. Contexto alinhado.")
            elif context_bias == "mixed_context":
                warnings.append("PM Note sinais mistos — reduzir tamanho, aguardar confirmacao.")

            warnings.append(
                "Suporte 0DTE de ontem nao carrega para hoje — usar apenas niveis do PDF atual.")
            context_warning = " | ".join(warnings)

    except Exception as ctx_err:
        context_bias    = "neutral_context"
        context_warning = f"PM Note nao disponivel: {ctx_err}"

    # ── Gap & Timing Filter ─────────────────────────────────────────────
    # Alerta de timing — nao muda a decisao principal
    gap_points     = None
    gap_pct        = None
    gap_type       = "none"
    gap_fill_level = None
    gap_warning    = ""
    timing_quality = "OK"
    early_entry_ok = True
    chase_warning  = False

    try:
        # yesterday_close via journal
        yc = None
        try:
            from journal import get_journal
            rows = get_journal(limit=5)
            for row in rows:
                if row.get("close") and float(row["close"]) > 0:
                    yc = float(row["close"])
                    break
        except Exception:
            yc = None

        # gap analysis
        if yc and spot_open:
            to = float(spot_open)
            gap_points     = round(to - yc, 2)
            gap_pct        = round(gap_points / yc * 100, 3)
            gap_fill_level = round(yc, 2)

            if abs(gap_pct) < 0.15:
                gap_type = "none"
            elif -0.50 <= gap_pct < -0.15:
                gap_type = "small_down"
                gap_warning = ("Gap down pequeno ainda aberto — cuidado com PUT cedo; "
                               "aguardar rejeicao do fechamento anterior "
                               "ou perda clara do Zero Gamma.")
            elif 0.15 < gap_pct <= 0.50:
                gap_type = "small_up"
                gap_warning = ("Gap up pequeno ainda aberto — cuidado com CALL cedo; "
                               "aguardar rejeicao do fechamento anterior "
                               "ou rompimento limpo.")
            elif gap_pct < -0.50:
                gap_type = "large_down"
                gap_warning = "Gap down grande — fill menos provavel; exigir confirmacao."
            elif gap_pct > 0.50:
                gap_type = "large_up"
                gap_warning = "Gap up grande — fill menos provavel; exigir confirmacao."

        # timing quality — horario ET
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        import datetime as _dt
        now_et = _dt.datetime.now(ZoneInfo("America/New_York"))
        hhmm   = now_et.hour * 100 + now_et.minute

        if hhmm < 945:
            timing_quality = "TOO_EARLY"
            early_entry_ok = False
        elif hhmm <= 1015:
            timing_quality = "OK"
            early_entry_ok = True
        elif hhmm <= 1045:
            timing_quality = "CAUTION"
            early_entry_ok = True
        else:
            timing_quality = "LATE"
            early_entry_ok = False

        # chase warning
        if decision and "CALL" in decision and vol_trig and spot_now:
            if float(spot_now) > float(vol_trig) + near_level:
                chase_warning = True
        if decision and "PUT" in decision and spot_now:
            zg_val = spy.get("zero_gamma")
            if zg_val and float(spot_now) < float(zg_val) - near_level:
                chase_warning = True

        # Put Wall check — nao perseguir PUT no suporte
        pw_val = spy.get("put_wall")
        if pw_val and spot_now and "PUT" in (decision or ""):
            if float(spot_now) <= float(pw_val) + 0.25:
                entry = f"SPY already at Put Wall {pw_val}. Wait for acceptance below {pw_val} or retest/rejection near VT {vol_trig}."
                stop  = f"SPY recovers above {pw_val}"
                t1    = round(float(pw_val) - 2, 2)
                t2    = round(float(pw_val) - 4, 2)
                chase_warning = True

    except Exception as gap_err:
        gap_warning = f"Gap analysis indisponivel: {gap_err}" 

    # Resumo em uma frase
    one_sentence = (f"{gamma_regime.replace('_', ' ')}, SPY {spot_now}"
                    f" vs VT {vol_trig} — {decision}. {entry}")

    # ── Próximo setup a monitorar (cockpit de espera) ─────────────────
    _vt  = vol_trig
    _zg  = spy.get("zero_gamma") or vol_trig
    _cw  = call_wall
    _pw  = put_wall
    _ref = spy.get("reference_price") or spot_now

    if _vt and _zg and str(_vt) != str(_zg):
        _key_level = f"{_vt}/{_zg}"
    else:
        _key_level = str(_vt or _zg or "—")

    if gamma_regime == "NEGATIVE_GAMMA":
        next_setup = {
            "call_setup":   f"SPY recuperar {_key_level} com aceitação (fechar acima por 2+ velas).",
            "put_setup":    f"SPY retestar {_key_level} e rejeitar — confirmação de continuação baixista.",
            "no_trade":     f"SPY entre {_ref}–{_vt} sem direção clara — aguardar.",
            "key_level":    _key_level,
            "invalidation": f"Viés PUT perde força se SPY recuperar {_key_level}.",
            "context":      "NEGATIVE GAMMA — mercado frágil. Dealers amplificam moves.",
        }
    elif gamma_regime == "POSITIVE_GAMMA":
        next_setup = {
            "call_setup":   f"SPY retestar {_key_level} e segurar — entrada CALL REVERSAL perto do piso.",
            "put_setup":    f"SPY se aproximar de {_cw} e rejeitar — entrada PUT REVERSAL perto do teto.",
            "no_trade":     f"SPY no meio da faixa {_vt}–{_cw} — sem edge estrutural.",
            "key_level":    _key_level,
            "invalidation": f"Viés CALL perde força se SPY perder {_key_level}. Viés PUT perde força se SPY superar {_cw}.",
            "context":      "POSITIVE GAMMA — dealers sustentam range. Reversões nos extremos.",
        }
    else:
        next_setup = {
            "call_setup":   None,
            "put_setup":    None,
            "no_trade":     "Dados insuficientes — preencher manualmente.",
            "key_level":    None,
            "invalidation": None,
            "context":      None,
        }

    # Output: compatível com Modo 3
    ow["rbc_decision"] = {
        "gamma_regime":     gamma_regime,
        "risk_pivot":       risk_pivot,
        "operational_regime_line":     operational_regime_line,
        "operational_regime_source":   operational_regime_source,
        "operational_regime":          operational_regime,
        "distance_to_operational_pct": distance_to_operational_pct,
        "regime_zone":      regime_zone,
        "regime_strength":  regime_strength,
        "operational_note": operational_note,
        "location":         location,
        "decision":         decision,
        "reason":           reason,
        "entry":            entry,
        "stop":             stop,
        "target_1":         str(t1) if t1 else None,
        "target_2":         str(t2) if t2 else None,
        "op_score":         op_score,
        "risk":             risk_str,
        "hard_rules":       hard_rules,
        "one_sentence":     one_sentence,
        "next_setup":       next_setup,
        "hiro":             None,
        "hiro_state":       hiro_state,
        "context_bias":     context_bias,
        "context_warning":  context_warning,
        "pm_context_date":  pm_context_date,
        "pm_hiro":          pm_hiro_ctx,
        "pm_vix_close":     pm_vix_ctx,
        "pm_cor1m_close":   pm_cor1m_ctx,
        "gap_points":       gap_points,
        "gap_pct":          gap_pct,
        "gap_type":         gap_type,
        "gap_fill_level":   gap_fill_level,
        "gap_warning":      gap_warning,
        "timing_quality":   timing_quality,
        "early_entry_ok":   early_entry_ok,
        "chase_warning":    chase_warning,
        "levels": {
            "vol_trigger":  vol_trig,
            "call_wall":    call_wall,
            "put_wall":     put_wall,
            "zero_gamma":   spy.get("zero_gamma"),
            "c4":           c4_level,
            "move_1d_high": move_1d_high,
            "move_1d_low":  move_1d_low,
            "near_level":   round(near_level, 2),
        },
    }

    ow["spot_now"]  = spot_now
    ow["vix_now"]   = vix_now
    ow["spot_open"] = spot_open
    ow["vix_open"]  = vix_open
    return jsonify(ow)


@app.route("/api/modo5/latest", methods=["GET"])
def modo5_latest():
    """Retorna o resultado mais recente do scanner Modo 5 via PostgreSQL."""
    try:
        from journal import get_swing_latest_scan
        rows = get_swing_latest_scan()
        if not rows:
            return jsonify({"error": "Nenhum resultado encontrado. Rode o scanner primeiro."}), 404

        # Reconstroi formato original do scanner
        results = []
        for r in rows:
            raw = r.get("raw") or {}
            if isinstance(raw, dict) and raw:
                results.append(raw)
            else:
                # Reconstroi do banco
                edge_fatores = {}
                for k in ['gex', 'vrp', 'skew', 'pc_ratio']:
                    field = 'edge_' + ('pc' if k == 'pc_ratio' else k)
                    if r.get(field):
                        edge_fatores[k] = r[field]
                results.append({
                    "ticker":           r.get("ticker"),
                    "direction":        r.get("direction"),
                    "spot":             float(r.get("spot") or 0),
                    "scanned":          r.get("scanned", 0),
                    "overall_verdict":  r.get("verdict"),
                    "timestamp":        r.get("scan_time"),
                    "edge": {
                        "verdict":    r.get("edge_verdict"),
                        "aprovados":  r.get("edge_aprovados", 0),
                        "fatores":    edge_fatores,
                    },
                    "top_contracts": r.get("contracts") or [],
                })

        ts = rows[0].get("scan_time", "") if rows else ""
        return jsonify({"ok": True, "timestamp": ts, "results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/modo3", methods=["POST"])
def modo3():
    """Operational scanner (after 10:00 ET): recommends 0DTE strike."""
    data = request.get_json(silent=True) or {}

    required = ["sg_raw", "spot_spy", "vix"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        spot_spy     = float(data["spot_spy"])
        vix          = float(data["vix"])
        iv           = round(vix / 100, 4)
        rf           = float(data.get("rf", 0.0527))
        hours_to_exp = float(data.get("hours_to_exp", 4.0))
        capital      = float(data.get("capital", 50000))
        premium_paid = float(data["premium_paid"]) if data.get("premium_paid") else None
        contracts    = int(data.get("contracts", 1))
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid numeric value: {e}"}), 400

    sg = parse_sg_data(data["sg_raw"])

    result = analyze_spy_0dte(
        sg_data=sg,
        spot_spy=spot_spy,
        iv=iv,
        rf=rf,
        hours_to_exp=hours_to_exp,
        capital=capital,
        premium_paid=premium_paid,
        contracts=contracts,
    )

    if "error" in result:
        return jsonify(result), 422

    return jsonify(result)


@app.route("/api/webhook", methods=["POST"])
def tradingview_webhook():
    """Recebe eventos do TradingView e atualiza o journal do dia."""
    data  = request.get_json(silent=True) or {}
    event = data.get("event")
    date  = data.get("date")
    time  = data.get("time")

    if not event:
        return jsonify({"error": "event required"}), 400

    try:
        from journal import save_snapshot, get_snapshot_by_date
        update = {"date": date} if date else {}

        if event == "c4_reclaimed":
            update.update({"c4_reclaimed": True, "c4_reclaimed_time": time})
        elif event == "c1_hit":
            update.update({"c1_hit": True, "c1_hit_time": time})
        elif event == "call_wall_hit":
            update.update({"call_wall_hit": True, "call_wall_hit_time": time})
        elif event == "near_call_wall":
            update.update({"near_call_wall": True})
        elif event == "vol_trigger_lost":
            update.update({"vol_trigger_lost": True, "vol_trigger_lost_time": time})
        elif event == "close_day":
            high  = float(data.get("high")  or 0)
            low   = float(data.get("low")   or 0)
            open_ = float(data.get("open")  or 0)
            close = float(data.get("close") or 0)

            update.update({
                "open_spy":  open_ or None,
                "close_spy": close or None,
                "max_spy":   high  or None,
                "min_spy":   low   or None,
            })

            row0 = get_snapshot_by_date(date) if date else {}
            c4_level  = float(row0.get("c4")          or 0)
            c1_level  = float(row0.get("c1")          or 0)
            cw_level  = float(row0.get("call_wall")   or 0)
            vt_level  = float(row0.get("vol_trigger") or 0)

            if not (c4_level and c1_level and cw_level and vt_level):
                return jsonify({"error": "Niveis nao encontrados para %s. Processe o PDF no Modo 1 primeiro." % date}), 400

            # ── calculate_trade_path_from_levels ────────────────────
            # Cruza OHLC do TradingView com níveis do SpotGamma
            # Nao depende de eventos webhook para reclaim

            zg_level = float(row0.get("zero_gamma") or 0)
            pw_level = float(row0.get("put_wall")   or 0)

            c4_rec   = high >= c4_level  if c4_level else False
            c1_hit   = high >= c1_level  if c1_level else False
            cw_hit   = high >= cw_level  if cw_level else False
            near_cw  = high >= (cw_level - 0.25) if cw_level else False

            # Vol Trigger — lost e reclaim via OHLC
            vt_lost    = (open_ < vt_level or low < vt_level) if vt_level else False
            vt_reclaim = vt_lost and close > vt_level if vt_level else False

            # Regime no fechamento
            if vt_level:
                regime_close = "POSITIVE_GAMMA" if close > vt_level else "NEGATIVE_GAMMA"
            else:
                regime_close = None

            update.update({
                "c4_reclaimed":     c4_rec,
                "c1_hit":           c1_hit,
                "call_wall_hit":    cw_hit,
                "near_call_wall":   near_cw,
                "vol_trigger_lost": vt_lost,
            })

            # ── Monta path em ordem cronológica ──────────────────────
            path_parts = []

            # 1. Compressão — abriu entre VT e C4
            if open_ and vt_level and c4_level and vt_level <= open_ <= c4_level:
                path_parts.append("compression")

            # 2. Vol Trigger perdido na abertura ou no low
            if vt_lost:
                path_parts.append("vol_trigger_lost")

            # 3. C4 reclaim
            if c4_rec:
                path_parts.append("c4")

            # 4. C1 hit
            if c1_hit:
                path_parts.append("c1")

            # 5. Call Wall
            if cw_hit:
                path_parts.append("call_wall")
                if close < cw_level:
                    path_parts.append("call_wall_rejection")
            elif near_cw:
                path_parts.append("near_call_wall")

            # 6. Reclaim do Vol Trigger no fechamento
            if vt_reclaim:
                path_parts.append("reclaim")

            if path_parts:
                update["trade_path"] = " -> ".join(path_parts)
            if regime_close:
                update["notes"] = (update.get("notes") or "") + f" | regime_close: {regime_close}"
            # ─────────────────────────────────────────────────────────

        row = save_snapshot(update)
        return jsonify({"ok": True, "event": event, "date": str(row["date"]), "update": {k:v for k,v in update.items() if k != "date"}})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/save-snapshot", methods=["POST"])
def save_snapshot_route():
    from journal import save_snapshot, init_db
    try:
        init_db()
        data = request.get_json(silent=True) or {}
        row = save_snapshot(data)
        return jsonify({"ok": True, "id": row["id"], "date": str(row["date"])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/journal", methods=["GET"])
def get_journal_route():
    from journal import get_journal
    try:
        limit = int(request.args.get("limit", 30))
        rows = get_journal(limit)
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=True, port=port)
