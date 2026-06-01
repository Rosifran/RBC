"""
RBC — Risk Bridge Capital | Flask API
"""

import io
import json
import os

import anthropic
import pdfplumber
from flask import Flask, jsonify, render_template, request

_anthropic = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

_PDF_PROMPT = """You are a quantitative trading assistant. Extract structured data from this SpotGamma PDF report.

Return ONLY a valid JSON object with exactly these fields. No markdown, no explanation.

{{
  "spy": {{
    "reference_price": null,
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

    put_line  = vol_trig or zero_g
    above_put = [c for c in combos_f if put_line and c > put_line]

    # no_trade_hi = segundo combo acima do put_line
    if len(above_put) >= 2:
        no_trade_hi = above_put[1]
    elif above_put:
        no_trade_hi = above_put[0]
    else:
        no_trade_hi = call_wall

    # CALL escalonado — começa acima de no_trade_hi
    if len(above_put) >= 3 and call_wall:
        parsed["plan"]["call_trigger"] = f"SPY above {above_put[1]}, better above {above_put[2]}, strongest above {call_wall}."
    elif len(above_put) >= 2 and call_wall:
        parsed["plan"]["call_trigger"] = f"SPY above {above_put[1]}, strongest above {call_wall}."
    elif call_wall:
        parsed["plan"]["call_trigger"] = f"SPY above {call_wall}."

    # PUT linha dura
    if put_line:
        parsed["plan"]["put_trigger"] = f"SPY below {put_line}."

    # NO TRADE zona de compressão
    if put_line and no_trade_hi:
        parsed["plan"]["avoid"] = f"SPY between {put_line} and {no_trade_hi}."

    # BEST operacional
    if put_line and no_trade_hi:
        parsed["plan"]["best_setup"] = f"Wait for breakout; do not trade inside {put_line}–{no_trade_hi} compression zone."

    # SCORE baseado em sinais de risco
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
    return jsonify(ow)


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=True, port=port)
