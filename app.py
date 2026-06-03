"""
RBC — Risk Bridge Capital | Flask API
"""

import io
import json
import os

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

    # ── Alertas 1D Move ──
    at_move_high = bool(move_1d_high and abs(float(spot_now) - float(move_1d_high)) <= near_level)
    at_move_low  = bool(move_1d_low  and abs(float(spot_now) - float(move_1d_low))  <= near_level)

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
        entry    = f"Buy put OTM. SPY accepted below {vol_trig}."
        stop     = f"SPY closes back above {vol_trig}."
        dns      = _below(all_lvls, spot_now, 2)
        t1       = dns[0] if dns else round(float(vol_trig) - 3, 2)
        t2       = _safe_t2_put(t1, all_lvls)
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

    # Resumo em uma frase
    one_sentence = (f"{gamma_regime.replace('_', ' ')}, SPY {spot_now}"
                    f" vs VT {vol_trig} — {decision}. {entry}")

    # Output: compatível com Modo 3
    ow["rbc_decision"] = {
        "gamma_regime": gamma_regime,
        "decision":     decision,
        "reason":       reason,
        "entry":        entry,
        "stop":         stop,
        "target_1":     str(t1) if t1 else None,
        "target_2":     str(t2) if t2 else None,
        "op_score":     op_score,
        "risk":         risk_str,
        "hard_rules":   hard_rules,
        "one_sentence": one_sentence,
        "hiro":         None,
        "hiro_state":   hiro_state,
        "levels": {
            "vol_trigger":  vol_trig,
            "call_wall":    call_wall,
            "put_wall":     put_wall,
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

            c4_rec  = high >= c4_level
            c1_hit  = high >= c1_level
            cw_hit  = high >= cw_level
            near_cw = high >= (cw_level - 0.25)
            vt_lost = low  <= vt_level

            update.update({
                "c4_reclaimed":       c4_rec,
                "c1_hit":             c1_hit,
                "call_wall_hit":      cw_hit,
                "near_call_wall":     near_cw,
                "vol_trigger_lost":   vt_lost,
            })

            path_parts = []
            if open_ and vt_level and c4_level and vt_level <= open_ <= c4_level:
                path_parts.append("compression")
            if c4_rec:   path_parts.append("c4")
            if c1_hit:   path_parts.append("c1")
            if cw_hit:   path_parts.append("call_wall")
            elif near_cw: path_parts.append("near_call_wall")
            if vt_lost:  path_parts.append("vol_trigger_lost")
            if path_parts:
                update["trade_path"] = " -> ".join(path_parts)

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
