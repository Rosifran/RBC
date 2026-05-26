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

_PDF_PROMPT = """\
You are a quantitative trading assistant. Below is text extracted from a SpotGamma PDF report.

Extract the following for SPY (and only SPY) and return ONLY a valid JSON object — no markdown, no explanation:

{
  "spy": {
    "call_wall":   <number>,
    "put_wall":    <number>,
    "zero_gamma":  <number>,
    "vol_trigger": <number>,
    "abs_gamma":   <number>,
    "move_1d":     <decimal, e.g. 0.0061 for 0.61%>,
    "combos":      [<number>, <number>, <number>, <number>]
  },
  "sg_string": "$SPY, SPY, <call_wall>, <put_wall>, <vol_trigger>, <abs_gamma>, <support1>, <support2>, <support3>, <combo1>, <combo2>, <combo3>, <combo4>, <move_1d>, <move_5d>, <zero_gamma>",
  "briefing": "<2-3 sentence macro summary from the founder note or commentary section>",
  "eventos": ["<key market event or risk today>", ...]
}

Rules:
- combos: pick the 4 combo/support levels closest to current price, ascending.
- sg_string supports (support1-3): use put_wall and next two support levels if available.
- move_1d and move_5d as decimals (divide % by 100).
- If a field is not found, use null.
- Return raw JSON only.

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
    return jsonify({"status": "ok", "version": "1.5-beta"})


@app.route("/")
def index():
    return render_template("index.html")


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
        msg = _anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": _PDF_PROMPT.format(text=text[:12000]),
            }],
        )
        raw = msg.content[0].text.strip()
        cleaned = raw
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            return jsonify({"error": f"Claude returned invalid JSON: {e}", "raw": raw}), 502
    except Exception as e:
        return jsonify({"error": f"Claude API error: {e}"}), 502

    return jsonify({
        "ok":       True,
        "spy":      parsed.get("spy"),
        "sg_string": parsed.get("sg_string"),
        "briefing": parsed.get("briefing"),
        "eventos":  parsed.get("eventos", []),
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

    required = ["sg_raw", "vix_open", "vix_now", "spot_open", "spot_now"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        vix_open  = float(data["vix_open"])
        vix_now   = float(data["vix_now"])
        spot_open = float(data["spot_open"])
        spot_now  = float(data["spot_now"])
        hiro      = data.get("hiro_direction", "neutral")
        capital   = float(data.get("capital", 50000))
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid numeric value: {e}"}), 400

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
